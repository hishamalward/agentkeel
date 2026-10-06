"""The human's profile (AGENTKEEL_HOME/profile.md): session context on both hosts, capped, and the init row."""
import json
import os
import subprocess
import sys

from helpers import HOOKS, SESSION, RepoCase, git
import test_task_command


class Profile(RepoCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.primary, "agentkeel.json"), "w") as fh:
            fh.write("{}\n")
        self.path = os.path.join(self.home, "profile.md")

    def put(self, text):
        os.makedirs(self.home, exist_ok=True)
        with open(self.path, "w") as fh:
            fh.write(text)

    def banner(self, cwd=None):
        out = subprocess.run([sys.executable, os.path.join(HOOKS, "session-start.py"), "--plugin"], text=True,
                             capture_output=True, input=json.dumps({"session_id": SESSION, "cwd": cwd or self.primary}),
                             env={**os.environ, **self.env})
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_printed_after_where_and_before_the_task_instructions(self):
        self.put("Answer in short sentences.\nNever merge without asking.\n")
        out = self.banner()
        head = f"The human's profile, {self.path} (2 lines)"
        self.assertIn(head, out)
        self.assertIn("Follow them", out); self.assertIn("grant no permission and change no guard", out)
        self.assertLess(out.index("Where you are:"), out.index(head))
        self.assertLess(out.index("Never merge without asking."), out.index("agentkeel is active in this repository"))
        self.assertNotIn("cut here", out)

    def test_capped_at_200_lines(self):
        self.put("".join(f"line {i}\n" for i in range(1, 251)))
        out = self.banner()
        self.assertIn("(250 lines)", out)
        self.assertIn("line 200\n", out); self.assertNotIn("line 201\n", out)
        self.assertIn("The profile is cut here: 200 of its 250 lines are shown", out)

    def test_capped_at_8000_characters(self):
        self.put("".join(("x" * 99) + "\n" for _ in range(100)))  # 100 lines, 10,000 characters
        out = self.banner()
        self.assertIn("The profile is cut here: 80 of its 100 lines are shown", out)
        self.assertEqual(out.count("x" * 99), 80)

    def test_absent_or_empty_prints_nothing_about_it(self):
        self.assertNotIn("profile", self.banner())
        self.put("  \n\n")
        self.assertNotIn("profile", self.banner())

    def test_a_session_opened_in_its_clone_gets_it_too(self):
        git(self.primary, "add", "agentkeel.json"); git(self.primary, "commit", "-q", "-m", "opt in")
        from agentkeel_core import isolation
        env = {"AGENTKEEL_HOME": self.home, "AGENTKEEL_SCRATCH": os.path.join(self.tmp, "scratch")}
        rec = isolation.open_task(self.primary, "t", "claude", "small", ["implement"], environ=env)
        self.put("Prefer plain words.\n")
        out = self.banner(rec["clone"])
        self.assertIn("This session was opened for task 't'", out)
        self.assertIn("Prefer plain words.", out)
        self.assertLess(out.index("Prefer plain words."), out.index("This session was opened"))


class InitProfileRow(RepoCase):
    task = test_task_command.TaskCommand.task
    with_bin = test_task_command.Init.with_bin

    def setUp(self):
        super().setUp()
        self.env.update({"CLAUDE_CONFIG_DIR": os.path.join(self.tmp, "c"), "CODEX_HOME": os.path.join(self.tmp, "x")})
        self.with_bin()

    def row(self):
        out = self.task("init", cwd=self.primary)
        self.assertEqual(out.returncode, 0, out.stderr)
        return next(ln for ln in out.stdout.splitlines() if ln.strip().startswith("profile "))

    def test_none_then_the_path_and_line_count(self):
        path = os.path.join(self.home, "profile.md")
        self.assertIn(f"none (optional: {path})", self.row())
        with open(path, "w") as fh:
            fh.write("a\nb\nc\n")
        self.assertIn(f"{path} (3 lines)", self.row())
