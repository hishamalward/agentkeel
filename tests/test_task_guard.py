"""task-guard.py: the reproduced bypasses are blocked, and authorized work is not."""
import json
import os
import subprocess
import unittest

from helpers import HOOKS, GIT_ENV, SESSION, RepoCase, git


class NoTask(RepoCase):
    def test_write_without_task_blocked(self):
        code, err = self.hook(self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("no task is declared", err)
        self.assertIn("--deliverable", err); self.assertIn("no-code|small|large", err)

    def test_docs_write_without_task_blocked_too(self):
        self.assertEqual(self.hook(self.write("docs/x.md"))[0], 2)

    def test_reads_and_plain_git_allowed_without_task(self):
        for c in ("ls -la", "git status", "git log --oneline", "git diff", "git fetch origin",
                  "git checkout -b feat/y", "npm test"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)

    def test_commit_without_task_blocked(self):
        self.assertEqual(self.hook(self.bash("git commit -m x -- a.py"))[0], 2)

    def test_malformed_input_allows(self):
        self.assertEqual(self.hook("{")[0], 0)


class SessionBinding(RepoCase):
    def test_allowed_commit_marks_report_due_and_local_state_commands_are_human_only(self):
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.hook(self.bash("git commit -m message -- file.py"))[0], 0)
        self.assertGreater(self.record().get("code_changed_at", 0), 0)
        for command in ("python3 task.py init", "python3 task.py deactivate",
                        "python3 task.py discard x --worktree /tmp/work"):
            self.assertEqual(self.hook(self.bash(command))[0], 2, command)

    def test_second_session_cannot_use_first_sessions_task(self):
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.hook(self.write("src/a.py"))[0], 0)
        code, err = self.hook(self.write("src/a.py", session="session-b"))
        self.assertEqual(code, 2); self.assertIn("no task is declared", err)

    def test_record_copied_under_another_session_name_grants_nothing(self):
        self.declare(); self.branch("feat/x")
        src = os.path.join(self.home, "tasks", SESSION + ".json")
        with open(src) as fh:
            data = fh.read()
        with open(os.path.join(self.home, "tasks", "session-b.json"), "w") as fh:
            fh.write(data)  # session_id inside still says session-a
        self.assertEqual(self.hook(self.write("src/a.py", session="session-b"))[0], 2)


class ProtectedConfig(RepoCase):
    def test_hook_config_and_state_never_edited_by_the_agent(self):
        from agentkeel_core import record
        for rel in (".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/task-guard.py",
                    ".codex/hooks.json", ".codex/config.toml", record.policy_path(self.repo)):
            self.assertEqual(self.hook(self.write(rel))[0], 2, rel)
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.hook(self.write(".claude/settings.json"))[0], 2)
        self.assertEqual(self.hook(self.write("src/agentkeel-policy.json"))[0], 0)
        rec = os.path.join(self.home, "tasks", SESSION + ".json")
        code, err = self.hook(self.write(rec, content="{}"))
        self.assertEqual(code, 2); self.assertIn("installer or by the human", err)


class WriteRoots(RepoCase):
    def setUp(self):
        super().setUp()
        self.report = os.path.join(self.tmp, "reports", "review-a")
        self.other_report = os.path.join(self.tmp, "reports", "review-b")
        os.makedirs(self.report); os.makedirs(self.other_report)

    def test_review_writes_only_its_report(self):
        self.declare(allow=("review",), write_roots=[self.report])
        self.assertEqual(self.hook(self.write(os.path.join(self.report, "page.html")))[0], 0)
        self.assertEqual(self.hook(self.write(os.path.join(self.other_report, "page.html")))[0], 2)
        self.branch("feat/x")
        code, err = self.hook(self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("writes only its", err)

    def test_review_cannot_commit_build_or_push(self):
        self.declare(allow=("review",), write_roots=[self.report]); self.branch("feat/x")
        self.assertEqual(self.hook(self.bash("git commit -m x -- a.py"))[0], 2)
        self.assertEqual(self.hook(self.bash("eas build --platform ios"))[0], 2)
        self.assertEqual(self.hook(self.bash("git push origin main"))[0], 2)

    def test_foreign_worktree_and_foreign_temp_repo_blocked(self):
        self.declare(); self.branch("feat/x")
        other = os.path.join(self.tmp, "other-task-repo")
        subprocess.run(["git", "init", "-q", "-b", "feat/o", other], check=True)
        code, err = self.hook(self.write(os.path.join(other, "a.py")))
        self.assertEqual(code, 2); self.assertIn("another worktree", err)

    def test_own_scratch_allowed_with_implement(self):
        self.declare(); self.branch("feat/x")
        session_dir = os.path.join(self.tmp, "claude-scratch", SESSION, "scratchpad")
        self.assertEqual(self.hook(self.write(os.path.join(session_dir, "n.txt")))[0], 0)

    def test_another_tasks_temp_file_blocked_for_implement(self):
        self.declare(); self.branch("feat/x")
        foreign = os.path.join(self.tmp, "other-session", "report.html")
        os.makedirs(os.path.dirname(foreign))
        with open(foreign, "w") as fh:
            fh.write("theirs")
        code, err = self.hook(self.write(foreign))
        self.assertEqual(code, 2); self.assertIn("scratch", err)

    def test_outside_everything_blocked(self):
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.hook(self.write("/etc/hosts"))[0], 2)


