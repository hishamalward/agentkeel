"""task.py: the record is bound to one session, size and permissions are separate."""
import json
import os
import subprocess
import sys
import unittest

from helpers import HOOKS, SESSION, RepoCase, run_hook

T = os.path.join(HOOKS, "task.py")


class TaskCommand(RepoCase):
    def task(self, *args, session=SESSION, cwd=None):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID")}
        env.update(self.env)
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        return subprocess.run([sys.executable, T, *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, env=env)

    def test_start_writes_a_session_bound_record(self):
        out = self.task("start", "json-flag", "--size", "medium", "--allow", "implement,merge")
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = self.record()
        self.assertEqual((rec["task"], rec["size"], rec["session_id"]), ("json-flag", "medium", SESSION))
        self.assertEqual(rec["permissions"], ["implement", "merge"])
        self.assertEqual(rec["worktrees"], [self.repo])

    def test_no_session_id_refused(self):
        out = self.task("start", "x", "--size", "small", "--allow", "implement", session=None)
        self.assertEqual(out.returncode, 2); self.assertIn("no session id", out.stderr)

    def test_bad_inputs_refused(self):
        self.assertNotEqual(self.task("start", "x", "--size", "huge", "--allow", "implement").returncode, 0)
        self.assertNotEqual(self.task("start", "Not Kebab", "--size", "small", "--allow", "implement").returncode, 0)
        out = self.task("start", "x", "--size", "small", "--allow", "deploy")
        self.assertEqual(out.returncode, 2); self.assertIn("unknown: deploy", out.stderr)
        self.assertNotEqual(self.task("start", "x", "--size", "small").returncode, 0)
        self.assertEqual(self.task("start", "x", "--size", "small", "--allow", "review",
                                   "--write-root", "/").returncode, 2)

    def test_changing_size_keeps_permissions_and_is_recorded(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        out = self.task("start", "x", "--size", "large", "--allow", "implement")
        self.assertIn("re-declared size small -> large", out.stderr)
        rec = self.record()
        self.assertEqual(rec["permissions"], ["implement"])
        self.assertEqual(rec["history"][0]["size"], "small")

    def test_widening_permissions_is_said_out_loud(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        out = self.task("start", "x", "--size", "small", "--allow", "implement,push")
        self.assertIn("permissions widened", out.stderr); self.assertIn("+push", out.stderr)

    def test_a_new_task_does_not_inherit_the_old_ones_resources(self):
        report = os.path.join(self.tmp, "r"); os.makedirs(report)
        self.task("start", "a", "--size", "small", "--allow", "review", "--write-root", report)
        self.task("start", "b", "--size", "small", "--allow", "implement")
        self.assertEqual(self.record()["write_roots"], [])

    def test_show_verify_end(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        self.assertEqual(self.task("show").returncode, 0)
        out = self.task("verify", "--", sys.executable, "-c", "raise SystemExit(3)")
        self.assertEqual(out.returncode, 3)
        ev = self.record()["evidence"][-1]
        self.assertEqual(ev["exit"], 3); self.assertTrue(ev["head"])
        self.assertEqual(self.task("end").returncode, 0)
        self.assertEqual(self.task("show").returncode, 1)

    def test_human_approve_sets_frontmatter(self):
        os.makedirs(os.path.join(self.repo, "docs", "specs"))
        p = os.path.join(self.repo, "docs", "specs", "x-spec.md")
        with open(p, "w") as fh:
            fh.write("---\nslug: x\nstatus: draft   # draft | approved\napproved_by:\napproved_on:\n---\n\nbody\n")
        out = self.task("approve", "x", session=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        from agentkeel_core import record
        with open(p) as fh:
            self.assertTrue(record.approval(fh.read())[0])

    def test_record_drives_the_guard(self):
        self.branch("feat/x")
        payload = {"tool_name": "Write", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {"file_path": os.path.join(self.repo, "a.py"), "content": ""}}
        self.assertEqual(run_hook("task-guard.py", payload, env=self.env)[0], 2)
        self.task("start", "x", "--size", "small", "--allow", "implement")
        self.assertEqual(run_hook("task-guard.py", payload, env=self.env)[0], 0)


if __name__ == "__main__":
    unittest.main()
