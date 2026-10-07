"""task-guard.py: the reproduced bypasses are blocked, and authorized work is not."""
import json
import os
import subprocess
import unittest

from helpers import HOOKS, approve_file, state_page, GIT_ENV, SESSION, RepoCase, git


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


class LargeAndBoundaryApproval(RepoCase):
    """A large task's limits come from its state page's approved boundary; approval is the human's."""
    PAGE = "docs/261005-json-flag-state.html"

    def setUp(self):
        super().setUp()
        self.declare(size="large", task="json-flag"); self.branch("feat/json-flag")
        os.makedirs(os.path.join(self.repo, "docs"))
        self.path = os.path.join(self.repo, self.PAGE)

    def put(self, text):
        with open(self.path, "w") as fh:
            fh.write(text)
        return text

    def approved(self, **kw):
        self.put(state_page(**kw))
        return approve_file(self.path, self.home)

    def test_no_page_blocks_code_but_not_docs(self):
        code, err = self.hook(self.write("cli.py"))
        self.assertEqual(code, 2); self.assertIn("no state page", err)
        self.assertEqual(self.hook(self.write(self.PAGE, content=state_page()))[0], 0)

    def test_unapproved_or_malformed_boundary_blocks_code(self):
        self.put(state_page())
        code, err = self.hook(self.write("cli.py"))
        self.assertEqual(code, 2); self.assertIn("not been approved", err)
        self.put(state_page().replace("</head>", '<meta name="keel-approval" content="sha256:zz by x on soon"></head>'))
        code, err = self.hook(self.write("cli.py"))
        self.assertEqual(code, 2); self.assertIn("malformed", err)
        self.put(state_page(boundary=False))
        self.assertIn("no boundary section", self.hook(self.write("cli.py"))[1])

    def test_agent_cannot_write_the_approval(self):
        draft = self.put(state_page())
        forged = state_page()
        from agentkeel_core import pages
        forged = pages.with_approval(os.path.basename(self.path), forged, "me", "2026-10-05")
        code, err = self.hook(self.write(self.PAGE, content=forged))
        self.assertEqual(code, 2); self.assertIn("human's ruling", err)
        meta = forged[forged.index("<meta name=\"keel-approval\""):forged.index("</head>")]
        edit = {"tool_name": "Edit", "cwd": self.repo, "session_id": SESSION,
                "tool_input": {"file_path": self.path, "old_string": "</head>", "new_string": meta + "</head>"}}
        self.assertEqual(self.hook(edit)[0], 2)
        self.assertEqual(self.hook(self.bash(".claude/hooks/task.py approve json-flag"))[0], 2)
        self.assertEqual(self.hook(self.bash(f"python3 hooks/task.py approve {self.PAGE}"))[0], 2)
        self.assertEqual(self.hook(self.bash("python3 -B hooks/task.py approve json-flag"))[0], 2)
        with open(self.path) as fh:
            self.assertEqual(draft, fh.read())

    def test_agent_cannot_remove_or_change_an_approval(self):
        text = self.approved()
        meta = text[text.index("<meta name=\"keel-approval\""):text.index("</head>")]
        for new in ("", meta.replace("hisham", "agent")):
            edit = {"tool_name": "Edit", "cwd": self.repo, "session_id": SESSION,
                    "tool_input": {"file_path": self.path, "old_string": meta, "new_string": new}}
            self.assertEqual(self.hook(edit)[0], 2, new)

    def test_approved_boundary_bounds_writes_to_its_changes_list(self):
        self.approved()
        self.assertEqual(self.hook(self.write("cli.py"))[0], 0)
        self.assertEqual(self.hook(self.write("tests/test_cli.py"))[0], 0)
        code, err = self.hook(self.write("src/other.py"))
        self.assertEqual(code, 2); self.assertIn("Changes list", err)
        code, err = self.hook(self.write("cli_legacy.py"))
        self.assertEqual(code, 2); self.assertIn("Must not change", err)

    def test_one_boundary_bounds_a_task_that_spans_two_repositories(self):
        """The second repository (Markdown docs, no page of its own) is a worktree of the same task;
        the page's lists name its paths as `<repository>:<path>`, by the main checkout's folder name."""
        from helpers import git
        other_primary = os.path.join(self.tmp, "tools")
        other = os.path.join(self.tmp, "tools-feat")
        subprocess.run(["git", "init", "-q", "-b", "main", other_primary], check=True)
        git(other_primary, "commit", "-q", "--allow-empty", "-m", "init")
        git(other_primary, "worktree", "add", "-q", other, "-b", "feat/json-flag")
        os.makedirs(os.path.join(other, "docs"))
        self.declare(size="large", task="json-flag", worktrees=[self.repo, other])
        # no page anywhere: code is blocked in both, and docs/ (the other repository's Markdown) is not
        code, err = self.hook(self.write(os.path.join(other, "hooks", "x.py"), cwd=other))
        self.assertEqual(code, 2); self.assertIn("no state page", err); self.assertIn("another worktree", err)
        self.assertEqual(self.hook(self.write(os.path.join(other, "docs", "guide.md"), cwd=other))[0], 0)
        # the page here lists nothing for the other repository: its code stays blocked, with the spelling
        self.approved()
        code, err = self.hook(self.write(os.path.join(other, "hooks", "x.py"), cwd=other))
        self.assertEqual(code, 2); self.assertIn("tools:<path>", err)
        # entries for the other repository apply only there; plain entries apply only here
        self.approved(changes=("cli.py", "tools:hooks/", "tools:README.md"), must_not=("tools:hooks/secret.py",))
        self.assertEqual(self.hook(self.write(os.path.join(other, "hooks", "x.py"), cwd=other))[0], 0)
        self.assertEqual(self.hook(self.write(os.path.join(other, "README.md"), cwd=other))[0], 0)
        code, err = self.hook(self.write(os.path.join(other, "hooks", "secret.py"), cwd=other))
        self.assertEqual(code, 2); self.assertIn("Must not change", err)
        code, err = self.hook(self.write(os.path.join(other, "cli.py"), cwd=other))
        self.assertEqual(code, 2); self.assertIn("Changes list", err)
        code, err = self.hook(self.write("hooks/x.py"))
        self.assertEqual(code, 2); self.assertIn("Changes list", err)
        self.assertEqual(self.hook(self.write("cli.py"))[0], 0)
        # a page in each repository for the same task is one too many to choose from
        with open(os.path.join(other, "docs", "261005-json-flag-state.html"), "w") as fh:
            fh.write(state_page(changes=("*",)))
        code, err = self.hook(self.write(os.path.join(other, "hooks", "x.py"), cwd=other))
        self.assertEqual(code, 2, err); self.assertIn("boundary", err)

    def test_editing_the_boundary_is_allowed_and_grants_nothing(self):
        text = self.approved()
        widened = text.replace("<li><code>tests/</code></li>", "<li><code>tests/</code></li><li><code>src/</code></li>")
        self.assertEqual(self.hook(self.write(self.PAGE, content=widened))[0], 0)  # drafting stays open
        self.put(widened)
        self.assertEqual(self.hook(self.write("src/b.py"))[0], 2)    # the approved copy still rules
        self.assertEqual(self.hook(self.write("cli.py"))[0], 0)
        import shutil
        shutil.rmtree(os.path.join(self.home, "approvals"))
        code, err = self.hook(self.write("cli.py"))                 # approved copy gone: no limits known
        self.assertEqual(code, 2); self.assertIn("changed since it was approved", err)

    def test_commit_outside_docs_waits_for_approval(self):
        self.assertEqual(self.hook(self.bash(f"git commit -m page -- {self.PAGE}"))[0], 0)
        self.assertEqual(self.hook(self.bash("git commit -m code -- cli.py"))[0], 2)
        self.approved()
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
        docs = os.path.join(self.repo, "docs"); os.makedirs(docs)
        page = os.path.join(docs, "261005-x-state.html")
        with open(page, "w") as fh:
            fh.write(state_page())
        from agentkeel_core import pages
        forged = pages.with_approval(os.path.basename(page), state_page(), "h", "2026-10-04")
        for allow in (("review",), ("implement",)):
            self.declare(allow=allow, write_roots=[docs])
            self.assertEqual(self.code(self.write(page, content=forged)), 2, allow)
        self.assertEqual(self.code(self.write(page, content=state_page(title="Edited"))), 0)
        approve_file(page, self.home)
        with open(page) as fh:
            approved = fh.read()
        self.assertEqual(self.code(self.write(page, content=approved.replace("on 2026-10-05", "on 2026-10-06"))), 2)

    def test_write_root_inside_a_large_task_keeps_the_blast_radius(self):
        self.declare(size="large", task="json-flag", write_roots=[os.path.join(self.repo, "src")])
        self.assertEqual(self.code(self.write("src/a.py")), 2)

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