class Branches(RepoCase):
    def test_implement_on_main_blocked_for_every_size(self):
        for size in ("small", "medium", "large"):
            self.declare(size=size)
            code, err = self.hook(self.write("src/a.py"))
            self.assertEqual(code, 2, size); self.assertIn("protected branch 'main'", err)

    def test_implement_on_branch_allowed(self):
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.hook(self.write("src/a.py"))[0], 0)

    def test_manual_worktree_add_does_not_claim_or_create_a_tree(self):
        self.declare()
        wt = os.path.join(self.tmp, "repo-x")
        code, err = self.hook(self.bash(f"git worktree add {wt} -b feat/x"))
        self.assertEqual(code, 2); self.assertIn("ownership manifest", err)
        self.assertNotIn(wt, self.record()["worktrees"])
        self.assertFalse(os.path.exists(wt))

    def test_protected_branches_from_policy_file(self):
        self.set_policy({"protected_branches": ["main", "release"]})
        self.declare(); self.branch("release")
        self.assertEqual(self.hook(self.write("src/a.py"))[0], 2)


class Commits(RepoCase):
    def setUp(self):
        super().setUp()
        self.declare(); self.branch("feat/x")

    def put(self, rel, text):
        with open(os.path.join(self.repo, rel), "w") as fh:
            fh.write(text)

    def test_explicit_paths_allowed(self):
        for c in ("git commit -m x -- a.py", "git commit -m 'x y' a.py b.py",
                  "git commit -m x --pathspec-from-file=list.txt"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)

    def test_bare_and_all_commits_blocked(self):
        for c in ("git commit -m x", "git commit -am x", "git commit --all -m x", "git add -A && git commit -m x"):
            code, err = self.hook(self.bash(c))
            self.assertEqual(code, 2, c); self.assertIn("does not name its paths", err)

    def test_commit_finishing_a_merge_allowed(self):
        git(self.repo, "checkout", "-q", "-b", "side")
        self.put("f", "a\n")
        git(self.repo, "add", "f"); git(self.repo, "commit", "-q", "-m", "a")
        git(self.repo, "checkout", "-q", "feat/x")
        self.put("f", "b\n")
        git(self.repo, "add", "f"); git(self.repo, "commit", "-q", "-m", "b")
        subprocess.run(["git", "-C", self.repo, "merge", "side"], capture_output=True, env={**os.environ, **GIT_ENV})
        self.assertEqual(self.hook(self.bash("git commit --no-edit"))[0], 0)

    def test_commit_on_main_needs_merge(self):
        git(self.repo, "checkout", "-q", "main")
        code, err = self.hook(self.bash("git commit -m x -- a.py"))
        self.assertEqual(code, 2); self.assertIn("'merge' permission", err)
        self.declare(allow=("implement", "merge"))
        self.assertEqual(self.hook(self.bash("git commit -m x -- a.py"))[0], 0)


