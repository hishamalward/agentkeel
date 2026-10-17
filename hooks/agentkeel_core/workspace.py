"""Create and release task worktrees without guessing which Git state is ours."""
import contextlib
import fcntl
import json
import os
import re
import secrets
import subprocess
import tempfile

from . import isolation, record, repostate
active_processes = isolation.active_processes


class WorkspaceError(Exception):
    pass


def _git(cwd, *args, check=True):
    try:
        env = {"PATH": repostate.FIXED_PATH, "HOME": os.path.expanduser("~"),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "LC_ALL": "C"}
        out = subprocess.run(["git", "-c", f"core.hooksPath={os.devnull}", "-C", cwd, *args],
                             capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WorkspaceError(f"git {args[0]} could not run: {error}") from error
    if check and out.returncode:
        raise WorkspaceError(f"git {args[0]} failed: {(out.stderr or out.stdout).strip()[:300]}")
    return out


def _gitdir(path):
    value = _git(path, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip()
    return os.path.realpath(value)


def _common(path):
    value = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return os.path.realpath(value)


def _gitpath(path, name):
    value = _git(path, "rev-parse", "--git-path", name).stdout.strip()
    # Preserve the final component: runtime marker checks must see dangling symlinks.
    return os.path.abspath(value if os.path.isabs(value) else os.path.join(path, value))


def runtime_path(path):
    """The runtime attachment marker shared with AgentSlots."""
    return _gitpath(path, "agent-runtime.json")


def _top(path):
    value = _git(path, "rev-parse", "--show-toplevel").stdout.strip()
    return os.path.realpath(value)


def _primary(repo, common):
    listing = _git(repo, "worktree", "list", "--porcelain").stdout
    for line in listing.splitlines():
        if line.startswith("worktree "):
            path = os.path.realpath(line[9:])
            if os.path.isdir(path) and _gitdir(path) == common:
                return path
    raise WorkspaceError("the repository has no identifiable primary worktree")


@contextlib.contextmanager
def _file_lock(path):
    try:
        lock = open(path, "a+b")
    except OSError as error:
        raise WorkspaceError(f"lifecycle lock is unavailable: {error}") from error
    with lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _write_manifest(path, manifest):
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".agent-workspace.", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        dfd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_manifest(path):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise WorkspaceError(f"workspace manifest cannot be read: {error}") from error
    if not isinstance(value, dict):
        raise WorkspaceError("workspace manifest is malformed")
    return value


def _same_identity(expected, actual):
    stable = ("version", "task", "session", "path", "gitdir", "common_dir", "primary",
              "branch", "base_sha", "identity", "dir_dev", "dir_ino", "retain_on_finish")
    return all(expected.get(key) == actual.get(key) for key in stable)


def _validate(manifest, allow_pending=True, allow_retained=False):
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise WorkspaceError("workspace manifest is missing or unsupported")
    path = manifest.get("path")
    if not isinstance(path, str) or not os.path.isabs(path) or os.path.realpath(path) != path:
        raise WorkspaceError("workspace path is not canonical")
    stored = _read_manifest(_gitpath(path, "agent-workspace.json"))
    if stored is None or not _same_identity(manifest, stored):
        raise WorkspaceError("workspace manifest identity does not match Git state")
    states = ("active", "disposal_pending") if allow_pending else ("active",)
    if stored.get("state") not in states + (("retained",) if allow_retained else ()):
        raise WorkspaceError(f"workspace is {stored.get('state')!r}, not active")
    required_strings = ("task", "session", "gitdir", "common_dir", "primary", "branch", "base_sha", "identity")
    if any(not isinstance(stored.get(key), str) or not stored[key] for key in required_strings):
        raise WorkspaceError("workspace manifest has missing identity fields")
    if not re.fullmatch(r"[0-9a-f]{64}", stored["identity"]):
        raise WorkspaceError("workspace identity token is malformed")
    try:
        info = os.stat(path)
    except OSError as error:
        raise WorkspaceError(f"workspace path is unavailable: {error}") from error
    if os.path.islink(path) or [info.st_dev, info.st_ino] != [stored.get("dir_dev"), stored.get("dir_ino")]:
        raise WorkspaceError("workspace directory was replaced")
    if _top(path) != path or _gitdir(path) != stored["gitdir"] or _common(path) != stored["common_dir"]:
        raise WorkspaceError("workspace Git identity changed")
    if not os.path.isdir(stored["primary"]) or _gitdir(stored["primary"]) != stored["common_dir"]:
        raise WorkspaceError("primary worktree identity changed")
    branch = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch.returncode or branch.stdout.strip() != stored["branch"]:
        raise WorkspaceError("workspace branch changed or is detached")
    return dict(stored)


def inspect(path):
    """Return the validated on-disk manifest, or None when this tree is unmanaged."""
    top = _top(path)
    if _gitdir(top) == _common(top):
        return None
    manifest = _read_manifest(_gitpath(top, "agent-workspace.json"))
    return _validate(manifest) if manifest else None


def validate(manifest):
    """Validate the caller's manifest against the path, Git administration and stored identity."""
    return _validate(manifest)


@contextlib.contextmanager
def resume(path, task, session, from_sessions, environ):
    """Claim an existing tree explicitly, without changing its files, index or Git refs."""
    path = os.path.abspath(os.path.expanduser(path))
    if path != os.path.realpath(path) or _top(path) != path:
        raise WorkspaceError("resume requires the canonical linked worktree root")
    common, gitdir = _common(path), _gitdir(path)
    if common == gitdir:
        raise WorkspaceError("resume requires a linked worktree, not the primary checkout")
    primary = _primary(path, common)
    with _file_lock(os.path.join(common, "agent-lifecycle.lock")):
        with _file_lock(os.path.join(gitdir, "agent-lifecycle.lock")):
            if _top(path) != path or _common(path) != common or _gitdir(path) != gitdir:
                raise WorkspaceError("worktree identity changed while waiting for handoff")
            branch = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
            if not branch or branch in record.policy(primary)["protected"] | record.policy(path)["protected"]:
                raise WorkspaceError("resume requires an attached, non-protected branch")
            if (path, "refs/heads/" + branch) not in _worktrees(primary):
                raise WorkspaceError("worktree is not registered with this repository")
            if os.path.lexists(runtime_path(path)):
                raise WorkspaceError("runtime is attached; its current owner must release it before session handoff")
            for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
                if os.path.lexists(os.path.join(gitdir, marker)):
                    raise WorkspaceError("finish the in-progress Git operation before session handoff")
            manifest_path = _gitpath(path, "agent-workspace.json")
            previous = _read_manifest(manifest_path)
            if previous:
                previous = _validate(previous, allow_pending=False, allow_retained=True)
                owners = {previous["session"]} if previous["state"] == "active" else set()
            else:
                owners = set()
                folder = os.path.join(record.home(environ), "tasks")
                for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
                    if not name.endswith(".json"):
                        continue
                    owner = _read_manifest(os.path.join(folder, name))
                    if owner and path in owner.get("worktrees", []):
                        if not owner.get("session_id"):
                            raise WorkspaceError("legacy worktree claim has no session identity")
                        owners.add(owner["session_id"])
            owners.discard(session)
            if set(from_sessions) != owners:
                flags = " ".join("--from-session " + s for s in sorted(owners)) or "no --from-session flags"
                raise WorkspaceError("ownership handoff requires " + flags +
                                     "; confirm those sessions are no longer using this worktree before transferring")
            info = os.stat(path)
            manifest = {"version": 1, "task": task, "session": session, "path": path,
                        "gitdir": gitdir, "common_dir": common, "primary": primary,
                        "branch": branch, "base_sha": _git(path, "rev-parse", "HEAD").stdout.strip(),
                        "identity": secrets.token_hex(32), "dir_dev": info.st_dev, "dir_ino": info.st_ino,
                        "state": "active", "retain_on_finish": True,
                        "previous_sessions": sorted(owners)}
            _write_manifest(manifest_path, manifest)
            try:
                yield dict(manifest)
            except BaseException:
                if previous:
                    _write_manifest(manifest_path, previous)
                else:
                    os.unlink(manifest_path)
                raise


def retain(manifest):
    """End the claim while keeping an adopted branch and all worktree content."""
    with _file_lock(os.path.join(manifest["common_dir"], "agent-lifecycle.lock")):
        with _file_lock(os.path.join(manifest["gitdir"], "agent-lifecycle.lock")):
            current = _validate(manifest)
            if os.path.lexists(runtime_path(current["path"])):
                raise WorkspaceError("runtime is still attached; release it before retaining the worktree")
            current["state"] = "retained"
            _write_manifest(_gitpath(current["path"], "agent-workspace.json"), current)
            return current


@contextlib.contextmanager
def lifecycle_lock(path_or_manifest, allow_pending=False):
    """Shared with Slots: attachment and disposal hold this stable per-worktree lock."""
    path = path_or_manifest["path"] if isinstance(path_or_manifest, dict) else path_or_manifest
    manifest = inspect(path)
    if manifest is None:
        raise WorkspaceError("workspace is not managed by AgentKeel")
    with _file_lock(os.path.join(manifest["gitdir"], "agent-lifecycle.lock")):
        current = _validate(manifest, allow_pending=allow_pending)
        if not allow_pending and current["state"] != "active":
            raise WorkspaceError("workspace disposal is pending; runtime attachment is blocked")
        yield dict(current)


def _worktrees(repo):
    listing = _git(repo, "worktree", "list", "--porcelain").stdout
    result, path, branch = [], None, None
    for line in listing.splitlines() + [""]:
        if line.startswith("worktree "):
            path = os.path.realpath(line[9:])
        elif line.startswith("branch "):
            branch = line[7:]
        elif not line:
            if path:
                result.append((path, branch))
            path, branch = None, None
    return result


def _rollback(repo, branch, base_sha, stage, target, owned_gitdir, stage_identity):
    errors = []
    for path in (target, stage):
        if not path or not os.path.isdir(path):
            continue
        try:
            listed = any(p == os.path.realpath(path) and b == f"refs/heads/{branch}"
                         for p, b in _worktrees(repo))
            info = os.stat(path)
            same_directory = [info.st_dev, info.st_ino] == stage_identity
            same_gitdir = not owned_gitdir or _gitdir(path) == owned_gitdir
            if listed and same_directory and same_gitdir and _top(path) == os.path.realpath(path):
                if _has_untracked_or_ignored(path) or repostate.inspect(path)["changed"]:
                    errors.append(f"{path} acquired files during rollback and was retained")
                else:
                    _git(repo, "worktree", "remove", path)
            elif path == stage:
                os.rmdir(path)  # only the empty directory this call made
        except (OSError, WorkspaceError) as error:
            errors.append(str(error))
    if branch:
        try:
            if not any(b == f"refs/heads/{branch}" for _, b in _worktrees(repo)):
                _git(repo, "update-ref", "-d", f"refs/heads/{branch}", base_sha)
        except WorkspaceError as error:
            errors.append(str(error))
    return errors


def destination(repo, task, path=None):
    if path:
        return os.path.realpath(os.path.expanduser(path))
    primary = _primary(repo, _common(repo))
    return os.path.join(os.path.dirname(primary), f"{os.path.basename(primary)}-{task}")


def create(repo, task, session, path=None, branch=None, base=None):
    """Create a branch and linked worktree; only this call's branch/tree are rolled back."""
    if not isinstance(task, str) or not task or not isinstance(session, str) or not session:
        raise WorkspaceError("task and session must be nonempty strings")
    source = _top(repo)
    common = _common(source)
    primary = _primary(source, common)
    if base is None:
        base = _git(primary, "symbolic-ref", "--short", "HEAD").stdout.strip()
        if base not in record.policy(primary)["protected"]:
            raise WorkspaceError("canonical checkout is not on a protected branch; select an explicit --base")
    branch = branch or f"feat/{task}"
    if _git(source, "check-ref-format", "--branch", branch, check=False).returncode:
        raise WorkspaceError(f"invalid branch name: {branch}")
    base_sha = _git(source, "rev-parse", "--verify", f"{base}^{{commit}}").stdout.strip()
    if not base_sha:
        raise WorkspaceError(f"base {base!r} does not resolve to a commit")
    target = destination(repo, task, path)
    target = os.path.abspath(target)
    if target == primary or target.startswith(primary + os.sep):
        raise WorkspaceError("worktree path must be outside the primary checkout")
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        raise WorkspaceError("worktree parent directory does not exist")
    with _file_lock(os.path.join(common, "agent-lifecycle.lock")):
        if os.path.lexists(target):
            raise WorkspaceError(f"{target} already exists; choose another path")
        if _git(source, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0:
            raise WorkspaceError(f"branch {branch} already exists; it was left untouched")
        stage = tempfile.mkdtemp(prefix=".agent-worktree.", dir=parent)
        stage_stat = os.stat(stage)
        stage_identity = [stage_stat.st_dev, stage_stat.st_ino]
        created_branch = False
        owned_gitdir = ""
        try:
            _git(source, "branch", branch, base_sha)
            created_branch = True
            _git(source, "worktree", "add", stage, branch)
            owned_gitdir = _gitdir(stage)
            _git(source, "worktree", "move", stage, target)
            info = os.stat(target)
            manifest = {
                "version": 1, "task": task, "session": session, "path": target,
                "gitdir": _gitdir(target), "common_dir": common, "primary": primary,
                "branch": branch, "base_sha": base_sha,
                "identity": secrets.token_hex(32), "dir_dev": info.st_dev, "dir_ino": info.st_ino,
                "state": "active",
            }
            _write_manifest(_gitpath(target, "agent-workspace.json"), manifest)
            return dict(manifest)
        except Exception as error:
            if created_branch:
                rollback_errors = _rollback(source, branch, base_sha, stage, target,
                                            owned_gitdir, stage_identity)
            else:
                rollback_errors = []
                if os.path.isdir(stage):
                    try:
                        os.rmdir(stage)
                    except OSError:
                        pass
            detail = f"; rollback also reported: {'; '.join(rollback_errors)}" if rollback_errors else ""
            raise WorkspaceError(f"workspace creation failed: {error}{detail}") from error


def _protected(primary):
    names = sorted(record.policy(primary)["protected"], key=lambda n: (n != "main", n != "master", n))
    refs = repostate.refs(repostate.locate(primary), "refs/heads/")
    found = [(name, refs[f"refs/heads/{name}"]) for name in names if f"refs/heads/{name}" in refs]
    if not found:
        raise WorkspaceError("no configured local protected branch exists to prove preservation")
    return found


def _ancestor(repo, sha, protected):
    for name, _ in protected:
        result = subprocess.run(["git", "-C", repo.top, "merge-base", "--is-ancestor", sha,
                                 f"refs/heads/{name}"], capture_output=True, timeout=30)
        if result.returncode == 0:
            return True
        if result.returncode != 1:
            raise WorkspaceError("Git could not verify that the work is preserved")
    return False


def _has_untracked_or_ignored(path):
    repo = repostate.locate(path)
    with repostate.Shadow(repo) as shadow:
        return bool(shadow.git("ls-files", "--others", "--ignored", "--exclude-standard", "-z"))


def _release_problems(manifest, discard_ignored=False, discard=False):
    path = manifest["path"]
    try:
        state = repostate.inspect(path)
    except repostate.InspectError as error:
        raise WorkspaceError(f"worktree could not be inspected: {error}") from error
    if state["top"] != path:
        raise WorkspaceError("workspace is not the root of its own Git worktree")
    if state["changed"] and not discard:
        raise WorkspaceError(f"workspace has {len(state['changed'])} changed or untracked file(s)")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        if os.path.lexists(os.path.join(manifest["gitdir"], marker)):
            raise WorkspaceError(f"workspace has an unfinished Git operation ({marker})")
    repo = repostate.locate(path)
    if not (discard_ignored or discard):
        disposable = record.policy(manifest["primary"])["disposable_ignored"]
        if not isinstance(disposable, list) or any(
                not isinstance(p, str) or any(part in ("", ".", "..") for part in p.split("/"))
                or any(c in p for c in "*?[]\\") for p in disposable):
            raise WorkspaceError("disposable_ignored must list relative file/directory paths without globs or dot segments")
        with repostate.Shadow(repo) as shadow:
            ignored = shadow.git("ls-files", "--others", "--ignored", "--exclude-standard", "-z").split("\0")
        # Ignored does not mean disposable: retain secrets/data, allow only common regenerated caches.
        caches = {"__pycache__", ".pytest_cache", "node_modules"}
        unknown = [p for p in ignored if p and p.split("/")[-1] != ".DS_Store"
                   and not caches.intersection(p.split("/")[:-1])
                   and not any(p == d or p.startswith(d + "/") for d in disposable)]
        if unknown:
            raise WorkspaceError("workspace contains ignored local files: " + ", ".join(unknown[:5])
                                 + "; preserve them or explicitly use finish --discard-ignored")
    branch_ref = f"refs/heads/{manifest['branch']}"
    tip = state["branches"].get(branch_ref)
    if not tip or (not discard and not _ancestor(repo, tip, _protected(manifest["primary"]))):
        raise WorkspaceError(f"branch {manifest['branch']} is not preserved in a protected branch")
    try:
        active = active_processes(path)
    except Exception as error:
        raise WorkspaceError(f"active processes could not be identified: {error}") from error
    if active:
        raise WorkspaceError(f"active processes still use the workspace: {', '.join(active)}")
    return state


def prepare_release(manifest):
    """Block new runtime attachment before the caller asks Slots to release its resources."""
    current = _validate(manifest)
    with _file_lock(os.path.join(current["common_dir"], "agent-lifecycle.lock")):
        with _file_lock(os.path.join(current["gitdir"], "agent-lifecycle.lock")):
            current = _validate(manifest)
            if current["state"] == "active":
                if _gitdir(current["primary"]) == current["gitdir"]:
                    raise WorkspaceError("refusing to dispose the primary worktree")
                current["state"] = "disposal_pending"
                _write_manifest(_gitpath(current["path"], "agent-workspace.json"), current)
            return dict(current)


def release(manifest, discard_ignored=False, discard=False):
    """Remove an owned inactive tree; only an explicit human discard waives work preservation."""
    current = _validate(manifest)
    common_lock = os.path.join(current["common_dir"], "agent-lifecycle.lock")
    with _file_lock(common_lock):
        with _file_lock(os.path.join(current["gitdir"], "agent-lifecycle.lock")):
            current = _validate(manifest)
            if _gitdir(current["primary"]) == current["gitdir"]:
                raise WorkspaceError("refusing to remove the primary worktree")
            if os.path.lexists(runtime_path(current["path"])):
                raise WorkspaceError("AgentSlots runtime is still attached; release it first")
            pending = dict(current, state="disposal_pending")
            if current["state"] == "active":
                _write_manifest(_gitpath(current["path"], "agent-workspace.json"), pending)
            # Recheck after publishing disposal_pending while the shared lifecycle lock is held.
            release_state = _release_problems(pending, discard_ignored, discard)
            try:
                _git(current["primary"], "worktree", "remove", *(["--force"] if discard else []), current["path"])
            except WorkspaceError as error:
                raise WorkspaceError(f"worktree removal failed; disposal remains pending for retry: {error}") from error
            branch_removed = False
            try:
                refs = [p for p, ref in _worktrees(current["primary"])
                        if ref == f"refs/heads/{current['branch']}"]
                if not refs:
                    ref = f"refs/heads/{current['branch']}"
                    tip = _git(current["primary"], "rev-parse", ref, check=False)
                    expected = release_state["branches"].get(ref)
                    if tip.returncode == 0 and expected == tip.stdout.strip() and \
                            (discard or _ancestor(repostate.locate(current["primary"]), expected,
                                                  _protected(current["primary"]))):
                        _git(current["primary"], "update-ref", "-d", ref, expected)
                        branch_removed = True
            except WorkspaceError:
                pass  # A concurrent ref change keeps the branch; the worktree itself is released.
            result = dict(current, state="released", branch_removed=branch_removed)
            return result
