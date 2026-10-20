"""The debugging guards of a task declared --kind fix: a failed check and a cause before any code
edit, three edit-then-fail cycles, and the human-only reopen."""
import json
import os
import subprocess
import sys
import time
import unittest

from helpers import HOOKS, SESSION, RepoCase

T = os.path.join(HOOKS, "task.py")


class FixGuards(RepoCase):
    def setUp(self):
        super().setUp()
        self.branch("fix/x")

    def fix_task(self, evidence=(), cause=None, cycles=0, edited=False):
        from agentkeel_core import record
        record.atomic_write_json(os.path.join(self.home, "tasks", SESSION + ".json"), {
            "version": 1, "task": "x", "session_id": SESSION, "size": "small", "kind": "fix",
            "permissions": ["implement"], "worktrees": [self.repo], "write_roots": [], "resources": [],
            "declared_at": int(time.time()), "evidence": list(evidence), "history": [], "cause": cause,
            "fix": {"cycles": cycles, "edited": edited}})

    def task(self, *args, session=SESSION):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID", "CODEX_THREAD_ID")}
        env.update(self.env)
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        return subprocess.run([sys.executable, T, *args], cwd=self.repo, capture_output=True, text=True, env=env)

    FAILED = {"command": "npm test", "result": "failed", "reason": "exit 1", "at": 0}

    def test_no_edit_before_a_failed_check(self):
        self.fix_task()
        code, err = self.hook(self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("before a check has failed", err)

    def test_no_edit_before_a_cause(self):
        self.fix_task(evidence=[self.FAILED])
        code, err = self.hook(self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("cause is on record", err)

    def test_edit_allowed_with_both_and_marks_the_cycle(self):
        self.fix_task(evidence=[self.FAILED], cause="x causes y because z")
        self.assertEqual(self.hook(self.write("src/a.py"))[0], 0)
        self.assertTrue(self.record()["fix"]["edited"])

    def test_docs_pages_are_not_code(self):
        self.fix_task()
        self.assertEqual(self.hook(self.write("docs/261005-x-state.html"))[0], 0)

    def test_fourth_cycle_refused_until_the_human_reopens(self):
        self.fix_task(evidence=[self.FAILED], cause="x causes y because z", cycles=3)
        code, err = self.hook(self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("three edit-then-fail cycles", err)
        # the agent cannot reopen
        self.assertEqual(self.hook(self.bash(f'python3 "{T}" reopen x'))[0], 2)
        # the human can
        out = self.task("reopen", "x", session=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.record()["fix"]["cycles"], 0)
        self.assertEqual(self.hook(self.write("src/a.py"))[0], 0)

    def test_verify_records_a_failure_and_counts_a_cycle(self):
        self.fix_task(evidence=[self.FAILED], cause="x causes y because z", edited=True)
        out = self.task("verify", "--", "false")
        self.assertEqual(out.returncode, 1)
        rec = self.record()
        self.assertEqual(rec["evidence"][-1]["result"], "failed")
        self.assertEqual((rec["fix"]["cycles"], rec["fix"]["edited"]), (1, False))
        self.assertIn("fix cycle 1 of 3", out.stderr)
        out = self.task("verify", "--", "true")  # the foreground CLI records an unchanged-code pass
        self.assertEqual(out.returncode, 0)
        self.assertEqual(len(self.record()["evidence"]), 3)

    def test_cause_command(self):
        self.fix_task()
        out = self.task("cause", "the", "zone", "causes", "the", "shift")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.record()["cause"], "the zone causes the shift")

    def test_warn_mode_lets_the_edit_through(self):
        self.fix_task()
        self.set_policy({"guards": {"fix": "warn"}})
        out = subprocess.run([sys.executable, os.path.join(HOOKS, "task-guard.py")], input=json.dumps(self.write("src/a.py")),
                             text=True, capture_output=True, env={**os.environ, **self.env})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("before a check has failed", json.loads(out.stdout)["systemMessage"])


if __name__ == "__main__":
    unittest.main()
