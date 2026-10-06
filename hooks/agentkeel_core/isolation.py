"""agentkeel isolation: a task in its own clone, with a write boundary set before its session starts.

The human runs `task.py open` in the shared checkout. It makes an independent clone of the
repository (`git clone --no-local`: its own object store, no alternates, no hard links), a
scratch folder, and an opened-task record in AGENTKEEL_HOME. It then starts the host in the clone
with that session's sandbox boundary: Claude Code through `--settings <file>`, Codex through
command-line overrides only. Nothing changes in user or project settings, and no other session's
boundary moves.

The session does not exist yet when `open` runs, so the opened-task record is keyed by the task
id. The SessionStart hook, which runs outside the sandbox, binds the session to it when the
session starts inside the task's clone: it writes the usual per-session task record, so the
guards judge the session as before. The sandbox makes AGENTKEEL_HOME, the shared checkout and
every other task's folders unwritable to the session's commands; see docs/enforcement-design.md.
"""
import json
import os
import re
import secrets
import stat
import subprocess
import time

from . import gitops, record, repostate

CLONE_ID_FILE = "agentkeel-clone-id"
# Read-only to the task's session, inside its clone: what git runs programs from (config, hooks),
# what redirects where git reads config (commondir), and what sets git's submodule rules
# (.gitmodules, and the exclude file that hides the one harden_clone adds). A host runs its own git
# in the clone outside the sandbox, so the session must not be able to change what that git
# executes. See harden_clone.
GUARDED = (".git/config", ".git/hooks", ".git/commondir", ".git/info/exclude", ".gitmodules")
TASK_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
HOSTS = ("claude", "codex")


def opened_dir(environ=os.environ):
    return os.path.join(record.home(environ), "opened")


def opened_path(task, environ=os.environ):
    return os.path.join(opened_dir(environ), task + ".json")


def session_settings_path(task, environ=os.environ):
    return os.path.join(record.home(environ), "sessions", task + ".claude.json")


def scratch_root(environ=os.environ):
    """Outside AGENTKEEL_HOME: the scratch folder is writable to the session, the home is not."""
    return os.path.realpath(os.path.expanduser(environ.get("AGENTKEEL_SCRATCH") or "~/.cache/agentkeel-scratch"))


def load_opened(task, environ=os.environ):
    try:
        with open(opened_path(task, environ)) as fh:
            rec = json.load(fh)
    except Exception:
        return None
    return rec if isinstance(rec, dict) and rec.get("task") == task else None


def all_opened(environ=os.environ):
    out = []
    try:
        names = sorted(os.listdir(opened_dir(environ)))
    except OSError:
        return out
    for name in names:
        if name.endswith(".json"):
            rec = load_opened(name[:-5], environ)
            if rec:
                out.append(rec)
    return out


def writable_extra(policy_data):
    """Declared caches from agentkeel.json "writable": absolute paths only, never a home or root."""
    home = os.path.realpath(os.path.expanduser("~"))
    out = []
    for p in policy_data or []:
        real = os.path.realpath(os.path.expanduser(str(p)))
        if os.path.isabs(os.path.expanduser(str(p))) and real not in ("/", home):
            out.append(real)
    return out


def _policy_writable(repo):
    try:
        with open(os.path.join(repo, "agentkeel.json")) as fh:
            return writable_extra((json.load(fh) or {}).get("writable"))
    except Exception:
        return []


class OpenError(Exception):
    pass


