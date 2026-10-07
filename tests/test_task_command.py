"""task.py: the record is bound to one session, size and permissions are separate."""
import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import HOOKS, SESSION, RepoCase, git, run_hook

T = os.path.join(HOOKS, "task.py")


class TaskCommand(RepoCase):
    def task(self, *args, session=SESSION, cwd=None):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID", "CODEX_THREAD_ID")}
        env.update(self.env)
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        return subprocess.run([sys.executable, T, *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, env=env)

    def test_start_writes_a_session_bound_record(self):
        out = self.task("start", "json-flag", "--size", "medium", "--allow", "implement,merge")
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = self.record()
        self.assertEqual((rec["task"], rec["size"], rec["session_id"]), ("json-flag", "medium", SESSION))
        self.assertEqual(rec["permissions"], ["implement", "merge"])
        self.assertEqual(rec["worktrees"], [self.repo])

    def test_shared_checkout_is_not_recorded_as_the_tasks_worktree(self):
        out = self.task("start", "x", "--size", "small", "--allow", "implement", cwd=self.primary)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.record()["worktrees"], [])
        self.assertIn("shared checkout", out.stdout)
        self.assertTrue(os.path.isdir(self.record()["scratch"]))

    def test_write_root_inside_a_repository_refused(self):
        out = self.task("start", "review-report", "--size", "large", "--allow", "review",
                        "--write-root", os.path.join(self.primary, "src"), cwd=self.primary)
        self.assertEqual(out.returncode, 2); self.assertIn("inside the repository", out.stderr)
        report = os.path.join(self.tmp, "report"); os.makedirs(report)
        self.assertEqual(self.task("start", "r", "--size", "small", "--allow", "review",
                                   "--write-root", report).returncode, 0)

    def test_no_session_id_refused(self):
        out = self.task("start", "x", "--size", "small", "--allow", "implement", session=None)
        self.assertEqual(out.returncode, 2); self.assertIn("no session id", out.stderr)

    def test_bad_inputs_refused(self):
        self.assertNotEqual(self.task("start", "x", "--size", "huge", "--allow", "implement").returncode, 0)
        self.assertNotEqual(self.task("start", "Not Kebab", "--size", "small", "--allow", "implement").returncode, 0)
        out = self.task("start", "x", "--size", "small", "--allow", "deploy")
        self.assertEqual(out.returncode, 2); self.assertIn("unknown: deploy", out.stderr)
        self.assertNotEqual(self.task("start", "x", "--size", "small").returncode, 0)
        self.assertEqual(self.task("start", "x", "--size", "small", "--allow", "review",
                                   "--write-root", "/").returncode, 2)

    def test_changing_size_keeps_permissions_and_is_recorded(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        out = self.task("start", "x", "--size", "large", "--allow", "implement")
        self.assertIn("re-declared size small -> large", out.stderr)
        rec = self.record()
        self.assertEqual(rec["permissions"], ["implement"])
        self.assertEqual(rec["history"][0]["size"], "small")

    def test_widening_permissions_is_said_out_loud(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        out = self.task("start", "x", "--size", "small", "--allow", "implement,push")
        self.assertIn("permissions widened", out.stderr); self.assertIn("+push", out.stderr)

    def test_a_new_task_does_not_inherit_the_old_ones_resources(self):
        report = os.path.join(self.tmp, "r"); os.makedirs(report)
        self.task("start", "a", "--size", "small", "--allow", "review", "--write-root", report)
        self.task("start", "b", "--size", "small", "--allow", "implement")
        self.assertEqual(self.record()["write_roots"], [])

    def test_show_verify_end(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        self.assertEqual(self.task("show").returncode, 0)
        out = self.task("verify", "--", sys.executable, "-c", "raise SystemExit(3)")
        self.assertEqual(out.returncode, 3)
        self.assertEqual(self.record()["evidence"], [])  # the hooks record results, not the command
        self.assertEqual(self.task("end").returncode, 0)
        self.assertEqual(self.task("show").returncode, 1)

    def test_human_approve_writes_the_boundary_approval(self):
        from helpers import state_page
        from agentkeel_core import pages, record
        os.makedirs(os.path.join(self.repo, "docs"))
        p = os.path.join(self.repo, "docs", "261005-x-state.html")
        with open(p, "w") as fh:
            fh.write(state_page())
        out = self.task("approve", "x", session=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("D-NNN", out.stdout)
        with open(p) as fh:
            text = fh.read()
        self.assertEqual(pages.boundary_state(os.path.basename(p), text)[0], "approved")
        kept = record.approved_boundary_path(pages.approval(text)[0], {"AGENTKEEL_HOME": self.home})
        self.assertTrue(os.path.exists(kept))
        with open(p, "w") as fh:
            fh.write(state_page(boundary=False))
        self.assertEqual(self.task("approve", "x", session=None).returncode, 2)  # nothing to approve

    def test_new_page_needs_a_task_its_worktree_and_implement(self):
        self.assertEqual(self.task("new", "state", "import").returncode, 2)            # no task
        self.task("start", "import", "--size", "small", "--allow", "review", "--write-root", self.tmp + "/out")
        self.assertEqual(self.task("new", "state", "import").returncode, 2)            # no implement
        self.task("start", "import", "--size", "large", "--allow", "implement")
        self.assertEqual(self.task("new", "state", "import", cwd=self.primary).returncode, 2)  # shared checkout
        out = self.task("new", "state", "import")
        self.assertEqual(out.returncode, 0, out.stderr)
        from agentkeel_core import pages
        docs = os.path.join(self.repo, "docs")
        names = sorted(os.listdir(docs))
        self.assertEqual(len(names), 2); self.assertIn("keel.css", names)
        page = os.path.join(docs, next(n for n in names if n.endswith("-import-state.html")))
        with open(page) as fh:
            text = fh.read()
        self.assertEqual(pages.boundary_state(os.path.basename(page), text)[0], "unapproved")  # large: boundary
        self.assertTrue(pages.sections(text, "working"))
        self.assertEqual(self.task("new", "state", "import").returncode, 2)            # one per feature
        self.assertEqual(self.task("new", "project").returncode, 0)
        self.assertEqual(self.task("new", "project").returncode, 2)                    # one canon
        self.assertEqual(self.task("new", "audit", "import", "--qualifier", "memory").returncode, 0)

    def test_finish_context_check_and_index(self):
        self.task("start", "import", "--size", "medium", "--allow", "implement")
        self.task("new", "state", "import")
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            fh.write('{"docs": "html"}')
        docs = os.path.join(self.repo, "docs")
        page = os.path.join(docs, next(n for n in os.listdir(docs) if n.endswith("-state.html")))
        out = self.task("check")
        self.assertEqual(out.returncode, 1); self.assertIn("Working section", out.stdout)
        ctx = self.task("context", page)
        self.assertEqual(ctx.returncode, 0); self.assertIn("[working section begins]", ctx.stdout)
        self.assertIn("## State now", ctx.stdout)
        self.assertEqual(self.task("finish", page).returncode, 0)
        out = self.task("check")
        self.assertEqual(out.returncode, 0, out.stdout)
        out = self.task("index")
        self.assertEqual(out.returncode, 0); self.assertIn("add docs/index.html to .gitignore", out.stdout)
        with open(os.path.join(docs, "index.html")) as fh:
            self.assertIn(os.path.basename(page), fh.read())
        self.assertEqual(self.task("check").returncode, 0)  # an untracked index is not a problem locally

    def test_a_family_keeps_its_first_date_and_one_index_group(self):
        # finding 4 of the Stage 2b review: a later audit took today's date and its own index group
        self.task("start", "history-import", "--size", "medium", "--allow", "implement")
        docs = os.path.join(self.repo, "docs")
        os.makedirs(docs)
        with open(os.path.join(docs, "260901-history-import-state.html"), "w") as fh:
            fh.write("<!doctype html><html><head><title>History import</title></head><body></body></html>")
        for args in (("audit", "history-import", "--qualifier", "memory"),
                     ("mockup", "history-import", "--qualifier", "empty-state"), ("new-family",)):
            out = self.task("new", *args) if args[0] != "new-family" else self.task("new", "reference", "deploy")
            self.assertEqual(out.returncode, 0, out.stderr)
        names = sorted(n for n in os.listdir(docs) if n.endswith(".html"))
        self.assertIn("260901-history-import-memory-audit.html", names)
        self.assertIn("260901-history-import-empty-state-mockup.html", names)
        import datetime
        today = datetime.date.today()
        self.assertIn(today.strftime("%y%m%d") + "-deploy-reference.html", names)  # a new family: today
        with open(os.path.join(docs, "260901-history-import-memory-audit.html")) as fh:
            self.assertIn(today.isoformat(), fh.read())                               # the real date, inside
        self.assertEqual(self.task("index").returncode, 0)
        with open(os.path.join(docs, "index.html")) as fh:
            index = fh.read()
        self.assertEqual(index.count("<h2>"), 2, index)                               # history-import, deploy
        self.assertNotIn("<h2>history-import-memory</h2>", index)

    def test_the_working_folder_check_skips_ignored_files(self):
        # found after the Stage 2b merge: Finder's docs/.DS_Store failed the local check
        self.task("start", "import", "--size", "medium", "--allow", "implement")
        self.task("new", "state", "import")
        docs = os.path.join(self.repo, "docs")
        self.task("finish", os.path.join(docs, next(n for n in os.listdir(docs) if n.endswith("-state.html"))))
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            fh.write('{"docs": "html"}')
        with open(os.path.join(docs, ".DS_Store"), "w") as fh:
            fh.write("x")
        out = self.task("check")
        self.assertEqual(out.returncode, 1); self.assertIn(".DS_Store", out.stdout)  # not ignored: a stray file
        with open(os.path.join(self.repo, ".gitignore"), "w") as fh:
            fh.write(".DS_Store\n")
        out = self.task("check")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_record_drives_the_guard(self):
        self.branch("feat/x")
        payload = {"tool_name": "Write", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {"file_path": os.path.join(self.repo, "a.py"), "content": ""}}
        self.assertEqual(run_hook("task-guard.py", payload, env=self.env)[0], 2)
        self.task("start", "x", "--size", "small", "--allow", "implement")
        self.assertEqual(run_hook("task-guard.py", payload, env=self.env)[0], 0)


class Status(RepoCase):
    """task.py status: derived facts, read-only, with or without a session."""
    task = TaskCommand.task

    def snapshot(self):
        """What status must not change: every worktree's porcelain status, refs and the records."""
        out = []
        for d in (self.primary, self.repo):
            out.append(subprocess.run(["git", "-C", d, "status", "--porcelain", "--untracked-files=all"],
                                      capture_output=True, text=True).stdout)
        out.append(subprocess.run(["git", "-C", self.primary, "for-each-ref"], capture_output=True, text=True).stdout)
        for folder, _, files in sorted(os.walk(self.home)):
            out += sorted(os.path.join(folder, f) for f in files)
        return out

    def test_with_no_session(self):
        out = self.task("status", session=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("this session's task: none", out.stdout)
        self.assertIn(f"  {self.primary}  branch base  no task record  (shared checkout)", out.stdout)
        self.assertIn(f"  {self.repo}  branch main  no task record", out.stdout)

    def test_a_session_with_a_dirty_worktree(self):
        self.branch("feat/x")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "work")
        with open(os.path.join(self.repo, "new.py"), "w") as fh:
            fh.write("x = 1\n")
        self.declare(task="x")
        before = self.snapshot()
        out = self.task("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("this session's task: x (small; implement)", out.stdout)
        self.assertRegex(out.stdout, rf"{self.repo}  branch feat/x  tip [0-9a-f]{{12}}  1 commit\(s\) not in main, "
                                     r"not merged, 1 changed or untracked file\(s\)")
        self.assertEqual(self.snapshot(), before)               # it changes nothing
        facts = json.loads(self.task("status", "--json").stdout)["worktrees"][0]
        self.assertEqual((facts["ahead"], facts["merged"], facts["changed"]), (1, False, 1))
        os.remove(os.path.join(self.repo, "new.py"))
        git(self.primary, "branch", "-q", "-f", "main", "feat/x")   # main catches up: merged, clean
        facts = json.loads(self.task("status", "--json").stdout)["worktrees"][0]
        self.assertEqual((facts["ahead"], facts["merged"], facts["changed"]), (0, True, 0))

    def test_an_unreadable_worktree_is_never_called_clean(self):
        self.declare(task="x")
        with open(os.path.join(self.repo, ".git")) as fh:
            gitfile = fh.read()
        with open(os.path.join(self.repo, ".git"), "w") as fh:
            fh.write("not a gitdir line\n")
        try:
            out = self.task("status", cwd=self.primary)
        finally:
            with open(os.path.join(self.repo, ".git"), "w") as fh:
                fh.write(gitfile)
        self.assertIn("cannot be read", out.stdout)
        self.assertIn("not known to be clean", out.stdout)

    def test_a_foreign_worktree_names_its_task(self):
        other = os.path.join(self.tmp, "other")
        git(self.primary, "worktree", "add", "-q", other, "-b", "feat/other")
        self.declare(task="mine")
        self.declare(task="theirs", session="session-b", worktrees=[other])
        out = self.task("status")
        self.assertIn(f"  {other}  branch feat/other  foreign: task theirs", out.stdout)
        self.assertNotIn("orphan", out.stdout)
        self.assertNotIn(f"  {self.repo}  branch main  ", out.stdout.split("other worktrees")[1])  # its own, above

    def test_an_opened_clone_and_whether_it_is_ready_to_release(self):
        self.env["AGENTKEEL_SCRATCH"] = os.path.join(self.tmp, "scratch")
        out = self.task("open", "t", "--host", "codex", "--size", "small", "--allow", "implement", "--print",
                        session=None, cwd=self.primary)
        self.assertEqual(out.returncode, 0, out.stderr)
        clone = os.path.join(self.tmp, "primary-t")
        out = self.task("status", session=None)
        self.assertIn(f"  t  {clone}  branch feat/t  ready to release", out.stdout)
        with open(os.path.join(clone, "loose.txt"), "w") as fh:
            fh.write("x")
        before = self.snapshot()
        out = self.task("status", session=None)
        self.assertIn(f"  t  {clone}  branch feat/t  not ready to release:", out.stdout)
        self.assertIn("    - the clone has 1 changed or untracked file(s)", out.stdout)
        self.assertTrue(os.path.exists(os.path.join(clone, "loose.txt")))
        self.assertEqual(self.snapshot(), before)

    def test_state_pages_with_state_now_and_claims(self):
        sha = subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        os.makedirs(os.path.join(self.repo, "docs"))
        with open(os.path.join(self.repo, "docs", "261005-import-state.html"), "w") as fh:
            fh.write("<title>Import</title><section class='state-now' id='state-now'><dl>"
                     f"<dt>Implementation</dt><dd>merged {sha} into main; merged feat/x into main</dd>"
                     "<dt>External checks</dt><dd>App Store review pending</dd></dl></section>")
        out = self.task("status", session=None)
        self.assertIn("  docs/261005-import-state.html", out.stdout)
        self.assertIn("    External checks: App Store review pending", out.stdout)
        self.assertIn(f"    claim 'merged {sha} into main': proven", out.stdout)
        self.assertIn("    claim 'merged feat/x into main': unknown", out.stdout)


class Init(RepoCase):
    task = TaskCommand.task
    """task.py init: opt in without overwriting policy; installation, opt-in and trust apart."""

    def setUp(self):
        super().setUp()
        self.claude_dir = os.path.join(self.tmp, "claude-config")
        self.codex_dir = os.path.join(self.tmp, "codex-home")
        os.makedirs(os.path.join(self.claude_dir, "plugins")); os.makedirs(self.codex_dir)
        self.env.update({"CLAUDE_CONFIG_DIR": self.claude_dir, "CODEX_HOME": self.codex_dir})
        self.policy = os.path.join(self.primary, "agentkeel.json")
        self.with_bin()  # no real claude or codex: every host fact in these tests is staged

    def init(self):
        return self.task("init", cwd=self.primary)

    def commits(self):
        return subprocess.run(["git", "-C", self.primary, "rev-list", "--all", "--count"],
                              capture_output=True, text=True).stdout.strip()

    def test_first_init_creates_the_file_registers_and_does_not_commit(self):
        self.with_bin()
        self.fake_cli("claude", "[]")
        self.fake_cli("codex", "No plugins found in marketplace `agentkeel`.\n")
        before = self.commits()
        out = self.init()
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(self.policy) as fh:
            self.assertEqual(json.load(fh), {})
        self.assertEqual(self.commits(), before)
        self.assertIn("??", subprocess.run(["git", "-C", self.primary, "status", "--porcelain", "agentkeel.json"],
                                           capture_output=True, text=True).stdout)
        with open(os.path.join(self.home, "opted-in.json")) as fh:
            self.assertEqual(len(json.load(fh)), 1)
        for text in ("created agentkeel.json", "protected branches: main, master", '"docs": "html"',
                     "require_check_before_push", "plugin not installed: claude plugin install",
                     "codex plugin add agentkeel@agentkeel", "git add agentkeel.json"):
            self.assertIn(text, out.stdout)

    def test_the_opt_in_reaches_a_worktree_without_a_commit(self):
        from agentkeel_core import record
        payload = {"cwd": self.repo, "tool_name": "Write", "tool_input": {"file_path": os.path.join(self.repo, "a.txt")}}
        self.assertTrue(record.plugin_inactive(["--plugin"], payload, {"AGENTKEEL_HOME": self.home}))
        self.assertEqual(self.init().returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "agentkeel.json")))
        self.assertFalse(record.plugin_inactive(["--plugin"], payload, {"AGENTKEEL_HOME": self.home}))

    def test_repeating_init_keeps_an_existing_policy_byte_for_byte(self):
        text = '{"protected_branches": ["release"], "docs": "html"}\n'
        with open(self.policy, "w") as fh:
            fh.write(text)
        for _ in range(2):
            out = self.init()
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("kept the existing agentkeel.json (keys: docs, protected_branches)", out.stdout)
        with open(self.policy) as fh:
            self.assertEqual(fh.read(), text)
        self.assertIn("protected branches: release", out.stdout)
        self.assertNotIn('HTML work records ("docs"', out.stdout)

    def test_a_malformed_policy_is_refused_and_left_alone(self):
        with open(self.policy, "w") as fh:
            fh.write("{not json")
        out = self.init()
        self.assertEqual(out.returncode, 2); self.assertIn("left as it is", out.stderr)
        with open(self.policy) as fh:
            self.assertEqual(fh.read(), "{not json")

    def fake_cli(self, name, stdout, code=0):
        """A host command on PATH that prints canned output."""
        os.makedirs(self.bin, exist_ok=True)
        path = os.path.join(self.bin, name)
        with open(os.path.join(self.bin, name + ".out"), "w") as fh:
            fh.write(stdout)
        with open(path, "w") as fh:
            fh.write(f'#!/bin/sh\n/bin/cat "{path}.out"\nexit {code}\n')
        os.chmod(path, 0o755)

    def with_bin(self):
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin, exist_ok=True)
        self.env["PATH"] = os.pathsep.join([self.bin, os.path.dirname(shutil.which("git")), "/usr/bin", "/bin"])

    def test_no_codex_configuration_means_no_trust_not_an_old_python(self):
        """Regression (CI at 9c0b309): a missing config.toml was blamed on the Python version."""
        self.fake_cli("codex", "PLUGIN               STATUS              VERSION  SOURCE\n"
                               "agentkeel@agentkeel  installed, enabled  0.4.0    ./\n")
        out = self.init().stdout
        self.assertIn("0 of 7 hooks trusted", out)
        self.assertNotIn("Python 3.11", out)

    def test_a_policy_created_after_an_absence_check_is_kept_byte_for_byte(self):
        """Regression: init checked exists() and then opened with "w", so a policy written in
        between was replaced with {}. The exclusive create cannot replace anything."""
        text = '{"docs": "html", "require_check_before_push": "agentkeel-required"}\n'
        with open(self.policy, "w") as fh:
            fh.write(text)
        probe = ("import os, runpy, sys\n"
                 "real = os.path.exists\n"
                 "os.path.exists = lambda p: False if str(p).endswith('agentkeel.json') else real(p)\n"
                 f"sys.argv = [{T!r}, 'init']\n"
                 f"runpy.run_path({T!r}, run_name='__main__')\n")
        env = {**os.environ, **self.env}
        out = subprocess.run([sys.executable, "-c", probe], cwd=self.primary, capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(self.policy) as fh:
            self.assertEqual(fh.read(), text)
        self.assertIn("kept the existing agentkeel.json", out.stdout)

    def test_a_dangling_symlink_is_left_and_its_target_never_created(self):
        target = os.path.join(self.tmp, "outside", "policy.json")
        os.symlink(target, self.policy)
        out = self.init()
        self.assertEqual(out.returncode, 2); self.assertIn("symbolic link to a missing file", out.stderr)
        self.assertTrue(os.path.islink(self.policy)); self.assertEqual(os.readlink(self.policy), target)
        self.assertFalse(os.path.exists(os.path.dirname(target)))

    def test_a_symlink_to_a_real_policy_is_read_and_never_written(self):
        target = os.path.join(self.tmp, "policy.json")
        with open(target, "w") as fh:
            fh.write('{"protected_branches": ["release"]}')
        os.symlink(target, self.policy)
        out = self.init()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("symbolic link, which init reads and never writes through", out.stdout)
        with open(target) as fh:
            self.assertEqual(fh.read(), '{"protected_branches": ["release"]}')

    def test_hosts_report_their_own_install_enable_and_version(self):
        self.with_bin()
        install = os.path.join(self.tmp, "cache", "0.4.0"); os.makedirs(install)
        self.fake_cli("claude", json.dumps([{"id": "agentkeel@agentkeel", "version": "0.4.0", "scope": "user",
                                             "enabled": False, "installPath": install}]))
        self.fake_cli("codex", "PLUGIN               STATUS               VERSION  SOURCE\n"
                               "agentkeel@agentkeel  installed, disabled  0.4.0    ./\n")
        out = self.init()
        self.assertIn("plugin 0.4.0 installed (user scope), not enabled: claude plugin enable", out.stdout)
        self.assertIn("plugin 0.4.0 installed, disabled", out.stdout)

    def test_a_missing_or_silent_host_is_unknown_not_absent(self):
        self.with_bin()
        self.env["PATH"] = self.bin + os.pathsep + os.path.dirname(shutil.which("git"))
        out = self.init()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("claude    unknown: the claude command was not found", out.stdout)
        self.assertIn("install state unknown: the codex command was not found", out.stdout)
        self.fake_cli("codex", "unexpected output\n")
        self.assertIn("install state unknown: codex plugin list did not show", self.init().stdout)
        self.fake_cli("codex", "No plugins found in marketplace `agentkeel`.\n")
        self.assertIn("codex     plugin not installed: codex plugin add", self.init().stdout)


    def claude_says(self, payload):
        self.fake_cli("claude", payload if isinstance(payload, str) else json.dumps(payload))
        line = [ln for ln in self.init().stdout.splitlines() if ln.startswith("  claude")]
        return line[0] if line else ""

    def test_an_unexpected_claude_answer_is_unknown_never_absent(self):
        """Regression: {} or {"plugins": []} read as "not installed", and null raised TypeError."""
        self.with_bin()
        for payload in ({}, {"plugins": []}, None, "not json", [1, 2], [{"version": "0.4.0"}]):
            line = self.claude_says(payload)
            self.assertIn("install state unknown: claude plugin list --json gave an unexpected answer", line,
                          repr(payload))
        self.assertIn("plugin not installed", self.claude_says([]))
        self.assertIn("plugin not installed", self.claude_says([{"id": "other@other", "enabled": True}]))

    def test_missing_claude_state_fields_stay_unknown(self):
        self.with_bin()
        install = os.path.join(self.tmp, "cache", "0.4.0"); os.makedirs(install)
        base = {"id": "agentkeel@agentkeel", "version": "0.4.0", "scope": "user", "installPath": install}
        self.assertIn("installed (user scope), enabled state unknown", self.claude_says([base]))
        self.assertIn("installed (user scope), enabled state unknown", self.claude_says([{**base, "enabled": "yes"}]))
        self.assertIn("install state unknown", self.claude_says([{**base, "enabled": True, "installPath": None}]))
        self.assertIn("installed (user scope), enabled", self.claude_says([{**base, "enabled": True}]))
        self.assertIn("not enabled: claude plugin enable", self.claude_says([{**base, "enabled": False}]))

    def test_an_unfamiliar_codex_status_is_unknown(self):
        self.with_bin()
        self.fake_cli("codex", "PLUGIN               STATUS                  VERSION  SOURCE\n"
                               "agentkeel@agentkeel  installed, quarantined  0.4.0    ./\n")
        self.assertIn("install state unknown: codex plugin list did not show", self.init().stdout)

    def test_init_outside_a_repository_is_refused(self):
        out = self.task("init", cwd=self.tmp)
        self.assertEqual(out.returncode, 2); self.assertIn("not inside a git repository", out.stderr)


class CodexTrust(unittest.TestCase):
    """Codex trust is read from config.toml with a real TOML parser, never a pattern."""

    CONFIG = (
        '[plugins."agentkeel@agentkeel"] # installed by hand\n'
        'enabled = true\n\n'
        '[hooks.state]\n\n'
        '[hooks.state."agentkeel@agentkeel:session_start:0:0"]\n'
        'note = ["a", "[not a table]"]\n'
        'trusted_hash = "sha256:a"\n\n'
        '[hooks.state."agentkeel@agentkeel:pre_tool_use:0:0"]   # a comment\n'
        'trusted_hash = "sha256:b"\n\n'
        '[hooks.state."agentkeel@agentkeel:pre_tool_use:1:0"]\n'
        'enabled = false\n\n'
        '[hooks.state."other@other:pre_tool_use:0:0"]\n'
        'trusted_hash = "sha256:c"\n')

    def trust(self, text, environ=None):
        from agentkeel_core import hostcheck
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            with open(os.path.join(home, "config.toml"), "w") as fh:
                fh.write(text)
            env = {"CODEX_HOME": home, "PATH": home}
            env.update(environ or {})
            return hostcheck.codex(home, env)["trusted"]

    def test_comments_arrays_and_order_do_not_change_the_count(self):
        from agentkeel_core import hostcheck
        if hostcheck._tomllib() is None:
            self.skipTest("no TOML parser: tomllib (Python 3.11+) or tomli")
        self.assertEqual(self.trust(self.CONFIG), 2)
        reordered = self.CONFIG.replace('note = ["a", "[not a table]"]\ntrusted_hash = "sha256:a"',
                                        'trusted_hash = "sha256:a"\nnote = ["a", "[not a table]"]')
        self.assertEqual(self.trust(reordered), 2)

    def test_without_a_toml_parser_trust_is_unknown(self):
        names = ("tomllib", "tomli", "pip._vendor.tomli")
        saved = {n: sys.modules.get(n) for n in names}
        for n in names:
            sys.modules[n] = None  # an import of a None entry raises ImportError
        try:
            self.assertIsNone(self.trust(self.CONFIG))
        finally:
            for n in names:
                if saved[n] is None:
                    sys.modules.pop(n, None)
                else:
                    sys.modules[n] = saved[n]


class SessionBanner(RepoCase):
    task = TaskCommand.task
    """3.3: the session-start message answers "worktree or main?" before anyone asks."""

    def banner(self, cwd, session=SESSION):
        out = subprocess.run([sys.executable, os.path.join(HOOKS, "session-start.py")], text=True, capture_output=True,
                             input=json.dumps({"session_id": session, "cwd": cwd}), env={**os.environ, **self.env})
        return out.stdout

    def test_the_shared_checkout_and_its_protected_branch_are_named(self):
        git(self.primary, "checkout", "-q", "-b", "master")
        out = self.banner(self.primary)
        self.assertIn(f"Where you are: {self.primary} (the repository's shared checkout), on branch master (protected).", out)
        self.assertIn("Your task: none declared yet.", out)
        self.assertIn(f"  {self.repo}  branch main  no task record", out)

    def test_a_declared_task_and_another_sessions_worktree_are_named(self):
        other = os.path.join(self.tmp, "other")
        git(self.primary, "worktree", "add", "-q", other, "-b", "feat/other")
        self.assertEqual(self.task("start", "other-task", "--size", "small", "--allow", "implement",
                                   session="session-b", cwd=other).returncode, 0)
        self.branch("feat/mine")
        self.assertEqual(self.task("start", "mine", "--size", "small", "--allow", "implement,merge").returncode, 0)
        out = self.banner(self.repo)
        self.assertIn(f"Where you are: {self.repo} (a linked worktree), on branch feat/mine.", out)
        self.assertIn("Your task: mine (small; implement, merge).", out)
        self.assertIn(f"  {other}  branch feat/other  task other-task", out)
        self.assertNotIn(f"  {self.repo}  ", out)


class SharedInstructions(RepoCase):
    """init keeps one agentkeel block in AGENTS.md for both hosts; nothing outside it changes."""
    task = TaskCommand.task

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin"); os.makedirs(self.bin)
        self.env.update({"CODEX_HOME": os.path.join(self.tmp, "codex"),
                         "PATH": os.pathsep.join([self.bin, os.path.dirname(shutil.which("git")), "/usr/bin", "/bin"])})
        self.agents = os.path.join(self.primary, "AGENTS.md")

    def init(self):
        out = self.task("init", cwd=self.primary)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def read(self):
        with open(self.agents, encoding="utf-8", newline="") as fh:
            return fh.read()

    def write(self, text):
        with open(self.agents, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)

    def test_first_init_creates_the_block_and_never_a_claude_file(self):
        out = self.init()
        self.assertIn("created AGENTS.md with the agentkeel block", out)
        text = self.read()
        self.assertTrue(text.startswith("<!-- agentkeel:start -->\n<!-- agentkeel:sha256="))
        self.assertIn("task.py start <task-id>", text)
        self.assertNotIn(".claude/hooks/task.py start", text)
        for name in ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md")):
            self.assertFalse(os.path.exists(os.path.join(self.primary, name)))
        self.assertIn("git add agentkeel.json AGENTS.md", out)

    def test_repeating_init_changes_nothing(self):
        self.init()
        before = self.read()
        out = self.init()
        self.assertEqual(self.read(), before)
        self.assertIn("AGENTS.md has this version's agentkeel block", out)
        self.assertNotIn("git add", out)

    def test_the_users_rules_stay_byte_for_byte(self):
        mine = "# My repo\r\n\nRules the team wrote.\n"
        self.write(mine)
        self.assertIn("added the agentkeel block to AGENTS.md", self.init())
        self.assertTrue(self.read().startswith(mine))

    def test_an_older_block_is_updated_and_its_surroundings_kept(self):
        from agentkeel_core import instructions
        before, after = "# Top\n\n", "\n## After the block\nmore rules\n"
        self.write(before + instructions.block_for("old text\n") + after)
        self.assertIn("updated the agentkeel block", self.init())
        text = self.read()
        self.assertTrue(text.startswith(before)); self.assertTrue(text.endswith(after))
        self.assertNotIn("old text", text)

    def test_an_edited_or_install_py_block_is_left_and_reported(self):
        from agentkeel_core import instructions
        edited = "# Top\n" + instructions.block_for("shipped text\n").replace("shipped text", "my own text")
        legacy = "# Top\n<!-- agentkeel:start -->\nwritten by install.py\n<!-- agentkeel:end -->\n"
        for text in (edited, legacy):
            self.write(text)
            self.assertIn("written by install.py or edited by hand, so init left", self.init())
            self.assertEqual(self.read(), text)

    def test_broken_markers_and_a_symlink_are_left(self):
        broken = "<!-- agentkeel:start -->\nno end marker\n"
        self.write(broken)
        self.assertIn("one agentkeel marker without the other", self.init())
        self.assertEqual(self.read(), broken)
        os.remove(self.agents)
        target = os.path.join(self.tmp, "elsewhere.md")
        with open(target, "w") as fh:
            fh.write("shared rules\n")
        os.symlink(target, self.agents)
        self.assertIn("symbolic link; init does not write through it", self.init())
        with open(target) as fh:
            self.assertEqual(fh.read(), "shared rules\n")

    def test_a_claude_file_is_reported_and_left(self):
        with open(os.path.join(self.primary, "CLAUDE.md"), "w") as fh:
            fh.write("old rules\n")
        out = self.init()
        self.assertIn("CLAUDE.md exists: Claude Code loads it instead of AGENTS.md", out)
        with open(os.path.join(self.primary, "CLAUDE.md")) as fh:
            self.assertEqual(fh.read(), "old rules\n")


if __name__ == "__main__":
    unittest.main()
