#!/usr/bin/env python3
"""agentkeel task: declare what this session's task is, before the first write.

  task.py init                     opt this repository in: create agentkeel.json if it is missing
                                   (never overwrite it), register the opt-in, report each host
  task.py open <task-id> --host claude|codex --size S --allow P [--base B] [--branch BR] [--path DIR]
               [--print]           HUMAN ONLY: make the task's own clone and scratch folder, and
                                   start the host in the clone with this session's sandbox boundary
  task.py start <task-id> --size small|medium|large --allow <permissions>
                [--write-root PATH]... [--worktree PATH]... [--resource NAME]...
  task.py show                     the record for this session
  task.py verify -- <command...>   run a check and record its exit code against HEAD
  task.py end                      drop the record (the task is finished or abandoned)
  task.py approve <task-id|page>   HUMAN ONLY: approve the boundary of a docs/ page

Documentation (repositories with "docs": "html" in agentkeel.json; see docs/ in agentkeel):
  task.py new <kind> <family> [--qualifier Q] [--title T] [--boundary]
                                   start a page from the starter: kind is state, reference,
                                   audit, mockup, or project (the one project canon)
  task.py context <page>           the page as plain structured text, for reading
  task.py finish <page>            remove the page's Working section before main moves
  task.py check [--rev R] [--base B]   the docs check main moves on (the working folder by default)
  task.py index                    write the derived docs/index.html (never committed)

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
import shlex
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import gitops, hostcheck, instructions, isolation, pages, record, starters  # noqa: E402

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


def open_cmd(args, environ):
    perms = [p.strip() for p in (args.allow or "").split(",") if p.strip()]
    unknown = [p for p in perms if p not in record.PERMISSIONS]
    if not perms or unknown:
        return fail(f"--allow needs one or more of: {', '.join(record.PERMISSIONS)}"
                    + (f" (unknown: {', '.join(unknown)})" if unknown else ""))
    try:
        rec = isolation.open_task(os.getcwd(), args.task, args.host, args.size, perms, base=args.base,
                                  branch=args.branch, path=args.path, environ=environ)
    except isolation.OpenError as exc:
        return fail(str(exc))
    argv = isolation.launch_argv(rec, environ)
    print(f"agentkeel: opened task '{rec['task']}' ({rec['size']}; {', '.join(rec['permissions'])})")
    print(f"  clone:   {rec['clone']} (branch {rec['branch']}, from {rec['base']} at {rec['base_sha'][:12]})")
    print(f"  scratch: {rec['scratch']}")
    print(f"  record:  {isolation.opened_path(rec['task'], environ)}")
    print("  start the session with:")
    print("    cd " + shlex.quote(rec["clone"]) + " && " + " ".join(shlex.quote(a) for a in argv))
    if args.print_only:
        return 0
    sys.stdout.flush()
    os.chdir(rec["clone"])
    os.execvp(argv[0], argv)


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


def find_page(target, top):
    """A page path from a path or a feature name (its state page)."""
    if target.endswith(".html"):
        return realpath(target, os.getcwd())
    import glob
    found = sorted(glob.glob(os.path.join(top, "docs", f"[0-9][0-9][0-9][0-9][0-9][0-9]-{target}-state.html")))
    return found[0] if len(found) == 1 else None


def approve(args, environ):
    cwd = os.getcwd()
    top = gitops.toplevel(cwd) or cwd
    path = find_page(args.target, top)
    text = record.read(path) if path else None
    if text is None:
        return fail(f"no page for '{args.target}': give a docs/ page path, or a feature with one state page")
    who = gitops.run_git(cwd, "config", "user.name") or os.environ.get("USER", "")
    today = datetime.date.today().isoformat()
    name = os.path.basename(path)
    try:
        new = pages.with_approval(name, text, who, today)
    except ValueError as exc:
        return fail(str(exc))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    boundary = pages.sections(new, "boundary")[0]
    record.save_approved_boundary(pages.digest(name, boundary), boundary, environ)
    print(f"agentkeel: the boundary of {os.path.relpath(path, top)} is approved by {who} on {today}.\n"
          "Later edits to it keep main from moving until it is approved again.")
    return 0


def own_page_folder(environ, what):
    """(record, repository top) when this session may write docs here, else (None, message)."""
    rec = record.load(record.session_from_env(environ), environ)
    top = gitops.toplevel(os.getcwd())
    if not rec:
        return None, "no task declared for this session; declare one with task.py start"
    if "implement" not in (rec.get("permissions") or []):
        return None, f"{what} writes a docs/ page: it needs the 'implement' permission"
    if not top or os.path.realpath(top) not in (rec.get("worktrees") or []):
        return None, (f"{what} writes in this task's own worktree; run it there "
                      f"({', '.join(rec.get('worktrees') or []) or 'none recorded'})")
    return rec, os.path.realpath(top)


def new(args, environ):
    rec, top = own_page_folder(environ, "task.py new")
    if rec is None:
        return fail(top)
    if args.kind not in ("state", "reference", "audit", "mockup", "project"):
        return fail("kind is one of: state, reference, audit, mockup, project")
    family = "project" if args.kind == "project" else args.family
    if not family or set(family) - TASK_ID_CHARS or (args.qualifier and set(args.qualifier) - TASK_ID_CHARS):
        return fail("family and qualifier are kebab-case (a-z, 0-9, -)")
    import glob
    docs = os.path.join(top, "docs")
    kind = "reference" if args.kind == "project" else args.kind
    if kind == "state" or args.kind == "project":
        existing = glob.glob(os.path.join(docs, f"[0-9][0-9][0-9][0-9][0-9][0-9]-{family}-{kind}.html"))
        if existing:
            return fail(f"{os.path.relpath(existing[0], top)} already exists: a feature has one state page "
                        "and a repository one canon. Edit it.")
    today = datetime.date.today()
    date = family_date(docs, family) or today.strftime("%y%m%d")
    name = f"{date}-{family}{'-' + args.qualifier if args.qualifier else ''}-{kind}.html"
    path = os.path.join(docs, name)
    if os.path.exists(path):
        return fail(f"{os.path.relpath(path, top)} already exists")
    title = args.title or ("Project canon" if args.kind == "project" else family.replace("-", " ").capitalize())
    boundary = args.boundary or (args.kind == "state" and rec.get("size") == "large")
    os.makedirs(docs, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(starters.page(args.kind, title, today.isoformat(), boundary=boundary))
    css = os.path.join(docs, "keel.css")
    if not os.path.exists(css):
        with open(css, "w", encoding="utf-8") as fh:
            fh.write(starters.KEEL_CSS)
        print(f"agentkeel: wrote {os.path.relpath(css, top)}")
    print(f"agentkeel: wrote {os.path.relpath(path, top)}"
          + (" (with a boundary for the human to approve)" if boundary else ""))
    return 0


def family_date(docs, family):
    """The date prefix a family already uses: every page of one feature shares its first date, so
    the files sort together. The family's state page sets it, else a page named for the family alone."""
    names = sorted(os.listdir(docs)) if os.path.isdir(docs) else []
    for kinds in (("state",), pages.KINDS):
        for name in names:
            m = pages.NAME_RE.match(name)
            if m and m.group(2) == family and m.group(3) in kinds:
                return m.group(1)
    return None


