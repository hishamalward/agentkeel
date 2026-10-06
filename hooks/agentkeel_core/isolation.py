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
import subprocess
import time

from . import gitops, record

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
    scratch = os.path.join(scratch_root(environ), f"{os.path.basename(top)}-{task}")
    os.makedirs(scratch, exist_ok=True)
    rec = {"version": 1, "task": task, "host": host, "size": size,
           "permissions": sorted(set(permissions)), "repo": top,
           "repo_common_dir": gitops.common_dir(top), "clone": clone, "branch": branch,
           "base": base, "base_sha": base_sha, "scratch": scratch,
           "writable": _policy_writable(top), "opened_at": int(time.time()), "sessions": []}
    record.atomic_write_json(opened_path(task, environ), rec)
    if host == "claude":
        record.atomic_write_json(session_settings_path(task, environ), claude_settings(rec))
    return rec


def claude_settings(rec):
    """Session-only sandbox settings for Claude Code (`claude --settings <file>`). The working
    folder, the clone, is writable by default; the scratch folder and declared caches are added."""
    return {"sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                        "filesystem": {"allowWrite": [rec["scratch"]] + list(rec.get("writable") or [])}}}


def _toml_str(s):
    return json.dumps(str(s))  # a JSON string is a valid TOML basic string


def codex_args(rec):
    """Command-line overrides for one Codex session: a named profile defined and selected here
    only. The filesystem rules are one inline table, because a dotted -c key cannot hold a path
    that contains a dot."""
    name = "agentkeel-" + rec["task"]
    rules = {'":workspace_roots"': '{"."="write",".git"="write"}',
             _toml_str(rec["scratch"]): '"write"', '":tmpdir"': '"read"', '":slash_tmp"': '"read"'}
    for w in rec.get("writable") or []:
        rules[_toml_str(w)] = '"write"'
    table = "{" + ",".join(f"{k}={v}" for k, v in rules.items()) + "}"
    return ["-C", rec["clone"],
            "-c", f'permissions.{name}.extends=":workspace"',
            "-c", f"permissions.{name}.filesystem={table}",
            "-c", f"shell_environment_policy.set.TMPDIR={_toml_str(rec['scratch'])}",
            "-P", name]


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
