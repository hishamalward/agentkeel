"""Shared helpers: drive a hook exactly as the harness does (JSON on stdin, exit code back)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, "hooks")
sys.path.insert(0, HOOKS)
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
SESSION = "session-a"


def run_hook(name, payload, env=None, cwd=None):
    """Return (exit_code, stderr). payload may be a dict or a raw string (malformed input)."""
    path = os.path.join(HOOKS, name)
    cmd = [sys.executable, path] if name.endswith(".py") else ["bash", path]
    data = payload if isinstance(payload, str) else json.dumps(payload)
    clean = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID", "CODEX_THREAD_ID")}
    out = subprocess.run(cmd, input=data, text=True, capture_output=True, cwd=cwd,
                         env={**clean, **GIT_ENV, **(env or {})}, timeout=60)
    return out.returncode, out.stderr


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True,
                   env={**os.environ, **GIT_ENV})


class RepoCase(unittest.TestCase):
    """A temp git repo on main with one commit, realpath-resolved (macOS /var -> /private/var),
    and a private AGENTKEEL_HOME so records never leak between tests."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        # The shared checkout (`primary`) stays on `base`; tasks work in `repo`, a linked worktree
        # that starts on main, as every code task does (its own worktree, never the shared one).
        self.primary = os.path.join(self.tmp, "primary")
        self.repo = os.path.join(self.tmp, "repo")
        self.home = os.path.join(self.tmp, "agentkeel-home")
        subprocess.run(["git", "init", "-q", "-b", "base", self.primary], check=True)
        git(self.primary, "commit", "-q", "--allow-empty", "-m", "init")
        git(self.primary, "worktree", "add", "-q", self.repo, "-b", "main")
        os.makedirs(os.path.join(self.repo, "src"))
        self.env = {"AGENTKEEL_HOME": self.home}

    def tearDown(self):
        self._tmp.cleanup()

    def branch(self, name, repo=None):
        git(repo or self.repo, "checkout", "-q", "-b", name)

    def declare(self, size="small", allow=("implement",), task="x", session=SESSION,
                worktrees=None, write_roots=()):
        from agentkeel_core import record
        record.atomic_write_json(os.path.join(self.home, "tasks", session + ".json"), {
            "version": 1, "task": task, "session_id": session, "size": size,
            "permissions": sorted(allow), "worktrees": list(worktrees or [self.repo]),
            "write_roots": list(write_roots), "resources": [], "declared_at": int(time.time()),
            "evidence": [], "history": []})

    def record(self, session=SESSION):
        with open(os.path.join(self.home, "tasks", session + ".json")) as fh:
            return json.load(fh)

    def write(self, rel_or_abs, content="", session=SESSION, cwd=None):
        path = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(self.repo, rel_or_abs)
        return {"tool_name": "Write", "cwd": cwd or self.repo, "session_id": session,
                "tool_input": {"file_path": path, "content": content}}

    def bash(self, command, session=SESSION, cwd=None):
        return {"tool_name": "Bash", "cwd": cwd or self.repo, "session_id": session,
                "tool_input": {"command": command}}

    def hook(self, payload, env=None):
        return run_hook("task-guard.py", payload, env={**self.env, **(env or {})})
