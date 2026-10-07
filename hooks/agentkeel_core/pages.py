"""agentkeel core: the HTML documentation model, read and checked.

A repository opts in with `"docs": "html"` in agentkeel.json. Its documentation is then authored
HTML in one flat docs/ folder, one source per artifact, named

    YYMMDD-<family>[-<qualifier>]-<kind>.html     kind: state | audit | mockup | reference
    YYMMDD-<family>[-<qualifier>]-asset.<ext>     a supporting file
    keel.css                                      the shared stylesheet
    index.html                                    derived, never committed (`index` below)

A page may carry two marked sections:

    <section data-keel-boundary> ... </section>          what was agreed: outcome, constraints,
                                                          acceptance checks; approval required
    <section data-keel-transient="working"> ... </section>  this phase's notes; removed before main

The human's `task.py approve` writes `<meta name="keel-approval" content="sha256:<hex> by <name>
on <date>">` in the head. The digest covers the page's file name and the boundary's HTML source
(line endings normalised), so changed words, links or list structure all need approval again.
The digest detects a change; it does not prove who approved (see docs: the shell is not guarded).

A state page's State now block (`<section class="state-now" id="state-now">` with dt/dd pairs,
or a "State now" section written as a two-column table) is read at each run, never stored. In it,
`merged <full-sha> into <ref>` is a claim the check proves with read-only git: proven when the
commit is in <ref> or in the candidate, a contradiction (fails) when it is in neither, unknown (a
warning) when git cannot tell or the text names a branch or a short id.

This module has no imports from the rest of agentkeel_core: CI copies it alone into a repository
(.github/agentkeel/pages.py) and runs `python3 pages.py check --rev <sha> --base <sha>`, the same
check the local guard runs before main moves, and `python3 pages.py index --root .` for the
derived index.
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
import urllib.parse
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


# ---- State now: the fixed block of a state page, and the claims in it ----------------------------

class _StateNow(HTMLParser):
    """(label, value) pairs of the State now block: dt/dd pairs, or the rows of a two-column table.
    The block is a section with id or class state-now, or the part under a "State now" heading."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pairs, self.depth = [], 0          # depth: open <section> elements
        self.by_section = None                  # the depth of the state-now section while inside it
        self.by_heading = None                  # (level, section depth) of a "State now" heading
        self.heading, self.cell, self.row, self.term = None, None, None, None

    def active(self):
        return self.by_section is not None or self.by_heading is not None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self.depth += 1
            if self.by_section is None and (a.get("id") == "state-now" or "state-now" in (a.get("class") or "").split()):
                self.by_section = self.depth
        if re.match(r"h[1-6]$", tag):
            if self.by_heading and int(tag[1]) <= self.by_heading[0]:
                self.by_heading = None
            self.heading = (int(tag[1]), "")
        if not self.active():
            return
        if tag in ("dt", "dd", "td", "th"):
            self.cell = ""
        if tag == "tr":
            self.row = []
        if tag == "br" and self.cell is not None:
            self.cell += " "

    def handle_endtag(self, tag):
        if self.heading and re.match(r"h[1-6]$", tag):
            level, text = self.heading
            self.heading = None
            if self.by_section is None and re.sub(r"\s+", " ", text).strip().lower() == "state now":
                self.by_heading = (level, self.depth)
        if tag == "section":
            if self.by_section == self.depth:
                self.by_section = None
            if self.by_heading and self.depth <= self.by_heading[1]:
                self.by_heading = None
            self.depth = max(self.depth - 1, 0)
        if not self.active() or self.cell is None and tag != "tr":
            return
        text = re.sub(r"\s+", " ", self.cell or "").strip()
        if tag == "dt":
            self.term, self.cell = text, None
        elif tag == "dd":
            if self.term:
                self.pairs.append((self.term, text))
            self.term, self.cell = None, None
        elif tag in ("td", "th"):
            if self.row is not None:
                self.row.append((tag, text))
            self.cell = None
        elif tag == "tr":
            row, self.row = self.row or [], None
            # a two-column row with a label; a row of headers only is the table's head
            if len(row) == 2 and row[0][1] and not all(t == "th" for t, _ in row):
                self.pairs.append((row[0][1], row[1][1]))

    def handle_data(self, data):
        if self.heading:
            self.heading = (self.heading[0], self.heading[1] + data)
        if self.active() and self.cell is not None:
            self.cell += data


def state_now(text):
    """The page's State now lines as (label, value) pairs, read from the page as it is now."""
    p = _StateNow()
    p.feed(text or "")
    p.close()
    return p.pairs


