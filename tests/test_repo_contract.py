"""Contracts the repo makes about itself."""
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RepoContract(unittest.TestCase):
    def test_claude_fragment_is_at_most_60_lines(self):
        path = os.path.join(ROOT, "templates", "CLAUDE.agentkeel.md")
        with open(path, encoding="utf-8") as fh:
            n = len(fh.read().rstrip("\n").split("\n"))
        self.assertLessEqual(n, 60, f"{path} is {n} lines")

    def test_no_em_dashes_anywhere(self):
        bad = []
        for dirpath, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for f in files:
                if f.endswith((".md", ".py", ".sh", ".json", ".yml")):
                    p = os.path.join(dirpath, f)
                    with open(p, encoding="utf-8", errors="ignore") as fh:
                        if "\u2014" in fh.read():
                            bad.append(os.path.relpath(p, ROOT))
        self.assertEqual(bad, [])

    def test_every_hook_selftests(self):
        hooks = os.path.join(ROOT, "hooks")
        for name in sorted(os.listdir(hooks)):
            path = os.path.join(hooks, name)
            cmd = ["bash", path, "--selftest"] if name.endswith(".sh") else ["python3", path, "--selftest"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, f"{name}: {out.stdout}\n{out.stderr}")

    def test_shell_hooks_parse(self):
        for name in ("tier.sh", "plan-size-guard.sh"):
            out = subprocess.run(["bash", "-n", os.path.join(ROOT, "hooks", name)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
