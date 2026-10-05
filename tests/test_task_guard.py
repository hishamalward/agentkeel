"""task-guard.py: the reproduced bypasses are blocked, and authorized work is not."""
import json
import os
import subprocess
import unittest

from helpers import GIT_ENV, SESSION, RepoCase, git


class NoTask(RepoCase):
    def test_write_without_task_blocked(self):
        code, err = self.hook(self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("no task is declared", err)

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
        for rel in (".claude/settings.json", ".claude/settings.local.json", ".claude/hooks/task-guard.py",
                    ".codex/hooks.json", ".codex/config.toml", "agentkeel.json"):
            self.assertEqual(self.hook(self.write(rel))[0], 2, rel)
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.hook(self.write(".claude/settings.json"))[0], 2)
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

    def test_worktree_add_is_recorded_as_owned(self):
        self.declare()
        wt = os.path.join(self.tmp, "repo-x")
        self.assertEqual(self.hook(self.bash(f"git worktree add {wt} -b feat/x"))[0], 0)
        self.assertIn(wt, self.record()["worktrees"])
        git(self.repo, "worktree", "add", "-q", wt, "-b", "feat/x")
        self.assertEqual(self.hook(self.write(os.path.join(wt, "src.py")))[0], 0)

    def test_protected_branches_from_policy_file(self):
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"protected_branches": ["main", "release"]}, fh)
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
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"commands": {"paid-job": [r"^npx tsx scripts/eval-"]}}, fh)
        self.declare(allow=("implement",))
        self.assertEqual(self.hook(self.bash("npx tsx scripts/eval-run.ts"))[0], 2)
        self.declare(allow=("implement", "paid-job"))
        self.assertEqual(self.hook(self.bash("npx tsx scripts/eval-run.ts"))[0], 0)