CLAIM_RE = re.compile(r"\bmerged\s+`?([^\s`]+?)`?\s+into\s+`?([A-Za-z0-9._/-]+)", re.IGNORECASE)
FULL_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def claims(text):
    """Every `merged <commit> into <ref>` in the State now values: [(label, claim text, commit, ref)].
    Any other text, an authored outside fact such as "App Store review pending", is not a claim."""
    out = []
    for label, value in state_now(text):
        for m in CLAIM_RE.finditer(value):
            commit, ref = m.group(1).rstrip(",;:.").lower(), m.group(2).rstrip(".")
            for prefix in ("refs/heads/", "refs/remotes/origin/", "origin/"):
                if ref.startswith(prefix):
                    ref = ref[len(prefix):]
            out.append((label, f"merged {commit} into {ref}", commit, ref))
    return out


def _git_ok(root, *args):
    """Exit status of a read-only git plumbing call (run as GitTree runs git); None if git cannot run."""
    try:
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=60).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _git_out(root, *args):
    try:
        out = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def judge(root, commit, ref, candidate="HEAD", targets=None):
    """('proven' | 'contradiction' | 'unknown', why) for the claim `merged <commit> into <ref>`.
    Proven: the commit is in <ref> (refs/heads or refs/remotes/origin, either one), or in the
    candidate when <ref> is a branch the candidate lands on (`targets`; every ref when None),
    because the candidate carries the page onto that branch. A branch name is never evidence. Only
    cat-file, rev-parse and merge-base --is-ancestor run: nothing refreshes the index or runs a
    filter."""
    if not FULL_SHA_RE.match(commit):
        return "unknown", f"'{commit}' is not a full commit id (40 or 64 hex characters), so it cannot be checked"
    if _git_ok(root, "cat-file", "-e", commit + "^{commit}") != 0:
        return "unknown", f"{commit[:12]} is not in this repository's objects (a shallow clone?)"
    tips = {}
    for full in (f"refs/heads/{ref}", f"refs/remotes/origin/{ref}"):
        tip = _git_out(root, "rev-parse", "--verify", "-q", full + "^{commit}")
        if tip:
            tips[full] = tip
    for full, tip in tips.items():
        if _git_ok(root, "merge-base", "--is-ancestor", commit, tip) == 0:
            return "proven", f"{commit[:12]} is in {full}"
    lands = targets is None or ref in targets
    cand = _git_out(root, "rev-parse", "--verify", "-q", candidate + "^{commit}") if candidate and lands else None
    if cand and _git_ok(root, "merge-base", "--is-ancestor", commit, cand) == 0:
        return "proven", f"{commit[:12]} is in the candidate {cand[:12]}, which carries this page onto {ref}"
    if not tips:
        return "unknown", f"'{ref}' is not a branch here (neither refs/heads/{ref} nor refs/remotes/origin/{ref})"
    if lands and not cand:
        return "unknown", "the candidate commit cannot be read"
    if _git_out(root, "rev-parse", "--is-shallow-repository") != "false":
        return "unknown", "the history is shallow, so the commit's absence cannot be proven"
    held = " nor ".join(f"{k} ({v[:12]})" for k, v in tips.items())
    return "contradiction", f"{commit[:12]} is in neither {held}" + (f" nor the candidate ({cand[:12]})" if cand else "")