def _git(cwd, *args):
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise OpenError(f"git {' '.join(args)} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def harden_clone(clone):
    """Fix, before the session starts, the git settings it could otherwise use to make git run a
    program for whoever runs git in the clone outside the sandbox (the host does: Codex runs
    `git status` there). The sandbox keeps the session from changing these afterwards (GUARDED).

    A nested repository with its own config is the one route that stays inside the writable work
    tree: git runs `status` inside a nested repository that the index lists, with that repository's
    config. So git is told to ignore nested repositories when it reports changes, for every path
    and for every submodule the repository names. A .gitmodules entry could turn that off again for
    a path, so the file is made to exist: git then reads it from the work tree, where the session
    cannot write it, and never from the index or a commit, where it can."""
    _git(clone, "config", "diff.ignoreSubmodules", "all")
    modules = os.path.join(clone, ".gitmodules")
    if os.path.lexists(modules):
        p = subprocess.run(["git", "config", "-z", "-f", modules, "--name-only", "--get-regexp", r"^submodule\..*\.path$"],
                           capture_output=True, text=True)
        for key in filter(None, p.stdout.split("\0")):
            _git(clone, "config", key[:-len(".path")] + ".ignore", "all")
    else:
        open(modules, "w").close()
        with open(os.path.join(clone, ".git", "info", "exclude"), "a") as fh:
            fh.write("# agentkeel: an empty .gitmodules pins where git reads submodule settings (isolation.py)\n/.gitmodules\n")


def open_task(repo, task, host, size, permissions, base=None, branch=None, path=None,
              environ=os.environ):
    """Create the clone, the scratch folder and the opened-task record. Returns the record."""
    if not TASK_RE.match(task or ""):
        raise OpenError("task id must be kebab-case (a-z, 0-9, -), e.g. json-flag")
    if host not in HOSTS:
        raise OpenError(f"--host must be one of {', '.join(HOSTS)}")
    top = gitops.toplevel(repo)
    if not top:
        raise OpenError(f"{repo} is not inside a git repository")
    top = os.path.realpath(top)
    if load_opened(task, environ):
        raise OpenError(f"task '{task}' is already open; `task.py release {task}` ends it")
    base = base or gitops.current_branch(top) or "main"
    branch = branch or f"feat/{task}"
    clone = os.path.realpath(os.path.expanduser(path)) if path else \
        os.path.join(os.path.dirname(top), f"{os.path.basename(top)}-{task}")
    if os.path.lexists(clone):
        raise OpenError(f"{clone} already exists; choose another --path")
    if clone == top or clone.startswith(top + os.sep):
        raise OpenError("the clone must be outside the repository (a sibling folder)")
    base_sha = _git(top, "rev-parse", "--verify", f"{base}^{{commit}}")
    _git(os.path.dirname(clone), "clone", "-q", "--no-local", "--branch", base, top, clone)
    _git(clone, "switch", "-q", "-c", branch)
    harden_clone(clone)
    scratch = os.path.join(scratch_root(environ), f"{os.path.basename(top)}-{task}")
    os.makedirs(scratch, exist_ok=True)
    st = os.lstat(clone)
    token = secrets.token_hex(16)
    with open(os.path.join(clone, ".git", CLONE_ID_FILE), "w") as fh:
        fh.write(token + "\n")
    rec = {"version": 1, "task": task, "host": host, "size": size,
           "permissions": sorted(set(permissions)), "repo": top,
           "repo_common_dir": gitops.common_dir(top), "clone": clone, "branch": branch,
           "base": base, "base_sha": base_sha, "scratch": scratch, "clone_id": [st.st_dev, st.st_ino], "clone_token": token,
           "writable": _policy_writable(top), "opened_at": int(time.time()), "sessions": []}
    record.atomic_write_json(opened_path(task, environ), rec)
    if host == "claude":
        record.atomic_write_json(session_settings_path(task, environ), claude_settings(rec))
    return rec


def claude_settings(rec):
    """Session-only sandbox settings for Claude Code (`claude --settings <file>`). The working
    folder, the clone, is writable by default; the scratch folder and declared caches are added."""
    return {"sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                        "filesystem": {"allowWrite": [rec["scratch"]] + list(rec.get("writable") or []),
                                       "denyWrite": [os.path.join(rec["clone"], g) for g in GUARDED]}}}


def _toml_str(s):
    return json.dumps(str(s))  # a JSON string is a valid TOML basic string


def codex_args(rec):
    """Command-line overrides for one Codex session: a named profile defined and selected here
    only. The filesystem rules are one inline table, because a dotted -c key cannot hold a path
    that contains a dot."""
    name = "agentkeel-" + rec["task"]
    # .claude holds a project install's hook scripts; Codex trusts a hook's command, not its file
    roots = {".": "write", ".git": "write", ".claude": "read", **{g: "read" for g in GUARDED}}
    rules = {'":workspace_roots"': "{" + ",".join(f"{_toml_str(k)}={_toml_str(v)}" for k, v in roots.items()) + "}",
             _toml_str(rec["scratch"]): '"write"', '":tmpdir"': '"read"', '":slash_tmp"': '"read"'}
    for w in rec.get("writable") or []:
        rules[_toml_str(w)] = '"write"'
    table = "{" + ",".join(f"{k}={v}" for k, v in rules.items()) + "}"
    return ["-C", rec["clone"],
            "-c", f'permissions.{name}.extends=":workspace"',
            "-c", f"permissions.{name}.filesystem={table}",
            "-c", f"shell_environment_policy.set.TMPDIR={_toml_str(rec['scratch'])}",
            "-c", f"default_permissions={_toml_str(name)}"]  # `codex exec` has no -P


def launch_argv(rec, environ=os.environ):
    if rec["host"] == "claude":
        return ["claude", "--settings", session_settings_path(rec["task"], environ)]
    return ["codex", *codex_args(rec)]


