"""Guard modes: agentkeel.json "guards" turns a refusal into a warning or switches it off."""
import json
import os
import subprocess
import sys
import unittest

from helpers import HOOKS, SESSION, RepoCase, git, run_hook


class GuardModes(RepoCase):
    def modes(self, **guards):
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"guards": guards}, fh)

    def test_task_guard_blocks_by_default(self):
        self.declare()  # on protected main: a write is refused
        code, err = self.hook(self.write("src/a.py"))
        self.assertEqual(code, 2); self.assertIn("protected branch", err)

    def test_task_guard_warn_lets_the_write_through_with_a_message(self):
        self.declare(); self.modes(task="warn")
        payload = self.write("src/a.py")
        out = subprocess.run([sys.executable, os.path.join(HOOKS, "task-guard.py")], input=json.dumps(payload),
                             text=True, capture_output=True, env={**os.environ, **self.env})
        self.assertEqual(out.returncode, 0, out.stderr)
        msg = json.loads(out.stdout)["systemMessage"]
        self.assertIn("warn mode", msg); self.assertIn("protected branch", msg)

    def test_task_guard_off_is_silent(self):
        self.declare(); self.modes(task="off")
        out = subprocess.run([sys.executable, os.path.join(HOOKS, "task-guard.py")], input=json.dumps(self.write("src/a.py")),
                             text=True, capture_output=True, env={**os.environ, **self.env})
        self.assertEqual((out.returncode, out.stdout.strip(), out.stderr.strip()), (0, "", ""))

    def test_unknown_mode_or_guard_name_means_block(self):
        self.declare(); self.modes(task="maybe", nonsense="off")
        self.assertEqual(self.hook(self.write("src/a.py"))[0], 2)

    def test_secret_guard_follows_its_own_mode(self):
        self.assertEqual(run_hook("secret-guard.py", self.bash("cat .env"), env=self.env)[0], 2)
        self.modes(secret="warn")
        code, err = run_hook("secret-guard.py", self.bash("cat .env"), env=self.env)
        self.assertEqual(code, 0)
        self.modes(task="warn")  # the task guard's mode does not soften the secret guard
        self.assertEqual(run_hook("secret-guard.py", self.bash("cat .env"), env=self.env)[0], 2)

    def test_plan_size_guard_follows_its_mode(self):
        docs = os.path.join(self.repo, "docs"); os.makedirs(docs, exist_ok=True)
        page = os.path.join(docs, "261005-x-state.html")
        with open(page, "w") as fh:
            fh.write('<section data-keel-transient="working">' + "<p>t</p>\n" * 301 + "</section>")
        payload = {"tool_name": "Write", "cwd": self.repo, "tool_input": {"file_path": page}}
        self.assertEqual(run_hook("plan-size-guard.sh", payload, env=self.env)[0], 2)
        self.modes(plan_size="warn")
        out = subprocess.run(["bash", os.path.join(HOOKS, "plan-size-guard.sh")], input=json.dumps(payload),
                             text=True, capture_output=True, env={**os.environ, **self.env})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("PLAN SIZE GUARD", json.loads(out.stdout)["systemMessage"])
        self.modes(plan_size="off")
        self.assertEqual(run_hook("plan-size-guard.sh", payload, env=self.env)[0], 0)


if __name__ == "__main__":
    unittest.main()