def claim_results(tree):
    """[(page, label, claim, result, why)] for the State now claims of every state page in the tree.
    A tree with no repository behind it (no root) has nothing to judge against. The candidate
    counts as evidence only for the repository's protected branches, which it lands on."""
    root = getattr(tree, "root", None)
    if not root:
        return []
    candidate = getattr(tree, "rev", None) or "HEAD"
    targets = config(tree).get("protected_branches") or ["main", "master"]
    targets = set(str(t) for t in targets) if isinstance(targets, list) else {"main", "master"}
    out = []
    for p in sorted(tree.paths):
        m = NAME_RE.match(p[len("docs/"):]) if p.startswith("docs/") else None
        if not (m and m.group(3) == "state"):
            continue
        for label, claim, commit, ref in claims(tree.read(p) or ""):
            result, why = judge(root, commit, ref, candidate, targets)
            out.append((p, label, claim, result, why))
    return out


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
    def __init__(self, root, under=""):
        self.root = root
        self.paths = set()
        for d, dirs, files in os.walk(os.path.join(root, under)):
            dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__")]
            for f in files:
                if os.path.islink(os.path.join(d, f)):
                    continue  # a link's target may be anywhere; the check never reads through one
                self.paths.add(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"))
        # a file git ignores never reaches a commit, so the working-folder check skips it too
        try:
            out = subprocess.run(["git", "-C", root, "check-ignore", "--stdin"], input="\n".join(sorted(self.paths)),
                                 capture_output=True, text=True, timeout=30)
            self.paths -= set(out.stdout.splitlines())
        except (OSError, subprocess.SubprocessError):
            pass

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


def check(tree, base=None, warnings=None):
    """Problems (strings) that keep this candidate off main. [] when the repo has not opted in.
    A State now claim git cannot judge goes to `warnings` (a list, when given) and never fails."""
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
    for p, label, claim, result, why in claim_results(tree):
        if result == "contradiction":
            problems.append(f"{p}: State now '{label}' says '{claim}', and git contradicts it: {why}")
        elif result == "unknown" and warnings is not None:
            warnings.append(f"{p}: State now '{label}' says '{claim}', which git cannot confirm: {why}")
    if base is not None:
        for p in sorted(base.paths):
            if p.startswith("docs/") and p.endswith(".html") and approval_metas(base.read(p)):
                if p not in tree.paths or not approval_metas(tree.read(p)):
                    problems.append(f"{p}: approved on main, and this candidate removes or renames it or "
                                    "its approval; an approved boundary cannot be dropped this way")
    return problems


# ---- the index: derived from the pages at each run, never committed --------------------------------

INDEX_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Docs index</title><link rel="stylesheet" href="keel.css"></head><body><main>
<header class="page"><div class="kicker">Derived by the index command &middot; not committed</div><h1>Docs index</h1></header>
"""
KIND_ORDER = {"state": 0, "reference": 1, "audit": 2, "mockup": 3}


def families(names):
    """{page name: family}. A name's slug is family[-qualifier]; the family is the longest state
    page slug with the same date that the slug starts with, else the shortest such page slug."""
    found = {n: NAME_RE.match(n) for n in names}
    found = {n: m for n, m in found.items() if m}
    states = {(m.group(1), m.group(2)) for m in found.values() if m.group(3) == "state"}
    slugs = {(m.group(1), m.group(2)) for m in found.values()}
    out = {}
    for n, m in found.items():
        date, slug = m.group(1), m.group(2)
        heads = lambda pool: [s for d, s in pool if d == date and (slug == s or slug.startswith(s + "-"))]
        st = heads(states)
        out[n] = max(st, key=len) if st else min(heads(slugs), key=len)
    return out


def legacy_title(path, text):
    """The first Markdown heading, or the HTML <title>, else the file name."""
    if text is not None and path.lower().endswith((".md", ".markdown")):
        m = re.search(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE)
        if m:
            return m.group(1)
    if text is not None and path.lower().endswith((".html", ".htm")):
        title = re.sub(r"\s+", " ", scan(text).title).strip()
        if title:
            return title
    return os.path.basename(path)


def build_index(root):
    """({family: [page]}, {folder: [(path, title)]}) from the working folder as it is now. A page is
    a dict: name, kind, title, boundary state, working, and its State now pairs (state pages)."""
    tree = FsTree(root, under="docs")
    names = sorted(p[len("docs/"):] for p in tree.paths if p.startswith("docs/") and "/" not in p[len("docs/"):])
    groups = {}
    for name, fam in families(names).items():
        text = tree.read("docs/" + name) or ""
        kind = NAME_RE.match(name).group(3)
        groups.setdefault(fam, []).append({
            "name": name, "kind": kind, "title": re.sub(r"\s+", " ", scan(text).title).strip() or name,
            "boundary": boundary_state(name, text)[0], "working": bool(sections(text, "working")),
            "state_now": state_now(text) if kind == "state" else []})
    for pages_ in groups.values():
        pages_.sort(key=lambda g: (KIND_ORDER[g["kind"]], g["name"]))
    globs = [str(g) for g in config(tree).get("docs_legacy") or []]
    legacy = {}
    for p in sorted(tree.paths):
        if p.startswith("docs/") and p != "docs/index.html" and any(fnmatch.fnmatchcase(p, g) for g in globs):
            text = tree.read(p) if p.lower().endswith((".md", ".markdown", ".html", ".htm")) else None
            legacy.setdefault(os.path.dirname(p), []).append((p, legacy_title(p, text)))
    ordered = {f: groups[f] for f in sorted(groups, key=lambda f: (f != "project", f))}
    return ordered, {f: legacy[f] for f in sorted(legacy)}


def index_html(groups, legacy):
    h = html.escape
    rows = []
    for fam, members in groups.items():
        rows.append(f"<h2>{h(fam)}</h2><ul>")
        for g in members:
            tags = f'<span class="tag">{g["kind"]}</span>'
            if g["boundary"] != "none":
                tags += f' <span class="tag {"ok" if g["boundary"] == "approved" else "warn"}">boundary {g["boundary"]}</span>'
            if g["working"]:
                tags += ' <span class="tag warn">working</span>'
            rows.append(f'<li><a href="{h(urllib.parse.quote(g["name"]))}">{h(g["title"])}</a> {tags}')
            if g["state_now"]:
                rows.append('<dl class="state-now">' + "".join(
                    f"<dt>{h(k)}</dt><dd>{h(v)}</dd>" for k, v in g["state_now"]) + "</dl>")
            rows.append("</li>")
        rows.append("</ul>")
    if legacy:
        rows.append('<h2 id="legacy">Legacy</h2><p class="muted">History kept as it is ("docs_legacy" in agentkeel.json).</p>')
        for folder, files in legacy.items():
            rows.append(f"<h3>{h(folder)} <small>({len(files)})</small></h3><ul>")
            for path, title in files:
                href = urllib.parse.quote(os.path.relpath(path, "docs").replace(os.sep, "/"))
                rows.append(f'<li><a href="{h(href)}">{h(title)}</a> <small>{h(os.path.basename(path))}</small></li>')
            rows.append("</ul>")
    return INDEX_HEAD + "\n".join(rows) + "\n</main></body></html>\n"


def index_text(groups, legacy, full=False):
    """The same index as plain text, for an agent to read."""
    lines = []
    for fam, members in groups.items():
        lines.append(fam)
        for g in members:
            tags = ([f"boundary {g['boundary']}"] if g["boundary"] != "none" else []) + (["working"] if g["working"] else [])
            lines.append(f"  {g['kind']:<9} {g['title']}  ({g['name']})" + (f"  [{', '.join(tags)}]" if tags else ""))
            for k, v in g["state_now"]:
                lines.append(f"      {k}: {v}")
    if legacy:
        lines.append(f"legacy ({sum(len(f) for f in legacy.values())} files; \"docs_legacy\" in agentkeel.json)")
        for folder, files in legacy.items():
            lines.append(f"  {folder}/  {len(files)} file(s)")
            if full:
                lines += [f"    {path}  {title}" for path, title in files]
    return "\n".join(lines) + "\n"


def write_index(root, full=False):
    docs = os.path.join(root, "docs")
    if not os.path.isdir(docs):
        print(f"agentkeel index: no docs/ folder in {root}")
        return 2
    groups, legacy = build_index(root)
    out = os.path.join(docs, "index.html")
    if os.path.islink(out):
        os.remove(out)  # never write through a link someone left at the index's name
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(index_html(groups, legacy))
    try:
        ignored = subprocess.run(["git", "-C", root, "check-ignore", "-q", out], capture_output=True,
                                 timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ignored = False
    print("agentkeel index: wrote docs/index.html"
          + ("" if ignored else "\n  note: add docs/index.html to .gitignore; the index is derived and never committed"))
    sys.stdout.write(index_text(groups, legacy, full))
    return 0


# ---- command line (CI runs this file on its own) --------------------------------------------------

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="pages.py", description="Check and index agentkeel HTML docs.")
    sub = ap.add_subparsers(dest="action")
    c = sub.add_parser("check")
    c.add_argument("--rev", help="the candidate commit (default: the working folder)")
    c.add_argument("--base", help="the commit the candidate replaces on main")
    c.add_argument("--root", default=".")
    x = sub.add_parser("context")
    x.add_argument("page")
    i = sub.add_parser("index", help="write docs/index.html and print the index as text")
    i.add_argument("--root", default=".")
    i.add_argument("--full", action="store_true", help="also list every legacy file with its title")
    args = ap.parse_args(argv)
    if args.action == "index":
        return write_index(os.path.abspath(args.root), args.full)
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
    warnings = []
    problems = check(tree, base, warnings)
    for w in warnings:
        print(f"  WARN {w}")
    for p in problems:
        print(f"  FAIL {p}")
    print(f"agentkeel docs check: {'FAIL' if problems else 'PASS'} ({len(problems)} problem(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
