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
from agentkeel_core import evidence, record, shipping, workspace


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
        self.assertEqual(shipping.sync_branch(self.primary, head, "main", self.env), head)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), head)
        self.assertEqual(shipping.sync_branch(self.primary, self.initial, "main", self.env), head)

    def test_sync_refuses_dirty_local_ahead_and_diverged_without_changing_bytes(self):
        head = self.remote_commit()
        dirty = os.path.join(self.primary, "untracked.txt")
        with open(dirty, "wb") as fh:
            fh.write(b"keep me\x00\n")
        with self.assertRaisesRegex(shipping.FinishError, "dirty"):
            shipping.sync_branch(self.primary, head, "main", self.env)
        with open(dirty, "rb") as fh:
            self.assertEqual(fh.read(), b"keep me\x00\n")
        os.unlink(dirty)

        git(self.primary, "commit", "--allow-empty", "-m", "local ahead")
        ahead = git(self.primary, "rev-parse", "HEAD")
        before = git(self.primary, "status", "--porcelain")
        with self.assertRaises(shipping.FinishError):
            shipping.sync_branch(self.primary, head, "main", self.env)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), ahead)
        self.assertEqual(git(self.primary, "status", "--porcelain"), before)

        # Move the remote from the common base, leaving local main divergent.
        git(self.primary, "reset", "--hard", self.initial)
        self.remote_commit("other-remote", parent=self.initial, force=True)
        git(self.primary, "commit", "--allow-empty", "-m", "diverged local")
        divergent = git(self.primary, "rev-parse", "HEAD")
        with self.assertRaises(shipping.FinishError):
            shipping.sync_branch(self.primary, self.initial, "main", self.env)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), divergent)

    def test_sync_refuses_busy_operations_without_touching_repository(self):
        head = self.remote_commit()
        gitdir = git(self.primary, "rev-parse", "--absolute-git-dir")
        lock = os.path.join(gitdir, "index.lock")
        with open(lock, "wb") as fh:
            fh.write(b"owner bytes")
        with self.assertRaisesRegex(shipping.FinishError, "busy"):
            shipping.sync_branch(self.primary, head, "main", self.env)
        with open(lock, "rb") as fh:
            self.assertEqual(fh.read(), b"owner bytes")
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), self.initial)

    def pr_fixture(self):
        git(self.primary, "branch", "-m", "release")
        record.save_policy(self.primary, {"protected_branches": ["release"]})
        git(self.primary, "push", "origin", "release")
        owned = workspace.create(self.primary, "ship", "session", path=os.path.join(self.root, "task"))
        task = owned["path"]
        Path(task, "change.txt").write_text("candidate\n")
        git(task, "add", "change.txt")
        git(task, "commit", "-m", "candidate")
        sha, tree = evidence.code_state(task)
        git(task, "push", "origin", f"{sha}:refs/heads/{owned['branch']}")
        report = Path(self.root, "report.html")
        report.write_text("<html><title>Report</title><body>Done</body></html>")
        self.rec = {"session_id": "session", "task": "ship", "permissions": ["merge", "push"],
                    "workspace": owned, "worktrees": [task], "write_roots": [self.root],
                    "deliverable": str(report), "evidence": [{"result": "passed", "head": sha, "tree": tree}],
                    "shipping": {}}
        self.pr_data = {"state": "OPEN", "isDraft": False, "headRefOid": sha,
                        "headRefName": owned["branch"], "baseRefName": "release",
                        "reviewDecision": "REVIEW_REQUIRED", "url": "https://github.com/owner/repo/pull/1",
                        "statusCheckRollup": [{"__typename": "StatusContext", "state": "SUCCESS"}]}
        self.env.update(AGENTKEEL_HOME=os.path.join(self.root, "home"), AGENTKEEL_GH="fake-gh")
        self.merge_calls = []
        self.merge_behavior = "merge"
        real_run = shipping.run

        def gh_run(root, argv, environ):
            if argv[0] != "fake-gh":
                return real_run(root, argv, environ)
            self.assertIn("--repo", argv)
            self.assertEqual(argv[argv.index("--repo") + 1], "owner/repo")
            if argv[1:3] == ["pr", "view"]:
                return json.dumps(self.pr_data)
            self.assertEqual(argv[1:3], ["pr", "merge"])
            self.assertIn("--merge", argv)
            self.assertEqual(argv[argv.index("--match-head-commit") + 1], sha)
            self.merge_calls.append(argv)
            if self.merge_behavior == "denied":
                raise shipping.FinishError("GitHub permission denied")
            if self.merge_behavior == "queued":
                return "queued"
            if self.merge_behavior == "head_changed":
                self.pr_data["headRefOid"] = "b" * 40
                raise shipping.FinishError("GitHub rejected changed head")
            self.server_merge()
            if self.merge_behavior == "timeout":
                raise shipping.FinishError("timed out after server merged")
            return "merged"

        for patch in (mock.patch.object(shipping, "run", side_effect=gh_run),
                      mock.patch.object(shipping.checks, "github_slug", return_value="owner/repo")):
            patch.start()
            self.addCleanup(patch.stop)
        return sha

    def server_merge(self):
        producer = os.path.join(self.root, "merger")
        subprocess.run(["git", "clone", "-q", "-b", "release", self.bare, producer], check=True)
        git(producer, "merge", "--no-ff", self.pr_data["headRefOid"], "-m", "Merge PR")
        merged = git(producer, "rev-parse", "HEAD")
        git(producer, "push", "origin", "release")
        self.pr_data.update(state="MERGED", mergeCommit={"oid": merged})
        return merged

    def test_admin_merge_sync_retry_uses_github_once_and_preserves_dirty_main(self):
        sha = self.pr_fixture()
        dirty = Path(self.primary, "keep.txt")
        dirty.write_bytes(b"preserve")
        with self.assertRaisesRegex(shipping.FinishError, "dirty"):
            shipping.ship(self.rec, 1, self.env, admin=True)
        self.assertTrue(self.rec["shipping"]["pushed"])
        self.assertEqual(self.rec["lifecycle"], "sync_pending")
        self.assertEqual(dirty.read_bytes(), b"preserve")
        self.assertEqual(len(self.merge_calls), 1)
        self.assertIn("--admin", self.merge_calls[0])
        git(self.primary, "checkout", "main")
        with self.assertRaisesRegex(shipping.FinishError, "not configured as protected"):
            shipping.ship(self.rec, 1, self.env)
        git(self.primary, "checkout", "release")
        dirty.unlink()
        shipping.ship(self.rec, 1, self.env)
        self.assertTrue(self.rec["shipping"]["synced"])
        self.assertEqual(len(self.merge_calls), 1)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), self.pr_data["mergeCommit"]["oid"])
        git(self.primary, "merge-base", "--is-ancestor", sha, "HEAD")

    def test_normal_review_refuses_then_approved_merge_omits_admin(self):
        self.pr_fixture()
        with self.assertRaisesRegex(shipping.FinishError, "review is pending"):
            shipping.ship(self.rec, 1, self.env)
        self.assertFalse(self.merge_calls)
        self.pr_data["reviewDecision"] = "APPROVED"
        shipping.ship(self.rec, 1, self.env)
        self.assertNotIn("--admin", self.merge_calls[0])
        self.assertTrue(self.rec["shipping"]["synced"])

    def test_existing_external_merge_resumes_without_merging_again(self):
        self.pr_fixture()
        merged = self.server_merge()
        shipping.ship(self.rec, 1, self.env)
        self.assertFalse(self.merge_calls)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), merged)

    def test_timeout_after_merge_recovers_from_saved_attempt(self):
        self.pr_fixture()
        self.merge_behavior = "timeout"
        with self.assertRaisesRegex(shipping.FinishError, "timed out"):
            shipping.ship(self.rec, 1, self.env, admin=True)
        self.assertNotIn("pushed", self.rec["shipping"])
        shipping.ship(self.rec, 1, self.env)
        self.assertEqual(len(self.merge_calls), 1)
        self.assertTrue(self.rec["shipping"]["synced"])

    def test_queued_merge_stays_pending_and_later_resumes(self):
        self.pr_fixture()
        self.merge_behavior = "queued"
        with self.assertRaisesRegex(shipping.FinishError, "merge is pending"):
            shipping.ship(self.rec, 1, self.env, admin=True)
        self.assertNotIn("pushed", self.rec["shipping"])
        self.assertTrue(Path(self.rec["workspace"]["path"]).is_dir())
        self.server_merge()
        shipping.ship(self.rec, 1, self.env)
        self.assertEqual(len(self.merge_calls), 1)

    def test_github_permission_denial_retains_work_and_does_not_sync(self):
        self.pr_fixture()
        before = git(self.primary, "rev-parse", "HEAD")
        self.merge_behavior = "denied"
        with self.assertRaisesRegex(shipping.FinishError, "permission denied"):
            shipping.ship(self.rec, 1, self.env, admin=True)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), before)
        self.assertNotIn("pushed", self.rec["shipping"])
        self.assertTrue(Path(self.rec["workspace"]["path"], "change.txt").is_file())
        with mock.patch.object(shipping.checks, "github_slug", return_value="other/repo"):
            with self.assertRaisesRegex(shipping.FinishError, "origin.*changed"):
                shipping.ship(self.rec, 1, self.env, admin=True)

    def test_head_changed_at_merge_does_not_sync(self):
        self.pr_fixture()
        self.merge_behavior = "head_changed"
        with self.assertRaisesRegex(shipping.FinishError, "changed head"):
            shipping.ship(self.rec, 1, self.env, admin=True)
        self.assertNotIn("pushed", self.rec["shipping"])
        with self.assertRaisesRegex(shipping.FinishError, "exact tested"):
            shipping.ship(self.rec, 1, self.env, admin=True)
        self.assertEqual(len(self.merge_calls), 1)

    def test_claimed_merged_pr_must_preserve_candidate_in_remote_base(self):
        self.pr_fixture()
        self.pr_data.update(state="MERGED", mergeCommit={"oid": self.initial})
        with self.assertRaises(shipping.FinishError):
            shipping.ship(self.rec, 1, self.env)
        self.assertNotIn("pushed", self.rec["shipping"])
        self.assertFalse(self.merge_calls)

    def test_ship_local_fast_forwards_verified_candidate_without_remote_access(self):
        git(self.primary, "branch", "-m", "release")
        record.save_policy(self.primary, {"protected_branches": ["release"]})
        owned = workspace.create(self.primary, "local-ship", "session",
                                 path=os.path.join(self.root, "local-task"))
        task = owned["path"]
        git(task, "config", "user.name", "test")
        git(task, "config", "user.email", "test@example.invalid")
        with open(os.path.join(task, "change.txt"), "w") as fh:
            fh.write("candidate\n")
        git(task, "add", "change.txt")
        git(task, "commit", "-m", "candidate")
        sha, tree = evidence.code_state(task)
        report = os.path.join(self.root, "local-report.html")
        with open(report, "w") as fh:
            fh.write("<html><title>Report</title><body>Done</body></html>")
        rec = {"session_id": "session", "task": "local-ship", "permissions": ["merge"],
               "workspace": owned, "worktrees": [task], "write_roots": [self.root],
               "deliverable": report, "evidence": [{"result": "passed", "head": sha, "tree": tree}],
               "shipping": {}}
        fake_env = {**self.env, "AGENTKEEL_HOME": os.path.join(self.root, "home")}
        dirty = Path(self.primary, "preserve.txt")
        dirty.write_bytes(b"keep")
        with self.assertRaisesRegex(shipping.FinishError, "dirty"):
            shipping.ship_local(rec, fake_env)
        self.assertEqual(dirty.read_bytes(), b"keep")
        self.assertEqual(rec["lifecycle"], "sync_pending")
        dirty.unlink()
        shipping.ship_local(rec, fake_env)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), sha)
        self.assertTrue(rec["shipping"]["synced"])
        self.assertEqual(rec["shipping"]["mode"], "local")
        self.assertEqual(rec["shipping"]["target_branch"], "release")
        self.assertEqual(rec["lifecycle"], "cleanup_pending")
        shipping.ship_local(rec, fake_env)  # already synced is a no-op even though ship outcome aged the HTML
        rec["shipping"]["target_branch"] = "another-branch"
        with self.assertRaisesRegex(shipping.FinishError, "protected branch changed"):
            shipping.ship_local(rec, fake_env)
        self.assertEqual(subprocess.run(["git", "--git-dir", self.bare, "rev-parse", "refs/heads/main"],
                                        check=True, capture_output=True, text=True).stdout.strip(), self.initial)

    def test_ship_local_requires_merge_permission_and_configured_canonical_branch(self):
        owned = workspace.create(self.primary, "local-deny", "session",
                                 path=os.path.join(self.root, "denied-task"))
        git(self.primary, "branch", "-m", "topic")
        rec = {"permissions": [], "workspace": owned, "shipping": {}}
        with self.assertRaisesRegex(shipping.FinishError, "lacks permission: merge"):
            shipping.ship_local(rec, self.env)
        rec["permissions"] = ["merge"]
        with self.assertRaisesRegex(shipping.FinishError, "not configured as protected"):
            shipping.ship_local(rec, self.env)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), self.initial)

    def test_ship_local_refuses_when_policy_requires_a_named_check(self):
        record.save_policy(self.primary, {"require_check_before_push": "ci/build"})
        owned = workspace.create(self.primary, "local-check-policy", "session",
                                 path=os.path.join(self.root, "check-policy-task"))
        task = owned["path"]
        git(task, "config", "user.name", "test")
        git(task, "config", "user.email", "test@example.invalid")
        Path(task, "change.txt").write_text("candidate\n")
        git(task, "add", "change.txt")
        git(task, "commit", "-m", "candidate")
        sha, tree = evidence.code_state(task)
        report = Path(self.root, "check-policy-report.html")
        report.write_text("<html><title>Report</title><body>Done</body></html>")
        rec = {"session_id": "session", "task": "local-check-policy", "permissions": ["merge"],
               "workspace": owned, "write_roots": [self.root], "deliverable": str(report),
               "evidence": [{"result": "passed", "head": sha, "tree": tree}], "shipping": {}}
        before = git(self.primary, "rev-parse", "HEAD")
        with self.assertRaisesRegex(shipping.FinishError, "requires.*PR"):
            shipping.ship_local(rec, self.env)
        self.assertEqual(git(self.primary, "rev-parse", "HEAD"), before)
        self.assertEqual(rec["shipping"], {})

    def test_pr_uses_canonical_configured_protected_branch_as_base(self):
        git(self.primary, "branch", "-m", "release")
        record.save_policy(self.primary, {"protected_branches": ["release"]})
        owned = workspace.create(self.primary, "base-test", "session",
                                 path=os.path.join(self.root, "base-task"))
        task = owned["path"]
        git(task, "config", "user.name", "test")
        git(task, "config", "user.email", "test@example.invalid")
        Path(task, "change.txt").write_text("candidate\n")
        git(task, "add", "change.txt")
        git(task, "commit", "-m", "candidate")
        sha, tree = evidence.code_state(task)
        report = Path(self.root, "base-report.html")
        report.write_text("<html><title>Report</title><body>Done</body></html>")
        body = Path(self.root, "pr-body.txt")
        body.write_text("body")
        args_file = Path(self.root, "gh-args")
        gh = Path(self.root, "gh")
        gh.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > '{args_file}'\nprintf 'https://example.invalid/pr/2\\n'\n")
        gh.chmod(0o755)
        rec = {"session_id": "session", "task": "base-test", "permissions": ["push"],
               "workspace": owned, "write_roots": [self.root], "deliverable": str(report),
               "evidence": [{"result": "passed", "head": sha, "tree": tree}]}
        env = {**self.env, "AGENTKEEL_GH": str(gh)}
        self.assertEqual(shipping.pr(rec, "title", str(body), env), "https://example.invalid/pr/2")
        self.assertIn("release", args_file.read_text().splitlines())
        self.assertIn("--base", args_file.read_text().splitlines())

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
        slug = mock.patch.object(shipping.checks, "github_slug", return_value="owner/repo")
        slug.start()
        self.addCleanup(slug.stop)
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

    def test_admin_only_waives_missing_review_and_keeps_other_gates(self):
        self.data["reviewDecision"] = "REVIEW_REQUIRED"
        self.write()
        self.assertEqual(shipping.reviewed(self.root, 1, "a" * 40, "feat/x", self.env,
                                          admin=True)["state"], "OPEN")
        for change in ({"reviewDecision": "CHANGES_REQUESTED"}, {"isDraft": True},
                       {"headRefOid": "b" * 40}, {"baseRefName": "other"},
                       {"state": "CLOSED"}, {"statusCheckRollup": []},
                       {"statusCheckRollup": [{"__typename": "StatusContext", "state": "PENDING"}]}):
            with self.subTest(change=change):
                previous = dict(self.data)
                self.data.update(change)
                self.write()
                with self.assertRaises(shipping.FinishError):
                    shipping.reviewed(self.root, 1, "a" * 40, "feat/x", self.env, admin=True)
                self.data = previous

    def test_merged_retry_still_refuses_requested_changes(self):
        self.data.update(state="MERGED", reviewDecision="CHANGES_REQUESTED")
        self.write()
        with self.assertRaisesRegex(shipping.FinishError, "review is pending"):
            shipping.reviewed(self.root, 1, "a" * 40, "feat/x", self.env,
                              admin=True, allow_merged=True)

    def test_admin_cannot_bypass_configured_required_check(self):
        self.data["reviewDecision"] = "REVIEW_REQUIRED"
        self.write()
        with mock.patch.object(shipping.record, "policy", return_value={"require_check": "ci"}), \
             mock.patch.object(shipping.checks, "conclusion", return_value=("failure", "ci failed")):
            with self.assertRaisesRegex(shipping.FinishError, "ci failed"):
                shipping.reviewed(self.root, 1, "a" * 40, "feat/x", self.env, admin=True)

    def test_cli_rejects_admin_with_local_shipping(self):
        cli = Path(__file__).resolve().parents[1] / "hooks/task.py"
        result = subprocess.run([sys.executable, str(cli), "ship", "--local", "--admin"],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--admin is only valid with --pr", result.stderr)

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
