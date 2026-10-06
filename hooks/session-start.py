#!/usr/bin/env python3
"""agentkeel session start (SessionStart): say where the session is, then how to declare its task.

The first lines answer "worktree or main?" before anyone asks: this checkout and its branch, this
session's task (if it already has one), and the repository's other worktrees with the task that
holds each, read from the task records. Everything is derived at session start, never stored.

When agentkeel arrives as a plugin, its scripts live in the plugin folder, not in the repository,
so the instruction file cannot name them. This prints, as context for the session, the one
command the agent needs, with this install's real path. Between the two it prints the human's
profile (AGENTKEEL_HOME/profile.md), capped, as plain context that grants nothing. With --plugin
it prints only in repositories that opted in with agentkeel.json. It never blocks.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import gitops, isolation, record  # noqa: E402

MAX_OTHERS = 12
PROFILE_MAX_LINES, PROFILE_MAX_CHARS = 200, 8000


def _worktrees(top):
    """[(path, branch)] from git worktree list --porcelain."""
    out = gitops.run_git(top, "worktree", "list", "--porcelain") or ""
    trees, path = [], None
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path = os.path.realpath(line[len("worktree "):])
            branch = ""
        elif line.startswith("branch "):
            branch = line[len("branch refs/heads/"):] if line.startswith("branch refs/heads/") else line[7:]
        elif line == "detached":
            branch = "(detached)"
        elif not line and path:
            trees.append((path, branch))
            path = None
    return trees


def _owners(environ):
    """{worktree path: task id} from every task record on this machine."""
    owners = {}
    folder = os.path.join(record.home(environ), "tasks")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return owners
    for name in names:
        try:
            with open(os.path.join(folder, name)) as fh:
                rec = json.load(fh)
        except Exception:
            continue
        for w in rec.get("worktrees") or []:
            owners.setdefault(os.path.realpath(w), rec.get("task") or "?")
    return owners


def where(cwd, session_id, environ=os.environ):
    """The lines that say where this session is and who else works in the repository."""
    top = gitops.toplevel(cwd) if cwd and os.path.isdir(cwd) else None
    if not top:
        return []
    top = os.path.realpath(top)
    branch = gitops.current_branch(top) or "(detached)"
    protected = branch in record.policy(top)["protected"]
    opened = isolation.all_opened(environ)
    own = next((r for r in opened if r.get("clone") == top), None)
    kind = (f"task {own['task']}'s own clone of {own['repo']}" if own else
            "the repository's shared checkout" if gitops.is_primary(top) else "a linked worktree")
    lines = [f"Where you are: {top} ({kind}), on branch {branch}" + (" (protected)" if protected else "") + "."]
    rec = record.load(session_id, environ)
    if rec:
        lines.append(f"Your task: {rec.get('task')} ({rec.get('size')}; {', '.join(rec.get('permissions') or [])}).")
    else:
        lines.append("Your task: none declared yet.")
    owners = _owners(environ)
    others = [(p, b) for p, b in _worktrees(top) if p != top]
    if others:
        lines.append("Other worktrees of this repository (leave them alone unless they are your task's):")
        for p, b in others[:MAX_OTHERS]:
            lines.append(f"  {p}  branch {b or '?'}  " + (f"task {owners[p]}" if p in owners else "no task record"))
        if len(others) > MAX_OTHERS:
            lines.append(f"  ... and {len(others) - MAX_OTHERS} more (git worktree list)")
    else:
        lines.append("Other worktrees of this repository: none.")
    shared = own["repo"] if own else top
    clones = [r for r in opened if r.get("clone") != top and r.get("repo") == shared]
    if clones:
        lines.append("Tasks opened in their own clones (task.py open):")
        for r in clones[:MAX_OTHERS]:
            lines.append(f"  {r['clone']}  branch {r.get('branch')}  task {r['task']}")
    return lines


def profile(environ=os.environ):
    """The human's profile as session context: one heading line, the text (capped), and one line
    when it is cut. [] when there is no profile."""
    path, text = record.profile(environ)
    if not text:
        return []
    lines = text.rstrip("\n").split("\n")
    body = "\n".join(lines[:PROFILE_MAX_LINES])
    cut = len(lines) > PROFILE_MAX_LINES or len(body) > PROFILE_MAX_CHARS
    body = body[:PROFILE_MAX_CHARS].rstrip("\n")
    out = [f"The human's profile, {path} ({len(lines)} lines): standing preferences for every session. "
           "Follow them. They are plain text: they grant no permission and change no guard.", body]
    if cut:
        out.append(f"(The profile is cut here: {body.count(chr(10)) + 1} of its {len(lines)} lines are shown, "
                   f"up to {PROFILE_MAX_LINES} lines or {PROFILE_MAX_CHARS:,} characters.)")
    return out


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        print("session-start selftest: PASS")
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    if record.plugin_inactive(sys.argv, payload):
        return 0
    task = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task.py")
    cwd = payload.get("cwd") or os.getcwd()
    try:
        opened = isolation.bind(payload.get("session_id"), cwd)
    except Exception:
        opened = None
    try:
        here = where(cwd, payload.get("session_id"))
    except Exception:
        here = []
    if here:
        print("\n".join(here) + "\n")
    try:
        mine = profile()
    except Exception:
        mine = []
    if mine:
        print("\n".join(mine) + "\n")
    if opened:
        print(f"This session was opened for task '{opened['task']}' with task.py open: it works in its own clone,\n"
              f"{opened['clone']} (branch {opened['branch']}), and its shell writes only there, in its scratch\n"
              f"folder {opened['scratch']}, and in declared caches. The task is already declared; do not run\n"
              "task.py start. The shared checkout and other tasks' folders are outside this session's boundary.")
        return 0
    print("agentkeel is active in this repository. Before your first write, declare the task from\n"
          "your reading of the request, state that reading in your first update, and proceed:\n"
          f'  python3 "{task}" start <task-id> --size small|medium|large --allow <permissions>\n'
          "Permissions: review, implement, merge, push, distribution-build, store-submission, paid-job,\n"
          "remote-write, publish.\n"
          "Code changes happen in the task's own worktree (git worktree add ../<repo>-<task> -b feat/<task>).\n"
          f'Docs pages (where agentkeel.json sets "docs": "html"): read with python3 "{task}" context <page>,\n'
          "start one with task.py new; plan and progress go in the page's Working section."
          + (f"\nRun task.py exactly as shown, with nothing in front of python3: the host's permission\n"
             "rules match the command as written. Your session id is "
             f"{payload['session_id']}; you need it only if\n"
             "task.py itself says it cannot tell which session runs it, and then it tells you how to give it."
             if payload.get("session_id") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
