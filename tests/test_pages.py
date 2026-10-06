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
        self.assertIn("Release: Not released.", pages.context("<dl><dt>Release</dt><dd>Not released.</dd></dl>"))
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


STATE_NOW = ('<!doctype html><html><head><title>Import</title></head><body>\n'
             '<section class="state-now" id="state-now"><h2>State now</h2><dl>\n'
             '<dt>Implementation</dt><dd>{impl}</dd>\n<dt>Release</dt><dd>{release}</dd>\n</dl></section>\n'
             '<section id="behavior"><h2>Behavior</h2><dl><dt>Not</dt><dd>state now</dd></dl></section>\n'
             '</body></html>\n')


def state_now_page(impl="Not started.", release="Not released."):
    return STATE_NOW.format(impl=impl, release=release)


class StateNow(unittest.TestCase):
    def test_from_the_starters_dl(self):
        from agentkeel_core import starters
        self.assertEqual([k for k, _ in pages.state_now(starters.page("state", "T", "2026-10-06"))],
                         ["Implementation", "Release", "External checks"])
        self.assertEqual(pages.state_now(state_now_page("On main.")),
                         [("Implementation", "On main."), ("Release", "Not released.")])

    def test_from_a_two_column_table(self):
        page = ("<title>t</title><section id='now'><h2>State now</h2><table><tr><th></th><th></th></tr>"
                "<tr><td>Implementation</td><td>On <code>main</code>\n since x</td></tr>"
                "<tr><th>Release</th><td>None</td></tr></table></section>"
                "<section><h2>Other</h2><table><tr><td>Not</td><td>this</td></tr></table></section>")
        self.assertEqual(pages.state_now(page), [("Implementation", "On main since x"), ("Release", "None")])
        bare = "<h2>State now</h2><table><tr><td>A</td><td>b</td></tr></table><h2>Next</h2><table><tr><td>C</td><td>d</td></tr></table>"
        self.assertEqual(pages.state_now(bare), [("A", "b")])


