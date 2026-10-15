"""Real-Git tests for shipping gates and canonical-main synchronization."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import GIT_ENV

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "hooks"))
from agentkeel_core import evidence, shipping, workspace


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


class ShippingGit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.bare = os.path.join(self.root, "origin.git")
        self.primary = os.path.join(self.root, "primary")
        subprocess.run(["git", "init", "--bare", "-q", self.bare], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.primary], check=True)
        git(self.primary, "commit", "--allow-empty", "-m", "initial")
        git(self.primary, "remote", "add", "origin", self.bare)
        git(self.primary, "push", "-u", "origin", "main")
        subprocess.run(["git", "--git-dir", self.bare, "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
        self.initial = git(self.primary, "rev-parse", "HEAD")
        self.env = {**os.environ, **GIT_ENV, "GIT_TERMINAL_PROMPT": "0"}

    def tearDown(self):
        self.tmp.cleanup()

    def remote_commit(self, name="remote", parent=None, force=False):
        producer = os.path.join(self.root, "producer-" + name)
        subprocess.run(["git", "clone", "-q", self.bare, producer], check=True)
        git(producer, "config", "user.name", "test")
        git(producer, "config", "user.email", "test@example.invalid")
        if parent:
            git(producer, "reset", "--hard", parent)
        with open(os.path.join(producer, name), "w") as fh:
            fh.write(name + "\n")
        git(producer, "add", name)
        git(producer, "commit", "-m", name)
        git(producer, "push", "--force", "origin", "main") if force else git(producer, "push", "origin", "main")
        return git(producer, "rev-parse", "HEAD")

    def test_sync_pulls_remote_advance_and_accepts_already_synced(self):
        head = self.remote_commit()
        self.assertEqual(shipping.sync_main(self.primary, head, self.env), head)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), head)
        self.assertEqual(shipping.sync_main(self.primary, self.initial, self.env), head)

    def test_sync_refuses_dirty_local_ahead_and_diverged_without_changing_bytes(self):
        head = self.remote_commit()
        dirty = os.path.join(self.primary, "untracked.txt")
        with open(dirty, "wb") as fh:
            fh.write(b"keep me\x00\n")
        with self.assertRaisesRegex(shipping.FinishError, "dirty"):
            shipping.sync_main(self.primary, head, self.env)
        with open(dirty, "rb") as fh:
            self.assertEqual(fh.read(), b"keep me\x00\n")
        os.unlink(dirty)

        git(self.primary, "commit", "--allow-empty", "-m", "local ahead")
        ahead = git(self.primary, "rev-parse", "HEAD")
        before = git(self.primary, "status", "--porcelain")
        with self.assertRaises(shipping.FinishError):
            shipping.sync_main(self.primary, head, self.env)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), ahead)
        self.assertEqual(git(self.primary, "status", "--porcelain"), before)

        # Move the remote from the common base, leaving local main divergent.
        git(self.primary, "reset", "--hard", self.initial)
        self.remote_commit("other-remote", parent=self.initial, force=True)
        git(self.primary, "commit", "--allow-empty", "-m", "diverged local")
        divergent = git(self.primary, "rev-parse", "HEAD")
        with self.assertRaises(shipping.FinishError):
            shipping.sync_main(self.primary, self.initial, self.env)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), divergent)

    def test_sync_refuses_busy_operations_without_touching_repository(self):
        head = self.remote_commit()
        gitdir = git(self.primary, "rev-parse", "--absolute-git-dir")
        lock = os.path.join(gitdir, "index.lock")
        with open(lock, "wb") as fh:
            fh.write(b"owner bytes")
        with self.assertRaisesRegex(shipping.FinishError, "busy"):
            shipping.sync_main(self.primary, head, self.env)
        with open(lock, "rb") as fh:
            self.assertEqual(fh.read(), b"owner bytes")
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), self.initial)

    def test_ship_retry_after_sync_failure_does_not_push_twice(self):
        # A task-owned linked tree whose exact committed state has passed local verification.
        owned = workspace.create(self.primary, "ship", "session", path=os.path.join(self.root, "task"))
        task = owned["path"]
        git(task, "config", "user.name", "test")
        git(task, "config", "user.email", "test@example.invalid")
        with open(os.path.join(task, "change.txt"), "w") as fh:
            fh.write("candidate\n")
        git(task, "add", "change.txt")
        git(task, "commit", "-m", "candidate")
        sha, tree = evidence.code_state(task)
        report = os.path.join(self.root, "report.html")
        with open(report, "w") as fh:
            fh.write("<html><title>Report</title><body>Done</body></html>")
        rec = {"session_id": "session", "task": "ship", "permissions": ["merge", "push"],
               "workspace": owned, "worktrees": [task], "write_roots": [self.root],
               "deliverable": report, "evidence": [{"result": "passed", "head": sha, "tree": tree}],
               "shipping": {}}
        hook = os.path.join(self.bare, "hooks", "pre-receive")
        pushes = os.path.join(self.root, "pushes")
        with open(hook, "w") as fh:
            fh.write("#!/bin/sh\nprintf x >> '" + pushes + "'\ncat >/dev/null\n")
        os.chmod(hook, 0o755)
        fake_env = {**self.env, "AGENTKEEL_HOME": os.path.join(self.root, "home")}
        with mock.patch.object(shipping, "reviewed", return_value="https://example.invalid/pr/1") as reviewed:
            # A dirty primary makes the post-push pull fail. The failed sync is recorded persistently.
            dirty = os.path.join(self.primary, "keep.txt")
            with open(dirty, "wb") as fh:
                fh.write(b"preserve")
            with self.assertRaisesRegex(shipping.FinishError, "dirty"):
                shipping.ship(rec, 1, fake_env)
            self.assertTrue(rec["shipping"]["pushed"])
            self.assertEqual(rec["lifecycle"], "sync_pending")
            self.assertEqual(Path(dirty).read_bytes(), b"preserve")
            self.assertEqual(Path(pushes).read_text(), "x")
            os.unlink(dirty)
            shipping.ship(rec, 1, fake_env)
            self.assertTrue(rec["shipping"]["synced"])
            self.assertEqual(Path(pushes).read_text(), "x")
            self.assertEqual(git(self.primary, "rev-parse", "HEAD"), sha)
            self.assertEqual(reviewed.call_count, 2)  # initial gate and final pre-push recheck

    def test_finish_without_slots_preserves_pending_then_releases_and_requires_final_report(self):
        owned = workspace.create(self.primary, "finish", "session")
        report = Path(self.root, "report.html")
        markup = "<html><title>Result</title><body>Work checked.</body></html>"
        report.write_text(markup)
        rec = {"session_id": "session", "task": "finish", "workspace": owned,
               "worktrees": [owned["path"]], "write_roots": [self.root], "deliverable": str(report)}
        env = {**self.env, "AGENTKEEL_HOME": os.path.join(self.root, "home"),
               "AGENTKEEL_SLOTS": "/not-installed/agent-slots"}
        with self.assertRaisesRegex(shipping.FinishError, "synchronize"):
            shipping.finish(rec, env)
        self.assertTrue(Path(owned["path"]).is_dir())
        rec["shipping"] = {"synced": True}
        with mock.patch.object(workspace, "active_processes", return_value=[]):
            with self.assertRaisesRegex(shipping.FinishError, "HTML pending"):
                shipping.finish(rec, env)
        self.assertFalse(Path(owned["path"]).exists())
        self.assertEqual(rec["lifecycle"], "report_pending")
        self.assertTrue(report.is_file())
        report.write_text(markup.replace("checked", "merged, synchronized and cleaned up"))
        shipping.finish(rec, env)
        self.assertEqual(rec["lifecycle"], "complete")


class ReviewGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.gh = os.path.join(self.root, "gh")
        self.data = {"state": "OPEN", "isDraft": False, "headRefOid": "a" * 40,
                     "headRefName": "feat/x", "baseRefName": "main", "reviewDecision": "APPROVED",
                     "statusCheckRollup": [{"__typename": "StatusContext", "state": "SUCCESS"}],
                     "url": "https://example.invalid/pr/1"}
        with open(self.gh, "w") as fh:
            fh.write("#!/bin/sh\ncat '" + os.path.join(self.root, "response.json") + "'\n")
        os.chmod(self.gh, 0o755)
        self.env = {**os.environ, "AGENTKEEL_GH": self.gh, "AGENTKEEL_HOME": os.path.join(self.root, "home")}
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        with open(os.path.join(self.root, "response.json"), "w") as fh:
            json.dump(self.data, fh)

    def rejected(self, match):
        self.write()
        with self.assertRaisesRegex(shipping.FinishError, match):
            shipping.reviewed(self.root, 1, "a" * 40, "feat/x", self.env)

    def test_skipped_jobs_alone_are_not_a_successful_check(self):
        self.data["statusCheckRollup"] = [{"__typename": "CheckRun", "status": "COMPLETED",
                                          "conclusion": "SKIPPED"}]
        self.rejected("no successful check")

    def test_wrong_sha_draft_review_request_and_failed_checks_are_rejected(self):
        self.data["headRefOid"] = "b" * 40
        self.rejected("exact tested")
        self.data.update(headRefOid="a" * 40, isDraft=True)
        self.rejected("ready, open")
        self.data.update(isDraft=False, reviewDecision="CHANGES_REQUESTED")
        self.rejected("review is pending")
        self.data.update(reviewDecision="APPROVED", statusCheckRollup=[
            {"__typename": "StatusContext", "state": "FAILURE"}])
        self.rejected("checks are pending or failed")


if __name__ == "__main__":
    unittest.main()
