#!/usr/bin/env python3
"""agentkeel tier guard (PreToolUse, matcher Write|Edit|Bash).

The tier is state, not a sentence. This hook reads .claude/state/agentkeel-tier.json at the top
of the worktree the call runs in and applies what the declared tier bought:

  no declaration, or expired  ->  no writes at all (declare with hooks/tier.sh)
  small                       ->  anything, in the tree you are in
  medium                      ->  writes only on a branch that is not main/master
  large                       ->  as medium, and no edit outside docs/ until
                                  docs/specs/<slug>-spec.md carries `status: approved`

What counts as a write here: a Write or Edit tool call, and a Bash command containing
`git commit`. Other shell writes (sed -i, redirects) are invisible to this hook and the README
says so. Edits under docs/ and .claude/ are always allowed: specs and plans must be writable
before the tier can be satisfied.

Exit 0 allows. Exit 2 blocks and the message on stderr is what the model reads. A payload this
hook cannot parse allows: a broken guard must never stop work on its own.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

MAIN_BRANCHES = {"main", "master"}
ALWAYS_ALLOWED_PREFIXES = ("docs/", ".claude/")
GIT_COMMIT_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
STATUS_RE = re.compile(r"^\s*status\s*:\s*([A-Za-z-]+)\s*(?:#.*)?$", re.MULTILINE)  # inline comments allowed


def git(cwd, *args):
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def toplevel(cwd):
    return git(cwd, "rev-parse", "--show-toplevel")


def branch_of(cwd):
    # symbolic-ref works on an unborn branch (fresh repo, no commits); rev-parse covers detached HEAD
    return git(cwd, "symbolic-ref", "--short", "HEAD") or git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or ""


def load_state(root):
    path = os.path.join(root, ".claude", "state", "agentkeel-tier.json")
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def spec_status(root, slug):
    path = os.path.join(root, "docs", "specs", f"{slug}-spec.md")
    try:
        with open(path, encoding="utf-8") as fh:
            head = fh.read(4000)
    except Exception:
        return None, path
    m = STATUS_RE.search(head)
    return (m.group(1).lower() if m else "missing"), path


def block(msg):
    sys.stderr.write("TIER GUARD: " + msg.rstrip() + "\n")
    return 2


def decide(payload, environ=os.environ):
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    if tool in ("Write", "Edit"):
        target = tool_input.get("file_path")
        if not target:
            return 0
        target = os.path.realpath(os.path.join(cwd, os.path.expanduser(str(target))))
    elif tool == "Bash":
        command = str(tool_input.get("command", ""))
        if not GIT_COMMIT_RE.search(command):
            return 0
        target = None
    else:
        return 0

    root = toplevel(cwd)
    if not root:
        return 0  # not a repository: nothing to price
    root = os.path.realpath(root)

    if target is not None:
        if not (target == root or target.startswith(root + os.sep)):
            return 0  # outside this worktree: write-path-guard's decision, not this one
        rel = os.path.relpath(target, root).replace(os.sep, "/")
        if rel.startswith(ALWAYS_ALLOWED_PREFIXES):
            return 0

    state = load_state(root)
    if not state or state.get("tier") not in ("small", "medium", "large"):
        return block(
            "no tier declared for this worktree.\n\n"
            "Declare it first, in one command, then retry:\n"
            "  .claude/hooks/tier.sh small|medium|large <slug>\n\n"
            "small: a direct ask, one file, under about an hour. medium: a feature spanning files\n"
            "(needs a branch). large: another session executes, or a spec was asked for (needs an\n"
            "approved spec). When in doubt pick the smaller tier; upgrading later is cheap."
        )
    if int(state.get("expires_at", 0)) < time.time():
        return block(
            f"the {state.get('tier')} declaration for '{state.get('slug')}' has expired.\n"
            "Re-declare with .claude/hooks/tier.sh so today's work is priced today."
        )

    tier = state["tier"]
    if tier == "small":
        return 0

    branch = branch_of(cwd)
    if branch in MAIN_BRANCHES or branch == "HEAD":
        return block(
            f"tier {tier} was declared for '{state.get('slug')}' but this tree is on '{branch or '?'}'.\n"
            "medium and large work happens on a branch, usually in its own worktree:\n"
            f"  git worktree add ../<repo>-{state.get('slug')} -b feat/{state.get('slug')}\n"
            "then declare the tier again inside that worktree. If this really is a one-file fix,\n"
            "declare small instead; that is recorded."
        )

    if tier == "large":
        status, path = spec_status(root, state.get("slug", ""))
        if status != "approved":
            why = "does not exist" if status is None else f"has status '{status}'"
            return block(
                f"tier large requires an approved spec before any edit outside docs/.\n"
                f"{os.path.relpath(path, root)} {why}.\n"
                "Write the spec from templates/spec.md, get the human's ruling, set\n"
                "`status: approved` with `approved_by` and `approved_on` in its frontmatter,\n"
                "and append the D-NNN entry. Edits under docs/ are allowed meanwhile."
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
    except Exception as exc:  # never block on our own failure
        sys.stderr.write(f"tier-guard: internal error, allowing: {exc}\n")
        return 0


def selftest():
    here = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.realpath(os.path.join(tmp, "repo"))
        os.makedirs(os.path.join(repo, "src"))
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "init"],
                       check=True, env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})

        def run(payload, expect):
            out = subprocess.run([sys.executable, here], input=json.dumps(payload), text=True,
                                 capture_output=True)
            ok = out.returncode == expect
            print(("PASS" if ok else "FAIL"), payload["tool_name"], payload["tool_input"], "->", out.returncode)
            return ok

        write = {"tool_name": "Write", "cwd": repo, "tool_input": {"file_path": os.path.join(repo, "src", "a.py")}}
        doc = {"tool_name": "Write", "cwd": repo, "tool_input": {"file_path": os.path.join(repo, "docs", "x.md")}}
        results = [run(write, 2), run(doc, 0)]
        state_dir = os.path.join(repo, ".claude", "state")
        os.makedirs(state_dir)
        now = int(time.time())
        with open(os.path.join(state_dir, "agentkeel-tier.json"), "w") as fh:
            json.dump({"tier": "small", "slug": "x", "expires_at": now + 3600}, fh)
        results.append(run(write, 0))
        with open(os.path.join(state_dir, "agentkeel-tier.json"), "w") as fh:
            json.dump({"tier": "medium", "slug": "x", "expires_at": now + 3600}, fh)
        results.append(run(write, 2))  # medium on main
        results.append(run({"tool_name": "Bash", "cwd": repo, "tool_input": {"command": "ls"}}, 0))
        results.append(run({"tool_name": "Bash", "cwd": repo, "tool_input": {"command": "git commit -m x"}}, 2))
    print("tier-guard selftest:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
