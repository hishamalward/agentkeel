"""agentkeel core: the HTML documentation model, read and checked.

A repository opts in with `"docs": "html"` in agentkeel.json. Its documentation is then authored
HTML in one flat docs/ folder, one source per artifact, named

    YYMMDD-<family>[-<qualifier>]-<kind>.html     kind: state | audit | mockup | reference
    YYMMDD-<family>[-<qualifier>]-asset.<ext>     a supporting file
    keel.css                                      the shared stylesheet
    index.html                                    derived, never committed (task.py index)

A page may carry two marked sections:

    <section data-keel-boundary> ... </section>          what was agreed: outcome, constraints,
                                                          acceptance checks; approval required
    <section data-keel-transient="working"> ... </section>  this phase's notes; removed before main

The human's `task.py approve` writes `<meta name="keel-approval" content="sha256:<hex> by <name>
on <date>">` in the head. The digest covers the page's file name and the boundary's HTML source
(line endings normalised), so changed words, links or list structure all need approval again.
The digest detects a change; it does not prove who approved (see docs: the shell is not guarded).

This module has no imports from the rest of agentkeel_core: CI copies it alone into a repository
(.github/agentkeel/pages.py) and runs `python3 pages.py check --rev <sha> --base <sha>`, the same
check the local guard runs before main moves.
"""
import datetime
import fnmatch
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser

KINDS = ("state", "audit", "mockup", "reference")
NAME_RE = re.compile(r"^(\d{6})-([a-z0-9]+(?:-[a-z0-9]+)*)-(state|audit|mockup|reference)\.html$")
ASSET_RE = re.compile(r"^(\d{6})-([a-z0-9]+(?:-[a-z0-9]+)*)-asset\.[A-Za-z0-9]+$")
FIXED = ("keel.css", "index.html")
BOUNDARY, WORKING, APPROVAL = "data-keel-boundary", "data-keel-transient", "keel-approval"
APPROVAL_RE = re.compile(r"^sha256:([0-9a-f]{64}) by (.+) on (\d{4}-\d{2}-\d{2})$")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
LINK_ATTRS = {("a", "href"), ("link", "href"), ("img", "src"), ("script", "src"), ("iframe", "src"),
              ("source", "src"), ("video", "src"), ("audio", "src")}
RETIRED_LOGS = ("DECISIONS.md",)


# ---- reading one page --------------------------------------------------------------------------

class _Scan(HTMLParser):
    """Title, ids, links, marked sections (with source offsets) and approval metas of one page."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.text = text
        self._line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
        self.title, self._in_title = "", False
        self.ids, self.links, self.approvals = set(), [], []
        self.marked, self.unclosed, self._sections = [], [], []
        self.scripts_at = []

    def _offset(self):
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        start = self._offset()
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        for t, attr in LINK_ATTRS:
            if tag == t and a.get(attr):
                self.links.append(a[attr])
        if tag == "title":
            self._in_title = True
        if tag == "script":
            self.scripts_at.append(start)
        if tag == "meta" and (a.get("name") or "").lower() == APPROVAL:
            raw = self.get_starttag_text() or ""
            self.approvals.append((a.get("content") or "", start, start + len(raw)))
        if tag == "section":
            kind = "boundary" if BOUNDARY in a else "working" if WORKING in a else None
            self._sections.append((kind, start))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag == "section":
            kind, start = self._sections.pop()
            if kind:
                self.marked.append((kind, start, start + len(self.get_starttag_text() or "")))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "section" and self._sections:
            kind, start = self._sections.pop()
            if kind:
                end = self.text.find(">", self._offset()) + 1
                self.marked.append((kind, start, end))

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def close(self):
        super().close()
        self.unclosed = [k for k, _ in self._sections if k]


def scan(text):
    s = _Scan(text or "")
    s.feed(text or "")
    s.close()
    return s


def sections(text, kind):
    """The HTML source of every `kind` section ('boundary' or 'working'), in order."""
    s = scan(text)
    return [text[a:b] for k, a, b in sorted(s.marked, key=lambda m: m[1]) if k == kind]


def digest(name, boundary_src):
    norm = boundary_src.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256((os.path.basename(name) + "\n" + norm).encode("utf-8")).hexdigest()


def approval(text):
    """(digest, by, on) of the page's single well-formed approval meta, else None."""
    metas = scan(text).approvals
    if len(metas) != 1:
        return None
    m = APPROVAL_RE.match(metas[0][0].strip())
    return (m.group(1), m.group(2), m.group(3)) if m else None