def families(names):
    """{page name: family}. A name's slug is family[-qualifier]; the family is the longest state
    page slug with the same date that the slug starts with, else the shortest such page slug."""
    found = {n: pages.NAME_RE.match(n) for n in names}
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


def context(args, environ):
    text = record.read(realpath(args.page, os.getcwd()))
    if text is None:
        return fail(f"cannot read {args.page}")
    sys.stdout.write(pages.context(text))
    return 0


def finish(args, environ):
    rec, top = own_page_folder(environ, "task.py finish")
    if rec is None:
        return fail(top)
    path = realpath(args.page, os.getcwd())
    text = record.read(path)
    if text is None or not path.startswith(top + os.sep):
        return fail(f"{args.page} is not a page in this task's worktree")
    if not pages.sections(text, "working"):
        print("agentkeel: no Working section; nothing to remove")
        return 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(pages.without_working(text))
    print(f"agentkeel: removed the Working section of {os.path.relpath(path, top)}.\n"
          "Anything still unfinished belongs in Remaining scope or Current limitations.")
    return 0


def check(args, environ):
    top = gitops.toplevel(os.getcwd()) or os.getcwd()
    return pages.main(["check", "--root", top] + (["--rev", args.rev] if args.rev else [])
                      + (["--base", args.base] if args.base else []))


