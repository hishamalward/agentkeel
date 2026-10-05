#!/usr/bin/env python3
"""agentkeel task: declare what this session's task is, before the first write.

  task.py start <task-id> --size small|medium|large --allow <permissions>
                [--write-root PATH]... [--worktree PATH]... [--resource NAME]...
  task.py show                     the record for this session
  task.py verify -- <command...>   run a check and record its exit code against HEAD
  task.py end                      drop the record (the task is finished or abandoned)
  task.py approve <task-id>        HUMAN ONLY: approve docs/specs/<task-id>-spec.md

Permissions (comma separated, any combination): review, implement, merge, push,
distribution-build, store-submission, paid-job. Size never grants a permission: they are
separate answers to separate questions. "merge and push" in the human's request means
--allow implement,merge,push; a distribution build is never implied by shipping.

The record is bound to this session (CLAUDE_CODE_SESSION_ID in Claude Code, CODEX_THREAD_ID in
Codex, AGENTKEEL_SESSION_ID given inline for other hosts or when both are set) and stored in
AGENTKEEL_HOME (default ~/.agentkeel). A second session cannot use it: the guard refuses an
AGENTKEEL_SESSION_ID that is not the caller's own id.
`approve` is refused when an agent runs it through its shell tool; the human runs it in a
terminal of their own, outside the agent session.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import gitops, record  # noqa: E402

TASK_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def fail(msg, code=2):
    sys.stderr.write("agentkeel: " + msg.rstrip() + "\n")
    return code


def realpath(p, cwd):
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(p)))


def start(args, environ):
    session = record.session_from_env(environ)
    if not session:
        return fail("no session id: cannot tell which session runs this. Run it from the agent\n"
                    "session (Claude Code sets CLAUDE_CODE_SESSION_ID, Codex sets CODEX_THREAD_ID). If both are set and the\n"
                    "running agent cannot be found, give your own id inline, as printed at session start:\n"
                    "  AGENTKEEL_SESSION_ID=<id> python3 task.py ...")
    if not args.task or set(args.task) - TASK_ID_CHARS:
        return fail("task id must be kebab-case (a-z, 0-9, -), e.g. json-flag")
    perms = [p.strip() for p in (args.allow or "").split(",") if p.strip()]
    unknown = [p for p in perms if p not in record.PERMISSIONS]
    if not perms or unknown:
        return fail(f"--allow needs one or more of: {', '.join(record.PERMISSIONS)}"
                    + (f" (unknown: {', '.join(unknown)})" if unknown else ""))
    cwd = os.getcwd()
    top = gitops.toplevel(cwd)
    shared = bool(top) and gitops.is_primary(top)
    worktrees = [os.path.realpath(top)] if top and not shared else []
    worktrees += [realpath(p, cwd) for p in args.worktree or []]
    roots = [realpath(p, cwd) for p in args.write_root or []]
    too_wide = {"/", os.path.realpath(os.path.expanduser("~")), record.home(environ)}
    for r in roots:
        if r in too_wide or r.startswith(record.home(environ) + os.sep):
            return fail(f"--write-root {r} is too wide or is agentkeel's own state")
        inside = gitops.toplevel(r if os.path.isdir(r) else os.path.dirname(r) or "/")
        if inside:
            return fail(f"--write-root {r} is inside the repository {inside}.\n"
                        "Write roots are report folders outside any repository. To change files in a\n"
                        "repository, use --allow implement in the task's own worktree.")
    if "review" in perms and "implement" not in perms and not roots:
        sys.stderr.write("agentkeel: note: a review task writes only to its --write-root folders; none given,\n"
                         "so every write will be refused.\n")

    prev = record.load(session, environ)
    now = int(time.time())
    rec = {"version": 1, "task": args.task, "session_id": session, "size": args.size,
           "permissions": sorted(set(perms)), "worktrees": [], "write_roots": [],
           "resources": sorted(set(args.resource or [])), "declared_at": now, "evidence": [],
           "history": []}
    if prev and prev.get("task") == args.task:
        rec["history"] = (prev.get("history") or []) + [
            {k: prev.get(k) for k in ("size", "permissions", "declared_at")}]
        rec["worktrees"] = prev.get("worktrees") or []
        rec["write_roots"] = prev.get("write_roots") or []
        rec["resources"] = sorted(set(rec["resources"]) | set(prev.get("resources") or []))
        rec["evidence"] = prev.get("evidence") or []
        widened = sorted(set(perms) - set(prev.get("permissions") or []))
        if widened:
            sys.stderr.write(f"agentkeel: permissions widened for '{args.task}': +{', +'.join(widened)}.\n"
                             "This is your reading of the human's request; say so in your next update.\n")
        if prev.get("size") != args.size:
            sys.stderr.write(f"agentkeel: re-declared size {prev.get('size')} -> {args.size}. "
                             "A task never grows on its own; the human decides re-scoping.\n")
    for w in worktrees:
        if w not in rec["worktrees"]:
            rec["worktrees"].append(w)
    for r in roots:
        if r not in rec["write_roots"]:
            rec["write_roots"].append(r)
    import tempfile
    rec["scratch"] = os.path.join(os.path.realpath(tempfile.gettempdir()), "agentkeel-scratch",
                                  record._safe(session))
    os.makedirs(rec["scratch"], exist_ok=True)
    path = record.save(rec, environ)
    print(f"agentkeel: task '{args.task}', size {args.size}, permissions {', '.join(rec['permissions'])}")
    print(f"  worktrees: {', '.join(rec['worktrees']) or '(none)'}")
    if rec["write_roots"]:
        print(f"  write roots: {', '.join(rec['write_roots'])}")
    print(f"  scratch: {rec['scratch']}")
    if shared and "implement" in rec["permissions"]:
        print(f"  note: {top} is the shared checkout. Code edits happen in this task's own worktree:\n"
              f"    git worktree add ../{os.path.basename(top)}-{args.task} -b feat/{args.task}")
    print(f"  record: {path}")
    return 0


def show(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        print("agentkeel: no task declared for this session")
        return 1
    print(json.dumps(rec, indent=2, sort_keys=True))
    return 0


def verify(args, environ):
    session = record.session_from_env(environ)
    rec = record.load(session, environ)
    if not rec:
        return fail("no task declared for this session; declare one with task.py start")
    cmd = list(args.cmd or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        return fail("usage: task.py verify -- <command...>")
    started = time.time()
    code = subprocess.call(cmd)
    head = gitops.run_git(os.getcwd(), "rev-parse", "HEAD")
    dirty = bool(gitops.run_git(os.getcwd(), "status", "--porcelain"))
    rec["evidence"] = (rec.get("evidence") or [])[-19:] + [{
        "command": " ".join(cmd), "exit": code, "head": head, "dirty_tree": dirty,
        "at": int(started), "seconds": round(time.time() - started, 1)}]
    record.save(rec, environ)
    sys.stderr.write(f"agentkeel: recorded `{' '.join(cmd)}` exit {code} at {head[:12] if head else '?'}"
                     f"{' (uncommitted changes present)' if dirty else ''}\n")
    return code


def end(args, environ):
    session = record.session_from_env(environ)
    rec = record.load(session, environ)
    if not rec:
        print("agentkeel: no task declared for this session")
        return 0
    os.remove(record.record_path(session, environ))
    print(f"agentkeel: task '{rec.get('task')}' ended. It owned:")
    for w in rec.get("worktrees") or []:
        print(f"  worktree {w}")
    for r in rec.get("write_roots") or []:
        print(f"  write root {r}")
    for r in rec.get("resources") or []:
        print(f"  resource {r}")
    return 0


def approve(args, environ):
    cwd = os.getcwd()
    top = gitops.toplevel(cwd) or cwd
    path = args.target if args.target.endswith(".md") else record.spec_path(top, args.target)
    path = realpath(path, cwd)
    text = record.read(path)
    if text is None:
        return fail(f"no spec at {path}")
    fm = record.frontmatter(text)
    if fm is None:
        return fail(f"{path} has no frontmatter block at the top; add one from templates/spec.md")
    who = gitops.run_git(cwd, "config", "user.name") or os.environ.get("USER", "")
    today = datetime.date.today().isoformat()
    lines = text.split("\n")
    end_idx = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    wanted = {"status": "approved", "approved_by": who, "approved_on": today}
    seen = set()
    for i in range(1, end_idx):
        key = lines[i].split(":", 1)[0].strip().lower()
        if key in wanted:
            lines[i] = f"{key}: {wanted[key]}"
            seen.add(key)
    missing = [f"{k}: {v}" for k, v in wanted.items() if k not in seen]
    lines[end_idx:end_idx] = missing
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"agentkeel: {os.path.relpath(path, top)} approved by {who} on {today}.\n"
          "Append the D-NNN entry the spec carries in its section 8.")
    return 0


def main(argv=None, environ=os.environ):
    p = argparse.ArgumentParser(prog="task.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="action")
    s = sub.add_parser("start")
    s.add_argument("task")
    s.add_argument("--size", required=True, choices=record.SIZES)
    s.add_argument("--allow", required=True)
    s.add_argument("--write-root", action="append")
    s.add_argument("--worktree", action="append")
    s.add_argument("--resource", action="append")
    sub.add_parser("show")
    v = sub.add_parser("verify")
    v.add_argument("cmd", nargs=argparse.REMAINDER)
    sub.add_parser("end")
    a = sub.add_parser("approve")
    a.add_argument("target")
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--selftest"]:
        return selftest()
    args = p.parse_args(argv)
    handlers = {"start": start, "show": show, "verify": verify, "end": end, "approve": approve}
    if args.action not in handlers:
        p.print_help()
        return 2
    return handlers[args.action](args, environ)


def selftest():
    import tempfile
    here = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        env = {**os.environ, "AGENTKEEL_HOME": os.path.join(tmp, "home"), "AGENTKEEL_SESSION_ID": "s1"}
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        run = lambda *a: subprocess.run([sys.executable, here, *a], cwd=repo, env=env,
                                        capture_output=True, text=True).returncode
        ok = [run("start", "json-flag", "--size", "medium", "--allow", "implement") == 0,
              run("start", "json-flag", "--size", "huge", "--allow", "implement") != 0,
              run("start", "json-flag", "--size", "small", "--allow", "deploy") != 0,
              run("show") == 0, run("end") == 0, run("show") == 1]
    print("task.py selftest:", "PASS" if all(ok) else f"FAIL {ok}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
