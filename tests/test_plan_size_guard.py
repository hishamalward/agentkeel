import os
import tempfile
import unittest

from helpers import run_hook

H = "plan-size-guard.sh"


class PlanSizeGuard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self._tmp.name, "docs", "plans"))
        os.makedirs(os.path.join(self._tmp.name, "docs", "specs"))

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, rel, lines):
        path = os.path.join(self._tmp.name, rel)
        with open(path, "w") as fh:
            fh.write("- task\n" * lines)
        return {"tool_name": "Write", "cwd": self._tmp.name, "tool_input": {"file_path": path}}

    def test_under_limit_allowed(self):
        self.assertEqual(run_hook(H, self.plan("docs/plans/x-plan.md", 299))[0], 0)

    def test_over_limit_blocked_with_count(self):
        code, err = run_hook(H, self.plan("docs/plans/x-plan.md", 301))
        self.assertEqual(code, 2); self.assertIn("PLAN SIZE GUARD", err); self.assertIn("301", err)
        self.assertIn("carrying code", err)

    def test_spec_not_a_plan(self):
        self.assertEqual(run_hook(H, self.plan("docs/specs/x-spec.md", 5000))[0], 0)

    def test_missing_path_and_malformed_allowed(self):
        self.assertEqual(run_hook(H, {"tool_name": "Write", "tool_input": {}})[0], 0)
        self.assertEqual(run_hook(H, "garbage")[0], 0)


if __name__ == "__main__":
    unittest.main()
