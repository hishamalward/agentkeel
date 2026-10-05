"""templates/ci: docs-only changes skip the app tests; anything else, or anything unknown, runs them."""
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import GIT_ENV, ROOT, git

SELECT = os.path.join(ROOT, "templates", "ci", "select_checks.py")
WORKFLOW = os.path.join(ROOT, "templates", "ci", "required-checks.yml")


class SelectChecks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self._tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        self.commit("README.md", "init")
        git(self.repo, "checkout", "-q", "-b", "feat/x")

    def tearDown(self):
        self._tmp.cleanup()

    def commit(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        git(self.repo, "add", rel)
        git(self.repo, "commit", "-q", "-m", rel)

    def select(self, base="main", env=None):
        out = subprocess.run([sys.executable, SELECT, "--base", base, "--head", "HEAD"], cwd=self.repo,
                             capture_output=True, text=True, env={**os.environ, **GIT_ENV, **(env or {})})
        return out.stdout.strip()

    def test_docs_only_skips_app_tests(self):
        self.commit("docs/plan.md", "x"); self.commit("NOTES.md", "y")
        self.assertEqual(self.select(), "app=false")

    def test_code_change_runs_app_tests(self):
        self.commit("docs/plan.md", "x"); self.commit("src/app.ts", "z")
        self.assertEqual(self.select(), "app=true")

    def test_unknown_base_runs_everything(self):
        self.commit("docs/plan.md", "x")
        self.assertEqual(self.select(base="no-such-ref"), "app=true")

    def test_push_to_main_judges_its_own_commit(self):
        git(self.repo, "checkout", "-q", "main")
        self.commit("src/app.ts", "z")
        self.assertEqual(self.select(), "app=true")

    def test_push_to_main_judges_every_pushed_commit(self):
        git(self.repo, "checkout", "-q", "main")
        before = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.commit("src/app.ts", "z"); self.commit("docs/note.md", "d")
        out = subprocess.run([sys.executable, SELECT, "--base", "main", "--head", "HEAD", "--since", before],
                             cwd=self.repo, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        self.assertEqual(out.stdout.strip(), "app=true")
        self.assertEqual(self.select(), "app=false")  # without --since only the tip is judged

    def test_docs_globs_are_configurable(self):
        self.commit("site/page.html", "x")
        self.assertEqual(self.select(env={"AGENTKEEL_DOCS_GLOBS": "site/*"}), "app=false")


class Workflow(unittest.TestCase):
    def test_one_always_reporting_required_check(self):
        with open(WORKFLOW) as fh:
            text = fh.read()
        self.assertIn("agentkeel-required:", text)
        self.assertIn("if: always()", text)
        self.assertIn("fetch-depth: 0", text)  # the selector needs history


if __name__ == "__main__":
    unittest.main()
