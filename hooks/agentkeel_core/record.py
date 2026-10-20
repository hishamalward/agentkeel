"""agentkeel core: private task and repository state, approved boundaries, and the override log.

A task record answers three separate questions (project canon, #task-record):

  size         no-code | small | large               how much process the task buys
  kind         feature | fix | review | docs | chore   what the task is; fix turns on the debugging guards
  permissions  review, implement, merge, push, distribution-build, store-submission, paid-job,
               remote-write, publish
  resources    the worktrees and report folders the task owns

It is bound to one agent session (the host's session id), so a second session cannot inherit
it, and it lives outside the repository in AGENTKEEL_HOME (default ~/.agentkeel), which the
guards refuse to let Write/Edit touch. The agent writes it with task.py from its reading of
the human's request; it is the agent's declaration, not the human's consent, and the README's
capability table says so.
"""
import contextlib
import fnmatch
import json
import os
import re
import tempfile
import time

SIZES = ("no-code", "small", "large")
SIZE_ALIASES = {"medium": "small"}  # accepted for one release; two sizes since 0.9, and the smaller one wins
KINDS = ("feature", "fix", "review", "docs", "chore")
GUARDS = ("task", "secret", "fix")
MODES = ("block", "warn", "off")
PERMISSIONS = ("review", "implement", "merge", "push", "distribution-build", "store-submission",
               "paid-job", "remote-write", "publish")
DEFAULT_PROTECTED = ("main", "master")
POLICY_NAME = "agentkeel-policy.json"
# The session id each host gives the shell commands it runs. When one agent runs inside another
# (Codex started from a Claude Code shell), both variables are set; the nearest agent process
# among this process's ancestors is the one actually running the command.
HOST_SESSION_ENV = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_THREAD_ID"}

# Command classes that are never implied by shipping (decision 2). Matched against the command's
# argv joined by spaces, after `npx eas-cli` and friends are normalised to the tool name.
DEFAULT_COMMANDS = {
    "distribution-build": [r"^eas build(\s|$)", r"^xcodebuild\b.*\b(archive|-exportArchive)\b",
                           r"^fastlane\b.*\b(gym|build_app|build_ios_app|build_android_app)\b"],
    "store-submission": [r"^eas submit\b", r"^eas update\b", r"^npm publish\b", r"^xcrun altool\b.*--upload",
                         r"^fastlane\b.*\b(deliver|pilot|supply|upload_to_app_store|upload_to_testflight|upload_to_play_store)\b"],
    "merge": [r"^gh pr merge\b"],  # a PR merge moves the remote base branch: merge and push
    "push": [r"^gh pr merge\b", r"^railway up\b", r"^vercel\b.*--prod\b", r"^fly deploy\b", r"^netlify deploy\b.*--prod\b"],
    "paid-job": [],
}


def home(environ=os.environ):
    return os.path.realpath(os.path.expanduser(environ.get("AGENTKEEL_HOME") or "~/.agentkeel"))


def profile(environ=os.environ):
    """(path, text) of the human's standing preferences, AGENTKEEL_HOME/profile.md. The text is
    None when the file is missing, unreadable or empty. It is session context only: it grants no
    permission and changes no guard."""
    path = os.path.join(home(environ), "profile.md")
    text = read(path)
    return path, (text if text and text.strip() else None)


def nearest_host(pid=None):
    """'claude' or 'codex': the closest agent process above `pid` (default: this process)."""
    import subprocess
    pid = pid or os.getpid()
    for _ in range(40):
        try:
            out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True,
                                 text=True, timeout=5).stdout.strip()
        except Exception:
            return None
        if not out:
            return None
        ppid, _, comm = out.partition(" ")
        name = os.path.basename(comm.strip()).lower()
        if name == "claude":
            return "claude"
        if name.startswith("codex"):
            return "codex"
        try:
            pid = int(ppid)
        except ValueError:
            return None
        if pid <= 1:
            return None
    return None


SESSION_VAR = "AGENTKEEL_SESSION_ID"


