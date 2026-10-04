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
        return subprocess.run([sys.executable, INSTALL, self.repo, *args], capture_output=True, text=True)

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
        self.assertEqual(os.listdir(os.path.join(self.repo, ".claude", "hooks")), [])

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


if __name__ == "__main__":
    unittest.main()
