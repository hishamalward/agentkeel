#!/usr/bin/env python3
"""agentkeel write-path guard (PreToolUse, matcher Bash|Write|Edit).

Invariant 1, every write is bounded before it happens, with teeth on the three writes that hurt
most:

  1. A `git commit` while on main/master is refused unless the declared tier is small (the one
     tier that permits explicit-path commits in the tree you are in). A `git push` that would
     move main/master is refused unless AGENTKEEL_ALLOW_PUSH_MAIN=1, so the transcript shows
     the human asked for it.
  2. Destructive git (push --force, reset --hard, checkout/restore of the whole tree, clean -f,
     branch -D, stash drop/clear) is refused unless AGENTKEEL_ALLOW_DESTRUCTIVE=1.
  3. A Write or Edit outside the git top-level of the directory the call runs in is refused.
     Temp directories are allowed (scratch is not a write path). Extra roots can be granted with
     AGENTKEEL_EXTRA_WRITE_ROOTS=/a:/b.

Every override used is echoed to stderr, so it is visible in the transcript.

What this cannot see: shell writes that are not git (sed -i, rm, redirects) and commands that cd
into a different repository first. The README says so.

Exit 0 allows; exit 2 blocks with the reason on stderr; an unparseable payload allows.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

MAIN_BRANCHES = {"main", "master"}
COMMIT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
PUSH_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b([^|;&]*)")
DESTRUCTIVE = [
    (re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b[^|;&]*\s(?:--force(?:-with-lease)?|-f)\b"), "force push"),
    (re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?reset\s+(?:\S+\s+)*--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?checkout\s+(?:--\s+)?\.(?:\s|$)"), "git checkout of the whole tree"),
    (re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?restore\s+(?:--\s+)?\.(?:\s|$)"), "git restore of the whole tree"),
    (re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?clean\s+-[A-Za-z]*f"), "git clean -f"),
    (re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?branch\s+(?:-D\b|--delete\s+--force\b|-d\s+-f\b)"), "git branch -D"),
    (re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?stash\s+(?:drop|clear)\b"), "git stash drop/clear"),
]


def git(cwd, *args):
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def block(msg):
    sys.stderr.write("WRITE PATH GUARD: " + msg.rstrip() + "\n")
    return 2


def note(msg):
    sys.stderr.write("WRITE PATH GUARD: " + msg.rstrip() + "\n")


def tier_of(root):
    try:
        with open(os.path.join(root, ".claude", "state", "agentkeel-tier.json")) as fh:
            state = json.load(fh)
        if int(state.get("expires_at", 0)) < time.time():
            return None
        return state.get("tier")
    except Exception:
        return None


def push_targets_main(rest, branch):
    tokens = [t for t in rest.split() if not t.startswith("-")]
    # tokens: [remote] [refspec...]
    refspecs = tokens[1:] if tokens else []
    if not refspecs:
        return branch in MAIN_BRANCHES
    for spec in refspecs:
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        dst = dst.replace("refs/heads/", "")
        if dst in MAIN_BRANCHES:
            return True
    return False


def temp_roots():
    roots = {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders", "/private/var/folders"}
    for var in ("TMPDIR", "TMP", "TEMP"):
        if os.environ.get(var):
            roots.add(os.environ[var])
    return {os.path.realpath(r) for r in roots}


def under(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def decide(payload, environ=os.environ):
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        if "git" not in command:
            return 0
        for pattern, name in DESTRUCTIVE:
            if pattern.search(command):
                if environ.get("AGENTKEEL_ALLOW_DESTRUCTIVE") == "1":
                    note(f"override AGENTKEEL_ALLOW_DESTRUCTIVE=1 used for: {name}")
                    break
                return block(
                    f"refusing {name}.\n"
                    "This discards work that may not be yours, in a tree other agents may share.\n"
                    "If the human asked for exactly this, run it with AGENTKEEL_ALLOW_DESTRUCTIVE=1 so\n"
                    "the override is visible in the transcript."
                )
        branch = git(cwd, "symbolic-ref", "--short", "HEAD") or git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or ""
        root = git(cwd, "rev-parse", "--show-toplevel") or cwd
        if COMMIT_RE.search(command) and branch in MAIN_BRANCHES:
            if tier_of(root) != "small":
                return block(
                    f"refusing a commit on '{branch}'.\n"
                    "Only work declared small commits in the main tree, with explicit paths\n"
                    "(git commit -m '...' -- <paths>). Medium and large work commits on a branch\n"
                    "and reaches main by a fast-forward merge the human asked for."
                )
        m = PUSH_RE.search(command)
        if m and push_targets_main(m.group(1), branch):
            if environ.get("AGENTKEEL_ALLOW_PUSH_MAIN") == "1":
                note("override AGENTKEEL_ALLOW_PUSH_MAIN=1 used: pushing main")
            else:
                return block(
                    "refusing a push that moves main.\n"
                    "Finishing the work and shipping it are two decisions; the second is the human's.\n"
                    "When asked, run it with AGENTKEEL_ALLOW_PUSH_MAIN=1 so the override is on record."
                )
        return 0

    if tool in ("Write", "Edit"):
        target = tool_input.get("file_path")
        if not target:
            return 0
        target = os.path.realpath(os.path.join(cwd, os.path.expanduser(str(target))))
        allowed = set()
        root = git(cwd, "rev-parse", "--show-toplevel")
        allowed.add(os.path.realpath(root if root else cwd))
        if environ.get("CLAUDE_PROJECT_DIR"):
            allowed.add(os.path.realpath(environ["CLAUDE_PROJECT_DIR"]))
        allowed |= temp_roots()
        extra = [p for p in environ.get("AGENTKEEL_EXTRA_WRITE_ROOTS", "").split(os.pathsep) if p]
        for a in allowed:
            if under(target, a):
                return 0
        for e in extra:
            if under(target, os.path.realpath(os.path.expanduser(e))):
                note(f"override AGENTKEEL_EXTRA_WRITE_ROOTS used for {target}")
                return 0
        return block(
            f"refusing to write outside this worktree: {target}\n"
            f"Allowed: {os.path.realpath(root) if root else cwd} and temp directories.\n"
            "Never edit outside your worktree; if a path outside it is legitimately yours, grant\n"
            "it with AGENTKEEL_EXTRA_WRITE_ROOTS=/that/path so the grant is on record."
        )
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        return selftest()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except Exception:
        return 0
    try:
        return decide(payload)
    except Exception as exc:
        sys.stderr.write(f"write-path-guard: internal error, allowing: {exc}\n")
        return 0


def selftest():
    here = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.realpath(os.path.join(tmp, "repo"))
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)

        def run(payload, expect, env=None):
            out = subprocess.run([sys.executable, here], input=json.dumps(payload), text=True,
                                 capture_output=True, env={**os.environ, **(env or {})})
            ok = out.returncode == expect
            print(("PASS" if ok else "FAIL"), payload["tool_input"], "->", out.returncode)
            return ok

        bash = lambda c: {"tool_name": "Bash", "cwd": repo, "tool_input": {"command": c}}
        results = [
            run(bash("git commit -m x"), 2),
            run(bash("git status"), 0),
            run(bash("git push --force origin feat"), 2),
            run(bash("git push --force origin feat"), 0, {"AGENTKEEL_ALLOW_DESTRUCTIVE": "1"}),
            run(bash("git push origin main"), 2),
            run({"tool_name": "Edit", "cwd": repo, "tool_input": {"file_path": "/etc/hosts"}}, 2),
            run({"tool_name": "Write", "cwd": repo, "tool_input": {"file_path": os.path.join(repo, "a.py")}}, 0),
        ]
    print("write-path-guard selftest:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