def session_from_env(environ=os.environ):
    """This command's agent session id: AGENTKEEL_SESSION_ID (the guard lets an agent give only its
    own, inline); else the one host variable that is set; else, with both set, the variable of the
    nearest agent process. When that cannot be told (a sandbox that hides the process tree), None:
    task.py refuses rather than guess, because a guess can act on another session's record."""
    if environ.get(SESSION_VAR):
        return environ[SESSION_VAR]
    present = {h: environ[v] for h, v in HOST_SESSION_ENV.items() if environ.get(v)}
    if len(present) == 1:
        return next(iter(present.values()))
    if present:
        h = nearest_host()
        if h and present.get(h):
            return present[h]
    return None


def _safe(session_id):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id))


def record_path(session_id, environ=os.environ):
    return os.path.join(home(environ), "tasks", _safe(session_id) + ".json")


def load(session_id, environ=os.environ):
    if not session_id:
        return None
    try:
        with open(record_path(session_id, environ)) as fh:
            rec = json.load(fh)
    except Exception:
        return None
    if not isinstance(rec, dict) or rec.get("session_id") != session_id:
        return None  # a copied or hand-made file for another session grants nothing
    return rec


def save(rec, environ=os.environ):
    path = record_path(rec["session_id"], environ)
    atomic_write_json(path, rec)
    return path


def ownership_problem(rec):
    """A workspace manifest supersedes old session records, including legacy claims."""
    from . import workspace
    for path in rec.get("worktrees") or []:
        if not os.path.isdir(path):
            continue
        try:
            current = workspace.inspect(path)
            if current and (current["session"] != rec.get("session_id") or current["task"] != rec.get("task")):
                return "worktree ownership was transferred; declare your own task or explicitly resume it"
            if current and rec.get("workspace"):
                workspace.validate(rec["workspace"])
        except (workspace.WorkspaceError, OSError, ValueError) as error:
            return "worktree ownership is unavailable: " + str(error)
    return None


def atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(path):
    """An exclusive lock beside `path`, for read-modify-write of shared counters."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = open(path + ".lock", "w")
    try:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover (Windows)
            pass
        yield
    finally:
        fh.close()


def log_override(name, command, session_id, environ=os.environ):
    """Append one line per override used. The command line itself is in the transcript too."""
    path = os.path.join(home(environ), "overrides.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps({"at": int(time.time()), "override": name, "session_id": session_id,
                                 "command": command[:500]}) + "\n")
    except Exception:
        pass


def _touched_dirs(payload):
    """Every directory an act lands in: the session folder, each edited file's folder, and the
    folder of every shell command and git -C target in the line."""
    from . import gitops, host, shell
    cwd = payload.get("cwd") or os.getcwd()
    dirs = [cwd]
    for ev in host.events(payload, cwd):
        if ev.kind == "edit":
            d = os.path.dirname(ev.path)
            while d and not os.path.isdir(d) and os.path.dirname(d) != d:
                d = os.path.dirname(d)
            dirs.append(d)
        elif ev.kind == "command":
            for sc in shell.commands(ev.command, cwd):
                dirs.append(sc.cwd)
                if sc.argv and os.path.basename(sc.argv[0]) == "git":
                    call = gitops.parse(sc.argv, sc.cwd)
                    if call:
                        dirs.append(call.cwd)
    return dirs


def plugin_inactive(argv, payload, environ=os.environ):
    """Plugin hooks run in every repository; a guard started with --plugin acts only where an act
    lands in a repository registered in the private AGENTKEEL_HOME/opted-in.json. A project
    install needs no registration because its hooks already belong to that repository."""
    if "--plugin" not in argv:
        return False
    from . import gitops
    reg_path = os.path.join(home(environ), "opted-in.json")
    try:
        with open(reg_path) as fh:
            registry = json.load(fh)
    except Exception:
        registry = {}
    if not isinstance(registry, dict):
        registry = {}
    seen = set()
    for d in _touched_dirs(payload):
        top = gitops.toplevel(d) if d and os.path.isdir(d) else None
        if not top or top in seen:
            continue
        seen.add(top)
        common = gitops.common_dir(top) or os.path.realpath(top)
        if common in registry:
            return False
    return True


def policy_path(root):
    """The private policy shared by every linked worktree of `root`."""
    if not root:
        return None
    from . import gitops
    common = gitops.common_dir(root)
    return os.path.join(common, POLICY_NAME) if common else None


def policy_data(root):
    path = policy_path(root)
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_policy(root, data):
    if not isinstance(data, dict):
        raise ValueError("policy must be a JSON object")
    path = policy_path(root)
    if not path:
        raise ValueError("not inside a Git repository")
    atomic_write_json(path, data)
    return path


def activate(root, data=None, environ=os.environ):
    """Register one repository locally and create or update its private policy."""
    from . import gitops
    common = gitops.common_dir(root)
    if not common:
        raise ValueError("not inside a Git repository")
    path = os.path.join(home(environ), "opted-in.json")
    with locked(path):
        try:
            with open(path) as fh:
                registry = json.load(fh)
            if not isinstance(registry, dict):
                registry = {}
        except Exception:
            registry = {}
        new = common not in registry
        registry.setdefault(common, int(time.time()))
        atomic_write_json(path, registry)
    private = policy_path(root)
    if data is not None or not os.path.exists(private):
        save_policy(root, data or {})
    return new, path, private


def deactivate(root, environ=os.environ):
    """Remove one repository's local registration and private policy."""
    from . import gitops
    common = gitops.common_dir(root)
    if not common:
        raise ValueError("not inside a Git repository")
    path = os.path.join(home(environ), "opted-in.json")
    with locked(path):
        try:
            with open(path) as fh:
                registry = json.load(fh)
            if not isinstance(registry, dict):
                registry = {}
        except Exception:
            registry = {}
        registered = common in registry
        registry.pop(common, None)
        atomic_write_json(path, registry)
    private = policy_path(root)
    removed = bool(private and os.path.lexists(private))
    if removed:
        os.unlink(private)
    return registered, removed, path, private


