"""Validation for persistent, free-form HTML task checkpoints."""
import hashlib
import os
from html.parser import HTMLParser

from . import evidence


class _Content(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open = []
        self.tags = set()
        self.content = {"title": "", "body": ""}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self.tags.add(tag)
        self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.tags.add(tag.lower())

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.open:
            del self.open[len(self.open) - 1 - self.open[::-1].index(tag):]

    def handle_data(self, data):
        for tag in ("title", "body"):
            if tag in self.open:
                self.content[tag] += data


def _inside(path, roots):
    for root in roots:
        root = os.path.realpath(os.path.expanduser(str(root)))
        try:
            if os.path.commonpath((path, root)) == root:
                return True
        except ValueError:
            pass
    return False


def _code(rec):
    if rec.get("report_root"):
        root = os.path.dirname(rec["report_root"])
        return {root: evidence.code_state(root)[1]}
    return {os.path.realpath(path): list(state) if state else None
            for path in rec.get("worktrees") or []
            for state in [evidence.code_state(path)]}


def report_path(worktree, value):
    root = os.path.join(os.path.realpath(worktree), "doc")
    path = os.path.realpath(os.path.join(worktree, os.path.expanduser(value)))
    if os.path.realpath(root) != root or not path.startswith(root + os.sep):
        raise ValueError("HTML pages must be inside the task worktree's root-level doc folder")
    if not path.lower().endswith((".html", ".htm")):
        raise ValueError("task pages must name HTML files")
    return path


def _read(rec):
    path = rec.get("deliverable")
    if not isinstance(path, str) or not path:
        return None, None, ["no HTML deliverable is declared"]
    path = os.path.realpath(os.path.expanduser(path))
    roots = rec.get("write_roots") or []
    if not os.path.isabs(str(rec.get("deliverable"))) or not _inside(path, roots):
        return path, None, ["the deliverable must be inside a declared write root"]
    if rec.get("report_root"):
        try:
            report_path(os.path.dirname(rec["report_root"]), path)
        except ValueError as exc:
            return path, None, [str(exc)]
    elif any(_inside(path, [w]) for w in rec.get("worktrees") or []):
        return path, None, ["the deliverable must be outside disposable worktrees"]
    try:
        if not os.path.isfile(path):
            return path, None, ["the deliverable is missing or is not a regular file"]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if not text.strip():
            return path, None, ["the deliverable is empty"]
        parser = _Content()
        parser.feed(text)
        parser.close()
    except (OSError, UnicodeError, ValueError) as exc:
        return path, None, [f"the deliverable cannot be read ({exc})"]
    missing = [tag for tag in ("html", "title", "body") if tag not in parser.tags]
    if missing:
        return path, text, ["the deliverable needs real html, title and body tags (missing " + ", ".join(missing) + ")"]
    if not parser.content["title"].strip() or not parser.content["body"].strip():
        return path, text, ["the deliverable needs nonempty title and body content"]
    return path, text, []


def checkpoint(rec):
    """Read the current deliverable and code snapshot for a human handoff."""
    path, text, _ = _read(rec)
    current = {**rec, "html_checkpoint": None}
    issues = problems(current, require_fresh=not rec.get("report_root"))
    try:
        mtime = os.stat(path).st_mtime if path and text is not None else None
    except OSError:
        mtime = None
    activity = [float(rec.get("declared_at") or 0), float(rec.get("outcome_at") or 0),
                float(rec.get("code_changed_at") or 0)]
    activity.extend(float(e.get("at") or 0) for e in rec.get("evidence") or [] if isinstance(e, dict))
    return {"path": path, "mtime": mtime, "activity_at": max(activity),
            "digest": hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None,
            "spec_digest": _spec_digest(rec),
            "code": _code(rec), "valid": not issues, "problems": issues}


def _spec_digest(rec):
    if not rec.get("spec"):
        return None
    _, text, issues = _read({**rec, "deliverable": rec["spec"]})
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text and not issues else None


def problems(rec, require_fresh=True):
    """Return actionable issues without imposing a page grammar on the HTML."""
    path, text, issues = _read(rec)
    if rec.get("spec"):
        _, _, spec_issues = _read({**rec, "deliverable": rec["spec"]})
        issues += ["specification: " + issue for issue in spec_issues]
    if issues or not require_fresh:
        return issues
    if rec.get("report_root"):
        if rec.get("lifecycle") == "complete":
            return []
        saved = rec.get("html_checkpoint") or {}
        code = _code(rec)
        if (not saved.get("valid") or not all(code.values()) or saved.get("code") != code
                or saved.get("digest") != hashlib.sha256(text.encode("utf-8")).hexdigest()
                or saved.get("spec_digest") != _spec_digest(rec)):
            return ["run handoff after reviewing the current work and task pages"]
        return []
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return ["the deliverable is missing or cannot be inspected"]
    latest = max([float(rec.get("declared_at") or 0), float(rec.get("outcome_at") or 0),
                  float(rec.get("code_changed_at") or 0)]
                 + [float(e.get("at") or 0) for e in rec.get("evidence") or [] if isinstance(e, dict)])
    if mtime < latest:
        issues.append("the deliverable is stale; update it after the latest task evidence")
    saved = rec.get("html_checkpoint")
    if saved and saved.get("digest") == hashlib.sha256(text.encode("utf-8")).hexdigest():
        checkpoint_activity = float(saved.get("activity_at", saved.get("mtime") or 0))
        if latest > checkpoint_activity:
            issues.append("the deliverable content has not changed since the latest task evidence")
        elif _code(rec) != saved.get("code"):
            issues.append("the code changed since the last HTML handoff checkpoint")
    return issues