class Shipping(RepoCase):
    """The shipping bypasses from the evidence table, each with its authorized counterpart."""

    def setUp(self):
        super().setUp()
        self.branch("feat/x")

    def assert_blocked(self, command, needs):
        code, err = self.hook(self.bash(command))
        self.assertEqual(code, 2, command); self.assertIn(needs, err, command)

    def test_push_to_main_needs_push(self):
        self.declare(allow=("implement",))
        for c in ("git push origin main", "git push origin HEAD:main", "git push origin feat/x:main",
                  "git push origin refs/heads/feat/x:refs/heads/main"):
            self.assert_blocked(c, "'push' permission")
        self.declare(allow=("implement", "push"))
        self.assertEqual(self.hook(self.bash("git push origin feat/x"))[0], 0)
        self.assertEqual(self.hook(self.bash("git push -u origin feat/x"))[0], 0)

    def test_compound_second_push_blocked(self):
        self.declare(allow=("implement",))
        self.assert_blocked("git push origin feat/x && git push origin main", "'push' permission")
        self.assert_blocked("git push origin feat/x; git push origin main", "'push' permission")
        self.assert_blocked("git status\ngit push origin main", "'push' permission")
        self.assert_blocked("echo $(git push origin main)", "'push' permission")
        self.assert_blocked("bash -c 'git push origin main'", "'push' permission")

    def test_plus_main_is_a_force_push(self):
        self.declare(allow=("implement", "push"))
        self.assert_blocked("git push origin +main", "force push")

    def test_global_options_and_other_repo(self):
        self.declare(allow=("implement",))
        self.assert_blocked("git -c core.pager=cat push origin main", "'push' permission")
        self.assert_blocked("git --no-pager push origin main", "'push' permission")
        other = os.path.join(self.tmp, "main-repo")
        subprocess.run(["git", "init", "-q", "-b", "main", other], check=True)
        self.assert_blocked(f"git -C {other} push", "'push' permission")
        self.assert_blocked(f"cd {other} && git push", "'push' permission")
        self.assert_blocked(f"git -C {other} commit -m x -- a.py", "not one of task 'x's worktrees")

    def test_alias_is_expanded(self):
        self.declare(allow=("implement",))
        self.assert_blocked("git -c alias.ship=push ship origin main", "'push' permission")

    def test_local_moves_of_main_need_merge(self):
        self.declare(allow=("implement",))
        main_wt = os.path.join(self.tmp, "repo-main")
        git(self.repo, "worktree", "add", "-q", main_wt, "main")
        for c in (f"git -C {main_wt} merge --ff-only feat/x", f"cd {main_wt} && git merge feat/x",
                  "git fetch . feat/x:main", "git push . feat/x:main", "git update-ref refs/heads/main HEAD",
                  "git branch -f main HEAD", "git checkout -B main", f"git -C {main_wt} reset --soft HEAD~1",
                  f"git -C {main_wt} rebase feat/x", "git rebase feat/x main", f"git -C {main_wt} pull"):
            self.assert_blocked(c, "'merge' permission")

    def test_merge_and_push_request_passes_first_try(self):
        self.declare(allow=("implement", "merge", "push"))
        main_wt = os.path.join(self.tmp, "repo-main")
        git(self.repo, "worktree", "add", "-q", main_wt, "main")
        for c in (f"git -C {main_wt} merge --ff-only feat/x", "git fetch . feat/x:main",
                  "git push origin main", f"git -C {main_wt} merge --ff-only feat/x && git push origin main"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)

    def test_merge_on_own_branch_needs_no_merge_permission(self):
        self.declare(allow=("implement",))
        for c in ("git merge main", "git rebase main", "git pull --rebase origin main", "git reset --soft HEAD~1"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)

    def test_size_never_grants_shipping(self):
        for size in ("small", "medium", "large"):
            self.declare(size=size, allow=("implement",))
            self.assert_blocked("git push origin main", "'push' permission")

    def test_heredoc_body_is_data(self):
        self.declare(allow=("implement",))
        cmd = "cat > notes.md <<'EOF'\nthen run git push origin main\nEOF\ngit status"
        self.assertEqual(self.hook(self.bash(cmd))[0], 0)

    def test_commit_message_mentioning_push_is_data(self):
        self.declare(allow=("implement",))
        self.assertEqual(self.hook(self.bash('git commit -m "docs: never git push origin main" -- a.md'))[0], 0)