class DocsGate(RepoCase):
    """In a repository with "docs": "html", main moves only to a commit whose docs check passes."""

    def setUp(self):
        super().setUp()
        self.declare(allow=("implement", "merge", "push"))
        os.makedirs(os.path.join(self.repo, "docs"))
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"docs": "html"}, fh)
        self.page = os.path.join(self.repo, "docs", "261005-x-state.html")
        self.put(state_page(boundary=False))
        self.main = self.commit("main")
        self.branch("feat/x")

    def put(self, text):
        with open(self.page, "w") as fh:
            fh.write(text)

    def commit(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", msg)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def test_a_working_section_keeps_main_still(self):
        self.put(state_page(boundary=False, working=True))
        bad = self.commit("wip")
        for cmd in (f"git push origin {bad}:main", f"git push . {bad}:main",
                    f"git -C {self.repo} fetch . {bad}:main", f"git update-ref refs/heads/main {bad}"):
            code, err = self.hook(self.bash(cmd))
            self.assertEqual(code, 2, cmd); self.assertIn("docs check fails", err); self.assertIn("Working section", err)
        for cmd in ("git push origin feat/x:main", "git push . feat/x:main"):  # a branch name can move
            code, err = self.hook(self.bash(cmd))
            self.assertEqual(code, 2, cmd); self.assertIn("full SHA", err)
        self.put(state_page(boundary=False))
        good = self.commit("finish")
        self.assertEqual(self.hook(self.bash(f"git push origin {good}:main"))[0], 0)
        self.assertEqual(self.hook(self.bash(f"git push . {good}:main"))[0], 0)
        self.assertEqual(self.hook(self.bash("git push origin feat/x"))[0], 0)  # a feature branch is not main

    def test_a_computed_source_or_destination_is_still_judged(self):
        # found live: `$(git rev-parse HEAD):main` was read as a push to a branch named `$`
        self.put(state_page(boundary=False, working=True))
        self.commit("wip")
        for cmd in ("git push origin $(git rev-parse HEAD):main", "git push origin `git rev-parse HEAD`:main",
                    "git push origin HEAD:$(echo main)", "B=main; git push origin HEAD:$B"):
            code, err = self.hook(self.bash(cmd))
            self.assertEqual(code, 2, cmd); self.assertNotIn("internal error", err)

    def test_local_fast_forward_on_main_is_checked(self):
        self.put(state_page())  # an unapproved boundary
        sha = self.commit("boundary")
        git(self.repo, "checkout", "-q", "main")
        code, err = self.hook(self.bash(f"git merge --ff-only {sha}"))
        self.assertEqual(code, 2); self.assertIn("not been approved", err)
        self.assertEqual(self.hook(self.bash(f"AGENTKEEL_ALLOW_DESTRUCTIVE=1 git reset --hard {sha}"))[0], 2)

    def test_dropping_an_approved_page_is_refused(self):
        git(self.repo, "checkout", "-q", "main")
        self.put(state_page()); approve_file(self.page, self.home)
        self.commit("approved"); git(self.repo, "checkout", "-q", "feat/x"); git(self.repo, "merge", "-q", "main")
        os.remove(self.page)
        gone = self.commit("drop")
        code, err = self.hook(self.bash(f"git push origin {gone}:main"))
        self.assertEqual(code, 2); self.assertIn("removes or renames", err)

    def test_disabling_in_the_candidate_does_not_escape(self):
        os.remove(os.path.join(self.repo, "agentkeel.json"))
        self.put(state_page(working=True))
        bad = self.commit("wip")
        self.assertEqual(self.hook(self.bash(f"git push origin {bad}:main"))[0], 2)

    def test_not_enabled_means_no_docs_gate(self):
        git(self.repo, "checkout", "-q", "main")
        os.remove(os.path.join(self.repo, "agentkeel.json"))
        self.commit("never opted in")
        git(self.repo, "checkout", "-q", "-B", "feat/y")
        self.put(state_page(working=True))
        bad = self.commit("wip")
        self.assertEqual(self.hook(self.bash(f"git push origin {bad}:main"))[0], 0)


class StageTwoBReviewFindings(RepoCase):
    """The independent Stage 2b review at 5d17846: one regression per confirmed finding."""

    def setUp(self):
        super().setUp()
        self.declare(allow=("implement", "merge", "push"))
        os.makedirs(os.path.join(self.repo, "docs"))
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"docs": "html"}, fh)
        self.page = os.path.join(self.repo, "docs", "261005-x-state.html")
        self.put(state_page(boundary=False))
        self.clean = self.commit("clean")
        self.branch("feat/x")

    def put(self, text, path=None):
        with open(path or self.page, "w") as fh:
            fh.write(text)

    def commit(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", msg)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def test_an_html_asset_never_opens_the_gate(self):
        # finding 1: an -asset.html crashed the check, and the guard allowed the move on its own error
        self.put(state_page(boundary=False, working=True))
        self.put("<!doctype html><title>preview</title><p>x</p>", os.path.join(self.repo, "docs", "261005-preview-asset.html"))
        bad = self.commit("wip plus an html asset")
        git(self.repo, "checkout", "-q", "main")
        for cmd in (f"git push origin {bad}:main", f"git merge --ff-only {bad}"):
            code, err = self.hook(self.bash(cmd))
            self.assertEqual(code, 2, cmd); self.assertNotIn("allowing", err); self.assertIn("Working section", err)

    def test_a_validator_failure_refuses_the_move(self):
        # finding 1: whatever the check raises, a protected move is refused, never allowed
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("ak_guard_2b", os.path.join(HOOKS, "task-guard.py"))
        guard = importlib.util.module_from_spec(spec); spec.loader.exec_module(guard)
        git(self.repo, "checkout", "-q", "main")
        env = {**os.environ, **self.env}
        with mock.patch.object(guard.pages, "check", side_effect=IndexError("no such group")):
            for cmd in (f"git push origin {self.clean}:main", f"git merge --ff-only {self.clean}"):
                self.assertEqual(guard.decide(self.bash(cmd), env), 2, cmd)

    def test_a_local_move_lands_the_commit_it_checked(self):
        # finding 2: the guard resolved `candidate`, then the line moved it before the merge ran
        self.put(state_page(boundary=False, working=True))
        bad = self.commit("wip")
        git(self.repo, "branch", "candidate", self.clean)
        git(self.repo, "checkout", "-q", "main")
        for cmd in (f"git update-ref refs/heads/candidate {bad} && git merge --ff-only candidate",
                    f"git branch -f candidate {bad}; git push . candidate:main",
                    f"git update-ref refs/heads/candidate {bad} && git merge --ff-only {self.clean}",
                    "git merge --ff-only candidate", "git push . candidate:main", "git fetch . candidate:main",
                    "git reset --hard candidate", "git update-ref refs/heads/main candidate"):
            code, err = self.hook(self.bash(cmd))
            self.assertEqual(code, 2, cmd); self.assertNotIn("allowing", err)
        for cmd in (f"git merge --ff-only {self.clean}", f"cd {self.repo} && git merge --ff-only {self.clean}",
                    f"git push . {self.clean}:main", f"git update-ref refs/heads/main {self.clean}"):
            code, err = self.hook(self.bash(cmd))
            self.assertEqual(code, 0, f"{cmd}: {err}")
        for cmd in (f"git merge --ff-only {bad}", f"git push . {bad}:main", f"git fetch . {bad}:main",
                    f"AGENTKEEL_ALLOW_DESTRUCTIVE=1 git reset --hard {bad}", f"git update-ref refs/heads/main {bad}"):
            code, err = self.hook(self.bash(cmd))
            self.assertEqual(code, 2, cmd); self.assertIn("Working section", err)

    def test_a_repo_without_html_docs_keeps_its_branch_merges(self):
        os.remove(os.path.join(self.repo, "agentkeel.json")); self.commit("off")
        git(self.repo, "checkout", "-q", "main"); git(self.repo, "merge", "-q", "feat/x")
        git(self.repo, "checkout", "-q", "feat/x")
        self.commit("more")
        git(self.repo, "checkout", "-q", "main")
        self.assertEqual(self.hook(self.bash("git merge --ff-only feat/x"))[0], 0)


class EmptyChangesList(RepoCase):
    """Finding 3 of the Stage 2b review: an approved boundary with no Changes list grants no source."""
    PAGE = "docs/261005-json-flag-state.html"

    def setUp(self):
        super().setUp()
        self.declare(size="large", task="json-flag"); self.branch("feat/json-flag")
        os.makedirs(os.path.join(self.repo, "docs"))
        self.path = os.path.join(self.repo, self.PAGE)

    def approved(self, text):
        with open(self.path, "w") as fh:
            fh.write(text)
        approve_file(self.path, self.home)

    def test_empty_or_missing_changes_grant_no_source(self):
        empty = state_page(changes=())
        missing = empty.replace("<ul data-keel-changes></ul>", "")
        prose = empty.replace("<ul data-keel-changes></ul>", "<ul data-keel-changes><li>src, mostly</li></ul>")
        for text in (empty, missing, prose):
            self.approved(text)
            code, err = self.hook(self.write("src/unrelated.py"))
            self.assertEqual(code, 2, text); self.assertIn("lists no paths", err)
            self.assertEqual(self.hook(self.bash("git commit -m code -- src/unrelated.py"))[0], 2)
            with open(self.path) as fh:
                self.assertEqual(self.hook(self.write(self.PAGE, content=fh.read() + " "))[0], 0)  # drafting stays open

    def test_listed_paths_pass_and_must_not_refuses(self):
        self.approved(state_page(changes=("src/allowed.py",), must_not=("src/allowed_not.py",)))
        self.assertEqual(self.hook(self.write("src/allowed.py"))[0], 0)
        self.assertEqual(self.hook(self.write("src/unrelated.py"))[0], 2)
        self.approved(state_page(changes=("*",), must_not=("src/auth/",)))  # broad access is explicit
        self.assertEqual(self.hook(self.write("src/unrelated.py"))[0], 0)
        self.assertEqual(self.hook(self.write("src/auth/key.py"))[0], 2)


class PushGate(RepoCase):
    """agentkeel.json require_check_before_push: an agent ships only a commit whose check passed."""

    def setUp(self):
        super().setUp()
        self.branch("feat/x")
        git(self.repo, "remote", "add", "origin", "https://github.com/someone/somerepo.git")
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"require_check_before_push": "agentkeel-required"}, fh)
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
        self.assertEqual(code, 2); self.assertIn("new commit", err)
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
