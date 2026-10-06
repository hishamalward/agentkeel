"""agentkeel evidence: a test run's result, recorded by the hooks, bound to the code it ran on.

`task.py verify -- <command>` only runs the command. The PreToolUse guard records the start of the
call (its id, the command, HEAD and a tree id that covers uncommitted and untracked files); the
PostToolUse hook closes it. A result is "passed" only for a completion the host reports
unambiguously and only if HEAD and the tree did not move during the run. Everything else is
"unrecorded" or "stale", never passed. A run with no completion stays pending, which counts as
unrecorded. Shipping itself is gated by the repository's CI required check (checks.py); this
record is what the task can honestly say about its local runs.

Host facts (measured, docs/enforcement-design.md):
  Claude Code  PostToolUse arrives only when the command exits 0; tool_response.interrupted is
               false and a background start carries backgroundTaskId.
  Codex        PostToolUse carries no exit status, so its runs stay unrecorded.
"""
import os
import re
import subprocess
import tempfile
import time

from . import record

VERIFY_RE = re.compile(r"(^|[\s/\"'])task\.py[\"']?\s+verify(\s|$)")
KEEP = 20


def is_verify(command):
    return bool(command) and bool(VERIFY_RE.search(command))


def _git(cwd, *args, env=None):
    p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    return p.stdout.strip() if p.returncode == 0 else None


def code_state(cwd):
    """(HEAD, tree id of the working folder as it is, untracked files included)."""
    head = _git(cwd, "rev-parse", "HEAD")
    fd, index = tempfile.mkstemp(prefix="agentkeel-index-")
    os.close(fd)
    try:
        env = {"GIT_INDEX_FILE": index}
        if head:
            _git(cwd, "read-tree", "HEAD", env=env)
        _git(cwd, "add", "-A", env=env)
        tree = _git(cwd, "write-tree", env=env)
    finally:
        os.remove(index)
    return head, tree


def host_of(payload):
    return "codex" if "turn_id" in payload else "claude"


def start(rec, payload, environ=os.environ):
    """PreToolUse, after the guard allowed the call: remember a verify run's start."""
    ti = payload.get("tool_input") or {}
    command = str(ti.get("command") or "")
    call_id = payload.get("tool_use_id")
    if not rec or not call_id or not is_verify(command):
        return
    head, tree = code_state(payload.get("cwd") or os.getcwd())
    rec.setdefault("pending", [])
    rec["pending"] = [p for p in rec["pending"] if p.get("id") != call_id][-(KEEP - 1):] + [{
        "id": call_id, "command": command[:300], "head": head, "tree": tree, "at": int(time.time()),
        "background": bool(ti.get("run_in_background"))}]
    record.save(rec, environ)


def judge(pending, payload, now_state):
    """(result, reason) for a completion event."""
    if host_of(payload) == "codex":
        return "unrecorded", "the host's completion event carries no exit status"
    resp = payload.get("tool_response")
    if pending.get("background") or not isinstance(resp, dict) or resp.get("backgroundTaskId"):
        return "unrecorded", "the command ran in the background; its exit reached no hook"
    if resp.get("interrupted") is not False:
        return "unrecorded", "the command was interrupted, or the host did not say it was not"
    if (pending.get("head"), pending.get("tree")) != now_state:
        return "stale", "HEAD or the working tree changed while the command ran"
    return "passed", "exit 0, in the foreground, on unchanged code"


def finish(payload, environ=os.environ):
    """PostToolUse: close the matching pending run. Returns the evidence entry, or None."""
    session, call_id = payload.get("session_id"), payload.get("tool_use_id")
    rec = record.load(session, environ) if session else None
    if not rec or not call_id:
        return None
    pending = next((p for p in rec.get("pending") or [] if p.get("id") == call_id), None)
    if not pending:
        return None
    state = code_state(payload.get("cwd") or os.getcwd())
    result, reason = judge(pending, payload, state)
    entry = {"command": pending["command"], "result": result, "reason": reason,
             "head": pending.get("head"), "tree": pending.get("tree"),
             "at": pending.get("at"), "seconds": int(time.time()) - int(pending.get("at") or 0)}
    rec["pending"] = [p for p in rec.get("pending") or [] if p.get("id") != call_id]
    rec["evidence"] = (rec.get("evidence") or [])[-(KEEP - 1):] + [entry]
    record.save(rec, environ)
    return entry

