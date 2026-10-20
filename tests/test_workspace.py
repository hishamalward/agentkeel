import concurrent.futures
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from helpers import RepoCase, git
from agentkeel_core import workspace


class Workspace(RepoCase):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.tmp, "task-worktree")

    def create(self, **kwargs):
        return workspace.create(self.repo, "task-x", "session-x", path=self.path,
                                branch="feat/task-x", base="main", **kwargs)

    def release(self, manifest):
        with patch.object(workspace, "active_processes", return_value=[]):
            return workspace.release(manifest)

    def test_create_records_canonical_git_identity_and_inspect_returns_a_copy(self):
        manifest = self.create()
        self.assertEqual(manifest["state"], "active")
        self.assertEqual(manifest["path"], os.path.realpath(self.path))
        self.assertEqual(manifest["task"], "task-x")
        self.assertEqual(manifest["session"], "session-x")
        self.assertEqual(manifest["base_sha"], subprocess.check_output(
            ["git", "-C", self.repo, "rev-parse", "main"], text=True).strip())
        self.assertEqual(workspace.inspect(self.path), manifest)
        manifest["branch"] = "feat/foreign"
        self.assertEqual(workspace.inspect(self.path)["branch"], "feat/task-x")

    def test_existing_path_and_branch_are_refused_without_removing_the_winner(self):
        os.mkdir(self.path)
        with open(os.path.join(self.path, "keep"), "w") as fh:
            fh.write("human data")
        with self.assertRaises(workspace.WorkspaceError):
            self.create()
        with open(os.path.join(self.path, "keep")) as fh:
            self.assertEqual(fh.read(), "human data")
        os.unlink(os.path.join(self.path, "keep"))
        os.rmdir(self.path)
        git(self.repo, "branch", "feat/task-x", "main")
        with self.assertRaises(workspace.WorkspaceError):
            self.create()
        self.assertEqual(subprocess.check_output(
            ["git", "-C", self.repo, "rev-parse", "feat/task-x"], text=True).strip(),
            subprocess.check_output(["git", "-C", self.repo, "rev-parse", "main"], text=True).strip())

    def test_creation_failure_rolls_back_only_its_worktree_and_branch(self):
        with patch.object(workspace, "_write_manifest", side_effect=OSError("disk full")):
            with self.assertRaises(workspace.WorkspaceError):
                self.create()
        self.assertFalse(os.path.exists(self.path))
        self.assertNotEqual(subprocess.run(["git", "-C", self.repo, "show-ref", "--verify",
                                            "--quiet", "refs/heads/feat/task-x"]).returncode, 0)

    def test_create_ignores_git_environment_overrides_and_repository_hooks(self):
        hook_dir = os.path.join(self.primary, ".git", "hooks")
        sentinel = os.path.join(self.tmp, "hook-ran")
        hook = os.path.join(hook_dir, "post-checkout")
        with open(hook, "w") as fh:
            fh.write(f"#!/bin/sh\ntouch '{sentinel}'\n")
        os.chmod(hook, 0o755)
        with patch.dict(os.environ, {"GIT_DIR": os.path.join(self.primary, ".git"),
                                     "GIT_WORK_TREE": self.primary}):
            manifest = self.create()
        self.assertEqual(workspace.inspect(self.path)["identity"], manifest["identity"])
        self.assertFalse(os.path.exists(sentinel))

    def test_partial_git_add_failure_rolls_back_its_staging_worktree(self):
        run_git = workspace._git

        def add_then_fail(repo, *args, **kwargs):
            result = run_git(repo, *args, **kwargs)
            if args[:2] == ("worktree", "add"):
                raise workspace.WorkspaceError("simulated post-add failure")
            return result

        with patch.object(workspace, "_git", side_effect=add_then_fail):
            with self.assertRaises(workspace.WorkspaceError):
                self.create()
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(any(path.startswith(os.path.join(self.tmp, ".agent-worktree."))
                             for path, _ in workspace._worktrees(self.repo)))
        self.assertNotEqual(subprocess.run(["git", "-C", self.repo, "show-ref", "--verify",
                                            "--quiet", "refs/heads/feat/task-x"]).returncode, 0)

    def test_rollback_keeps_files_that_appear_after_the_staged_move(self):
        run_git = workspace._git

        def move_then_change(repo, *args, **kwargs):
            result = run_git(repo, *args, **kwargs)
            if args[:2] == ("worktree", "move"):
                with open(os.path.join(self.path, "arrived-during-rollback"), "w") as fh:
                    fh.write("human data")
                raise workspace.WorkspaceError("simulated interruption after move")
            return result

        with patch.object(workspace, "_git", side_effect=move_then_change):
            with self.assertRaises(workspace.WorkspaceError):
                self.create()
        self.assertTrue(os.path.isfile(os.path.join(self.path, "arrived-during-rollback")))
        self.assertTrue(any(p == self.path for p, _ in workspace._worktrees(self.repo)))
        self.assertEqual(subprocess.check_output(["git", "-C", self.repo, "rev-parse", "feat/task-x"],
                                                 text=True).strip(),
                         subprocess.check_output(["git", "-C", self.repo, "rev-parse", "main"],
                                                 text=True).strip())

    def test_competing_creates_leave_exactly_one_winner(self):
        paths = [os.path.join(self.tmp, "winner-a"), os.path.join(self.tmp, "winner-b")]

        def create(path):
            return workspace.create(self.repo, "task-x", "session-x", path=path,
                                    branch="feat/task-x", base="main")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda p: self._capture(create, p), paths))
        winners = [result for result in results if not isinstance(result, Exception)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(sum(os.path.isdir(path) for path in paths), 1)
        self.assertEqual(workspace.inspect(winners[0]["path"])["identity"], winners[0]["identity"])

    @staticmethod
    def _capture(fn, arg):
        try:
            return fn(arg)
        except Exception as error:
            return error

    def test_release_refuses_modified_ignored_and_unpreserved_work(self):
        with open(os.path.join(self.repo, ".gitignore"), "w") as fh:
            fh.write("ignored-data\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-q", "-m", "ignore generated files")
        manifest = self.create()
        with open(os.path.join(self.path, "untracked"), "w") as fh:
            fh.write("keep")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.release(manifest)
        self.assertTrue(os.path.isdir(self.path))
        runtime = workspace.runtime_path(self.path)
        with open(runtime, "w") as fh:
            json.dump({"identity": manifest["identity"], "state": "attached"}, fh)
        with self.assertRaises(workspace.WorkspaceError):
            workspace.release(manifest)
        self.assertTrue(os.path.isdir(self.path))
        os.unlink(os.path.join(self.path, "untracked"))
        with open(os.path.join(self.path, "ignored-data"), "w") as fh:
            fh.write("keep")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.release(manifest)
        os.unlink(os.path.join(self.path, "ignored-data"))
        with open(os.path.join(self.path, "work"), "w") as fh:
            fh.write("new commit")
        git(self.path, "add", "work")
        git(self.path, "commit", "-q", "-m", "unpreserved")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.release(manifest)
        self.assertTrue(os.path.exists(os.path.join(self.path, "work")))

    def test_broken_runtime_marker_symlink_blocks_release(self):
        manifest = self.create()
        os.symlink(os.path.join(self.tmp, "missing-runtime-marker"), workspace.runtime_path(self.path))
        with self.assertRaises(workspace.WorkspaceError):
            workspace.release(manifest)
        self.assertTrue(os.path.isdir(self.path))

    def test_release_allows_ignored_regenerable_caches_but_preserves_local_data(self):
        from pathlib import Path
        Path(self.repo, ".gitignore").write_text("__pycache__/\n.pytest_cache/\nnode_modules/\n.DS_Store\n.env\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-qm", "ignore local files")
        manifest = self.create()
        for folder in ("__pycache__", ".pytest_cache", "node_modules"):
            Path(self.path, folder).mkdir()
            Path(self.path, folder, "generated").write_text("cache")
        Path(self.path, ".DS_Store").write_text("cache")
        Path(self.path, ".env").write_text("local data")
        with self.assertRaises(workspace.WorkspaceError):
            self.release(manifest)
        self.assertEqual(Path(self.path, ".env").read_text(), "local data")
        Path(self.path, ".env").unlink()
        self.assertEqual(self.release(manifest)["state"], "released")

    def test_release_accepts_merged_tip_after_amend_and_rebase(self):
        from pathlib import Path
        for operation in ("amend", "rebase"):
            with self.subTest(operation=operation):
                manifest = self.create()
                Path(self.path, "work").write_text(operation)
                git(self.path, "add", "work")
                git(self.path, "commit", "-qm", "original")
                if operation == "amend":
                    git(self.path, "commit", "--amend", "-qm", "revised")
                else:
                    Path(self.repo, "other").write_text("base advance")
                    git(self.repo, "add", "other")
                    git(self.repo, "commit", "-qm", "base advance")
                    git(self.path, "rebase", "main")
                git(self.repo, "merge", "--ff-only", "feat/task-x")
                self.assertEqual(self.release(manifest)["state"], "released")

    def test_project_disposable_paths_preserve_other_ignored_data(self):
        from pathlib import Path
        Path(self.repo, ".gitignore").write_text(".venv/\nx.pyc\n.env\n.venv-backup/\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-qm", "ignore local files")
        self.set_policy({"disposable_ignored": [".venv", "x.pyc"]})
        manifest = self.create()
        for name in (".venv/bin/python", "x.pyc", ".env", ".venv-backup/data"):
            path = Path(self.path, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("local")
        with self.assertRaisesRegex(workspace.WorkspaceError, r"\.env"):
            self.release(manifest)
        self.assertEqual(Path(self.path, ".env").read_text(), "local")
        Path(self.path, ".env").unlink()
        with self.assertRaisesRegex(workspace.WorkspaceError, "venv-backup"):
            self.release(manifest)
        Path(self.path, ".venv-backup/data").unlink()
        self.assertEqual(self.release(manifest)["state"], "released")

    def test_invalid_disposable_paths_do_not_expand_cleanup(self):
        from pathlib import Path
        manifest = self.create()
        for value in (".venv", [""], ["."], [".."], ["/tmp"], ["../data"], ["*"], [None]):
            with self.subTest(value=value):
                self.set_policy({"disposable_ignored": value})
                with self.assertRaisesRegex(workspace.WorkspaceError, "disposable_ignored"):
                    self.release(manifest)
                self.assertTrue(Path(self.path).is_dir())

    def test_explicit_ignored_disposal_keeps_process_and_tip_checks(self):
        from pathlib import Path
        Path(self.repo, ".gitignore").write_text(".env\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-qm", "ignore local env")
        manifest = self.create()
        Path(self.path, ".env").write_text("private")
        with patch.object(workspace, "active_processes", return_value=["123"]):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.release(manifest, discard=True)
        self.assertTrue(Path(self.path, ".env").exists())
        Path(self.path, "work").write_text("unmerged")
        git(self.path, "add", "work")
        git(self.path, "commit", "-qm", "work")
        with patch.object(workspace, "active_processes", return_value=[]):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.release(manifest, discard_ignored=True)
            git(self.repo, "merge", "--ff-only", "feat/task-x")
            self.assertEqual(workspace.release(manifest, discard_ignored=True)["state"], "released")

    def test_release_of_merged_tree_ignores_other_worktrees_branch_stash_and_files(self):
        first = self.create()
        second_path = os.path.join(self.tmp, "task-worktree-b")
        second = workspace.create(self.repo, "task-y", "session-y", path=second_path,
                                  branch="feat/task-y", base="main")
        with open(os.path.join(second_path, "other-task"), "w") as fh:
            fh.write("unmerged")
        git(second_path, "add", "other-task")
        git(second_path, "commit", "-q", "-m", "other task work")
        with open(os.path.join(second_path, "stashed"), "w") as fh:
            fh.write("other task stash")
        git(second_path, "stash", "push", "-u", "-qm", "other task stash")
        with open(os.path.join(self.path, "merged"), "w") as fh:
            fh.write("preserved")
        git(self.path, "add", "merged")
        git(self.path, "commit", "-q", "-m", "task x work")
        git(self.repo, "merge", "--ff-only", "feat/task-x")
        self.assertEqual(self.release(first)["state"], "released")
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.isdir(second_path))
        self.assertTrue(os.path.exists(os.path.join(second_path, "other-task")))
        self.assertEqual(subprocess.check_output(["git", "-C", second_path, "rev-parse", "HEAD"],
                                                 text=True).strip(),
                         subprocess.check_output(["git", "-C", self.repo, "rev-parse", "feat/task-y"],
                                                 text=True).strip())
        self.assertEqual(subprocess.check_output(["git", "-C", second_path, "stash", "list"],
                                                 text=True).strip(), "stash@{0}: On feat/task-y: other task stash")

    def test_release_refuses_active_or_unidentifiable_processes(self):
        manifest = self.create()
        with patch.object(workspace, "active_processes", return_value=["123"]):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.release(manifest)
        with patch.object(workspace, "active_processes", side_effect=workspace.WorkspaceError("lsof failed")):
            with self.assertRaisesRegex(workspace.WorkspaceError, "lsof failed"):
                workspace.release(manifest)
        self.assertTrue(os.path.isdir(self.path))

    def test_release_requires_preserved_tip_and_matching_manifest(self):
        manifest = self.create()
        with open(os.path.join(self.path, "work"), "w") as fh:
            fh.write("commit")
        git(self.path, "add", "work")
        git(self.path, "commit", "-q", "-m", "preserved")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.release(manifest)
        self.assertTrue(os.path.isdir(self.path))
        git(self.repo, "merge", "--ff-only", "feat/task-x")
        foreign = dict(manifest, identity="foreign")
        with self.assertRaises(workspace.WorkspaceError):
            workspace.release(foreign)
        self.assertTrue(os.path.isdir(self.path))
        result = self.release(manifest)
        self.assertEqual(result["state"], "released")
        self.assertFalse(os.path.exists(self.path))
        self.assertNotEqual(subprocess.run(["git", "-C", self.repo, "show-ref", "--verify",
                                            "--quiet", "refs/heads/feat/task-x"]).returncode, 0)

    def test_prepare_release_marks_pending_and_slots_can_lock_for_cleanup(self):
        manifest = self.create()
        pending = workspace.prepare_release(manifest)
        self.assertEqual(pending["state"], "disposal_pending")
        with self.assertRaises(workspace.WorkspaceError):
            with workspace.lifecycle_lock(manifest):
                pass
        with workspace.lifecycle_lock(manifest, allow_pending=True) as current:
            self.assertEqual(current["identity"], manifest["identity"])
        self.assertEqual(self.release(manifest)["state"], "released")


if __name__ == "__main__":
    unittest.main()