class Claims(unittest.TestCase):
    """`merged <full-sha> into <ref>` in State now, judged by read-only git."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self._tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        self.put("agentkeel.json", json.dumps({"docs": "html"}))
        self.sha("init")
        git(self.repo, "checkout", "-q", "-b", "feat/x")
        self.merged = self.sha("feature work")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "merge", "-q", "--ff-only", "feat/x")
        git(self.repo, "checkout", "-q", "-b", "side")
        self.unmerged = self.sha("side work")
        git(self.repo, "checkout", "-q", "main")

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def sha(self, msg):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", msg)
        return subprocess.run(["git", "-C", self.repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

    def page(self, impl):
        self.put("docs/" + NAME, state_now_page(impl))

    def results(self, tree=None):
        warnings = []
        problems = pages.check(tree or pages.FsTree(self.repo), None, warnings)
        return [r[3] for r in pages.claim_results(tree or pages.FsTree(self.repo))], problems, warnings

    def run_check(self, *args):
        out = subprocess.run([sys.executable, PAGES, "check", "--root", self.repo, *args],
                             capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        return out.returncode, out.stdout

    def test_a_merged_commit_stays_proven_as_its_branch_moves_and_goes(self):
        self.page(f"merged {self.merged} into main.")
        self.assertEqual(self.results()[:2], (["proven"], []))
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "later work on the branch")
        git(self.repo, "branch", "-q", "-f", "feat/x", "HEAD")
        git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        self.assertEqual(self.results()[:2], (["proven"], []))
        git(self.repo, "branch", "-q", "-D", "feat/x")
        self.assertEqual(self.results()[:2], (["proven"], []))
        # proven by main itself, not only by the candidate: a candidate without the commit
        git(self.repo, "checkout", "-q", "--orphan", "lone")
        self.page(f"merged {self.merged} into main.")
        lone = self.sha("lone")
        self.assertEqual(self.results(pages.GitTree(self.repo, lone))[:2], (["proven"], []))

    def test_the_candidate_proves_a_claim_main_does_not_hold_yet(self):
        git(self.repo, "checkout", "-q", "side")
        self.page(f"merged {self.unmerged} into main")
        cand = self.sha("page lands with the side work")
        self.assertEqual(self.results(pages.GitTree(self.repo, cand))[:2], (["proven"], []))

    def test_a_branch_name_or_short_id_is_unknown_and_never_fails(self):
        self.page(f"merged feat/x into main; merged {self.merged[:7]} into main; merged {'f' * 40} into main;"
                  f" merged {self.merged} into nowhere")
        found, problems, warnings = self.results()
        self.assertEqual(found, ["unknown"] * 3 + ["proven"])  # the candidate holds it, whatever the ref
        self.assertEqual(problems, [])
        self.assertEqual(len(warnings), 3, warnings)
        code, out = self.run_check()
        self.assertEqual(code, 0, out); self.assertEqual(out.count("WARN"), 3, out)
        self.page(f"merged {self.unmerged} into nowhere")
        self.assertEqual(self.results()[0], ["unknown"])      # an unresolvable ref is no contradiction

    def test_a_real_contradiction_fails_the_check(self):
        self.page(f"merged {self.unmerged} into main")
        found, problems, _ = self.results()
        self.assertEqual(found, ["contradiction"])
        self.assertTrue(any("contradicts" in p for p in problems), problems)
        cand = self.sha("the page")
        code, out = self.run_check("--rev", cand)
        self.assertEqual(code, 1, out); self.assertIn("contradicts", out)

    def test_an_authored_outside_fact_is_untouched(self):
        text = state_now_page("App Store review pending since 2026-10-01; build merged by the release team")
        self.put("docs/" + NAME, text)
        self.assertEqual(pages.claims(text), [])
        self.assertEqual(self.results(), ([], [], []))
        with open(os.path.join(self.repo, "docs", NAME)) as fh:
            self.assertEqual(fh.read(), text)


class IndexFromACleanCopy(unittest.TestCase):
    """An adopting repository copies pages.py alone to .github/agentkeel/ and runs `index` there."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.realpath(self._tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        os.makedirs(os.path.join(self.repo, ".github", "agentkeel"))
        import shutil
        shutil.copy(PAGES, os.path.join(self.repo, ".github", "agentkeel", "pages.py"))
        self.put("agentkeel.json", json.dumps({"docs": "html", "docs_legacy": ["docs/specs/*", "docs/archive/*"]}))
        self.put("docs/261005-import-state.html", state_now_page("Not started."))
        self.put("docs/261005-import-memory-audit.html", "<title>Memory audit</title>")
        self.put("docs/261101-project-reference.html", "<title>Project canon</title>")
        self.put("docs/260101-alpha-reference.html", "<title>Alpha</title>")
        self.legacy = {"docs/specs/a-spec.md": "Spec A", "docs/specs/b notes.md": "b notes.md",
                       "docs/archive/old.html": "Old plan", "docs/archive/deep/x.md": "Deep",
                       "docs/archive/pic.png": "pic.png"}
        self.put("docs/specs/a-spec.md", "intro\n\n## Spec A\n\n# Later\n")
        self.put("docs/specs/b notes.md", "no heading\n")
        self.put("docs/archive/old.html", "<html><head><title>Old plan</title></head></html>")
        self.put("docs/archive/deep/x.md", "# Deep\n")
        self.put("docs/archive/pic.png", "x")

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def index(self, *args):
        # -I: no script folder or user site on sys.path, so only the copied file itself can run
        out = subprocess.run([sys.executable, "-I", ".github/agentkeel/pages.py", "index", "--root", ".", *args],
                             cwd=self.repo, capture_output=True, text=True, env={**os.environ, **GIT_ENV})
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        with open(os.path.join(self.repo, "docs", "index.html")) as fh:
            return out.stdout, fh.read()

    def test_the_copy_alone_lists_pages_state_now_and_legacy(self):
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".github", "agentkeel", "agentkeel_core")))
        text, page = self.index()
        lines = text.splitlines()
        families = [l for l in lines if l and not l.startswith(" ") and not l.startswith(("agentkeel", "legacy"))]
        self.assertEqual(families, ["project", "alpha", "import"])
        self.assertIn("  state     Import  (261005-import-state.html)", lines)
        self.assertIn("      Implementation: Not started.", lines)
        self.assertIn("  audit     Memory audit  (261005-import-memory-audit.html)", lines)
        self.assertIn("  docs/archive/  2 file(s)", lines)
        self.assertIn("  docs/archive/deep/  1 file(s)", lines)
        self.assertIn("  docs/specs/  2 file(s)", lines)
        self.assertNotIn("Spec A", text)                       # titles only with --full
        self.assertIn("<dt>Implementation</dt><dd>Not started.</dd>", page)

    def test_a_changed_state_now_shows_in_the_next_run(self):
        self.index()
        self.put("docs/261005-import-state.html", state_now_page("On main since today."))
        text, page = self.index()
        self.assertIn("Implementation: On main since today.", text)
        self.assertNotIn("Not started.", text + page)

    def test_every_legacy_file_is_reachable_from_the_index(self):
        _, page = self.index()
        import urllib.parse
        targets = {os.path.normpath(os.path.join("docs", urllib.parse.unquote(link))) for link in pages.scan(page).links
                   if link != "keel.css"}
        self.assertTrue(set(self.legacy) <= targets, set(self.legacy) - targets)
        for path, title in self.legacy.items():
            self.assertIn(f">{title}</a>", page)

    def test_full_lists_every_legacy_file_with_its_title(self):
        text, _ = self.index("--full")
        for path, title in self.legacy.items():
            self.assertIn(f"    {path}  {title}", text.splitlines())


if __name__ == "__main__":
    unittest.main()