class Destructive(RepoCase):
    def setUp(self):
        super().setUp()
        self.declare(allow=("implement", "merge", "push")); self.branch("feat/x")

    def test_blocked_even_with_every_permission(self):
        for c in ("git push --force origin feat/x", "git push -f", "git push --force-with-lease origin feat/x",
                  "git reset --hard HEAD~1", "git checkout -- .", "git checkout .", "git restore .",
                  "git clean -fd", "git branch -D other", "git branch -d -f other", "git stash drop",
                  "git stash pop", "git stash clear", "git push origin :feat/y", "git push --delete origin main",
                  "git worktree remove --force ../x", "git checkout -f other"):
            code, err = self.hook(self.bash(c))
            self.assertEqual(code, 2, c); self.assertIn("refusing", err, c)

    def test_benign_forms_allowed(self):
        for c in ("git reset --soft HEAD~1", "git stash list", "git stash", "git branch -d merged",
                  "git restore --staged a.py", "git checkout -- a.py", "git clean -n", "git stash apply"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)

    def test_inline_override_works_once_and_is_logged(self):
        code, _ = self.hook(self.bash("AGENTKEEL_ALLOW_DESTRUCTIVE=1 git reset --hard"))
        self.assertEqual(code, 0)
        with open(os.path.join(self.home, "overrides.jsonl")) as fh:
            line = json.loads(fh.readline())
        self.assertEqual(line["override"], "AGENTKEEL_ALLOW_DESTRUCTIVE")
        self.assertEqual(line["session_id"], SESSION)
        self.assertEqual(self.hook(self.bash("git reset --hard"))[0], 2)  # once means once

    def test_harness_environment_is_not_an_override(self):
        code, _ = self.hook(self.bash("git reset --hard"), env={"AGENTKEEL_ALLOW_DESTRUCTIVE": "1"})
        self.assertEqual(code, 2)


class CommandClasses(RepoCase):
    def setUp(self):
        super().setUp()
        self.branch("feat/x")

    def test_distribution_builds_and_submissions_need_their_own_permission(self):
        self.declare(allow=("implement", "merge", "push"))
        for c in ("eas build --platform ios", "npx eas-cli build -p android", "eas submit -p ios",
                  "eas update --branch production", "npm publish"):
            code, err = self.hook(self.bash(c))
            self.assertEqual(code, 2, c); self.assertIn("permission", err)
        self.declare(allow=("implement", "distribution-build"))
        self.assertEqual(self.hook(self.bash("eas build --platform ios"))[0], 0)
        self.assertEqual(self.hook(self.bash("eas submit -p ios"))[0], 2)

    def test_deploy_commands_need_push(self):
        self.declare(allow=("implement",))
        self.assertEqual(self.hook(self.bash("railway up"))[0], 2)
        self.declare(allow=("implement", "push"))
        self.assertEqual(self.hook(self.bash("railway up"))[0], 0)

    def test_local_build_is_part_of_implement(self):
        self.declare(allow=("implement",))
        for c in ("npm run build", "eas build:list", "xcodebuild -scheme App build", "npx tsc --noEmit"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)

    def test_paid_job_patterns_from_policy_file(self):
        self.set_policy({"commands": {"paid-job": [r"^npx tsx scripts/eval-"]}})
        self.declare(allow=("implement",))
        self.assertEqual(self.hook(self.bash("npx tsx scripts/eval-run.ts"))[0], 2)
        self.declare(allow=("implement", "paid-job"))
        self.assertEqual(self.hook(self.bash("npx tsx scripts/eval-run.ts"))[0], 0)


class LargeCheckpoint(RepoCase):
    """Large records keep authorization and worktree checks without an HTML path grammar."""

    def setUp(self):
        super().setUp()
        self.declare(size="large", task="json-flag"); self.branch("feat/json-flag")
        os.makedirs(os.path.join(self.repo, "docs"))

    def test_free_form_checkpoint_and_any_owned_path_are_writable(self):
        page = os.path.join(self.repo, "docs", "261015-json-flag-state.html")
        self.assertEqual(self.hook(self.write(page, content="free form checkpoint"))[0], 0)
        self.assertEqual(self.hook(self.write("src/unlisted.py"))[0], 0)
        self.assertEqual(self.hook(self.bash("git commit -m code -- src/unlisted.py"))[0], 0)

    def test_size_does_not_grant_write_or_checkout_access(self):
        self.declare(size="large", allow=("review",), worktrees=[])
        self.assertEqual(self.hook(self.write("src/unlisted.py"))[0], 2)
        self.assertEqual(self.hook(self.write(os.path.join(self.primary, "src", "x.py")))[0], 2)


