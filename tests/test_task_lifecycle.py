"""Standalone task lifecycle: real Git, no AgentSlots installation."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import HOOKS, GIT_ENV, git


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.report = self.root / "reports" / "task.html"
        git(str(self.root), "init", "-q", "-b", "main", str(self.repo))
        git(str(self.repo), "commit", "--allow-empty", "-qm", "initial")
        self.env = {**os.environ, **GIT_ENV, "AGENTKEEL_HOME": str(self.root / "state"),
                    "AGENTKEEL_SESSION_ID": "test"}

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, *args, cwd=None):
        return subprocess.run([sys.executable, os.path.join(HOOKS, "task.py"), *args],
                              cwd=cwd or self.repo, env=self.env, capture_output=True, text=True)

    def start(self, size="small"):
        return self.task("start", "work", "--size", size, "--allow", "review,implement",
                         "--deliverable", str(self.report))

    def rec(self):
        return json.loads((self.root / "state/tasks/test.json").read_text())

    def test_coding_creates_owned_tree_and_redeclaration_reuses_it(self):
        out = self.start()
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = self.rec()
        self.assertEqual(len(rec["worktrees"]), 1)
        self.assertNotEqual(rec["worktrees"][0], str(self.repo))
        self.assertTrue(Path(rec["worktrees"][0], ".git").is_file())
        self.assertTrue(rec["workspace"]["identity"])
        self.assertEqual(self.start("large").returncode, 0)
        self.assertEqual(self.rec()["workspace"], rec["workspace"])

    def test_no_code_needs_no_tree_but_requires_current_html(self):
        out = self.start("no-code")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.rec()["worktrees"], [])
        self.assertNotEqual(self.task("handoff").returncode, 0)
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text("<!doctype html><html><head><title>Review</title></head>"
                               "<body><h1>Current result</h1></body></html>")
        self.assertEqual(self.task("handoff").returncode, 0)
        self.assertEqual(self.task("finish").returncode, 0)
        self.assertEqual(self.rec()["lifecycle"], "complete")

    def test_cancel_preserves_work_and_cannot_hide_it_with_new_task(self):
        self.assertEqual(self.start().returncode, 0)
        owned = self.rec()["worktrees"][0]
        self.assertEqual(self.task("cancel").returncode, 0)
        self.assertTrue(Path(owned).is_dir())
        out = self.task("start", "other", "--size", "no-code", "--allow", "review",
                        "--deliverable", str(self.report))
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.rec()["task"], "work")

    def test_verify_records_pass_only_if_code_did_not_change(self):
        self.assertEqual(self.start().returncode, 0)
        tree = self.rec()["worktrees"][0]
        self.assertEqual(self.task("verify", "--", sys.executable, "-c", "pass", cwd=tree).returncode, 0)
        self.assertEqual(self.rec()["evidence"][-1]["result"], "passed")
        self.task("verify", "--", sys.executable, "-c", "open('changed', 'w').write('x')", cwd=tree)
        self.assertEqual(self.rec()["evidence"][-1]["result"], "stale")

    def test_verify_state_read_does_not_run_repository_filters_or_fsmonitor(self):
        self.assertEqual(self.start().returncode, 0)
        tree = self.rec()["worktrees"][0]
        marker = self.root / "planted-ran"
        script = self.root / "planted.sh"
        script.write_text(f"#!/bin/sh\nprintf x >> '{marker}'\ncat\n")
        script.chmod(0o755)
        (Path(tree) / ".gitattributes").write_text("* filter=planted\n")
        git(tree, "config", "filter.planted.clean", str(script))
        git(tree, "config", "core.fsmonitor", str(script))
        out = self.task("verify", "--", sys.executable, "-c", "pass", cwd=tree)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(marker.exists(), "verify's code-state read ran a repository-configured program")
        self.assertEqual(self.rec()["evidence"][-1]["result"], "passed")