def bind(session_id, cwd, environ=os.environ):
    """SessionStart: if this session starts inside an opened task's clone and has no task record
    yet, give it the opened task's record. Returns the opened record, or None."""
    if not session_id or not cwd:
        return None
    here = os.path.realpath(cwd)
    for rec in all_opened(environ):
        clone = rec.get("clone") or ""
        if here != clone and not here.startswith(clone + os.sep):
            continue
        current = record.load(session_id, environ)
        if current and current.get("task") != rec["task"]:
            return None  # the session already declared another task; leave it
        if not current:
            record.save({"version": 1, "task": rec["task"], "session_id": session_id,
                         "size": rec.get("size") or "small", "permissions": rec.get("permissions") or [],
                         "worktrees": [clone], "clone": clone, "write_roots": [],
                         "resources": [], "declared_at": int(time.time()), "evidence": [],
                         "history": [], "scratch": rec["scratch"], "opened": True}, environ)
        with record.locked(opened_path(rec["task"], environ)):
            fresh = load_opened(rec["task"], environ) or rec
            if session_id not in fresh.get("sessions", []):
                fresh.setdefault("sessions", []).append(session_id)
                record.atomic_write_json(opened_path(rec["task"], environ), fresh)
        return rec
    return None


# ---- import and release (the human's commands) ------------------------------------------------

SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def staging_ref(task):
    return f"refs/agentkeel/import/{task}"


def accepted_ref(task):
    return f"refs/agentkeel/accepted/{task}"


def _fixed_git(repo, *args):
    """git in the shared repository with a fixed program, an emptied environment and no hooks:
    nothing from the task's clone or the session's environment chooses what runs."""
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": os.path.expanduser("~"),
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false",
                           "-c", "protocol.file.allow=always", *args], capture_output=True, text=True, env=env)


def import_task(task, sha, environ=os.environ):
    """Fetch the task's branch from its recorded clone into a staging ref of the shared
    repository, and accept it only if it is exactly `sha`. Returns the accepted SHA. Holds the
    lock release takes, so a release never runs between the fetch and the accept."""
    if not SHA_RE.match(sha or ""):
        raise OpenError("--sha needs the full commit id (40 or 64 hex characters)")
    with record.locked(opened_path(task, environ)):
        return _import_locked(task, sha, environ)


def _import_locked(task, sha, environ):
    rec = load_opened(task, environ)
    if not rec:
        raise OpenError(f"no opened task '{task}'")
    branch = rec["branch"]
    if branch.startswith(("-", "refs/")) or ":" in branch or ".." in branch:
        raise OpenError(f"the recorded branch '{branch}' is not a plain branch name")
    repo, stage = rec["repo"], staging_ref(task)
    fetch = _fixed_git(repo, "fetch", "-q", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                       rec["clone"], f"+refs/heads/{branch}:{stage}")
    if fetch.returncode != 0:
        raise OpenError(f"the fetch from {rec['clone']} failed: {(fetch.stderr or '').strip()[:300]}")
    got = _fixed_git(repo, "rev-parse", "--verify", f"{stage}^{{commit}}").stdout.strip()
    if got != sha:
        _fixed_git(repo, "update-ref", "-d", stage)
        raise OpenError(f"the clone's {branch} is at {got[:12] or '?'}, not {sha[:12]}: nothing accepted.\n"
                        "Import the commit that was reviewed and tested, by its full id.")
    _fixed_git(repo, "update-ref", accepted_ref(task), sha)
    _fixed_git(repo, "update-ref", "-d", stage)
    return sha


def _reachable_in_repo(repo, sha):
    if _fixed_git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return False
    out = _fixed_git(repo, "for-each-ref", "--contains", sha, "--format=%(refname)",
                     "refs/heads", "refs/agentkeel/accepted").stdout
    return bool(out.strip())


# a fixed system path, never the session's PATH: macOS keeps lsof in /usr/sbin, Linux in /usr/bin
LSOF = next((p for p in ("/usr/sbin/lsof", "/usr/bin/lsof") if os.path.exists(p)), "/usr/sbin/lsof")


