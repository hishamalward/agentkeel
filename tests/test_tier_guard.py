import os
import unittest

from helpers import RepoCase, run_hook

H = "tier-guard.py"


class TierGuard(RepoCase):
    def test_no_declaration_blocks_write(self):
        code, err = run_hook(H, self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("no tier declared", err)

    def test_docs_always_allowed(self):
        self.assertEqual(run_hook(H, self.write("docs/specs/x-spec.md"))[0], 0)

    def test_expired_declaration_blocks(self):
        self.declare("small", expires_in=-10)
        code, err = run_hook(H, self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("expired", err)

    def test_small_allows_on_main(self):
        self.declare("small")
        self.assertEqual(run_hook(H, self.write("src/a.py"))[0], 0)
        self.assertEqual(run_hook(H, self.bash("git commit -m x -- src/a.py"))[0], 0)

    def test_medium_blocks_on_main(self):
        self.declare("medium")
        code, err = run_hook(H, self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("main", err)

    def test_medium_allows_on_branch(self):
        self.declare("medium"); self.branch("feat/x")
        self.assertEqual(run_hook(H, self.write("src/a.py"))[0], 0)

    def test_large_blocks_without_approved_spec(self):
        self.declare("large", slug="json-flag"); self.branch("feat/json-flag")
        code, err = run_hook(H, self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("approved spec", err)
        os.makedirs(os.path.join(self.repo, "docs", "specs"))
        with open(os.path.join(self.repo, "docs", "specs", "json-flag-spec.md"), "w") as fh:
            fh.write("---\nslug: json-flag\nstatus: draft\n---\n")
        code, err = run_hook(H, self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("draft", err)

    def test_spec_status_with_inline_comment_is_read(self):
        # found in the worked example: the template's "status: draft   # draft | approved" was read as missing
        self.declare("large", slug="json-flag"); self.branch("feat/json-flag")
        os.makedirs(os.path.join(self.repo, "docs", "specs"))
        with open(os.path.join(self.repo, "docs", "specs", "json-flag-spec.md"), "w") as fh:
            fh.write("---\nstatus: draft            # draft | approved | superseded\n---\n")
        code, err = run_hook(H, self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("status 'draft'", err)
        with open(os.path.join(self.repo, "docs", "specs", "json-flag-spec.md"), "w") as fh:
            fh.write("---\nstatus: approved   # ruled by the human\napproved_by: h\n---\n")
        self.assertEqual(run_hook(H, self.write("src/a.py"))[0], 0)

    def test_large_allows_with_approved_spec(self):
        self.declare("large", slug="json-flag"); self.branch("feat/json-flag")
        os.makedirs(os.path.join(self.repo, "docs", "specs"))
        with open(os.path.join(self.repo, "docs", "specs", "json-flag-spec.md"), "w") as fh:
            fh.write("---\nslug: json-flag\nstatus: approved\napproved_by: human\n---\n")
        self.assertEqual(run_hook(H, self.write("src/a.py"))[0], 0)

    def test_non_git_bash_ignored_and_other_tools_ignored(self):
        self.assertEqual(run_hook(H, self.bash("ls -la"))[0], 0)
        self.assertEqual(run_hook(H, {"tool_name": "Read", "cwd": self.repo, "tool_input": {"file_path": "x"}})[0], 0)

    def test_malformed_input_allows(self):
        self.assertEqual(run_hook(H, "not json")[0], 0)


if __name__ == "__main__":
    unittest.main()
