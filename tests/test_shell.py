"""agentkeel_core.shell: every simple command in a line, with its env and directory."""
import unittest

import helpers  # noqa: F401  (puts hooks/ on sys.path)
from agentkeel_core import shell


def argvs(cmd, cwd="/r"):
    return [c.argv for c in shell.commands(cmd, cwd)]


class Shell(unittest.TestCase):
    def test_separators(self):
        self.assertEqual(argvs("a 1 && b 2; c | d || e & f\ng"),
                         [["a", "1"], ["b", "2"], ["c"], ["d"], ["e"], ["f"], ["g"]])

    def test_quotes_keep_separators_as_data(self):
        self.assertEqual(argvs("git commit -m 'a; git push origin main' -- x"),
                         [["git", "commit", "-m", "a; git push origin main", "--", "x"]])

    def test_env_prefix_and_wrappers(self):
        c = shell.commands("FOO=1 BAR=2 sudo -u me env BAZ=3 timeout 10 git push", "/r")[0]
        self.assertEqual(c.argv, ["git", "push"]); self.assertEqual(c.env, {"FOO": "1", "BAR": "2", "BAZ": "3"})

    def test_cd_changes_directory_for_later_commands(self):
        cs = shell.commands("cd /other && git push; cd sub && git status", "/r")
        self.assertEqual([c.cwd for c in cs], ["/other", "/other/sub"])

    def test_nested_shells_and_substitutions(self):
        self.assertIn(["git", "push", "origin", "main"], argvs("bash -c 'git push origin main'"))
        self.assertIn(["git", "push", "origin", shell.SUBST + ":main"], argvs("git push origin $(git rev-parse HEAD):main"))
        inner = shell.commands("A=1 bash -c 'B=2 sh -c \"tool x\"'; eval A=3 tool y", "/")
        self.assertEqual([(c.argv, c.env) for c in inner], [(["tool", "x"], {"A": "1", "B": "2"}), (["tool", "y"], {"A": "3"})])
        self.assertIn(["git", "push", "origin", "main"], argvs("echo $(git push origin main)"))
        self.assertIn(["git", "push", "origin", "main"], argvs("echo `git push origin main`"))
        self.assertIn(["git", "push", "origin", "main"], argvs('eval "git push origin main"'))

    def test_heredoc_body_is_skipped(self):
        self.assertEqual(argvs("cat > f <<'EOF'\ngit push origin main\nEOF\nls"), [["cat"], ["ls"]])

    def test_redirects_are_not_arguments(self):
        self.assertEqual(argvs("git push origin feat 2>&1 > out.txt"), [["git", "push", "origin", "feat"]])

    def test_unbalanced_quotes_still_split(self):
        self.assertTrue(any(a[:2] == ["git", "push"] for a in argvs("echo 'x && git push origin main")))


if __name__ == "__main__":
    unittest.main()