def approval_metas(text):
    """The raw content strings of every approval meta: what an agent edit must leave unchanged."""
    return [c for c, _, _ in scan(text or "").approvals]


def boundary_state(name, text):
    """('none' | 'approved' | 'unapproved' | 'changed' | 'invalid', detail)."""
    s = scan(text)
    bounds = [m for m in s.marked if m[0] == "boundary"]
    if "boundary" in s.unclosed:
        return "invalid", "its boundary section is not closed"
    if len(bounds) > 1:
        return "invalid", f"it has {len(bounds)} boundary sections; one page has at most one"
    if not bounds:
        return ("invalid", "it has approval data but no boundary section") if s.approvals else ("none", "")
    _, a, b = bounds[0]
    src = text[a:b]
    if any(a <= p < b for p in s.scripts_at):
        return "invalid", "its boundary contains a script; a boundary must be static HTML"
    if not re.sub(r"<[^>]*>", "", src).strip():
        return "invalid", "its boundary section is empty"
    if len(s.approvals) > 1:
        return "invalid", "it has more than one keel-approval meta"
    if not s.approvals:
        return "unapproved", "its boundary has not been approved (the human runs task.py approve)"
    got = approval(text)
    if not got:
        return "invalid", "its keel-approval meta is malformed"
    if got[0] != digest(name, src):
        return "changed", "its boundary changed since it was approved (the human runs task.py approve again)"
    return "approved", f"approved by {got[1]} on {got[2]}"


def with_approval(name, text, by, on):
    """The page text with a fresh approval meta for its current boundary; ValueError if it cannot."""
    for _, a, b in sorted(scan(text).approvals, key=lambda m: -m[1]):
        text = text[:a] + text[b + 1 if text[b:b + 1] == "\n" else b:]
    state, why = boundary_state(name, text)
    if state != "unapproved":
        raise ValueError(f"{name}: {why or 'it has no <section ' + BOUNDARY + '> to approve'}")
    meta = f'<meta name="{APPROVAL}" content="sha256:{digest(name, sections(text, "boundary")[0])} by {html.escape(by)} on {on}">'
    head = re.search(r"</head\s*>", text, re.IGNORECASE)
    if not head:
        raise ValueError(f"{name} has no </head>; the approval meta goes in the head")
    return text[:head.start()] + meta + "\n" + text[head.start():]


def without_working(text):
    """The page text with its Working sections removed (and the blank line they leave)."""
    for _, a, b in sorted([m for m in scan(text).marked if m[0] == "working"], key=lambda m: -m[1]):
        a2 = text.rfind("\n", 0, a) + 1 if not text[text.rfind("\n", 0, a) + 1:a].strip() else a
        b2 = b + 1 if text[b:b + 1] == "\n" else b
        text = text[:a2] + text[b2:]
    return text


