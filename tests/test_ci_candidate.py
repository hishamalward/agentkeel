"""A PR tests its exact head; only completed evidence for that head can skip main's app tests."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from helpers import ROOT, git

sys.path.insert(0, os.path.join(ROOT, "templates", "ci"))
import candidate

SHA = "a" * 40
REPO = "owner/project"
WORKFLOW = "agentkeel-checks.yml"


class Evidence(unittest.TestCase):
    def setUp(self):
        self.run = dict(id=17, run_number=4, run_attempt=2, event="pull_request", head_sha=SHA,
                        path=f".github/workflows/{WORKFLOW}", head_repository={"full_name": REPO},
                        status="completed", conclusion="success")
        self.jobs = [dict(name="select", status="completed", conclusion="success",
                          steps=[dict(name="Bind tested commit", conclusion="success")]),
                     dict(name="agentkeel-required", status="completed", conclusion="success")]

    def query(self, path):
        if "/attempts/" in path:
            self.assertIn("/17/attempts/2/jobs", path)
            return {"jobs": self.jobs}
        return {"workflow_runs": self.runs}

    def check(self, runs=None):
        self.runs = runs if runs is not None else [self.run]
        return candidate.reusable_run(REPO, SHA, WORKFLOW, self.query)

    def test_successful_exact_head_and_latest_attempt_can_be_reused(self):
        self.assertEqual(self.check(), 17)

    def test_wrong_commit_workflow_repository_or_event_cannot_be_reused(self):
        for key, value in (("head_sha", "b" * 40), ("path", ".github/workflows/unrelated.yml"),
                           ("head_repository", {"full_name": "fork/project"}), ("event", "push")):
            with self.subTest(key=key):
                run = {**self.run, key: value}
                self.assertIsNone(self.check([run]))

    def test_newer_failure_pending_cancelled_or_skipped_blocks_older_green(self):
        for state in ("failure", "cancelled", "skipped", None):
            newer = {**self.run, "id": 18, "run_number": 5, "conclusion": state,
                     "status": "in_progress" if state is None else "completed"}
            with self.subTest(state=state):
                self.assertIsNone(self.check([self.run, newer]))

    def test_missing_or_non_successful_required_job_cannot_be_reused(self):
        for state in ("failure", "skipped", "cancelled", None):
            self.jobs[-1]["conclusion"] = state
            self.assertIsNone(self.check())
        self.jobs.pop()
        self.assertIsNone(self.check())

    def test_old_workflow_without_explicit_head_binding_is_not_evidence(self):
        self.jobs[0]["steps"] = []
        self.assertIsNone(self.check())

    def test_api_failure_falls_back_to_running_checks(self):
        event = {"before": "b" * 40, "repository": {"default_branch": "main"}}
        with tempfile.NamedTemporaryFile(mode="w") as fh:
            import json
            json.dump(event, fh); fh.flush()
            env = dict(GITHUB_EVENT_PATH=fh.name, GITHUB_EVENT_NAME="push", GITHUB_REPOSITORY=REPO,
                       GITHUB_WORKFLOW_REF=f"{REPO}/.github/workflows/{WORKFLOW}@refs/heads/main")
            with patch.object(candidate, "candidate", return_value=(SHA, "b" * 40)), \
                 patch.object(candidate, "reusable_run", side_effect=ValueError("unavailable")), \
                 patch.object(candidate, "changed", return_value=["app.py"]), \
                 patch("builtins.print") as output:
                self.assertEqual(candidate.main(env), 0)
                self.assertTrue(any("app=true\nreuse=false" in c.args[0] for c in output.call_args_list))


class Candidate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        subprocess.run(["git", "init", "-q", "-b", "main", self.root], check=True)
        git(self.root, "commit", "--allow-empty", "-qm", "base")
        self.base = self.readgit("rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/main", self.base)
        git(self.root, "checkout", "-qb", "feature")
        git(self.root, "commit", "--allow-empty", "-qm", "feature")
        self.head = self.readgit("rev-parse", "HEAD")
        self.payload = {"repository": {"default_branch": "main"}, "pull_request": {
            "draft": False, "head": {"sha": self.head}, "base": {"ref": "main", "sha": self.base}}}

    def readgit(self, *args):
        return subprocess.check_output(["git", "-C", self.root, *args], text=True).strip()

    def bind(self, event="pull_request", env=None):
        with patch.object(candidate, "git", side_effect=self.readgit):
            return candidate.candidate(event, self.payload, env or {})

    def test_exact_up_to_date_head_is_accepted(self):
        self.assertEqual(self.bind(), (self.head, self.base))

    def test_synthetic_merge_or_different_checkout_is_rejected(self):
        self.payload["pull_request"]["head"]["sha"] = self.base
        with self.assertRaises(ValueError):
            self.bind()

    def test_draft_and_backup_push_are_not_candidates(self):
        self.payload["pull_request"]["draft"] = True
        with self.assertRaises(ValueError):
            self.bind()
        with self.assertRaises(ValueError):
            self.bind("push", {"GITHUB_REF": "refs/heads/feature"})

    def test_main_advancing_requires_branch_update(self):
        git(self.root, "checkout", "-q", "main")
        git(self.root, "commit", "--allow-empty", "-qm", "another task")
        git(self.root, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.root, "checkout", "-q", "feature")
        with self.assertRaises(subprocess.CalledProcessError):
            self.bind()


if __name__ == "__main__":
    unittest.main()