class LargeAndSpecApproval(RepoCase):
    SPEC = "docs/specs/json-flag-spec.md"

    def setUp(self):
        super().setUp()
        self.declare(size="large", task="json-flag"); self.branch("feat/json-flag")
        os.makedirs(os.path.join(self.repo, "docs", "specs"))

    def spec(self, text):
        with open(os.path.join(self.repo, self.SPEC), "w") as fh:
            fh.write(text)

    APPROVED = ("---\nstatus: approved\napproved_by: hisham\napproved_on: 2026-10-04\n---\n\n"
                "## 4. Blast radius\n\n- **Changes** (paths that may change): `cli.py`, `tests/`\n"
                "- **Must not change**: `cli_legacy.py`\n- **Boundary**: none\n")

    def test_no_spec_blocks_code_but_not_docs(self):
        code, err = self.hook(self.write("cli.py"))
        self.assertEqual(code, 2); self.assertIn("does not exist", err)
        self.assertEqual(self.hook(self.write("docs/plans/json-flag-plan.md"))[0], 0)

    def test_approval_inside_a_code_block_is_not_approval(self):
        self.spec("---\nstatus: draft\n---\n\n```yaml\nstatus: approved\napproved_by: x\napproved_on: 2026-10-04\n```\n")
        code, err = self.hook(self.write("cli.py"))
        self.assertEqual(code, 2); self.assertIn("status 'draft'", err)

    def test_approval_without_approver_or_date_is_not_approval(self):
        self.spec("---\nstatus: approved\n---\n")
        self.assertIn("approved_by", self.hook(self.write("cli.py"))[1])
        self.spec("---\nstatus: approved\napproved_by: h\napproved_on: soon\n---\n")
        self.assertIn("approved_on", self.hook(self.write("cli.py"))[1])

    def test_inline_comment_on_status_is_read(self):
        self.spec("---\nstatus: draft            # draft | approved | superseded\n---\n")
        self.assertIn("status 'draft'", self.hook(self.write("cli.py"))[1])

    def test_agent_cannot_write_the_approval(self):
        self.spec("---\nstatus: draft\napproved_by:\napproved_on:\n---\n")
        code, err = self.hook(self.write(self.SPEC, content=self.APPROVED))
        self.assertEqual(code, 2); self.assertIn("human's ruling", err)
        edit = {"tool_name": "Edit", "cwd": self.repo, "session_id": SESSION,
                "tool_input": {"file_path": os.path.join(self.repo, self.SPEC),
                               "old_string": "status: draft\napproved_by:\napproved_on:",
                               "new_string": "status: approved\napproved_by: me\napproved_on: 2026-10-04"}}
        self.assertEqual(self.hook(edit)[0], 2)
        self.assertEqual(self.hook(self.bash(f".claude/hooks/task.py approve json-flag"))[0], 2)
        self.assertEqual(self.hook(self.bash(f"python3 hooks/task.py approve {self.SPEC}"))[0], 2)
        self.assertEqual(self.hook(self.bash("python3 -B hooks/task.py approve json-flag"))[0], 2)

    def test_approved_spec_changes_only_to_be_superseded(self):
        self.spec(self.APPROVED)
        widened = self.APPROVED.replace("`cli.py`, `tests/`", "`cli.py`, `tests/`, `src/`")
        code, err = self.hook(self.write(self.SPEC, content=widened))
        self.assertEqual(code, 2); self.assertIn("approved spec", err)
        self.assertEqual(self.hook(self.write("src/b.py"))[0], 2)
        superseded = self.APPROVED.replace("status: approved", "status: superseded")
        self.assertEqual(self.hook(self.write(self.SPEC, content=superseded))[0], 0)

    def test_approved_spec_bounds_writes_to_its_changes_list(self):
        self.spec(self.APPROVED)
        self.assertEqual(self.hook(self.write("cli.py"))[0], 0)
        self.assertEqual(self.hook(self.write("tests/test_cli.py"))[0], 0)
        code, err = self.hook(self.write("src/other.py"))
        self.assertEqual(code, 2); self.assertIn("Changes list", err)
        code, err = self.hook(self.write("cli_legacy.py"))
        self.assertEqual(code, 2); self.assertIn("Must not change", err)

    def test_commit_outside_docs_waits_for_approval(self):
        self.assertEqual(self.hook(self.bash(f"git commit -m spec -- {self.SPEC}"))[0], 0)
        self.assertEqual(self.hook(self.bash("git commit -m code -- cli.py"))[0], 2)
        self.spec(self.APPROVED)
        self.assertEqual(self.hook(self.bash("git commit -m code -- cli.py"))[0], 0)


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

    def test_worktree_add_of_an_existing_directory_grants_nothing(self):
        self.assertEqual(self.hook(self.bash(f"git worktree add {self.other}"))[0], 0)
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

    def test_write_roots_keep_the_approval_checks(self):
        specs = os.path.join(self.repo, "docs", "specs"); os.makedirs(specs)
        spec = os.path.join(specs, "x-spec.md")
        approved = "---\nstatus: approved\napproved_by: h\napproved_on: 2026-10-04\n---\nbody\n"
        with open(spec, "w") as fh:
            fh.write("---\nstatus: draft\n---\n")
        self.declare(allow=("review",), write_roots=[specs])
        self.assertEqual(self.code(self.write(spec, content=approved)), 2)
        self.assertEqual(self.code(self.write(spec, content="---\nstatus: draft\n---\nmore\n")), 0)
        with open(spec, "w") as fh:
            fh.write(approved)
        self.assertEqual(self.code(self.write(spec, content=approved + "widened\n")), 2)
        self.assertEqual(self.code(self.write(os.path.join(specs, "notes.md"), content="x")), 0)

    def test_write_root_inside_a_large_task_keeps_the_blast_radius(self):
        self.declare(size="large", task="json-flag", write_roots=[os.path.join(self.repo, "src")])
        self.assertEqual(self.code(self.write("src/a.py")), 2)

    def test_shared_checkout_never_takes_code_edits(self):
        git(self.primary, "checkout", "-q", "-b", "feat/in-shared")
        self.declare(worktrees=[self.repo])
        code, err = self.hook(self.write(os.path.join(self.primary, "a.py")))
        self.assertEqual(code, 2); self.assertIn("shared checkout", err)
        self.assertEqual(self.code(self.write("src/a.py")), 0)  # its own worktree works


if __name__ == "__main__":
    unittest.main()
