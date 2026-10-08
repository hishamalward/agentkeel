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


class DocsJob(unittest.TestCase):
    """The docs check runs on every candidate, docs-only included, and the required check needs it."""

    def test_required_check_needs_a_successful_docs_job(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML is not installed")
        with open(WORKFLOW) as fh:
            wf = yaml.safe_load(fh)
        jobs = wf["jobs"]
        self.assertEqual(jobs["docs"]["needs"], "select")
        self.assertIn("pages.py check --rev", jobs["docs"]["steps"][-1]["run"])
        self.assertIn("docs", jobs["agentkeel-required"]["needs"])
        self.assertIn('test "${{ needs.docs.result }}" = "success"', jobs["agentkeel-required"]["steps"][0]["run"])
        on = wf.get("on", wf.get(True))
        self.assertEqual(set(on), {"push", "pull_request"})
        self.assertEqual(on["push"]["branches"], ["main"])
        self.assertIn("ready_for_review", on["pull_request"]["types"])
        self.assertIn("!github.event.pull_request.draft", jobs["select"]["if"])
        self.assertEqual(jobs["select"]["steps"][0]["with"]["ref"],
                         "${{ github.event.pull_request.head.sha || github.sha }}")
        self.assertIn("needs.select.outputs.reuse", jobs["app-tests"]["if"])
        self.assertFalse(any(isinstance(v, dict) and ("paths" in v or "paths-ignore" in v) for v in on.values()))


if __name__ == "__main__":
    unittest.main()
