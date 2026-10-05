import os
import tempfile
import unittest

from helpers import run_hook

H = "plan-size-guard.sh"


class PlanSizeGuard(unittest.TestCase):
    """The plan is the Working section of a state page; past 300 lines it is carrying code."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self._tmp.name, "docs"))

    def tearDown(self):
        self._tmp.cleanup()

    def page(self, rel, working_lines, durable_lines=0):
        path = os.path.join(self._tmp.name, rel)
        with open(path, "w") as fh:
            fh.write("<p>current</p>\n" * durable_lines)
            if working_lines:
                fh.write('<section data-keel-transient="working">\n' + "<p>task</p>\n" * (working_lines - 2) + "</section>\n")
        return {"tool_name": "Write", "cwd": self._tmp.name, "tool_input": {"file_path": path}}

    def test_under_limit_allowed(self):
        self.assertEqual(run_hook(H, self.page("docs/261005-x-state.html", 299))[0], 0)

    def test_over_limit_blocked_with_count(self):
        code, err = run_hook(H, self.page("docs/261005-x-state.html", 301))
        self.assertEqual(code, 2); self.assertIn("PLAN SIZE GUARD", err); self.assertIn("301", err)
        self.assertIn("carrying code", err)

    def test_durable_content_is_not_the_plan(self):
        self.assertEqual(run_hook(H, self.page("docs/261005-x-state.html", 10, durable_lines=5000))[0], 0)
        self.assertEqual(run_hook(H, self.page("docs/261005-x-reference.html", 900))[0], 0)

    def test_missing_path_and_malformed_allowed(self):
        self.assertEqual(run_hook(H, {"tool_name": "Write", "tool_input": {}})[0], 0)
        self.assertEqual(run_hook(H, "garbage")[0], 0)


if __name__ == "__main__":
    unittest.main()
