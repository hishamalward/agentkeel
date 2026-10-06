#!/usr/bin/env python3
"""agentkeel task: declare what this session's task is, before the first write.

  task.py init                     opt this repository in: create agentkeel.json if it is missing
                                   (never overwrite it), register the opt-in, report each host
  task.py open <task-id> --host claude|codex --size S --allow P [--base B] [--branch BR] [--path DIR]
               [--print]           HUMAN ONLY: make the task's own clone and scratch folder, and
                                   start the host in the clone with this session's sandbox boundary
  task.py import <task-id> --sha <full id>
                                   HUMAN ONLY: bring the clone's branch into the shared repository as
                                   refs/agentkeel/accepted/<task-id>, only if it is exactly that commit
  task.py release <task-id> [--discard]
                                   HUMAN ONLY: delete the clone, scratch and records once nothing in the
                                   clone is unpreserved (--discard deletes it anyway)
  task.py start <task-id> --size small|medium|large --allow <permissions>
                [--write-root PATH]... [--worktree PATH]... [--resource NAME]...
  task.py show                     the record for this session
  task.py status [--json]          derived facts, read-only, with or without a session: this task's
                                   worktrees, tasks in their own clones, other worktrees, and each
                                   state page's State now with its claims
  task.py verify -- <command...>   run a check; the hooks record its result against HEAD and the tree
  task.py end                      drop the record (the task is finished or abandoned)
  task.py approve <task-id|page>   HUMAN ONLY: approve the boundary of a docs/ page

Documentation (repositories with "docs": "html" in agentkeel.json; see docs/ in agentkeel):
  task.py new <kind> <family> [--qualifier Q] [--title T] [--boundary]
                                   start a page from the starter: kind is state, reference,
                                   audit, mockup, or project (the one project canon)
  task.py context <page>           the page as plain structured text, for reading
  task.py finish <page>            remove the page's Working section before main moves
  task.py check [--rev R] [--base B]   the docs check main moves on (the working folder by default)
  task.py index [--full]           write the derived docs/index.html (never committed) and print
                                   it as text; --full lists every legacy file

Permissions (comma separated, any combination): review, implement, merge, push,
distribution-build, store-submission, paid-job, remote-write (changes on a guarded MCP service,
within the targets agentkeel.json lists), publish (an MCP call that makes something live for end
users or sends to them; store-submission covers the app stores). Size never grants a permission: they are
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


def import_cmd(args, environ):
    try:
        sha = isolation.import_task(args.task, args.sha.strip().lower(), environ)
    except isolation.OpenError as exc:
        return fail(str(exc))
    rec = isolation.load_opened(args.task, environ)
    print(f"agentkeel: accepted {sha} as {isolation.accepted_ref(args.task)} in {rec['repo']}")
    print("  main has not moved. To bring it in, in the shared checkout:")
    print(f"    git merge --ff-only {sha}")
    return 0


def release_cmd(args, environ):
    try:
        dropped = isolation.release_task(args.task, discard=args.discard, environ=environ)
    except isolation.OpenError as exc:
        return fail(str(exc))
    print(f"agentkeel: released task '{args.task}': clone, scratch folder and records deleted")
    for d in dropped:
        print(f"  discarded: {d}")
    return 0


def show(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        print("agentkeel: no task declared for this session")
        return 1
    print(json.dumps(rec, indent=2, sort_keys=True))
    return 0


def verify(args, environ):
    """Run a check. The hooks, not this command, record its result: the guard notes the start
    (HEAD and the working tree), and the PostToolUse hook the completion the host reports. A
    record the agent's own command writes would prove nothing."""
    cmd = list(args.cmd or [])
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        return fail("usage: task.py verify -- <command...>")
    code = subprocess.call(cmd)
    sys.stderr.write(f"agentkeel: `{' '.join(cmd)}` exited {code}; the hooks record the result "
                     "(task.py show)\n")
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


def record_interpreter(environ):
    """The interpreter the plugin's hook launcher (hooks/run.sh) runs, recorded by the human's init
    so a session's environment cannot choose it. Python 3.10 or later, by its real path."""
    exe = os.path.realpath(sys.executable)
    if sys.version_info < (3, 10) or not os.path.isabs(exe):
        return f"not recorded: {exe} is Python {sys.version.split()[0]}; run init with Python 3.10 or later"
    path = os.path.join(record.home(environ), "interpreter")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(exe + "\n")
    return f"run with {exe} in isolated mode (recorded in {path})"


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
    rows.append(("hooks", record_interpreter(environ)))
    ppath, ptext = record.profile(environ)
    rows.append(("profile", f"{ppath} ({ptext.rstrip(chr(10)).count(chr(10)) + 1} lines)" if ptext
                 else f"none (optional: {ppath})"))
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
    top = os.path.realpath(gitops.toplevel(os.getcwd()) or os.getcwd())
    return pages.main(["index", "--root", top] + (["--full"] if args.full else []))


def _worktree_list(top):
    """[(path, branch)] from git worktree list --porcelain; the first is the shared checkout."""
    out = gitops.run_git(top, "worktree", "list", "--porcelain") or ""
    trees, path, branch = [], None, ""
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            path, branch = os.path.realpath(line[len("worktree "):]), ""
        elif line.startswith("branch "):
            branch = line[len("branch "):].replace("refs/heads/", "", 1)
        elif line == "detached":
            branch = "(detached)"
        elif not line and path:
            trees.append((path, branch))
            path = None
    return trees


def _task_owners(environ):
    """{worktree path: task id} from every task record on this machine."""
    owners = {}
    folder = os.path.join(record.home(environ), "tasks")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        try:
            with open(os.path.join(folder, name)) as fh:
                rec = json.load(fh)
            for w in rec.get("worktrees") or []:
                owners.setdefault(os.path.realpath(w), rec.get("task") or "?")
        except Exception:
            continue
    return owners


