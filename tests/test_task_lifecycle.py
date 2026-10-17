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
        self.report = self.root / ("reports" if size == "no-code" else "repo-work/doc") / "task.html"
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

    def test_cancel_preserves_work_and_archives_ownership_for_new_task(self):
        self.assertEqual(self.start().returncode, 0)
        owned = self.rec()["worktrees"][0]
        self.assertEqual(self.task("cancel").returncode, 0)
        self.assertTrue(Path(owned).is_dir())
        out = self.task("start", "other", "--size", "no-code", "--allow", "review",
                        "--deliverable", str(self.root / "reports/other.html"))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.rec()["task"], "other")
        retained = [json.loads(p.read_text()) for p in (self.root / "state/tasks").glob("*.json")]
        cancelled = next(r for r in retained if r["task"] == "work")
        self.assertEqual(cancelled["lifecycle"], "cancelled")
        self.assertEqual(cancelled["worktrees"], [owned])
        status = json.loads(self.task("status", "--json").stdout)
        self.assertEqual(next(w["task"] for w in status["others"] if w["path"] == owned), "work")
        out = self.task("discard", "work", "--worktree", owned)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.rec()["task"], "other")
        self.assertFalse(Path(owned).exists())

    def test_human_discard_releases_cancelled_work_but_not_active_task(self):
        self.assertEqual(self.start().returncode, 0)
        tree = self.rec()["worktrees"][0]
        Path(tree, "unfinished").write_text("discard me")
        out = self.task("discard", "work", "--worktree", tree)
        self.assertNotEqual(out.returncode, 0)
        self.assertTrue(Path(tree).is_dir())
        self.assertEqual(self.task("cancel").returncode, 0)
        out = self.task("discard", "work", "--worktree", tree)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(Path(tree).exists())
        self.assertEqual(self.rec()["worktrees"], [])
        self.assertIn("discard", (self.root / "state/overrides.jsonl").read_text())

    def test_failed_replacement_keeps_one_cancelled_ownership_record(self):
        self.assertEqual(self.start().returncode, 0)
        tree = self.rec()["worktrees"][0]
        self.assertEqual(self.task("cancel").returncode, 0)
        out = self.task("start", "other", "--size", "small", "--allow", "implement",
                        "--base", "missing-branch", "--deliverable", "doc/task.html")
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.rec()["task"], "work")
        self.assertEqual(len(list((self.root / "state/tasks").glob("*.json"))), 1)
        out = self.task("discard", "work", "--worktree", tree)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_local_only_cli_finishes_rewritten_commit_with_generated_cache(self):
        self.report = self.root / "repo-work/doc/task.html"
        git(str(self.repo), "branch", "-m", "main", "master")
        Path(self.repo, ".gitignore").write_text("__pycache__/\n")
        git(str(self.repo), "add", ".gitignore")
        git(str(self.repo), "commit", "-qm", "ignore generated cache")
        out = self.task("start", "work", "--size", "small", "--allow", "review,implement,merge",
                        "--deliverable", str(self.report))
        self.assertEqual(out.returncode, 0, out.stderr)
        tree = self.rec()["worktrees"][0]
        Path(tree, "code.py").write_text("value = 1\n")
        self.report.parent.mkdir(parents=True)
        self.report.write_text("<html><title>Task</title><body>Candidate checked</body></html>")
        git(tree, "add", "code.py", "doc/task.html")
        git(tree, "commit", "-qm", "first")
        git(tree, "commit", "--amend", "-qm", "revised")
        out = self.task("verify", "--", sys.executable, "-m", "py_compile", "code.py", cwd=tree)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.task("handoff").returncode, 0)
        out = self.task("ship", "--local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(Path(self.repo, "code.py").read_text(), "value = 1\n")
        out = self.task("finish")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(Path(tree).exists())
        self.assertTrue((self.repo / "doc/task.html").is_file())
        self.assertEqual(self.rec()["lifecycle"], "complete")

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
