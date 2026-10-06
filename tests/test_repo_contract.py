"""Contracts the repo makes about itself."""
import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RepoContract(unittest.TestCase):
    def test_no_claude_md_anywhere(self):
        # Claude Code loads CLAUDE.md instead of AGENTS.md when one exists; agentkeel never ships one
        found = [os.path.join(d, f) for d, _, fs in os.walk(ROOT) if ".git" not in d
                 for f in fs if f in ("CLAUDE.md", "CLAUDE.local.md")]
        self.assertEqual(found, [])

    def test_agents_fragment_is_at_most_60_lines(self):
        path = os.path.join(ROOT, "templates", "AGENTS.agentkeel.md")
        with open(path, encoding="utf-8") as fh:
            n = len(fh.read().rstrip("\n").split("\n"))
        self.assertLessEqual(n, 60, f"{path} is {n} lines")

    def test_no_em_dashes_anywhere(self):
        bad = []
        for dirpath, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for f in files:
                if f.endswith((".md", ".py", ".sh", ".json", ".yml", ".html", ".css")):
                    p = os.path.join(dirpath, f)
                    with open(p, encoding="utf-8", errors="ignore") as fh:
                        if "\u2014" in fh.read():
                            bad.append(os.path.relpath(p, ROOT))
        self.assertEqual(bad, [])

    def test_every_hook_selftests(self):
        hooks = os.path.join(ROOT, "hooks")
        for name in sorted(os.listdir(hooks)):
            path = os.path.join(hooks, name)
            if not name.endswith((".py", ".sh")):
                continue
            cmd = ["bash", path, "--selftest"] if name.endswith(".sh") else ["python3", path, "--selftest"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, f"{name}: {out.stdout}\n{out.stderr}")

    def test_shell_hooks_parse(self):
        for name in ("plan-size-guard.sh",):
            out = subprocess.run(["bash", "-n", os.path.join(ROOT, "hooks", name)], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)


class ProductDocs(unittest.TestCase):
    """AgentKeel's own docs are Markdown that GitHub renders (README.md and docs/*.md). The HTML
    records AgentKeel creates in an adopting repository are checked by pages.py instead."""

    @staticmethod
    def slugs(path):
        """The heading anchors GitHub gives a Markdown file, duplicates numbered as GitHub does."""
        import re
        seen, out = {}, set()
        with open(path, encoding="utf-8") as fh:
            text = re.sub(r"(?ms)^```.*?^```", "", fh.read())
        for m in re.finditer(r"(?m)^#{1,6} +(.+?) *#*$", text):
            s = re.sub(r"[^\w\- ]", "", m.group(1).replace("`", "").strip().lower()).replace(" ", "-")
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
        return out

    def targets(self, path):
        import re
        with open(path, encoding="utf-8") as fh:
            text = re.sub(r"(?ms)^```.*?^```", "", fh.read())
        text = re.sub(r"`[^`\n]*`", "", text)
        found = re.findall(r"\]\(([^)\s]+)\)", text)
        found += re.findall(r'(?:src|srcset|href)="([^"]+)"', text)
        return [t for t in found if not re.match(r"^[a-z][a-z0-9+.-]*:", t)]

    def test_every_relative_link_and_anchor_resolves(self):
        files = [os.path.join(ROOT, "README.md")] + sorted(
            os.path.join(ROOT, "docs", f) for f in os.listdir(os.path.join(ROOT, "docs")) if f.endswith(".md"))
        bad = []
        for src in files:
            for t in self.targets(src):
                path, _, frag = t.partition("#")
                target = os.path.normpath(os.path.join(os.path.dirname(src), path)) if path else src
                where = f"{os.path.relpath(src, ROOT)} -> {t}"
                if not os.path.exists(target):
                    bad.append(where + " (no such file)")
                elif frag and target.endswith(".md") and frag not in self.slugs(target):
                    bad.append(where + " (no such heading)")
        self.assertEqual(bad, [])

    def test_no_html_page_left_in_the_product_docs(self):
        html = [f for f in os.listdir(os.path.join(ROOT, "docs")) if f.endswith(".html")]
        self.assertEqual(html, [], "AgentKeel's own docs are Markdown; HTML is for adopter records")

    def test_the_link_check_catches_a_broken_anchor(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a.md"), os.path.join(d, "b.md")
            with open(b, "w") as fh:
                fh.write("# Title\n\n## The `docs` check\n\n## Limits\n\n## Limits\n")
            self.assertEqual(self.slugs(b), {"title", "the-docs-check", "limits", "limits-1"})
            with open(a, "w") as fh:
                fh.write("[ok](b.md#the-docs-check) [bad](b.md#nope) [gone](c.md) `[skip](x.md)`\n")
            self.assertEqual(self.targets(a), ["b.md#the-docs-check", "b.md#nope", "c.md"])


if __name__ == "__main__":
    unittest.main()


class ReleaseCheck(unittest.TestCase):
    """release_check.py: one product version in every version field, and the tag on a release."""

    FILES = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".claude-plugin/marketplace.json",
             ".agents/plugins/marketplace.json", "README.md")

    def run_check(self, root, *args):
        import subprocess, sys
        return subprocess.run([sys.executable, os.path.join(ROOT, "release_check.py"), "--root", root, *args],
                              capture_output=True, text=True)

    def copy(self):
        import shutil, tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        for rel in self.FILES:
            os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, rel), os.path.join(tmp, rel))
        return tmp

    def version(self):
        with open(os.path.join(ROOT, ".claude-plugin/plugin.json")) as fh:
            return json.load(fh)["version"]

    def test_this_repository_agrees_with_itself_and_its_own_tag(self):
        self.assertEqual(self.run_check(ROOT).returncode, 0)
        self.assertEqual(self.run_check(ROOT, "--tag", "v" + self.version()).returncode, 0)

    def test_a_mismatched_manifest_fails(self):
        tmp = self.copy()
        path = os.path.join(tmp, ".codex-plugin/plugin.json")
        with open(path) as fh:
            data = json.load(fh)
        data["version"] = "9.9.9"
        with open(path, "w") as fh:
            json.dump(data, fh)
        out = self.run_check(tmp)
        self.assertEqual(out.returncode, 1)
        self.assertIn(".codex-plugin/plugin.json = 9.9.9", out.stdout)

    def test_a_stale_readme_path_fails(self):
        tmp = self.copy()
        path = os.path.join(tmp, "README.md")
        with open(path) as fh:
            text = fh.read()
        with open(path, "w") as fh:
            fh.write(text.replace(f"agentkeel/agentkeel/{self.version()}/", "agentkeel/agentkeel/0.0.1/", 1))
        self.assertEqual(self.run_check(tmp).returncode, 1)

    def test_a_tag_that_disagrees_fails(self):
        out = self.run_check(ROOT, "--tag", "v0.1.0")
        self.assertEqual(out.returncode, 1)
        self.assertIn("does not match the tag v0.1.0", out.stdout)