INDEX_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Docs index</title><link rel="stylesheet" href="keel.css"></head><body><main>
<header class="page"><div class="kicker">Derived by task.py index &middot; not committed</div><h1>Docs index</h1></header>
"""


def init(args, environ):
    """Opt the repository in without touching an existing policy, and say what that does and
    does not turn on. Installation (the host has the plugin), opt-in (this repository) and trust
    (Codex: the human trusted the hooks in /hooks) are reported separately. It never commits."""
    top = gitops.toplevel(os.getcwd())
    if not top:
        return fail("not inside a git repository: run init from the repository you want to opt in")
    top = os.path.realpath(top)
    path = os.path.join(top, "agentkeel.json")
    rows = []
    # One exclusive create: an entry that appears at any moment before it, a dangling symbolic
    # link included, makes it fail, so nothing that exists is ever replaced or written through.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except FileExistsError:
        fd = None
    except OSError as e:
        return fail(f"could not create agentkeel.json ({e}); nothing was written")
    if fd is not None:
        with os.fdopen(fd, "w") as fh:
            fh.write("{}\n")
        data, created = {}, True
        rows.append(("policy", "created agentkeel.json with {}: the defaults below"))
    else:
        link = os.path.islink(path)
        if link and not os.path.exists(path):
            return fail("agentkeel.json is a symbolic link to a missing file. It was left as it is, and\n"
                        "nothing was created at its target; replace it with a real file by hand.")
        try:
            with open(path) as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
        except Exception as e:
            return fail(f"agentkeel.json exists but is not a JSON object ({e}). It was left as it is;\n"
                        "fix it by hand, then run init again.")
        created = False
        keys = ", ".join(sorted(data)) or "none set, so the defaults apply"
        rows.append(("policy", f"kept the existing agentkeel.json (keys: {keys})"
                     + ("; it is a symbolic link, which init reads and never writes through" if link else "")))
    status, detail = instructions.ensure(top)
    rows.append(("agents", {
        "created": "created AGENTS.md with the agentkeel block: the shared instructions for Claude Code and Codex",
        "added": "added the agentkeel block to AGENTS.md; nothing outside the block changed",
        "updated": "updated the agentkeel block in AGENTS.md to this version; nothing outside it changed",
        "current": "AGENTS.md has this version's agentkeel block",
        "edited": "the agentkeel block in AGENTS.md was written by install.py or edited by hand, so init left\n"
                  "it as it is. To take this version's text, delete the block (both markers) and run init again",
        "broken": "AGENTS.md has one agentkeel marker without the other, or out of order; init left it. Fix\n"
                  "the markers by hand, then run init again",
    }.get(status, detail)))
    conflicts = instructions.claude_conflicts(top)
    if conflicts:
        rows.append(("conflict", ", ".join(conflicts) + " exists: Claude Code loads it instead of AGENTS.md, so the\n"
                     "shared instructions are hidden from Claude. Move its content into AGENTS.md and delete it, or\n"
                     "add the line @AGENTS.md to it. init does not touch it"))
    common = gitops.common_dir(top) or top
    reg_path = os.path.join(record.home(environ), "opted-in.json")
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    with record.locked(reg_path):
        try:
            with open(reg_path) as fh:
                registry = json.load(fh)
        except Exception:
            registry = {}
        new = common not in registry
        registry.setdefault(common, int(time.time()))
        record.atomic_write_json(reg_path, registry)
    rows.append(("opt-in", ("registered" if new else "already registered")
                 + f" in {reg_path}: on every host with the plugin, the guards act in this repository and"
                 " all its worktrees, before any commit"))
    pol = record.policy(top)
    rows.append(("in force", "protected branches: " + ", ".join(sorted(pol["protected"]))
                 + "; every write needs a declared task and its own worktree; shipping needs its permission"))
    off = []
    if data.get("docs") != "html":
        off.append('HTML work records ("docs": "html")')
    if not pol["require_check"]:
        off.append('the push gate ("require_check_before_push": "<check name>", see docs/required-checks.md)')
    if off:
        rows.append(("not on", "; ".join(off)))
    hooks_dir = os.path.dirname(os.path.abspath(__file__))
    c = hostcheck.claude(top, environ)
    if not c["cli"]:
        state = "unknown: the claude command was not found or did not answer"
    elif c["installed"] is None:
        state = "install state unknown: claude plugin list --json gave an unexpected answer"
    elif not c["installed"]:
        state = "plugin not installed: claude plugin install agentkeel@agentkeel"
    else:
        state = (f"plugin {c['version'] or '(version unknown)'} installed"
                 + (f" ({c['scope']} scope)" if c["scope"] else "") + ", "
                 + {True: "enabled", False: "not enabled: claude plugin enable agentkeel@agentkeel"}.get(
                     c["enabled"], "enabled state unknown"))
    if c["project_install"]:
        state += "; a project install is in .claude/settings.json" + (
            ": use one way per repository, not both" if c["installed"] and c["enabled"] else "")
    rows.append(("claude", state))
    x = hostcheck.codex(top, environ)
    want = hostcheck.plugin_hook_count(hooks_dir)
    if not x["cli"]:
        state = "install state unknown: the codex command was not found or did not answer"
    elif x["installed"] is False:
        state = "plugin not installed: codex plugin add agentkeel@agentkeel"
    elif x["installed"] is None:
        state = "install state unknown: codex plugin list did not show agentkeel@agentkeel clearly"
    else:
        state = f"plugin {x['version'] or '(version unknown)'} installed, " + {
            True: "enabled", False: "disabled"}.get(x["enabled"], "enabled state unknown")
    if x["installed"] is not False:
        if x["trusted"] is None:
            state += f"; trust unknown: {x['trust_unknown_because']}, so check /hooks in codex"
        else:
            state += f"; {x['trusted']}" + (f" of {want}" if want else "") + " hooks trusted (hashes not re-verified)"
            if not want or x["trusted"] < want:
                state += ": open codex in this repository and trust the agentkeel hooks in /hooks"
    if x["project_install"]:
        state += "; a project install is in .codex/hooks.json"
    rows.append(("codex", state))
    if created or status in ("created", "added", "updated"):
        rows.append(("next", "share the policy and instructions through your normal workflow, for example:\n"
                     "git add agentkeel.json AGENTS.md && git commit -m \"Opt in to AgentKeel\" -- agentkeel.json AGENTS.md"))
    width = max(len(k) for k, _ in rows)
    rows = [(k, v.replace("\n", "\n" + " " * (width + 4))) for k, v in rows]
    print(f"agentkeel init: {top}")
    for k, v in rows:
        print(f"  {k.ljust(width)}  {v}")
    return 0


def index(args, environ):
    import html as h
    top = os.path.realpath(gitops.toplevel(os.getcwd()) or os.getcwd())
    docs = os.path.join(top, "docs")
    if not os.path.isdir(docs):
        return fail("no docs/ folder here")
    groups = {}
    for name, fam in sorted(families(os.listdir(docs)).items()):
        m = pages.NAME_RE.match(name)
        text = record.read(os.path.join(docs, name)) or ""
        title = pages.scan(text).title.strip() or name
        state = pages.boundary_state(name, text)[0]
        working = bool(pages.sections(text, "working"))
        groups.setdefault(fam, []).append((m.group(3), name, title, state, working))
    rows = []
    order = {"state": 0, "reference": 1, "audit": 2, "mockup": 3}
    for fam in sorted(groups, key=lambda f: (f != "project", f)):
        rows.append(f"<h2>{h.escape(fam)}</h2><ul>")
        for kind, name, title, state, working in sorted(groups[fam], key=lambda r: (order[r[0]], r[1])):
            tags = f'<span class="tag">{kind}</span>'
            if state != "none":
                tags += f' <span class="tag {"ok" if state == "approved" else "warn"}">boundary {state}</span>'
            if working:
                tags += ' <span class="tag warn">working</span>'
            rows.append(f'<li><a href="{h.escape(name)}">{h.escape(title)}</a> {tags}</li>')
        rows.append("</ul>")
    out = os.path.join(docs, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(INDEX_HEAD + "\n".join(rows) + "\n</main></body></html>\n")
    ignored = gitops.run_git(top, "check-ignore", "-q", out) is not None
    print(f"agentkeel: wrote {os.path.relpath(out, top)}"
          + ("" if ignored else "\n  note: add docs/index.html to .gitignore; the index is derived and never committed"))
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
    o = sub.add_parser("open")
    o.add_argument("task")
    o.add_argument("--host", required=True, choices=isolation.HOSTS)
    o.add_argument("--size", required=True, choices=record.SIZES)
    o.add_argument("--allow", required=True)
    o.add_argument("--base")
    o.add_argument("--branch")
    o.add_argument("--path")
    o.add_argument("--print", dest="print_only", action="store_true")
    sub.add_parser("show")
    sub.add_parser("init")
    v = sub.add_parser("verify")
    v.add_argument("cmd", nargs=argparse.REMAINDER)
    sub.add_parser("end")
    a = sub.add_parser("approve")
    a.add_argument("target")
    n = sub.add_parser("new")
    n.add_argument("kind")
    n.add_argument("family", nargs="?", default="")
    n.add_argument("--qualifier")
    n.add_argument("--title")
    n.add_argument("--boundary", action="store_true")
    for name in ("context", "finish"):
        sub.add_parser(name).add_argument("page")
    c = sub.add_parser("check")
    c.add_argument("--rev")
    c.add_argument("--base")
    sub.add_parser("index")
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--selftest"]:
        return selftest()
    args = p.parse_args(argv)
    handlers = {"init": init, "open": open_cmd, "start": start, "show": show, "verify": verify, "end": end, "approve": approve, "new": new,
                "context": context, "finish": finish, "check": check, "index": index}
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
