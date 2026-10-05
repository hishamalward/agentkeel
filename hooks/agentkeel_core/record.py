"""agentkeel core: the task record, the repo policy file, spec approval, and the override log.

A task record answers three separate questions (D-004):

  size         small | medium | large      how much process the task buys
  permissions  review, implement, merge, push, distribution-build, store-submission, paid-job
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

SIZES = ("small", "medium", "large")
PERMISSIONS = ("review", "implement", "merge", "push", "distribution-build", "store-submission",
               "paid-job")
DEFAULT_PROTECTED = ("main", "master")
SESSION_ENV = ("AGENTKEEL_SESSION_ID", "CLAUDE_CODE_SESSION_ID")

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


def session_from_env(environ=os.environ):
    for name in SESSION_ENV:
        if environ.get(name):
            return environ[name]
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


def policy(root):
    """agentkeel.json at the repository root: protected branches and extra command classes."""
    data = {}
    if root:
        try:
            with open(os.path.join(root, "agentkeel.json")) as fh:
                data = json.load(fh) or {}
        except Exception:
            data = {}
    protected = set(data.get("protected_branches") or DEFAULT_PROTECTED)
    commands = {k: list(v) for k, v in DEFAULT_COMMANDS.items()}
    for k, v in (data.get("commands") or {}).items():
        if k in commands and isinstance(v, list):
            commands[k] += [str(x) for x in v]
    return {"protected": protected, "commands": commands}


# ---- spec frontmatter -----------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def frontmatter(text):
    """Key/value pairs of a leading `---` block. Anything else (a code block, a later `---`) is
    not frontmatter, so a `status: approved` line pasted into the body approves nothing."""
    if not text.startswith("---"):
        return None
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line)
        if m:
            value = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("'\"")
            out[m.group(1).lower()] = value
    return None  # never closed


def approval(text):
    """(approved: bool, reason). Approved needs status, approver and date, all in frontmatter."""
    fm = frontmatter(text or "")
    if fm is None:
        return False, "has no frontmatter block at the top"
    status = (fm.get("status") or "missing").lower()
    if status != "approved":
        return False, f"has status '{status}'"
    if not fm.get("approved_by"):
        return False, "is marked approved but names no approved_by"
    if not DATE_RE.match(fm.get("approved_on") or ""):
        return False, "is marked approved but approved_on is not a YYYY-MM-DD date"
    return True, "approved"


def spec_path(worktree, task):
    return os.path.join(worktree, "docs", "specs", f"{task}-spec.md")


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


BACKTICK_RE = re.compile(r"`([^`]+)`")


def blast_radius(text):
    """(changes, must_not) path patterns from the spec's Blast radius section."""
    changes, must_not, mode = [], [], None
    for line in (text or "").split("\n"):
        if "**Changes**" in line:
            mode = changes
        elif "**Must not change**" in line:
            mode = must_not
        elif "**Boundary**" in line or line.startswith("## "):
            mode = None
        if mode is not None:
            tail = line.split(":", 1)[1] if ("**Changes**" in line or "**Must not change**" in line) and ":" in line else line
            mode.extend(p.strip() for p in BACKTICK_RE.findall(tail) if p.strip())
    return changes, must_not


def matches(rel, patterns):
    for p in patterns:
        if p.endswith("/") and rel.startswith(p):
            return True
        if rel == p or fnmatch.fnmatchcase(rel, p):
            return True
    return False