def active_processes(clone):
    """Process ids whose working folder is inside the clone (a session or its tools still run).
    Raises OpenError when the processes cannot be listed: unknown is not "none"."""
    try:
        p = subprocess.run([LSOF, "-w", "-a", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OpenError(f"the processes could not be listed ({e}), so nothing is deleted") from e
    if p.returncode != 0 or not p.stdout.strip():
        raise OpenError(f"lsof could not list the processes (exit {p.returncode}), so nothing is deleted")
    pids, pid = [], None
    for line in p.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid and pid != str(os.getpid()):
            path = os.path.realpath(line[1:])
            if path == clone or path.startswith(clone + os.sep):
                pids.append(pid)
    return sorted(set(pids))


def release_problems(rec):
    """What is not preserved: an empty list means the clone holds nothing the shared repository
    lacks. Checked at the moment of release, under the release lock. The clone is read without its
    own config (repostate.py), and a clone that cannot be read is a problem, never "clean"."""
    repo, clone = rec["repo"], rec["clone"]
    try:
        st = repostate.inspect(clone)
    except repostate.InspectError as e:
        return [f"the clone could not be inspected ({e}), so its work is not known to be preserved"]
    if st["top"] != clone:
        return [f"{clone} is not the top of its own repository, so its work is not known to be preserved"]
    problems = []
    tip = st["head"]
    if tip and not _reachable_in_repo(repo, tip):
        problems.append(f"the clone's tip {tip[:12]} is not in the shared repository (task.py import it first)")
    for name, sha in sorted(st["branches"].items()):
        if not _reachable_in_repo(repo, sha):
            problems.append(f"{name} at {sha[:12]} is not in the shared repository")
    for sha in st["stashes"]:
        if not _reachable_in_repo(repo, sha):
            problems.append(f"stash entry {sha[:12]} is not in the shared repository")
    if st["changed"]:
        problems.append(f"the clone has {len(st['changed'])} changed or untracked file(s)")
    return problems


def identity_problem(rec):
    """None when the folder at the recorded path is the clone `open` made, else why it is not
    proven to be. Two proofs: the folder's device and inode (a file system can reuse an inode
    number for a new folder) and the random id `open` wrote into its .git. A folder that is not
    proven to be the clone is never deleted, even with --discard."""
    clone = rec.get("clone") or ""
    home = os.path.realpath(os.path.expanduser("~"))
    repo = os.path.realpath(rec.get("repo") or "/")
    if not os.path.isabs(clone) or os.path.realpath(clone) != clone or clone in ("/", home) \
            or clone == repo or repo.startswith(clone + os.sep):
        return f"the recorded clone path {clone!r} is not a separate folder beside the repository"
    if not os.path.lexists(clone):
        return None
    st = os.lstat(clone)
    if not stat.S_ISDIR(st.st_mode):
        return f"{clone} is not a folder"
    want = rec.get("clone_id")
    if not want or [st.st_dev, st.st_ino] != list(want):
        return f"{clone} is not the folder task.py open made (another folder now has its name)"
    try:
        token = repostate._read(os.path.join(clone, ".git", CLONE_ID_FILE)).strip()
    except repostate.InspectError:
        token = None
    if not rec.get("clone_token") or token != rec["clone_token"]:
        return f"{clone} is not proven to be the folder task.py open made: its .git lacks the id open wrote"
    return None


def release_task(task, discard=False, environ=os.environ):
    """Delete the task's clone, scratch folder and records. Refused while a process works in the
    clone, and, unless the human discards, while any of the clone's work is not preserved."""
    import shutil
    path = opened_path(task, environ)
    with record.locked(path):
        rec = load_opened(task, environ)
        if not rec:
            raise OpenError(f"no opened task '{task}'")
        clone = rec["clone"]
        wrong = identity_problem(rec)
        if wrong:
            raise OpenError(f"{wrong}.\nNothing is deleted, not even with --discard; remove it yourself if it must go.")
        problems = []
        if os.path.lexists(clone):
            busy = active_processes(clone)
            if busy:
                raise OpenError(f"processes still work in {clone} (pid {', '.join(busy)}): end the session first")
            problems += release_problems(rec)
            if problems and not discard:
                raise OpenError("not released, so no work is lost:\n  " + "\n  ".join(problems)
                                + f"\nTo delete it anyway: task.py release {task} --discard")
        repo = rec["repo"]
        _fixed_git(repo, "update-ref", "-d", staging_ref(task))
        acc = _fixed_git(repo, "rev-parse", "--verify", "-q", accepted_ref(task)).stdout.strip()
        if acc and _fixed_git(repo, "for-each-ref", "--contains", acc, "--format=x", "refs/heads").stdout.strip():
            _fixed_git(repo, "update-ref", "-d", accepted_ref(task))  # a branch keeps it now
        shutil.rmtree(clone, ignore_errors=True)
        shutil.rmtree(rec["scratch"], ignore_errors=True)
        for sid in rec.get("sessions") or []:
            bound = record.load(sid, environ)
            if bound and bound.get("task") == task and bound.get("clone") == clone:
                os.remove(record.record_path(sid, environ))
        for p in (session_settings_path(task, environ), path):
            if os.path.exists(p):
                os.remove(p)
    if os.path.exists(path + ".lock"):
        os.remove(path + ".lock")
    return problems
