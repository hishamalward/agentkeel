import os
import tempfile
import unittest

from helpers import RepoCase, run_hook

H = "write-path-guard.py"


class WritePathGuard(RepoCase):
    def test_commit_on_main_blocked_unless_small(self):
        code, err = run_hook(H, self.bash("git commit -m x"))
        self.assertEqual(code, 2); self.assertIn("commit on 'main'", err)
        self.declare("small")
        self.assertEqual(run_hook(H, self.bash("git commit -m x -- a.py"))[0], 0)
        self.declare("medium")
        self.assertEqual(run_hook(H, self.bash("git commit -m x"))[0], 2)

    def test_commit_on_branch_allowed(self):
        self.branch("feat/x")
        self.assertEqual(run_hook(H, self.bash("git commit -m x"))[0], 0)

    def test_push_to_main_blocked_and_override_echoed(self):
        self.branch("feat/x")
        self.assertEqual(run_hook(H, self.bash("git push origin feat/x"))[0], 0)
        self.assertEqual(run_hook(H, self.bash("git push origin main"))[0], 2)
        self.assertEqual(run_hook(H, self.bash("git push origin HEAD:main"))[0], 2)
        code, err = run_hook(H, self.bash("git push origin main"), env={"AGENTKEEL_ALLOW_PUSH_MAIN": "1"})
        self.assertEqual(code, 0); self.assertIn("override AGENTKEEL_ALLOW_PUSH_MAIN", err)

    def test_push_while_on_main_without_refspec_blocked(self):
        self.assertEqual(run_hook(H, self.bash("git push"))[0], 2)

    def test_destructive_git_blocked_and_override_echoed(self):
        self.branch("feat/x")
        for cmd in ("git push --force origin feat/x", "git push -f", "git reset --hard HEAD~1",
                    "git checkout -- .", "git restore .", "git clean -fd", "git branch -D other",
                    "git stash drop"):
            self.assertEqual(run_hook(H, self.bash(cmd))[0], 2, cmd)
        code, err = run_hook(H, self.bash("git reset --hard"), env={"AGENTKEEL_ALLOW_DESTRUCTIVE": "1"})
        self.assertEqual(code, 0); self.assertIn("override AGENTKEEL_ALLOW_DESTRUCTIVE", err)

    def test_benign_git_allowed(self):
        for cmd in ("git status", "git checkout -b feat/y", "git reset --soft HEAD~1", "git stash list",
                    "git branch -d merged", "git restore --staged a.py", "git checkout -- a.py"):
            self.assertEqual(run_hook(H, self.bash(cmd))[0], 0, cmd)

    def test_edit_outside_worktree_blocked(self):
        code, err = run_hook(H, {"tool_name": "Edit", "cwd": self.repo, "tool_input": {"file_path": "/etc/hosts"}})
        self.assertEqual(code, 2); self.assertIn("outside this worktree", err)

    def test_edit_inside_and_temp_allowed(self):
        self.assertEqual(run_hook(H, self.write("src/a.py"))[0], 0)
        tmp = os.path.join(tempfile.gettempdir(), "scratch.txt")
        self.assertEqual(run_hook(H, {"tool_name": "Write", "cwd": self.repo, "tool_input": {"file_path": tmp}})[0], 0)

    def test_extra_root_override_echoed(self):
        with tempfile.TemporaryDirectory() as other:
            other = os.path.realpath(other)
            # a temp dir is allowed anyway; use a subdir of home-like path that is not temp
            target = os.path.join(other, "x.txt")
            code, err = run_hook(H, {"tool_name": "Write", "cwd": self.repo, "tool_input": {"file_path": target}},
                                 env={"AGENTKEEL_EXTRA_WRITE_ROOTS": other, "TMPDIR": "/nonexistent-tmp"})
            self.assertEqual(code, 0)

    def test_malformed_input_allows(self):
        self.assertEqual(run_hook(H, "{")[0], 0)


if __name__ == "__main__":
    unittest.main()