def policy(root):
    """Private repository policy: protected branches and extra command classes."""
    data = policy_data(root)
    protected = set(data.get("protected_branches") or DEFAULT_PROTECTED)
    commands = {k: list(v) for k, v in DEFAULT_COMMANDS.items()}
    for k, v in (data.get("commands") or {}).items():
        if k in commands and isinstance(v, list):
            commands[k] += [str(x) for x in v]
    guards = {g: "block" for g in GUARDS}
    for k, v in (data.get("guards") or {}).items() if isinstance(data.get("guards"), dict) else []:
        if k in guards:
            guards[k] = v if v in MODES else "block"  # an unknown value blocks
    return {"protected": protected, "commands": commands, "guards": guards,
            "disposable_ignored": data.get("disposable_ignored", []),
            "require_check": str(data.get("require_check_before_push") or "")}


def guard_mode(name, cwd):
    """block, warn or off for one guard, from the private policy of the repository `cwd` is in.
    Outside any repository, or with no setting, a guard blocks."""
    from . import gitops
    try:
        root = gitops.toplevel(cwd) if cwd and os.path.isdir(cwd) else None
    except Exception:
        root = None
    return policy(os.path.realpath(root) if root else None)["guards"].get(name, "block")


def soften(name, text, cwd):
    """Apply a guard's mode to a refusal: block writes `text` to stderr and returns 2; warn lets
    the call through and shows the text to the human and the agent as a systemMessage; off is silent. The text carries the guard's own prefix (AGENTKEEL:, SECRET GUARD:, ...)."""
    import sys
    mode = guard_mode(name, cwd)
    if mode == "off":
        return 0
    if mode == "warn":
        sys.stdout.write(json.dumps({"systemMessage": "(warn mode, the call ran) " + text.rstrip()}) + "\n")
        return 0
    sys.stderr.write(text.rstrip() + "\n")
    return 2


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def matches(rel, patterns):
    for p in patterns:
        if p.endswith("/") and rel.startswith(p):
            return True
        if rel == p or fnmatch.fnmatchcase(rel, p):
            return True
    return False
