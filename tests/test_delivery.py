import os
import time
import unittest
from unittest import mock

from helpers import HOOKS  # adds hooks/ to sys.path, like the existing hook tests
from agentkeel_core import delivery


class Delivery(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.report = os.path.join(self.root, "review.html")
        self.rec = {"deliverable": self.report, "write_roots": [self.root], "worktrees": [],
                    "declared_at": int(time.time()), "evidence": []}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, html):
        with open(self.report, "w", encoding="utf-8") as fh:
            fh.write(html)
        os.utime(self.report, (self.rec["declared_at"] + 1, self.rec["declared_at"] + 1))

    def test_accepts_free_form_html_and_returns_digest_checkpoint(self):
        self.write("<!doctype html><html><head><title>Notes</title></head><body><h1>Hi</h1></body></html>")
        self.assertEqual(delivery.problems(self.rec), [])
        self.assertTrue(delivery.checkpoint(self.rec)["digest"])

    def test_rejects_missing_empty_and_missing_required_tags(self):
        self.assertTrue(delivery.problems(self.rec))
        missing = {**self.rec, "deliverable": None}
        self.assertTrue(delivery.problems(missing))
        self.write(" \n")
        self.assertTrue(delivery.problems(self.rec))
        self.write("<html><head><title>Notes</title></head><body></body></html>")
        self.assertTrue(delivery.problems(self.rec))

    def test_requires_freshness_after_declaration_evidence_and_outcome(self):
        self.write("<html><head><title>Notes</title></head><body>Done</body></html>")
        self.rec["evidence"] = [{"at": self.rec["declared_at"] + 5}]
        self.assertTrue(delivery.problems(self.rec))
        self.rec["evidence"] = []
        self.rec["outcome_at"] = self.rec["declared_at"] + 5
        self.assertTrue(delivery.problems(self.rec))
        os.utime(self.report, (self.rec["outcome_at"] + 1, self.rec["outcome_at"] + 1))
        self.assertEqual(delivery.problems(self.rec), [])

    def test_requires_write_root_and_keeps_report_outside_disposable_worktrees(self):
        self.rec["write_roots"] = [os.path.join(self.root, "other")]
        self.assertTrue(delivery.problems(self.rec))

        self.rec["write_roots"] = [self.root]
        self.rec["worktrees"] = [self.root]
        self.assertTrue(delivery.problems(self.rec))

    def test_observed_edit_and_code_checkpoint_invalidate_an_old_report(self):
        self.write("<html><title>Result</title><body>Before edit</body></html>")
        self.rec["code_changed_at"] = self.rec["declared_at"] + 2.5
        self.assertTrue(delivery.problems(self.rec))
        self.rec["code_changed_at"] = 0
        with mock.patch.object(delivery, "_code", return_value={"tree": ["head", "before"]}):
            self.rec["html_checkpoint"] = delivery.checkpoint(self.rec)
        with mock.patch.object(delivery, "_code", return_value={"tree": ["head", "after"]}) as code_state:
            self.assertTrue(delivery.problems(self.rec))
            code_state.assert_called_once_with(self.rec)
            self.write("<html><title>Result</title><body>After edit</body></html>")
            self.assertEqual(delivery.problems(self.rec), [])

    def test_touching_unchanged_report_does_not_clear_new_task_activity(self):
        self.write("<html><title>Result</title><body>Before activity</body></html>")
        self.rec["html_checkpoint"] = delivery.checkpoint(self.rec)
        for key in ("code_changed_at", "outcome_at"):
            with self.subTest(activity=key):
                self.rec[key] = self.rec["declared_at"] + 5
                os.utime(self.report, (self.rec[key] + 1, self.rec[key] + 1))
                with mock.patch.object(delivery, "_code", side_effect=AssertionError("unexpected Git scan")):
                    self.assertIn("the deliverable content has not changed since", delivery.problems(self.rec)[0])
                self.rec.pop(key)
        self.rec["evidence"] = [{"at": self.rec["declared_at"] + 5}]
        os.utime(self.report, (self.rec["declared_at"] + 6, self.rec["declared_at"] + 6))
        with mock.patch.object(delivery, "_code", side_effect=AssertionError("unexpected Git scan")):
            self.assertIn("the deliverable content has not changed since", delivery.problems(self.rec)[0])

        self.write("<html><title>Result</title><body>Updated after activity</body></html>")
        os.utime(self.report, (self.rec["evidence"][0]["at"] + 1, self.rec["evidence"][0]["at"] + 1))
        self.assertEqual(delivery.problems(self.rec), [])

    def test_status_page_does_not_claim_stop_hooks_are_active(self):
        from agentkeel_core import statuspage
        page = statuspage.render({"repository": "/repo", "task": None, "worktrees": []}, None,
                                 {"guards": {}}, [])
        self.assertEqual(page.count("Stop enforcement not verified here; handoff/finish enforce HTML"), 2)
        self.assertIn("do not prove this Stop hook ran", page)


if __name__ == "__main__":
    unittest.main()
