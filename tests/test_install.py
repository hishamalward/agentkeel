"""install.py: preview by default, merges without overwriting, never creates CLAUDE.md, reverses."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT

INSTALL = os.path.join(ROOT, "install.py")
OTHER_HOOK = {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-own-hook.sh"}]}


class Install(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(os.path.join(self._tmp.name, "repo"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        os.makedirs(os.path.join(self.repo, ".claude"))
        self.settings = {"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"PreToolUse": [OTHER_HOOK]}}
        self.put(".claude/settings.json", json.dumps(self.settings))
        self.put("AGENTS.md", "# Rules\n\nBe kind.\n")

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, text):
        with open(os.path.join(self.repo, rel), "w") as fh:
            fh.write(text)

    def get(self, rel):
        with open(os.path.join(self.repo, rel)) as fh:
            return fh.read()

    def run_install(self, *args):
        env = {**os.environ, "AGENTKEEL_HOME": os.path.join(self._tmp.name, "agentkeel-home")}
        return subprocess.run([sys.executable, INSTALL, self.repo, *args], capture_output=True, text=True, env=env)

    def commands(self):
        hooks = json.loads(self.get(".claude/settings.json")).get("hooks", {})
        return [h["command"] for groups in hooks.values() for g in groups for h in g["hooks"]]

    def test_preview_changes_nothing(self):
        before = (self.get(".claude/settings.json"), self.get("AGENTS.md"))
        out = self.run_install()
        self.assertEqual(out.returncode, 0, out.stderr); self.assertIn("preview", out.stdout)
        self.assertEqual((self.get(".claude/settings.json"), self.get("AGENTS.md")), before)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "hooks")))

    def test_apply_merges_and_keeps_everything_else(self):
        out = self.run_install("--apply")
        self.assertEqual(out.returncode, 0, out.stderr)
        s = json.loads(self.get(".claude/settings.json"))
        self.assertEqual(s["permissions"], self.settings["permissions"])
        cmds = self.commands()
        self.assertIn("my-own-hook.sh", cmds)
        self.assertTrue(any(c.endswith("/.claude/hooks/task-guard.py") for c in cmds))
        agents = self.get("AGENTS.md")
        self.assertTrue(agents.startswith("# Rules\n\nBe kind.\n")); self.assertIn("agentkeel:start", agents)
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".claude", "hooks", "agentkeel_core", "gitops.py")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "CLAUDE.md")))
        self.assertIn("Configured, not yet verified", out.stdout)

    def test_second_apply_is_idempotent(self):
        self.run_install("--apply")
        first = (self.get(".claude/settings.json"), self.get("AGENTS.md"))
        self.run_install("--apply")
        self.assertEqual((self.get(".claude/settings.json"), self.get("AGENTS.md")), first)
        self.assertEqual(len([c for c in self.commands() if "task-guard" in c]), 1)

    def test_v01_entries_are_replaced(self):
        self.settings["hooks"]["PreToolUse"].append({"matcher": "Write|Edit|Bash", "hooks": [
            {"type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/tier-guard.py"}]})
        self.put(".claude/settings.json", json.dumps(self.settings))
        self.run_install("--apply")
        self.assertFalse(any("tier-guard" in c for c in self.commands()))

    def test_existing_claude_md_is_warned_about_not_touched(self):
        self.put("CLAUDE.md", "mine\n")
        out = self.run_install("--apply")
        self.assertIn("Claude Code loads it instead of AGENTS.md", out.stdout)
        self.assertEqual(self.get("CLAUDE.md"), "mine\n")

    def test_uninstall_restores(self):
        self.run_install("--apply")
        out = self.run_install("--uninstall", "--apply")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(self.get(".claude/settings.json")), self.settings)
        self.assertEqual(self.get("AGENTS.md"), "# Rules\n\nBe kind.\n")
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "hooks")))

    def test_agents_md_created_and_removed_when_absent(self):
        os.remove(os.path.join(self.repo, "AGENTS.md"))
        self.run_install("--apply")
        self.assertIn("agentkeel:start", self.get("AGENTS.md"))
        self.run_install("--uninstall", "--apply")
        self.assertFalse(os.path.exists(os.path.join(self.repo, "AGENTS.md")))

    def test_invalid_settings_json_changes_nothing(self):
        self.put(".claude/settings.json", "{ not json")
        out = self.run_install("--apply")
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.get("AGENTS.md"), "# Rules\n\nBe kind.\n")

    def test_foreign_hook_with_the_same_name_is_left_alone(self):
        os.makedirs(os.path.join(self.repo, ".claude", "hooks"))
        self.put(".claude/hooks/secret-guard.py", "my own\n")
        out = self.run_install("--apply")
        self.assertIn("not agentkeel's; left alone", out.stdout)
        self.assertEqual(self.get(".claude/hooks/secret-guard.py"), "my own\n")
        self.run_install("--uninstall", "--apply")
        self.assertEqual(self.get(".claude/hooks/secret-guard.py"), "my own\n")

    def test_symlink_and_permissions_kept(self):
        os.remove(os.path.join(self.repo, "AGENTS.md"))
        self.put("RULES.md", "# Rules\n")
        os.chmod(os.path.join(self.repo, "RULES.md"), 0o644)
        os.symlink("RULES.md", os.path.join(self.repo, "AGENTS.md"))
        os.chmod(os.path.join(self.repo, ".claude", "settings.json"), 0o644)
        self.run_install("--apply")
        self.assertTrue(os.path.islink(os.path.join(self.repo, "AGENTS.md")))
        self.assertIn("agentkeel:start", self.get("RULES.md"))
        for rel in ("RULES.md", ".claude/settings.json"):
            self.assertEqual(os.stat(os.path.join(self.repo, rel)).st_mode & 0o777, 0o644, rel)

    def test_markers_out_of_order_change_nothing(self):
        self.put("AGENTS.md", "<!-- agentkeel:end -->\nx\n<!-- agentkeel:start -->\n")
        out = self.run_install("--apply")
        self.assertNotEqual(out.returncode, 0); self.assertIn("broken agentkeel block", out.stderr)
        self.assertNotIn("Traceback", out.stderr)

    def test_codex_hooks_installed_and_removed(self):
        self.run_install("--apply")
        cfg = json.loads(self.get(".codex/hooks.json"))
        cmds = [h["command"] for g in cfg["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertTrue(any("/.claude/hooks/task-guard.py" in c for c in cmds))
        stop = [h["command"] for g in cfg["hooks"]["Stop"] for h in g["hooks"]]
        self.assertTrue(any("/.claude/hooks/stop-report.py" in c for c in stop))
        self.assertTrue(os.path.exists(os.path.join(self.repo, ".claude", "hooks", "stop-report.py")))
        self.run_install("--uninstall", "--apply")
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".codex", "hooks.json")))

    def test_host_flag_limits_the_change(self):
        self.run_install("--apply", "--host", "claude")
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".codex", "hooks.json")))

    def test_existing_codex_toml_hooks_are_flagged(self):
        os.makedirs(os.path.join(self.repo, ".codex"))
        self.put(".codex/config.toml", '[[hooks.PreToolUse]]\nmatcher = "^Agent$"\n'
                 '[[hooks.PreToolUse.hooks]]\ncommand = "python3 .codex/hooks/plan-gate-guard.py"\n')
        out = self.run_install()
        self.assertIn("would run twice", out.stdout)

    def test_doctor_reports_without_changing_anything(self):
        self.run_install("--apply")
        before = self.get(".claude/settings.json")
        out = self.run_install("--doctor", "--host", "claude")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("PASS  claude", out.stdout); self.assertIn("Not verified live", out.stdout)
        self.assertEqual(self.get(".claude/settings.json"), before)
        os.remove(os.path.join(self.repo, ".claude", "hooks", "task-guard.py"))
        self.assertEqual(self.run_install("--doctor", "--host", "claude").returncode, 1)

    def test_uninstall_restores_the_original_bytes(self):
        original = '{"permissions":{"allow":["Bash(ls:*)"]}}\n'
        self.put(".claude/settings.json", original)
        self.run_install("--apply"); self.run_install("--apply")
        self.run_install("--uninstall", "--apply")
        self.assertEqual(self.get(".claude/settings.json"), original)
        left = [os.path.join(d, f) for d, _, fs in os.walk(self.repo) if ".git" not in d for f in fs]
        self.assertEqual(sorted(os.path.relpath(p, self.repo) for p in left), [".claude/settings.json", "AGENTS.md"])
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "hooks")))


if __name__ == "__main__":
    unittest.main()


class InstallContract(unittest.TestCase):
    def test_installer_ships_every_core_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ak_install_c", INSTALL)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        core = os.path.join(os.path.dirname(INSTALL), "hooks", "agentkeel_core")
        self.assertEqual(sorted(mod.CORE_FILES), sorted(f for f in os.listdir(core) if f.endswith(".py")))
        hooks = os.path.join(os.path.dirname(INSTALL), "hooks")
        shipped = set(mod.HOOK_FILES) | {"session-start.py", "run.sh"}  # these ship only with the plugin
        self.assertEqual(shipped, {f for f in os.listdir(hooks) if f.endswith((".py", ".sh"))})


class SharedSkill(unittest.TestCase):
    """skills/review-page/SKILL.md ships in the plugin root, which both hosts install whole."""

    def test_the_review_page_skill_is_shipped_to_both_hosts(self):
        path = os.path.join(ROOT, "skills", "review-page", "SKILL.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        front = text.split("---\n")[1]
        self.assertIn("name: review-page\n", front)
        self.assertIn("description: \"Write or update a present-state review page:", front)
        self.assertLessEqual(len(text.splitlines()), 60)
        # Claude Code loads skills/<name>/SKILL.md from the plugin root; Codex needs the manifest field
        with open(os.path.join(ROOT, ".codex-plugin", "plugin.json")) as fh:
            self.assertEqual(json.load(fh)["skills"], "./skills/")
        for rel in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
            with open(os.path.join(ROOT, rel)) as fh:
                src = json.load(fh)["plugins"][0]["source"]
            self.assertIn(src if isinstance(src, str) else src["path"], ("./", "."), rel)


class UserHookWithAgentkeelName(unittest.TestCase):
    def test_user_entry_and_file_survive_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as t:
            repo = os.path.realpath(os.path.join(t, "repo"))
            subprocess.run(["git", "init", "-q", repo], check=True)
            os.makedirs(os.path.join(repo, ".claude", "hooks"))
            with open(os.path.join(repo, ".claude", "hooks", "plan-gate-guard.py"), "w") as fh:
                fh.write("# mine\n")
            original = json.dumps({"hooks": {"PreToolUse": [{"matcher": "Agent", "hooks": [{"type": "command",
                "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/plan-gate-guard.py" --strict'}]}]}})
            with open(os.path.join(repo, ".claude", "settings.json"), "w") as fh:
                fh.write(original)
            env = {**os.environ, "AGENTKEEL_HOME": os.path.join(t, "home")}
            run = lambda *a: subprocess.run([sys.executable, INSTALL, repo, "--host", "claude", *a],
                                            capture_output=True, text=True, env=env)
            run("--apply")
            with open(os.path.join(repo, ".claude", "settings.json")) as fh:
                cmds = [h["command"] for gs in json.load(fh)["hooks"].values() for g in gs for h in g["hooks"]]
            self.assertIn('python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/plan-gate-guard.py" --strict', cmds)
            self.assertFalse(any(c.endswith('/.claude/hooks/plan-gate-guard.py') for c in cmds))
            run("--uninstall", "--apply")
            with open(os.path.join(repo, ".claude", "settings.json")) as fh:
                self.assertEqual(fh.read(), original)


class StageTwoReviewInstall(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(os.path.join(self._tmp.name, "repo"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.env = {**os.environ, "AGENTKEEL_HOME": os.path.join(self._tmp.name, "home")}

    def tearDown(self):
        self._tmp.cleanup()

    def run_install(self, *args):
        return subprocess.run([sys.executable, INSTALL, self.repo, *args], capture_output=True, text=True, env=self.env)

    def agents(self):
        with open(os.path.join(self.repo, "AGENTS.md"), "rb") as fh:
            return fh.read()

    def test_agents_md_round_trips_byte_for_byte(self):
        for original in (b"\n# Existing local rules\n\n\n", b"# A\r\n\r\nB\r\n", b"no newline at end", b"# R\n"):
            with open(os.path.join(self.repo, "AGENTS.md"), "wb") as fh:
                fh.write(original)
            self.run_install("--apply"); self.run_install("--apply")
            self.run_install("--uninstall", "--apply")
            self.assertEqual(self.agents(), original)

    def test_user_edits_after_install_survive_uninstall(self):
        with open(os.path.join(self.repo, "AGENTS.md"), "w") as fh:
            fh.write("# Rules\n")
        self.run_install("--apply")
        with open(os.path.join(self.repo, "AGENTS.md"), "a") as fh:
            fh.write("\n## Added later by the user\n")
        self.run_install("--uninstall", "--apply")
        text = self.agents().decode()
        self.assertIn("## Added later by the user", text); self.assertIn("# Rules", text)
        self.assertNotIn("agentkeel:start", text)

    def test_whitespace_only_edits_after_install_survive(self):
        for original, edit in ((b"Line one\nLine two\n", lambda t: t.replace(b"Line one\n", b"Line one  \n", 1)),
                               (b"# R\n\nbody\n", lambda t: t.replace(b"# R\n\n", b"# R\n\n\n", 1)),
                               (b"# R\nbody\n", lambda t: t.replace(b"# R\n", b"# R\r\n", 1))):
            with open(os.path.join(self.repo, "AGENTS.md"), "wb") as fh:
                fh.write(original)
            self.run_install("--apply")
            edited = edit(self.agents())
            with open(os.path.join(self.repo, "AGENTS.md"), "wb") as fh:
                fh.write(edited)
            self.run_install("--uninstall", "--apply")
            self.assertEqual(self.agents(), edit(original), original)

    def test_reinstall_after_an_edit_does_not_restore_stale_bytes(self):
        with open(os.path.join(self.repo, "AGENTS.md"), "wb") as fh:
            fh.write(b"# R\n")
        self.run_install("--apply")
        with open(os.path.join(self.repo, "AGENTS.md"), "ab") as fh:
            fh.write(b"\nlater\n")
        self.run_install("--apply")
        self.run_install("--uninstall", "--apply")
        self.assertIn(b"later", self.agents())

    def test_doctor_never_touches_an_existing_file(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("ak_install", INSTALL)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        old_probe = os.path.join(self.repo, "agentkeel-doctor-probe.txt")
        with open(old_probe, "w") as fh:
            fh.write("user data\n")
        os.symlink("agentkeel-doctor-probe.txt", os.path.join(self.repo, "probe-link"))
        real_run = subprocess.run

        def refusal(cmd, *a, **k):
            if cmd and cmd[0] in ("claude", "codex"):
                return subprocess.CompletedProcess(cmd, 0, "AGENTKEEL: no task is declared for this session.", "")
            return real_run(cmd, *a, **k)

        def timeout(cmd, *a, **k):
            if cmd and cmd[0] in ("claude", "codex"):
                raise subprocess.TimeoutExpired(cmd, 1)
            return real_run(cmd, *a, **k)

        for fake in (refusal, timeout):
            with mock.patch("subprocess.run", fake), \
                    mock.patch.dict(os.environ, {"AGENTKEEL_HOME": self.env["AGENTKEEL_HOME"]}):
                mod.doctor(self.repo, ("claude",), live=True)
            with open(old_probe) as fh:
                self.assertEqual(fh.read(), "user data\n")
            self.assertTrue(os.path.islink(os.path.join(self.repo, "probe-link")))
        self.assertEqual(sorted(f for f in os.listdir(self.repo) if f.startswith("agentkeel-doctor-probe")),
                         ["agentkeel-doctor-probe.txt"])