def _worktree_facts(path, protected):
    """Branch, tip, commits not in the protected branch, merged, and changed or untracked files.
    Read without running anything the repository's config names (repostate); a worktree that cannot
    be read says so and is never called clean."""
    from agentkeel_core import repostate
    try:
        repo = repostate.locate(path)
        head = repostate._read(os.path.join(repo.gitdir, "HEAD")).strip()
        st = repostate.inspect(path)
        facts = {"path": path, "branch": head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/")
                 else "(detached)", "tip": st["head"], "changed": len(st["changed"])}
        name = next((b for b in protected if repostate.resolve(repo, "refs/heads/" + b)), None)
        base = repostate.resolve(repo, "refs/heads/" + name) if name else None
        facts["protected"] = name
        if st["head"] and base:
            with repostate.Shadow(repo) as sh:
                ahead = int(sh.git("rev-list", "--count", st["head"], "^" + base))
            facts.update(ahead=ahead, merged=ahead == 0)
        return facts
    except (repostate.InspectError, ValueError) as e:
        return {"path": path, "error": f"cannot be read ({e}); not known to be clean"}


def status(args, environ):
    """Derived facts only: it reads, and deletes or changes nothing."""
    top = gitops.toplevel(os.getcwd())
    if not top:
        return fail("not inside a git repository")
    top = os.path.realpath(top)
    pol = record.policy(top)
    protected = sorted(pol["protected"], key=lambda b: (b != "main", b))
    rec = record.load(record.session_from_env(environ), environ)
    mine = [w for w in (rec.get("worktrees") or []) if os.path.isdir(w)] if rec else []
    out = {"repository": top, "task": None, "worktrees": [], "opened": [], "others": [], "pages": []}
    if rec:
        out["task"] = {"id": rec.get("task"), "size": rec.get("size"), "permissions": rec.get("permissions") or []}
        out["worktrees"] = [_worktree_facts(w, protected) for w in mine]
    common = gitops.common_dir(top)
    for r in isolation.all_opened(environ):
        if r.get("repo_common_dir") == common or r.get("repo") == top:
            problems = isolation.release_problems(r)
            out["opened"].append({"task": r["task"], "clone": r["clone"], "branch": r.get("branch"),
                                  "ready": not problems, "problems": problems})
    owners = _task_owners(environ)
    trees = _worktree_list(top)
    for i, (path, branch) in enumerate(trees):
        if path in mine:
            continue
        out["others"].append({"path": path, "branch": branch, "shared": i == 0,
                              "task": owners.get(path)})
    docs = os.path.join(top, "docs")
    for name in sorted(os.listdir(docs)) if os.path.isdir(docs) else []:
        m = pages.NAME_RE.match(name)
        if not (m and m.group(3) == "state"):
            continue
        text = record.read(os.path.join(docs, name)) or ""
        out["pages"].append({"page": "docs/" + name, "state_now": [list(p) for p in pages.state_now(text)],
                             "claims": [{"label": label, "claim": claim, "result": r[0], "why": r[1]}
                                        for label, claim, commit, ref in pages.claims(text)
                                        for r in [pages.judge(top, commit, ref, "HEAD")]]})
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    print(f"agentkeel status: {top}")
    t = out["task"]
    print(f"this session's task: {t['id']} ({t['size']}; {', '.join(t['permissions'])})" if t
          else "this session's task: none")
    for w in out["worktrees"]:
        if "error" in w:
            print(f"  {w['path']}  {w['error']}")
            continue
        where = (f"{w['ahead']} commit(s) not in {w['protected']}, " + ("merged" if w["merged"] else "not merged")
                 if "ahead" in w else "no protected branch to compare with")
        print(f"  {w['path']}  branch {w['branch']}  tip {(w['tip'] or 'none')[:12]}  {where}, "
              f"{w['changed']} changed or untracked file(s)")
    print("tasks in their own clones:" if out["opened"] else "tasks in their own clones: none")
    for o in out["opened"]:
        print(f"  {o['task']}  {o['clone']}  branch {o['branch']}  "
              + ("ready to release" if o["ready"] else "not ready to release:"))
        for p in o["problems"]:
            print(f"    - {p}")
    print("other worktrees:" if out["others"] else "other worktrees: none")
    for o in out["others"]:
        print(f"  {o['path']}  branch {o['branch'] or '?'}  "
              + (f"foreign: task {o['task']}" if o["task"] else "no task record")
              + ("  (shared checkout)" if o["shared"] else "") + ("  (here)" if o["path"] == top else ""))
    print("state pages:" if out["pages"] else "state pages: none")
    for pg in out["pages"]:
        print(f"  {pg['page']}")
        for k, v in pg["state_now"]:
            print(f"    {k}: {v}")
        for c in pg["claims"]:
            print(f"    claim '{c['claim']}': {c['result']} ({c['why']})")
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
    im = sub.add_parser("import")
    im.add_argument("task")
    im.add_argument("--sha", required=True)
    rl = sub.add_parser("release")
    rl.add_argument("task")
    rl.add_argument("--discard", action="store_true")
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
    sub.add_parser("index").add_argument("--full", action="store_true")
    sub.add_parser("status").add_argument("--json", action="store_true")
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--selftest"]:
        return selftest()
    args = p.parse_args(argv)
    handlers = {"init": init, "open": open_cmd, "import": import_cmd, "release": release_cmd, "start": start, "show": show, "verify": verify, "end": end, "approve": approve, "new": new,
                "context": context, "finish": finish, "check": check, "index": index, "status": status}
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
