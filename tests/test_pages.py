"""agentkeel_core.pages: the HTML documentation model's validator, approval digest and context."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import GIT_ENV, HOOKS, git, state_page
from agentkeel_core import pages

PAGES = os.path.join(HOOKS, "agentkeel_core", "pages.py")
NAME = "261005-import-state.html"


def approved(text=None, name=NAME):
    return pages.with_approval(name, text or state_page(), "hisham", "2026-10-05")


class Tree:
    """An in-memory tree: path -> text."""

    def __init__(self, files, docs_html=True):
        self.files = dict(files)
        if docs_html:
            self.files.setdefault("agentkeel.json", json.dumps({"docs": "html"}))
        self.paths = set(self.files)

    def read(self, path):
        return self.files.get(path)

    def exists(self, path):
        return path in self.paths or any(p.startswith(path.rstrip("/") + "/") for p in self.paths)


def problems(files, base=None, **kw):
    return pages.check(Tree(files, **kw), Tree(base) if base is not None else None)


class Boundary(unittest.TestCase):
    def test_states(self):
        self.assertEqual(pages.boundary_state(NAME, state_page(boundary=False))[0], "none")
        self.assertEqual(pages.boundary_state(NAME, state_page())[0], "unapproved")
        self.assertEqual(pages.boundary_state(NAME, approved())[0], "approved")

    def test_edits_outside_the_boundary_keep_the_approval(self):
        text = approved().replace("Current behavior.", "New behavior.")
        text = text.replace("</body>", '<section data-keel-transient="working"><p>x</p></section></body>')
        self.assertEqual(pages.boundary_state(NAME, text)[0], "approved")

    def test_words_links_and_structure_inside_the_boundary_need_approval_again(self):
        base = approved(state_page(extra=""))
        for old, new in (("Outcome.", "Outcome, widened."),
                         ("<li><code>tests/</code></li>", "<li><code>tests/</code></li><li><code>src/</code></li>"),
                         ("</ul>\n<ul data-keel-must-not>", "\n<ul data-keel-must-not>")):
            self.assertIn(old, base)
            self.assertEqual(pages.boundary_state(NAME, base.replace(old, new, 1))[0], "changed", old)
        linked = approved(state_page().replace("<p>Outcome.</p>", '<p><a href="a.html">Outcome</a></p>'))
        self.assertEqual(pages.boundary_state(NAME, linked.replace('href="a.html"', 'href="b.html"'))[0], "changed")

    def test_the_digest_binds_the_file_name(self):
        text = approved()
        self.assertEqual(pages.boundary_state("261005-other-state.html", text)[0], "changed")

    def test_invalid_shapes(self):
        two = state_page().replace("</body>", '<section data-keel-boundary><p>b</p></section></body>')
        self.assertEqual(pages.boundary_state(NAME, two)[0], "invalid")
        scripted = state_page().replace("<p>Outcome.</p>", "<p>Outcome.</p><script>x()</script>")
        self.assertEqual(pages.boundary_state(NAME, scripted)[0], "invalid")
        empty = state_page(boundary=False).replace("</body>", "<section data-keel-boundary> <h2></h2> </section></body>")
        self.assertEqual(pages.boundary_state(NAME, empty)[0], "invalid")
        malformed = state_page().replace("</head>", '<meta name="keel-approval" content="sha256:abc by x on 2026-1-1"></head>')
        self.assertIn("malformed", pages.boundary_state(NAME, malformed)[1])
        doubled = approved().replace("</head>", '<meta name="keel-approval" content="x"></head>')
        self.assertEqual(pages.boundary_state(NAME, doubled)[0], "invalid")
        orphan = approved().replace("data-keel-boundary", "data-x")
        self.assertIn("no boundary section", pages.boundary_state(NAME, orphan)[1])
        unclosed = state_page(boundary=False).replace("</body>", "<section data-keel-boundary><p>x</p></body>")
        self.assertEqual(pages.boundary_state(NAME, unclosed)[0], "invalid")

    def test_approve_replaces_an_old_approval_and_refuses_without_a_boundary(self):
        text = approved()
        again = pages.with_approval(NAME, text.replace("Outcome.", "Outcome 2."), "h", "2026-10-06")
        self.assertEqual(len(pages.approval_metas(again)), 1)
        self.assertEqual(pages.boundary_state(NAME, again)[0], "approved")
        with self.assertRaises(ValueError):
            pages.with_approval(NAME, state_page(boundary=False), "h", "2026-10-06")

    def test_blast_radius_reads_only_the_marked_lists(self):
        b = pages.sections(state_page(changes=("a.py", "tests/"), must_not=("b.py",)), "boundary")[0]
        self.assertEqual(pages.blast_radius(b), (["a.py", "tests/"], ["b.py"]))

    def test_without_working_keeps_everything_else(self):
        text = state_page(working=True)
        out = pages.without_working(text)
        self.assertNotIn("data-keel-transient", out)
        self.assertEqual(out, state_page(working=False))


class Check(unittest.TestCase):
    def test_a_clean_tree_passes(self):
        self.assertEqual(problems({"docs/" + NAME: approved(), "docs/keel.css": "",
                                   "docs/260823-project-reference.html": "<title>Canon</title>"}), [])

    def test_not_enabled_means_nothing_to_check(self):
        self.assertEqual(problems({"docs/bad name.md": "x"}, docs_html=False), [])

    def test_names_folder_and_index(self):
        found = problems({"docs/plan.md": "x", "docs/261340-x-state.html": "<title>t</title>",
                          "docs/sub/261005-x-state.html": "<title>t</title>",
                          "docs/261005-x-asset.png": "", "docs/261005-Bad-state.html": "<title>t</title>"})
        self.assertEqual(len(found), 4, found)
        self.assertTrue(any("flat folder" in p for p in found))
        legacy = problems({"docs/archive/old.md": "x", "agentkeel.json": json.dumps({"docs": "html", "docs_legacy": ["docs/archive/*"]})})
        self.assertEqual(legacy, [])

    def test_working_section_and_unapproved_boundary_fail(self):
        found = problems({"docs/" + NAME: state_page(working=True)})
        self.assertTrue(any("Working section" in p for p in found))
        self.assertTrue(any("not been approved" in p for p in found))

    def test_title_links_and_anchors(self):
        page = ("<title>t</title><a href='261005-b-reference.html#rules'>ok</a><a href='https://x.y/z'>ext</a>"
                "<a href='261005-b-reference.html#nope'>bad anchor</a><a href='missing.html'>gone</a>"
                "<a href='#here'>self</a><h2 id='here'>h</h2><a href='../../etc/passwd'>out</a>"
                "<a href='../README.md'>readme</a><a href='mailto:a@b'>m</a>")
        found = problems({"docs/261005-a-reference.html": page, "README.md": "x",
                          "docs/261005-b-reference.html": "<title>b</title><section id='rules'></section>",
                          "docs/261005-c-reference.html": "<p>no title</p>"})
        self.assertEqual(sorted(p.split(": ", 1)[1][:22] for p in found),
                         sorted(["link '261005-b-referen", "link 'missing.html' po", "link '../../etc/passwd",
                                 "no <title>"]), found)

    def test_one_state_page_per_feature_and_one_canon(self):
        found = problems({"docs/261005-a-state.html": "<title>a</title>", "docs/261101-a-state.html": "<title>a</title>",
                          "docs/261005-project-reference.html": "<title>c</title>",
                          "docs/261101-project-reference.html": "<title>c</title>"})
        self.assertTrue(any("two state pages for 'a'" in p for p in found))
        self.assertTrue(any("more than one project canon" in p for p in found))

    def test_retired_logs(self):
        found = problems({"DECISIONS.md": "x", "docs/DECISIONS.md": "x", "CANON.md": "x",
                          "agentkeel.json": json.dumps({"docs": "html", "retired": ["CANON.md"]})})
        self.assertEqual(len([p for p in found if "retired log" in p]), 3, found)

    def test_an_approved_page_cannot_be_dropped_renamed_or_unapproved(self):
        base = {"docs/" + NAME: approved()}
        self.assertEqual(problems(dict(base), base), [])
        self.assertTrue(problems({}, base))
        renamed = {"docs/261005-import2-state.html": approved(name="261005-import2-state.html")}
        self.assertTrue(any("removes or renames" in p for p in problems(renamed, base)))
        self.assertTrue(problems({"docs/" + NAME: state_page()}, base))
        relabelled = {"docs/261005-import-reference.html": approved(name="261005-import-reference.html")}
        self.assertTrue(any("removes or renames" in p for p in problems(relabelled, base)))

    def test_base_enabling_is_enough(self):
        cand = Tree({"docs/" + NAME: state_page(working=True)}, docs_html=False)
        self.assertTrue(pages.check(cand, Tree({})))


class Context(unittest.TestCase):
    def test_structure_survives_and_code_does_not_run(self):
        page = ("<html><head><title>T &amp; U</title><style>.x{color:red}</style></head><body>"
                "<h2 id='rules'>Rules &lt;now&gt;</h2><ul><li>one <code>a.py</code></li><li>two<ul><li>nested</li></ul></li></ul>"
                "<table><tr><th>K</th><th>V</th></tr><tr><td><code>x</code></td><td><a href='y.html'>y</a></td></tr></table>"
                "<script>document.write('SECRET')</script>" + pages.sections(state_page(working=True), "working")[0]
                + "</body></html>")
        out = pages.context(page)
        for want in ("title: T & U", "[#rules]", "## Rules <now>", "- one `a.py`", "  - nested",
                     "| K | V |", "| `x` | y (y.html) |", "[working section begins]", "[section ends]"):
            self.assertIn(want, out)
        self.assertNotIn("SECRET", out)
        self.assertNotIn("color:red", out)


class CommandLine(unittest.TestCase):
    """CI runs pages.py alone against commits: the candidate and what it replaces."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self._tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        self.put("agentkeel.json", json.dumps({"docs": "html"}))
        self.put("docs/" + NAME, approved())
        self.base = self.commit("base")

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def commit(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", msg)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def run_check(self, *args):
        out = subprocess.run([sys.executable, PAGES, "check", "--root", self.repo, *args],
                             capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        return out.returncode, out.stdout

    def test_commit_checks_ignore_the_working_folder(self):
        self.assertEqual(self.run_check("--rev", self.base)[0], 0)
        self.put("docs/" + NAME, state_page(working=True))      # uncommitted: not the candidate
        self.assertEqual(self.run_check("--rev", self.base, "--base", self.base)[0], 0)
        self.assertEqual(self.run_check()[0], 1)                 # the working folder is

    def test_a_docs_only_commit_with_problems_fails(self):
        self.put("docs/" + NAME, approved().replace("Current behavior.", "x") .replace("</body>",
                 '<section data-keel-transient="working"></section></body>'))
        cand = self.commit("docs only")
        code, out = self.run_check("--rev", cand, "--base", self.base)
        self.assertEqual(code, 1); self.assertIn("Working section", out)
        os.remove(os.path.join(self.repo, "docs", NAME))
        cand = self.commit("drop")
        code, out = self.run_check("--rev", cand, "--base", self.base)
        self.assertEqual(code, 1); self.assertIn("removes or renames", out)
        self.assertEqual(self.run_check("--rev", cand, "--base", "0" * 40)[0], 0)  # first push: no base

    def test_committed_index_fails(self):
        self.put("docs/index.html", "<title>i</title>")
        self.assertIn("derived", self.run_check("--rev", self.commit("index"))[1])


if __name__ == "__main__":
    unittest.main()