class ReviewFindings(RepoCase):
    """Regression tests for the first review of v0.2 (2026-10-04), one per confirmed finding."""

    def setUp(self):
        super().setUp()
        self.declare(); self.branch("feat/x")
        self.other = os.path.join(self.tmp, "other")
        git(self.repo, "worktree", "add", "-q", self.other, "-b", "feat/y")

    def blocked(self, command):
        code, err = self.hook(self.bash(command))
        self.assertEqual(code, 2, command)
        self.assertNotIn("internal error", err, command)

    def test_option_without_value_does_not_crash_the_line_through(self):
        self.blocked("git --git-dir ; git push origin main")
        self.blocked("git --work-tree && git push origin main")
        self.blocked("git -C\ngit push origin main")

    def test_manual_worktree_add_of_an_existing_directory_is_refused(self):
        code, err = self.hook(self.bash(f"git worktree add {self.other}"))
        self.assertEqual(code, 2); self.assertIn("task.py start", err)
        self.assertNotIn(self.other, self.record()["worktrees"])
        self.assertEqual(self.hook(self.write(os.path.join(self.other, "b.py")))[0], 2)

    def test_checkout_main_earlier_in_the_line_counts(self):
        self.blocked("git checkout main && git merge feat/x")
        self.blocked("git switch main; git reset --soft HEAD~1")
        self.blocked("git rebase --onto feat/x HEAD~1 main")
        self.assertEqual(self.hook(self.bash("git checkout -b feat/z && git commit -m x -- a.py"))[0], 0)

    def test_parser_shapes_that_hid_a_push(self):
        for c in ("bash -lc 'git push origin main'", "zsh -ic 'git push origin main'",
                  "bash <<EOF\ngit push origin main\nEOF",
                  "git commit -m 'a<<b' -- a.py\ngit push origin main",
                  "echo $((1<<2))\ngit push origin main", "echo hi # note\ngit push origin main",
                  "git push \\\norigin main", "env -S 'git push origin main'",
                  "git config alias.p 'push origin main' && git p",
                  "git -c remote.origin.push=HEAD:refs/heads/main push origin"):
            self.blocked(c)

    def test_data_heredocs_and_messages_still_pass(self):
        for c in ("cat > f <<'EOF'\ngit push origin main\nEOF",
                  'git commit -m "$(cat <<\'EOF\'\nfix: never push to main\nEOF\n)" -- a.py',
                  "echo '# not a comment' && git status"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)

    def test_merge_permission_alone_cannot_commit_in_a_foreign_worktree(self):
        self.declare(allow=("merge",))
        self.blocked(f"git -C {self.other} commit -m m -- b.py")
        self.blocked(f"GIT_DIR={self.other}/.git git -C {self.other} commit -m m -- b.py")

    def test_package_runner_forms_of_a_build(self):
        for c in ("npx eas-cli@latest build", "npx --yes eas-cli@latest build -p ios", "pnpm exec eas build",
                  "npm exec -- eas build", "gh pr merge 12 --merge"):
            self.blocked(c)

    def test_dry_runs_are_not_the_action(self):
        for c in ("npm publish --dry-run", "git push --dry-run origin main"):
            self.assertEqual(self.hook(self.bash(c))[0], 0, c)