class _Codes(HTMLParser):
    """Text of <code> elements inside data-keel-changes / data-keel-must-not containers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.out, self._code = [], {"changes": [], "must-not": []}, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        mode = "changes" if "data-keel-changes" in a else "must-not" if "data-keel-must-not" in a else None
        if tag not in VOID:
            self.stack.append((tag, mode))
        if tag == "code" and self.mode():
            self._code = ""

    def mode(self):
        return next((m for _, m in reversed(self.stack) if m), None)

    def handle_endtag(self, tag):
        if tag == "code" and self._code is not None:
            if self.mode() and self._code.strip():
                self.out[self.mode()].append(self._code.strip())
            self._code = None
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if self._code is not None:
            self._code += data


def blast_radius(boundary_src):
    """(changes, must_not) path patterns: <code> items in the boundary's marked lists."""
    p = _Codes()
    p.feed(boundary_src or "")
    p.close()
    return p.out["changes"], p.out["must-not"]


# ---- context: the page as plain structured text, for an agent to read ---------------------------

class _Text(HTMLParser):
    SKIP = {"style", "script", "template", "head"}
    BLOCK = {"p", "div", "section", "article", "header", "footer", "main", "nav", "aside", "blockquote",
             "figure", "figcaption", "details", "summary", "dl", "dt", "dd", "form", "ul", "ol", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.buf, self.skip, self.lists, self.pre = [], "", 0, [], 0
        self.title, self._title, self.row, self.cell, self._href = "", False, None, None, []
        self.sections = []

    def flush(self):
        text = self.buf if self.pre else re.sub(r"\s+", " ", self.buf).strip()
        if text:
            indent = "  " * max(len(self.lists) - 1, 0)
            self.lines.append(indent + text)
        self.buf = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._title = True
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if self.cell is not None and tag not in ("td", "th", "tr"):
            if tag == "br":
                self.cell += " "
            if tag == "a":
                self._href.append(a.get("href") or "")
            if tag == "code":
                self.cell += "`"
            return
        if tag == "dd" and self.buf.strip():
            self.buf = self.buf.rstrip() + ": "  # a definition stays on its term's line
        elif tag in self.BLOCK or tag in ("li", "tr", "pre", "br", "hr") or re.match(r"h[1-6]$", tag):
            self.flush()
        if tag == "section":
            kind = "boundary" if BOUNDARY in a else "working" if WORKING in a else ""
            self.sections.append(kind)
            if kind:
                self.lines.append(f"[{kind} section begins]")
        if re.match(r"h[1-6]$", tag):
            self.buf = "#" * int(tag[1]) + " "
        if tag in ("ul", "ol"):
            self.lists.append(tag)
        if tag == "li":
            self.buf = "- "
        if tag == "pre":
            self.pre += 1
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.cell = ""
        if tag == "a":
            self._href.append(a.get("href") or "")
        if tag == "code" and not self.pre:
            self.buf += "`"
        if tag == "img" and a.get("alt"):
            self.buf += f"[image: {a['alt']}]"
        if a.get("id") and (tag == "section" or re.match(r"h[1-6]$", tag)):
            self.lines.append(f"[#{a['id']}]")

    def handle_endtag(self, tag):
        if tag == "title":
            self._title = False
        if tag in self.SKIP:
            self.skip = max(self.skip - 1, 0)
            return
        if self.skip:
            return
        if tag == "a" and self._href:
            href = self._href.pop()
            if href and not href.startswith("#") or (href.startswith("#") and len(href) > 1):
                target = f" ({href})"
                if self.cell is not None:
                    self.cell += target
                else:
                    self.buf += target
            return
        if self.cell is not None and tag not in ("td", "th", "tr"):
            if tag == "code":
                self.cell += "`"
            return
        if tag in ("td", "th"):
            if self.row is not None:
                self.row.append(re.sub(r"\s+", " ", self.cell or "").strip())
            self.cell = None
            return
        if tag == "tr":
            if self.row:
                self.lines.append("| " + " | ".join(self.row) + " |")
            self.row = None
            return
        if tag == "code" and not self.pre:
            self.buf += "`"
            return
        if tag in ("ul", "ol") and self.lists:
            self.flush()
            self.lists.pop()
            return
        if tag == "pre":
            self.flush()
            self.pre = max(self.pre - 1, 0)
            return
        if tag == "section":
            self.flush()
            if self.sections and self.sections.pop():
                self.lines.append("[section ends]")
        if tag == "dt":
            return
        if tag in self.BLOCK or tag == "li" or re.match(r"h[1-6]$", tag):
            self.flush()

    def handle_data(self, data):
        if self._title:
            self.title += data
        if self.skip:
            return
        if self.cell is not None:
            self.cell += data
        else:
            self.buf += data


def context(text):
    """The page's content as structured plain text: headings, lists, table rows, link targets and
    section ids; no style, script or page code. Nothing is executed or written."""
    p = _Text()
    p.feed(text or "")
    p.close()
    p.flush()
    out = [f"title: {p.title.strip()}"] if p.title.strip() else []
    return "\n".join(out + p.lines) + "\n"


# ---- trees: the files of a candidate commit, or of a working folder ------------------------------

class GitTree:
    def __init__(self, root, rev):
        self.root, self.rev = root, rev
        out = subprocess.run(["git", "-C", root, "ls-tree", "-r", "--name-only", "-z", rev],
                             capture_output=True, text=True)
        if out.returncode != 0:
            raise ValueError(f"cannot read {rev}: {out.stderr.strip()[:200]}")
        self.paths = set(p for p in out.stdout.split("\0") if p)
        self._cache = {}

    def read(self, path):
        if path not in self.paths:
            return None
        if path not in self._cache:
            out = subprocess.run(["git", "-C", self.root, "show", f"{self.rev}:{path}"], capture_output=True)
            self._cache[path] = out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None
        return self._cache[path]

    def exists(self, path):
        return path in self.paths or any(p.startswith(path.rstrip("/") + "/") for p in self.paths)


class FsTree:
    def __init__(self, root):
        self.root = root
        self.paths = set()
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__")]
            for f in files:
                self.paths.add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))

    def read(self, path):
        try:
            with open(os.path.join(self.root, path), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    def exists(self, path):
        return os.path.exists(os.path.join(self.root, path))


def config(tree):
    try:
        data = json.loads(tree.read("agentkeel.json") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def enabled(tree):
    return config(tree).get("docs") == "html"


# ---- the check ------------------------------------------------------------------------------------

def _valid_date(yymmdd):
    try:
        datetime.datetime.strptime(yymmdd, "%y%m%d")
        return True
    except ValueError:
        return False


def _resolve(page, link):
    """(repo-relative path or '' for the page itself, fragment), or None for an external link."""
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", link) or link.startswith("//"):
        return None
    path, _, frag = link.partition("#")
    path = path.split("?", 1)[0]
    if not path:
        return "", frag
    target = os.path.normpath(os.path.join(os.path.dirname(page), path)).replace(os.sep, "/")
    return target, frag


def check(tree, base=None):
    """Problems (strings) that keep this candidate off main. [] when the repo has not opted in."""
    if not (enabled(tree) or (base is not None and enabled(base))):
        return []
    cfg = config(tree)
    legacy = [str(g) for g in cfg.get("docs_legacy") or []]
    retired = list(RETIRED_LOGS) + [str(p) for p in cfg.get("retired") or []]
    problems = []
    for p in sorted(tree.paths):
        if p in retired or os.path.basename(p) in RETIRED_LOGS:
            problems.append(f"{p}: a retired log; the current owner of each rule is its page in docs/")
    pages, states, projects = {}, {}, []
    for p in sorted(tree.paths):
        if not p.startswith("docs/") or any(fnmatch.fnmatchcase(p, g) for g in legacy):
            continue
        name = p[len("docs/"):]
        if "/" in name:
            problems.append(f"{p}: docs/ is one flat folder; no subfolders")
            continue
        if name in FIXED:
            if name == "index.html" and isinstance(tree, GitTree):
                problems.append(f"{p}: the index is derived (task.py index); do not commit it")
            continue
        m = NAME_RE.match(name)
        asset = None if m else ASSET_RE.match(name)
        if not (m or asset) or not _valid_date((m or asset).group(1)):
            problems.append(f"{p}: name must be YYMMDD-<family>[-<qualifier>]-<kind>.html "
                            f"(kind: {', '.join(KINDS)}) or ...-asset.<ext>, with a real date")
            continue
        if name.endswith(".html"):
            pages[p] = asset or m  # an HTML asset is checked like a page: links, Working section
            if m and m.group(3) == "state":
                states.setdefault(m.group(2), []).append(p)
            if m and m.group(3) == "reference" and m.group(2) == "project":
                projects.append(p)
    for family, ps in states.items():
        if len(ps) > 1:
            problems.append(f"two state pages for '{family}': {', '.join(ps)}; a feature has one")
    if len(projects) > 1:
        problems.append(f"more than one project canon: {', '.join(projects)}")
    scans = {}
    for p in pages:
        text = tree.read(p) or ""
        s = scans[p] = scan(text)
        if not s.title.strip():
            problems.append(f"{p}: no <title>")
        if "working" in s.unclosed or sum(1 for m in s.marked if m[0] == "working"):
            problems.append(f"{p}: has a Working section; remove it before main moves (task.py finish {p})")
        state, why = boundary_state(os.path.basename(p), text)
        if state in ("invalid", "unapproved", "changed"):
            problems.append(f"{p}: {why}")
    for p, s in scans.items():
        for link in s.links:
            r = _resolve(p, link)
            if r is None:
                continue
            target, frag = r
            if target.startswith(".."):
                problems.append(f"{p}: link '{link}' leaves the repository")
                continue
            if target and not tree.exists(target):
                problems.append(f"{p}: link '{link}' points to a file that does not exist")
                continue
            if frag:
                ids = s.ids if not target else (scans[target].ids if target in scans else
                                                 scan(tree.read(target) or "").ids if target.endswith(".html") else None)
                if ids is not None and frag not in ids:
                    problems.append(f"{p}: link '{link}' names an anchor that does not exist")
    if base is not None:
        for p in sorted(base.paths):
            if p.startswith("docs/") and p.endswith(".html") and approval_metas(base.read(p)):
                if p not in tree.paths or not approval_metas(tree.read(p)):
                    problems.append(f"{p}: approved on main, and this candidate removes or renames it or "
                                    "its approval; an approved boundary cannot be dropped this way")
    return problems


# ---- command line (CI runs this file on its own) --------------------------------------------------

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="pages.py", description="Check agentkeel HTML docs.")
    sub = ap.add_subparsers(dest="action")
    c = sub.add_parser("check")
    c.add_argument("--rev", help="the candidate commit (default: the working folder)")
    c.add_argument("--base", help="the commit the candidate replaces on main")
    c.add_argument("--root", default=".")
    x = sub.add_parser("context")
    x.add_argument("page")
    args = ap.parse_args(argv)
    if args.action == "context":
        with open(args.page, encoding="utf-8", errors="replace") as fh:
            sys.stdout.write(context(fh.read()))
        return 0
    if args.action != "check":
        ap.print_help()
        return 2
    root = os.path.abspath(args.root)
    try:
        tree = GitTree(root, args.rev) if args.rev else FsTree(root)
        base = GitTree(root, args.base) if args.base and not re.fullmatch(r"0+", args.base) else None
    except ValueError as exc:
        print(f"agentkeel docs check: {exc}")
        return 2
    if not (enabled(tree) or (base is not None and enabled(base))):
        print('agentkeel docs check: not enabled ("docs": "html" is not set in agentkeel.json)')
        return 0
    problems = check(tree, base)
    for p in problems:
        print(f"  FAIL {p}")
    print(f"agentkeel docs check: {'FAIL' if problems else 'PASS'} ({len(problems)} problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
