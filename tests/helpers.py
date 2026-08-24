"""Shared helpers: drive a hook exactly as the harness does (JSON on stdin, exit code back)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}


def run_hook(name, payload, env=None, cwd=None):
    """Return (exit_code, stderr). payload may be a dict or a raw string (malformed input)."""
    path = os.path.join(HOOKS, name)
    cmd = [sys.executable, path] if name.endswith(".py") else ["bash", path]
    data = payload if isinstance(payload, str) else json.dumps(payload)
    out = subprocess.run(cmd, input=data, text=True, capture_output=True, cwd=cwd,
                         env={**os.environ, **GIT_ENV, **(env or {})}, timeout=60)
    return out.returncode, out.stderr


class RepoCase(unittest.TestCase):
    """A temp git repo on main with one commit, realpath-resolved (macOS /var -> /private/var)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(os.path.join(self._tmp.name, "repo"))
        os.makedirs(os.path.join(self.repo, "src"))
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "commit", "-q", "--allow-empty", "-m", "init"],
                       check=True, env={**os.environ, **GIT_ENV})

    def tearDown(self):
        self._tmp.cleanup()

    def branch(self, name):
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "-b", name], check=True)

    def declare(self, tier, slug="x", expires_in=3600):
        import time
        d = os.path.join(self.repo, ".claude", "state")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "agentkeel-tier.json"), "w") as fh:
            json.dump({"tier": tier, "slug": slug, "declared_at": int(time.time()),
                       "expires_at": int(time.time()) + expires_in}, fh)

    def write(self, rel):
        return {"tool_name": "Write", "cwd": self.repo,
                "tool_input": {"file_path": os.path.join(self.repo, rel), "content": ""}}

    def bash(self, command):
        return {"tool_name": "Bash", "cwd": self.repo, "tool_input": {"command": command}}