class StageReviewFindings(RepoCase):
    """Regression tests for the Stage 1 review (2026-10-04), one class of cases per finding."""

    def setUp(self):
        super().setUp()
        self.branch("feat/x")

    def code(self, payload):
        return self.hook(payload)[0]

    def test_every_remote_push_needs_push(self):
        report = os.path.join(self.tmp, "report"); os.makedirs(report)
        self.declare(allow=("review",), write_roots=[report])
        self.assertEqual(self.code(self.bash("git push origin feat/example")), 2)
        self.declare(allow=("implement", "push"))
        self.assertEqual(self.code(self.bash("git push origin main")), 2)  # also needs merge
        self.declare(allow=("implement", "merge"))
        self.assertEqual(self.code(self.bash("git push origin main")), 2)  # also needs push
        self.declare(allow=("implement", "merge", "push"))
        self.assertEqual(self.code(self.bash("git push origin main")), 0)
        self.declare(allow=("implement",))
        self.assertEqual(self.code(self.bash("git push origin feat/example")), 2)
        self.assertEqual(self.code(self.bash("git push . feat/x:feat/y")), 0)  # a local ref move

    def test_pr_merge_needs_merge_and_push(self):
        self.declare(allow=("implement", "push"))
        self.assertEqual(self.code(self.bash("gh pr merge 123 --merge")), 2)
        self.declare(allow=("implement", "merge"))
        self.assertEqual(self.code(self.bash("gh pr merge 123 --merge")), 2)
        self.declare(allow=("implement", "merge", "push"))
        self.assertEqual(self.code(self.bash("gh pr merge 123 --merge")), 0)
        self.assertEqual(self.code(self.bash("git push origin main")), 0)

    def test_html_checkpoint_has_no_special_write_approval(self):
        docs = os.path.join(self.repo, "docs"); os.makedirs(docs)
        page = os.path.join(docs, "261005-x-state.html")
        with open(page, "w") as fh:
            fh.write("<not-html>free form checkpoint")
        for allow in (("review",), ("implement",)):
            self.declare(allow=allow)
            code, _ = self.hook(self.write(page, content="any HTML or free-form checkpoint"))
            self.assertEqual(code, 0 if "implement" in allow else 2, allow)

    def test_write_root_never_reaches_repository_source(self):
        shared_src = os.path.join(self.primary, "src")
        for size, allow in (("large", ("review",)), ("large", ("implement",)), ("small", ("implement",))):
            self.declare(size=size, allow=allow, worktrees=[], write_roots=[shared_src])
            code, err = self.hook(self.write(os.path.join(shared_src, "app.py")))
            self.assertEqual(code, 2, (size, allow))
        other = os.path.join(self.tmp, "foreign-wt")
        git(self.primary, "worktree", "add", "-q", other, "-b", "feat/foreign")
        self.declare(allow=("implement",), write_roots=[other])
        self.assertEqual(self.code(self.write(os.path.join(other, "a.py"))), 2)
        git(self.repo, "checkout", "-q", "main")
        self.declare(allow=("implement",), write_roots=[os.path.join(self.repo, "src")])
        self.assertEqual(self.code(self.write("src/a.py")), 2)  # protected branch

    def test_report_folder_outside_the_repo_still_works(self):
        report = os.path.join(self.tmp, "reports", "r1"); os.makedirs(report)
        self.declare(allow=("review",), write_roots=[report])
        self.assertEqual(self.code(self.write(os.path.join(report, "page.html"))), 0)

    def test_shared_checkout_never_takes_code_edits(self):
        git(self.primary, "checkout", "-q", "-b", "feat/in-shared")
        self.declare(worktrees=[self.repo])
        code, err = self.hook(self.write(os.path.join(self.primary, "a.py")))
        self.assertEqual(code, 2); self.assertIn("shared checkout", err)
        self.assertEqual(self.code(self.write("src/a.py")), 0)  # its own worktree works


if __name__ == "__main__":
    unittest.main()


FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_GH_STATE"]))
a = sys.argv[1:]
if a[:1] == ["api"]:
    sha = a[1].split("/commits/")[1].split("/")[0]
    runs = state.get("runs", {}).get(sha, [])
    print(json.dumps({"check_runs": runs})); sys.exit(0)
