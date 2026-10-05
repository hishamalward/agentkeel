"""agentkeel core: turn one git invocation into the operations a policy has to judge.

An operation is one of:

  push        a ref update on a remote; `targets` are destination branch names
  move        a local protected branch changes (commit, merge, reset, rebase, update-ref, ...)
  commit      a commit; `explicit` says whether it names its paths
  worktree    a worktree is created at `path` (recorded as owned by the task)
  destructive work that may not be yours is discarded (force push, reset --hard, ...)

Global options are honoured: every `-C <dir>`, `-c key=value`, `--git-dir` and `--work-tree`
changes which repository the operation lands in, and aliases are expanded once. The repository
facts (current branch, upstream, merge in progress) are read with git itself.
"""
import os
import subprocess
from dataclasses import dataclass, field

GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
                     "--config-env", "--super-prefix"}
GLOBAL_FLAGS = {"-p", "-P", "--paginate", "--no-pager", "--bare", "--no-replace-objects",
                "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs",
                "--no-optional-locks", "--no-advice", "--no-lazy-fetch"}
BUILTINS = {"add", "am", "apply", "bisect", "blame", "branch", "checkout", "cherry-pick", "clean",
            "clone", "commit", "config", "describe", "diff", "fetch", "filter-branch", "filter-repo",
            "gc", "grep", "init", "log", "ls-files", "merge", "mv", "notes", "pull", "push", "rebase",
            "reflog", "remote", "replace", "reset", "restore", "revert", "rev-parse", "rm", "show",
            "stash", "status", "switch", "symbolic-ref", "tag", "update-ref", "worktree", "help",
            "rev-list", "for-each-ref", "ls-remote", "cat-file", "check-ignore", "shortlog",
            "range-diff", "sparse-checkout", "submodule", "archive", "bundle", "format-patch"}
COMMIT_VALUE_OPTS = {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c",
                     "--reedit-message", "--fixup", "--squash", "--author", "--date", "-t",
                     "--template", "--cleanup", "--trailer", "--pathspec-from-file"}
PUSH_VALUE_OPTS = {"-o", "--push-option", "--receive-pack", "--exec", "--repo"}


@dataclass
class Op:
    kind: str
    name: str = ""
    targets: list = field(default_factory=list)
    explicit: bool = True
    paths: list = field(default_factory=list)
    path: str = ""
    local: bool = False
    remote: str = ""
    sources: dict = field(default_factory=dict)   # push: destination branch -> the rev it receives
    source: str = ""                               # move: the rev the branch becomes, when known


@dataclass
class GitCall:
    prefix: list          # global options to replay when asking git about the same repository
    cwd: str
    sub: str
    args: list
    config: dict


