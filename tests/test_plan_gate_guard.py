import os
import tempfile
import unittest

from helpers import run_hook

H = "plan-gate-guard.py"


class PlanGateGuard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = {"AGENTKEEL_HOME": self._tmp.name}

    def tearDown(self):
        self._tmp.cleanup()

    def agent(self, prompt):
        return {"tool_name": "Agent", "cwd": self._tmp.name, "tool_input": {"prompt": prompt}}

    def test_one_round_of_two_then_refused_marker(self):
        p = "[plan-gate] Review docs/261005-json-flag-state.html"
        self.assertEqual(run_hook(H, self.agent(p), self.env)[0], 0)
        self.assertEqual(run_hook(H, self.agent(p), self.env)[0], 0)
        code, err = run_hook(H, self.agent(p), self.env)
        self.assertEqual(code, 2); self.assertIn("PLAN GATE GUARD", err)
        self.assertTrue(os.path.exists(os.path.join(self._tmp.name, "plan-gates.json")))

    def test_heuristic_detects_gate_words(self):
        p = "Act as Gate A: review the plan docs/261005-json-flag-state.html and give a verdict"
        for _ in range(2):
            self.assertEqual(run_hook(H, self.agent(p), self.env)[0], 0)
        self.assertEqual(run_hook(H, self.agent(p), self.env)[0], 2)

    def test_implementer_dispatch_not_counted(self):
        p = "Implement task 3 of docs/261005-json-flag-state.html"
        for _ in range(4):
            self.assertEqual(run_hook(H, self.agent(p), self.env)[0], 0)

    def test_task_review_excluded(self):
        p = "Review the plan docs/261005-json-flag-state.html against review-package-3.md"
        for _ in range(4):
            self.assertEqual(run_hook(H, self.agent(p), self.env)[0], 0)

    def test_per_plan_counters_independent(self):
        a = "[plan-gate] docs/261005-a-state.html"; b = "[plan-gate] docs/261005-b-state.html"
        for p in (a, a, b, b):
            self.assertEqual(run_hook(H, self.agent(p), self.env)[0], 0)
        self.assertEqual(run_hook(H, self.agent(a), self.env)[0], 2)
        self.assertEqual(run_hook(H, self.agent(b), self.env)[0], 2)

    def test_parallel_dispatches_cannot_both_read_the_old_count(self):
        import subprocess, sys, json
        from helpers import HOOKS
        p = "[plan-gate] Review docs/261005-race-state.html"
        payload = json.dumps(self.agent(p))
        procs = [subprocess.Popen([sys.executable, os.path.join(HOOKS, H)], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
                                  env={**os.environ, **self.env}) for _ in range(6)]
        for pr in procs:
            pr.stdin.write(payload); pr.stdin.close()
        codes = sorted(pr.wait() for pr in procs)
        self.assertEqual(codes, [0, 0, 2, 2, 2, 2])

    def test_wrong_tool_and_malformed_allowed(self):
        self.assertEqual(run_hook(H, {"tool_name": "Bash", "tool_input": {"command": "ls"}}, self.env)[0], 0)
        self.assertEqual(run_hook(H, "nope", self.env)[0], 0)


if __name__ == "__main__":
    unittest.main()
