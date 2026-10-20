"""task.py: the record is bound to one session, size and permissions are separate."""
import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import HOOKS, SESSION, RepoCase, git

T = os.path.join(HOOKS, "task.py")


class TaskCommand(RepoCase):
    """New start/handoff/finish behavior is covered in test_task_lifecycle.py."""

    def task(self, *args, session=SESSION, cwd=None):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID", "CODEX_THREAD_ID")}
        env.update(self.env)
        if args[:1] == ("start",) and "--deliverable" not in args:
            args = (*args, "--deliverable", "doc/" + args[1] + ".html")
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        return subprocess.run([sys.executable, T, *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, env=env)


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
        self.assertIn("this session's task: x (small, feature; implement)", out.stdout)
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



class Init(RepoCase):
    task = TaskCommand.task
    """task.py init: private activation and policy; installation, opt-in and trust apart."""

    def setUp(self):
        super().setUp()
        self.claude_dir = os.path.join(self.tmp, "claude-config")
        self.codex_dir = os.path.join(self.tmp, "codex-home")
        os.makedirs(os.path.join(self.claude_dir, "plugins")); os.makedirs(self.codex_dir)
        self.env.update({"CLAUDE_CONFIG_DIR": self.claude_dir, "CODEX_HOME": self.codex_dir})
        from agentkeel_core import record
        self.policy = record.policy_path(self.primary)
        self.with_bin()  # no real claude or codex: every host fact in these tests is staged

    def init(self, *extra):
        return self.task("init", *extra, cwd=self.primary)

    def commits(self):
        return subprocess.run(["git", "-C", self.primary, "rev-list", "--all", "--count"],
                              capture_output=True, text=True).stdout.strip()

    def test_first_init_creates_only_private_state(self):
        self.with_bin()
        self.fake_cli("claude", "[]")
        self.fake_cli("codex", "No plugins found in marketplace `agentkeel`.\n")
        before = (self.commits(), subprocess.run(
            ["git", "-C", self.primary, "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True).stdout)
        out = self.init()
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(self.policy) as fh:
            self.assertEqual(json.load(fh), {})
        after = (self.commits(), subprocess.run(
            ["git", "-C", self.primary, "status", "--porcelain", "--untracked-files=all"],
            capture_output=True, text=True).stdout)
        self.assertEqual(after, before)
        with open(os.path.join(self.home, "opted-in.json")) as fh:
            self.assertEqual(len(json.load(fh)), 1)
        for text in ("created privately", "protected branches: main, master",
                     "require_check_before_push", "plugin not installed: claude plugin install",
                     "codex plugin add agentkeel@agentkeel"):
            self.assertIn(text, out.stdout)
        self.assertNotIn("git add", out.stdout)

    def test_the_opt_in_reaches_a_worktree_without_a_commit(self):
        from agentkeel_core import record
        payload = {"cwd": self.repo, "tool_name": "Write", "tool_input": {"file_path": os.path.join(self.repo, "a.txt")}}
        self.assertTrue(record.plugin_inactive(["--plugin"], payload, {"AGENTKEEL_HOME": self.home}))
        self.assertEqual(self.init().returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "agentkeel.json")))
        self.assertFalse(record.plugin_inactive(["--plugin"], payload, {"AGENTKEEL_HOME": self.home}))

    def test_repeating_init_keeps_an_existing_policy_byte_for_byte(self):
        self.set_policy({"protected_branches": ["release"], "docs": "html"})
        with open(self.policy, "rb") as fh:
            before = fh.read()
        for _ in range(2):
            out = self.init()
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("kept privately", out.stdout)
        with open(self.policy, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertIn("protected branches: release", out.stdout)

    def test_policy_import_requires_a_json_object_and_preserves_existing_policy(self):
        self.set_policy({"protected_branches": ["release"]})
        source = os.path.join(self.tmp, "policy.json")
        with open(source, "w") as fh:
            fh.write("[1, 2]")
        out = self.init("--policy", source)
        self.assertEqual(out.returncode, 2); self.assertIn("not a JSON object", out.stderr)
        with open(self.policy) as fh:
            self.assertEqual(json.load(fh), {"protected_branches": ["release"]})

    def test_policy_import_and_deactivate_leave_repository_files_unchanged(self):
        source = os.path.join(self.tmp, "policy.json")
        with open(source, "w") as fh:
            json.dump({"protected_branches": ["release"]}, fh)
        before = subprocess.run(["git", "-C", self.primary, "status", "--porcelain", "--untracked-files=all"],
                                capture_output=True, text=True).stdout
        out = self.init("--policy", source)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("created privately", out.stdout)
        with open(self.policy) as fh:
            self.assertEqual(json.load(fh), {"protected_branches": ["release"]})
        out = self.task("deactivate", cwd=self.primary)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("repository files unchanged", out.stdout)
        self.assertFalse(os.path.exists(self.policy))
        with open(os.path.join(self.home, "opted-in.json")) as fh:
            self.assertEqual(json.load(fh), {})
        after = subprocess.run(["git", "-C", self.primary, "status", "--porcelain", "--untracked-files=all"],
                               capture_output=True, text=True).stdout
        self.assertEqual(after, before)

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
        self.assertIn("0 of 4 hooks trusted", out)
        self.assertNotIn("Python 3.11", out)

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
                                   "--base", "main",
                                   session="session-b", cwd=other).returncode, 0)
        other_record = json.load(open(os.path.join(self.home, "tasks", "session-b.json")))
        other_owned = other_record["worktrees"][0]
        self.assertEqual(self.task("start", "mine", "--size", "small", "--allow", "implement,merge",
                                   "--branch", "feat/mine", "--base", "main").returncode, 0)
        mine_record = self.record()
        mine_owned = mine_record["worktrees"][0]
        out = self.banner(mine_owned)
        self.assertIn(f"Where you are: {mine_owned} (a linked worktree), on branch feat/mine.", out)
        self.assertIn("Your task: mine (small; implement, merge).", out)
        self.assertIn(f"  {other_owned}  branch feat/other-task  task other-task", out)


if __name__ == "__main__":
    unittest.main()