def run_git(call_or_cwd, *args, prefix=None):
    cwd = call_or_cwd.cwd if isinstance(call_or_cwd, GitCall) else call_or_cwd
    prefix = call_or_cwd.prefix if isinstance(call_or_cwd, GitCall) else (prefix or [])
    try:
        out = subprocess.run(["git", *prefix, *args], cwd=cwd if os.path.isdir(cwd) else None,
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def parse(argv, cwd):
    """argv starts with git. Returns a GitCall, or None when there is no subcommand."""
    i, prefix, config = 1, [], {}
    here = cwd
    while i < len(argv):
        a = argv[i]
        if a in ("-C", "-c") and i + 1 >= len(argv):
            return None
        if a == "-C" and i + 1 < len(argv):
            here = os.path.normpath(os.path.join(here, os.path.expanduser(argv[i + 1])))
            i += 2
        elif a == "-c" and i + 1 < len(argv):
            k, _, v = argv[i + 1].partition("=")
            config[k.lower()] = v
            prefix += ["-c", argv[i + 1]]
            i += 2
        elif a in GLOBAL_WITH_VALUE and i + 1 >= len(argv):
            return None  # an option missing its value: git itself refuses this
        elif a in GLOBAL_WITH_VALUE and i + 1 < len(argv):
            if a in ("--git-dir", "--work-tree"):
                prefix += [a, os.path.normpath(os.path.join(here, os.path.expanduser(argv[i + 1])))]
            i += 2
        elif "=" in a and a.split("=", 1)[0] in ("--git-dir", "--work-tree"):
            k, v = a.split("=", 1)
            prefix += [k, os.path.normpath(os.path.join(here, os.path.expanduser(v)))]
            i += 1
        elif a.startswith("--") and a.split("=", 1)[0] in GLOBAL_WITH_VALUE:
            i += 1
        elif a in GLOBAL_FLAGS or a.startswith("--exec-path"):
            i += 1
        else:
            break
    if i >= len(argv):
        return None
    return GitCall(prefix=prefix, cwd=here, sub=argv[i], args=list(argv[i + 1:]), config=config)


def expand_alias(call):
    """One level of alias expansion. Returns (call, shell_text): shell_text for `!` aliases."""
    if call.sub in BUILTINS:
        return call, None
    value = call.config.get(f"alias.{call.sub}") or run_git(call, "config", "--get", f"alias.{call.sub}")
    if not value:
        return call, None
    if value.startswith("!"):
        return call, value[1:] + " " + " ".join(call.args)
    import shlex
    try:
        words = shlex.split(value)
    except ValueError:
        return call, None
    if not words:
        return call, None
    return GitCall(prefix=call.prefix, cwd=call.cwd, sub=words[0], args=words[1:] + call.args,
                   config=call.config), None


def current_branch(call):
    return run_git(call, "symbolic-ref", "--short", "-q", "HEAD") or ""


def upstream_branch(call, branch):
    merge = run_git(call, "config", "--get", f"branch.{branch}.merge") if branch else None
    return merge.replace("refs/heads/", "", 1) if merge else ""


def toplevel(call_or_cwd):
    return run_git(call_or_cwd, "rev-parse", "--show-toplevel")


def is_primary(cwd):
    """True for a repository's main checkout (the shared one), False for a linked worktree."""
    git_dir = run_git(cwd, "rev-parse", "--path-format=absolute", "--git-dir")
    common = common_dir(cwd)
    return bool(git_dir and common) and os.path.realpath(git_dir) == common


def common_dir(call_or_cwd):
    d = run_git(call_or_cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.realpath(d) if d else None


def in_progress(call):
    """A merge, cherry-pick or revert waiting for its commit (a partial commit is impossible)."""
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        p = run_git(call, "rev-parse", "--git-path", name)
        if p and os.path.exists(os.path.join(call.cwd, p) if not os.path.isabs(p) else p):
            return True
    return False


def _flags(args):
    """Split args into (short flag letters, long flags, positionals after option values removed)."""
    shorts, longs, pos = set(), set(), []
    after_dashdash = False
    for a in args:
        if after_dashdash:
            pos.append(a)
        elif a == "--":
            after_dashdash = True
        elif a.startswith("--"):
            longs.add(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1:
            shorts.update(a[1:])
        else:
            pos.append(a)
    return shorts, longs, pos


def _positionals(args, value_opts):
    """Positional arguments after removing options, including those that take a separate value."""
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a in value_opts:
            i += 2
            continue
        if not a.startswith("-") or a == "-":
            pos.append(a)
        i += 1
    return pos


def _strip_ref(name):
    for p in ("refs/heads/", "heads/"):
        if name.startswith(p):
            return name[len(p):]
    return name


def push_ops(call, branch):
    args, force, delete, everything, dry = call.args, False, False, False, False
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        if a in PUSH_VALUE_OPTS:
            if a == "--repo" and i + 1 < len(args):
                pos.insert(0, args[i + 1])
            i += 2
            continue
        if a.startswith("--repo="):
            pos.insert(0, a.split("=", 1)[1])
        elif a.startswith("--"):
            key = a.split("=", 1)[0]
            force |= key in ("--force", "--force-with-lease", "--force-if-includes", "--mirror")
            delete |= key == "--delete"
            everything |= key in ("--all", "--branches", "--mirror")
            dry |= key == "--dry-run"
        elif a.startswith("-") and len(a) > 1:
            letters = a[1:]
            force |= "f" in letters
            delete |= "d" in letters
            dry |= "n" in letters
            if letters.endswith("o"):
                i += 1  # -o takes a value
        else:
            pos.append(a)
        i += 1
    if dry:
        return []
    remote = pos[0] if pos else ""
    refspecs = pos[1:]
    targets, deleted, sources = [], [], {}
    if everything:
        targets.append("*")
    for spec in refspecs:
        if spec.startswith("+"):
            force = True
            spec = spec[1:]
        if ":" in spec:
            src, dst = spec.split(":", 1)
            if not src:
                deleted.append(_strip_ref(dst))
            dst = dst or src
        else:
            src = dst = spec
        if dst in ("HEAD", "@"):
            dst = branch or "HEAD"
        dst = _strip_ref(dst)
        if delete:
            deleted.append(dst)
        # a destination built from a variable or a command substitution is not known: any branch
        targets.append("*" if "*" in dst or "$" in dst or "__agentkeel_subst__" in dst else dst)
        sources.setdefault(dst, src or "")
    if not refspecs and not everything:
        targets.append(branch or "HEAD")
        sources[branch or "HEAD"] = "HEAD"
        up = upstream_branch(call, branch)
        if up:
            targets.append(up)
            sources[up] = "HEAD"
        name = remote or "origin"
        configured = [call.config[k] for k in call.config if k == f"remote.{name}.push".lower()]
        configured += (run_git(call, "config", "--get-all", f"remote.{name}.push") or "").split("\n")
        for spec in filter(None, configured):
            dst = spec.lstrip("+").split(":", 1)[-1]
            if dst in ("HEAD", "@"):
                dst = branch or "HEAD"
            targets.append("*" if "*" in dst else _strip_ref(dst))
            src_part = spec.lstrip("+").split(":", 1)[0] if ":" in spec else "HEAD"
            sources[_strip_ref(dst)] = src_part or "HEAD"
            if spec.startswith("+"):
                force = True
    # explicit: every destination came from a refspec on this command line, so its source is known.
    # A bare push (current branch, upstream, remote.*.push) or --all depends on state outside it.
    ops = [Op("push", targets=targets, local=(remote == "."), remote=remote, sources=sources,
              explicit=bool(refspecs) and not everything)]
    if force:
        ops.append(Op("destructive", name="force push"))
    for d in deleted:
        ops.append(Op("destructive", name=f"remote branch delete ({d})", targets=[d]))
    return ops


def commit_explicit(call):
    """Does this commit name its paths (pathspec or --pathspec-from-file)?"""
    args, i, paths = call.args, 0, []
    all_flag = False
    while i < len(args):
        a = args[i]
        if a == "--":
            paths += args[i + 1:]
            break
        if a in COMMIT_VALUE_OPTS:
            if a == "--pathspec-from-file":
                return True, ["<from file>"], False
            i += 2
            continue
        if a.startswith("--"):
            key = a.split("=", 1)[0]
            if key == "--pathspec-from-file":
                return True, ["<from file>"], False
            all_flag |= key in ("--all", "--include")
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            letters = a[1:]
            all_flag |= "a" in letters or "i" in letters
            # a short option that takes a value consumes the rest of the word or the next word
            for j, ch in enumerate(letters):
                if ch in "mFCctS":
                    if j == len(letters) - 1 and ch != "S":
                        i += 1
                    break
            i += 1
            continue
        paths.append(a)
        i += 1
    return bool(paths), paths, all_flag


def _moves_by_reset(call):
    shorts, longs, pos = _flags(call.args)
    if longs & {"--soft", "--hard", "--mixed", "--keep", "--merge"}:
        return True
    if "--" in call.args or not pos:
        return False
    first = pos[0]
    if os.path.exists(os.path.join(call.cwd, first)):
        return False
    return run_git(call, "rev-parse", "--verify", "--quiet", f"{first}^{{commit}}") is not None


def switched_to(call):
    """The branch a checkout/switch in this call leaves HEAD on, or None."""
    if call.sub not in ("checkout", "switch") or "--" in call.args:
        return None
    pos = _positionals(call.args, {"-b", "-B", "-c", "-C", "--orphan"})
    for flag in ("-b", "-B", "-c", "-C", "--orphan"):
        if flag in call.args:
            i = call.args.index(flag)
            return call.args[i + 1] if i + 1 < len(call.args) else None
    return _strip_ref(pos[0]) if pos else None


def ops_for(call, protected, branch=None):
    """The operations one git call performs. `protected` is the set of protected branch names.
    `branch` overrides the current branch when an earlier command in the same line switched it."""
    sub, args = call.sub, call.args
    branch = branch if branch is not None else current_branch(call)
    on_protected = branch in protected
    shorts, longs, pos = _flags(args)
    ops = []

    def move(name, source=""):
        ops.append(Op("move", name=name, targets=[branch], source=source))

    if sub == "push":
        return push_ops(call, branch)

    if sub == "commit":
        if "--dry-run" in longs:
            return []
        explicit, paths, all_flag = commit_explicit(call)
        if in_progress(call):
            explicit = True
        if all_flag:
            explicit = False
        ops.append(Op("commit", explicit=explicit, paths=paths, targets=[branch]))
        if on_protected:
            move("commit")
    elif sub in ("merge", "pull", "cherry-pick", "revert", "am"):
        if not longs & {"--abort", "--quit", "--skip"} and on_protected:
            # a fast-forward merge of one named rev makes the branch exactly that rev
            ff = sub == "merge" and "--ff-only" in longs and len(pos) == 1
            move(sub, pos[0] if ff else "")
        if sub == "pull":
            for spec in pos[1:]:
                dst = _strip_ref(spec.split(":", 1)[1]) if ":" in spec else ""
                if dst in protected:
                    ops.append(Op("move", name="pull into a protected ref", targets=[dst]))
    elif sub == "rebase":
        pos = _positionals(args, {"--onto", "-s", "--strategy", "-X", "--strategy-option", "-x", "--exec",
                                  "-C", "--whitespace"})
        if not longs & {"--abort", "--quit", "--skip", "--continue", "--edit-todo", "--show-current-patch"}:
            if on_protected:
                move("rebase")
            if len(pos) >= 2 and pos[1] in protected:
                ops.append(Op("move", name="rebase of a protected branch", targets=[pos[1]]))
    elif sub == "reset":
        if "--hard" in longs:
            ops.append(Op("destructive", name="git reset --hard"))
        if on_protected and _moves_by_reset(call):
            move("reset", pos[0] if pos and "--" not in call.args else "")
    elif sub == "update-ref":
        refs = [_strip_ref(p) for p in pos[:1]]
        if "d" in shorts:
            ops.append(Op("destructive", name="git update-ref -d"))
        for r in refs:
            if r in protected:
                ops.append(Op("move", name="update-ref", targets=[r], source=pos[1] if len(pos) > 1 else ""))
    elif sub == "fetch":
        for spec in pos[1:]:
            spec = spec.lstrip("+")
            if ":" in spec:
                dst = _strip_ref(spec.split(":", 1)[1])
                if dst in protected:
                    local = pos[0] == "." if pos else False
                    ops.append(Op("move", name="fetch into a protected ref", targets=[dst],
                                  source=spec.split(":", 1)[0] if local else ""))
    elif sub == "branch":
        deleting = "d" in shorts or "D" in shorts or "--delete" in longs
        forced = "D" in shorts or "f" in shorts or "--force" in longs
        if deleting and forced:
            ops.append(Op("destructive", name="git branch -D"))
        if deleting:
            for p in pos:
                if p in protected:
                    ops.append(Op("destructive", name=f"delete of {p}"))
        elif forced or "M" in shorts or "C" in shorts:
            target = pos[-1] if pos and ("M" in shorts or "C" in shorts or "m" in shorts) else (pos[0] if pos else "")
            if target in protected:
                ops.append(Op("move", name="branch -f/-M onto a protected branch", targets=[target]))
    elif sub in ("checkout", "switch"):
        create = None
        for flag in ("B", "C"):
            if flag in shorts and pos:
                create = pos[0]
        if "--force-create" in longs and pos:
            create = pos[0]
        if create in protected:
            ops.append(Op("move", name=f"{sub} -B onto a protected branch", targets=[create]))
        if "f" in shorts or "--force" in longs or "--discard-changes" in longs:
            ops.append(Op("destructive", name=f"git {sub} --force"))
        if sub == "checkout" and "--" in args:
            after = args[args.index("--") + 1:]
            if any(p in (".", ":/", "*") for p in after):
                ops.append(Op("destructive", name="git checkout of the whole tree"))
        elif sub == "checkout" and any(p in (".", ":/") for p in pos):
            ops.append(Op("destructive", name="git checkout of the whole tree"))
    elif sub == "restore":
        staged_only = ("S" in shorts or "--staged" in longs) and not ("W" in shorts or "--worktree" in longs)
        if not staged_only and any(p in (".", ":/", "*") for p in pos):
            ops.append(Op("destructive", name="git restore of the whole tree"))
    elif sub == "clean":
        if ("f" in shorts or "--force" in longs) and not ("n" in shorts or "--dry-run" in longs):
            ops.append(Op("destructive", name="git clean -f"))
    elif sub == "stash":
        action = pos[0] if pos else ""
        if action in ("drop", "clear", "pop"):
            ops.append(Op("destructive", name=f"git stash {action} (the stash is shared by every worktree)"))
    elif sub == "worktree":
        action = pos[0] if pos else ""
        if action == "add" and len(pos) >= 2:
            # value-taking options of `worktree add` (-b/-B <branch>) were not removed by _flags
            rest = [a for a in args[1:]]
            path, j = None, 0
            while j < len(rest):
                a = rest[j]
                if a in ("-b", "-B", "--reason"):
                    j += 2
                    continue
                if a.startswith("-"):
                    j += 1
                    continue
                path = a
                break
            if path:
                ops.append(Op("worktree", path=os.path.normpath(os.path.join(call.cwd, os.path.expanduser(path)))))
        if action == "remove" and ("f" in shorts or "--force" in longs):
            ops.append(Op("destructive", name="git worktree remove --force"))
    elif sub == "reflog" and pos[:1] == ["expire"]:
        ops.append(Op("destructive", name="git reflog expire"))
    elif sub == "gc" and any(a.startswith("--prune=now") for a in args):
        ops.append(Op("destructive", name="git gc --prune=now"))
    elif sub in ("filter-branch", "filter-repo"):
        ops.append(Op("destructive", name=f"git {sub}"))
    return ops
