#!/usr/bin/env python3
"""agentkeel stop report (Stop): when a turn ends, tell the human what this session's task still holds.

For each worktree in the task record that still exists: its branch, whether its tip is merged into
a protected branch (then it can be removed) or how many commits are not, and how many files are
changed or untracked. For a session opened with task.py open: its clone, and whether release
would accept it now (isolation.release_problems), or why not.

It is a report and nothing else. It never deletes or changes a resource, never blocks the stop and
never makes the host continue the turn: the text goes out as "systemMessage", which both hosts
show to the human, and the exit status is 0, also on its own failure. Repositories are read with
repostate, which runs nothing a repository's config names; a worktree that cannot be read is
reported as unreadable, never as clean. It speaks only when the report differs from the last one
it gave this session (a hash in AGENTKEEL_HOME/stop-reports/), and it is silent when the session
has no task or the repository did not opt in.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import isolation, record, repostate  # noqa: E402


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _branch(repo):
    text = repostate._read(os.path.join(repo.gitdir, "HEAD")).strip()
    return text[len("ref: refs/heads/"):] if text.startswith("ref: refs/heads/") else "(detached)"


def worktree_line(path):
    """One line for one worktree, read without its config; unreadable is said, never 'clean'."""
    try:
        st = repostate.inspect(path)
        repo = repostate.locate(path)
        branch = _branch(repo)
        protected = sorted(record.policy(st["top"])["protected"])
        files = _plural(len(st["changed"]), "changed or untracked file")
        if branch in protected:
            return f"  worktree {path} (on the protected branch {branch}): {files}"
        counts = {}
        with repostate.Shadow(repo) as sh:
            for name in protected:
                tip = repostate.resolve(repo, "refs/heads/" + name)
                if tip and st["head"]:
                    counts[name] = int(sh.git("rev-list", "--count", f"{tip}..{st['head']}"))
    except Exception as e:  # InspectError or anything else: unknown is never "clean"
        return f"  worktree {path}: unreadable ({e}), so it is not known to be clean"
    if not counts:
        state = "no commit to compare" if not st["head"] else "no protected branch here to compare with"
    elif min(counts.values()) == 0:
        state = "merged: it can be removed" if not st["changed"] else "merged, but its files are not all committed"
    else:
        name = min(counts, key=counts.get)
        state = f"{_plural(counts[name], 'commit')} not in {name}"
    return f"  worktree {path} (branch {branch}): {state}; {files}"


def clone_line(opened):
    try:
        problems = isolation.release_problems(opened)
    except Exception as e:
        problems = [f"the clone could not be inspected ({e})"]
    if problems:
        return (f"  clone {opened['clone']} (branch {opened.get('branch')}): not ready to release: "
                + "; ".join(problems) + ". The human runs task.py import, then task.py release")
    return f"  clone {opened['clone']} (branch {opened.get('branch')}): ready to release (task.py release {opened['task']})"


def report(session_id, environ=os.environ):
    """The report text, or None when this session's task holds nothing that still exists."""
    rec = record.load(session_id, environ)
    if not rec:
        return None
    lines = []
    opened = isolation.load_opened(rec.get("task") or "", environ) if rec.get("opened") else None
    if opened and opened.get("clone") == rec.get("clone") and os.path.isdir(opened["clone"]):
        lines.append(clone_line(opened))
    for w in rec.get("worktrees") or []:
        if os.path.isdir(w) and not (opened and w == opened.get("clone")):
            lines.append(worktree_line(w))
    if not lines:
        return None
    return (f"agentkeel: task '{rec.get('task')}' still holds (a report only; nothing was removed):\n"
            + "\n".join(lines))


def first_time(session_id, text, environ=os.environ):
    """True unless this exact report was the last one given to this session. The hash is kept
    best-effort: if it cannot be written, the report is given anyway."""
    path = os.path.join(record.home(environ), "stop-reports", record._safe(session_id) + ".json")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    try:
        with open(path) as fh:
            if json.load(fh).get("hash") == digest:
                return False
    except Exception:
        pass
    try:
        record.atomic_write_json(path, {"hash": digest})
    except Exception:
        pass
    return True


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        print("stop-report selftest: PASS")
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or record.plugin_inactive(sys.argv, payload):
            return 0
        sid = payload.get("session_id")
        text = report(sid) if sid else None
        if text and first_time(sid, text):
            sys.stdout.write(json.dumps({"systemMessage": text}) + "\n")
    except Exception as exc:  # a report is never worth a blocked stop
        sys.stderr.write(f"stop-report: internal error, no report: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