sys.exit(1)
"""


class PushGate(RepoCase):
    """Private require_check_before_push policy: only a commit whose check passed ships."""

    def setUp(self):
        super().setUp()
        self.branch("feat/x")
        git(self.repo, "remote", "add", "origin", "https://github.com/someone/somerepo.git")
        self.set_policy({"require_check_before_push": "agentkeel-required"})
        self.gh = os.path.join(self.tmp, "fake-gh")
        with open(self.gh, "w") as fh:
            fh.write(FAKE_GH)
        os.chmod(self.gh, 0o755)
        self.state = os.path.join(self.tmp, "gh-state.json")
        self.sha = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.declare(allow=("implement", "merge", "push"))

    def runs(self, *conclusions, status="completed", sha=None):
        runs = [{"name": "agentkeel-required", "status": status, "conclusion": c,
                 "started_at": f"2026-10-04T00:00:0{i}Z"} for i, c in enumerate(conclusions)]
        with open(self.state, "w") as fh:
            json.dump({"runs": {sha or self.sha: runs}}, fh)

    def push(self, command=None):
        command = command or f"git push origin {self.sha}:main"
        return self.hook(self.bash(command), env={"AGENTKEEL_GH": self.gh, "FAKE_GH_STATE": self.state})

    def test_green_check_on_the_exact_commit_ships(self):
        self.runs("success")
        self.assertEqual(self.push()[0], 0)
        self.assertEqual(self.push(f"cd {self.repo} && git push origin {self.sha}:main")[0], 0)

    def test_a_branch_name_or_head_as_the_source_is_refused(self):
        self.runs("success")  # green, but a name can move between the check and the push
        for cmd in ("git push origin main", "git push origin feat/x:main", "git push origin HEAD:main",
                    f"git push origin {self.sha[:12]}:main"):
            code, err = self.push(cmd)
            self.assertEqual(code, 2, cmd); self.assertIn("full SHA", err)

    def ahead(self):
        """feat/x one commit ahead of main: HEAD and main are different commits."""
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "feature")
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def test_a_push_that_does_not_name_its_source_is_refused(self):
        self.runs("success", sha=self.ahead())  # HEAD green, main never checked
        code, err = self.push("git push origin --all")
        self.assertEqual(code, 2); self.assertIn("without naming what it sends", err)
        git(self.repo, "config", "remote.origin.push", "main")
        code, err = self.push("git push origin")
        self.assertEqual(code, 2); self.assertIn("without naming what it sends", err)

    def test_a_ref_moved_earlier_in_the_same_call_is_refused(self):
        self.ahead()
        self.runs("success")  # main green, feat/x never checked
        for cmd in (f"git -C {self.repo} checkout -q main && git merge --ff-only feat/x && git push origin main",
                    "git fetch . feat/x:main && git push origin main",
                    "./ship.sh; git push origin main"):
            code, err = self.push(cmd)
            self.assertEqual(code, 2, cmd); self.assertIn("Run the push alone", err)

    def test_pr_merge_is_refused_even_with_a_green_head(self):
        self.runs("success")
        code, err = self.push("gh pr merge 3 --merge")
        self.assertEqual(code, 2); self.assertIn("task.py ship --pr NUMBER", err)
        self.assertEqual(self.push("gh pr merge 3 --squash")[0], 2)

    def test_failed_missing_or_pending_check_refused(self):
        for setup, word in ((lambda: self.runs("failure"), "ended failure"), (lambda: self.runs(), "no 'agentkeel-required'"),
                            (lambda: self.runs(None, status="in_progress"), "still in_progress")):
            setup()
            code, err = self.push()
            self.assertEqual(code, 2); self.assertIn(word, err)
            self.assertEqual(self.push("gh pr merge 3 --merge")[0], 2)

    def test_latest_run_wins(self):
        self.runs("failure", "success")
        self.assertEqual(self.push()[0], 0)
        self.runs("success", "failure")
        self.assertEqual(self.push()[0], 2)

    def test_a_computed_source_cannot_skip_the_gate(self):
        self.runs("failure")
        for cmd in ("git push origin $(git rev-parse HEAD):main", "git push origin HEAD:$(echo main)",
                    "git push origin `git rev-parse HEAD`:main"):
            self.assertEqual(self.push(cmd)[0], 2, cmd)

    def test_feature_branch_push_needs_no_check(self):
        self.runs("failure")
        self.assertEqual(self.push("git push origin feat/x")[0], 0)

    def test_unverifiable_is_refused(self):
        self.runs("success")
        code, err = self.hook(self.bash(f"git push origin {self.sha}:main"), env={"AGENTKEEL_GH": "/nonexistent/gh"})
        self.assertEqual(code, 2); self.assertIn("could not ask GitHub", err)
