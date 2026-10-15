#!/usr/bin/env python3
"""AgentKeel: declare a task, own its worktree, keep current HTML, and finish safely.

start requires --size no-code|small|large, --allow and --deliverable. Medium aliases small.
Coding tasks create their own linked worktree; no-code tasks only own report folders.
verify records a foreground check against unchanged code. handoff validates free-form HTML.
pr opens a pull request; ship sends the exact verified commit then pulls canonical main.
finish releases owned resources/worktree and validates the final HTML. cancel preserves work.
Legacy human-only open/import/release retain independent-clone containment.
"""
import argparse
import shlex
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import evidence, gitops, hostcheck, instructions, isolation, mcp, record, delivery, workspace, shipping  # noqa: E402

TASK_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")


def fail(msg, code=2):
    sys.stderr.write("agentkeel: " + msg.rstrip() + "\n")
    return code


def realpath(p, cwd):
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(p)))


def start(args, environ):
    session = record.session_from_env(environ)
    if not session:
        return fail("no session id; use the identity printed by your host at session start")
    if not args.task or set(args.task) - TASK_ID_CHARS:
        return fail("task id must be kebab-case (a-z, 0-9, -)")
    perms = sorted(set(p.strip() for p in args.allow.split(",") if p.strip()))
    if not perms or set(perms) - set(record.PERMISSIONS):
        return fail("unknown or empty permission; choose from " + ", ".join(record.PERMISSIONS))
    size = record.SIZE_ALIASES.get(args.size, args.size)
    cwd = os.getcwd()
    deliverable = realpath(args.deliverable, cwd)
    roots = [realpath(p, cwd) for p in args.write_root or [os.path.dirname(deliverable)]]
    for root in roots:
        if root in ("/", os.path.realpath(os.path.expanduser("~")), record.home(environ)) or root.startswith(record.home(environ) + os.sep):
            return fail("report root is too wide or inside AgentKeel state: " + root)
        probe = root
        while not os.path.isdir(probe):
            probe = os.path.dirname(probe)
        if gitops.toplevel(probe):
            return fail("report root is inside a repository; choose a persistent folder outside it")
    if not any(deliverable.startswith(root + os.sep) for root in roots):
        return fail("--deliverable must be inside a declared --write-root")
    if not deliverable.lower().endswith((".html", ".htm")):
        return fail("--deliverable must name an HTML file")
    with record.locked(record.record_path(session, environ)):
        prev = record.load(session, environ)
        if prev and prev.get("task") != args.task:
            if prev.get("lifecycle") != "complete" or prev.get("worktrees"):
                return fail("finish the existing task before replacing its ownership record")
            archive = os.path.join(record.home(environ), "completed", record._safe(session), prev["task"] + ".json")
            record.atomic_write_json(archive, prev)
            prev = None
        if prev and size == "no-code" and prev.get("worktrees"):
            return fail("a task with a worktree cannot become no-code; finish it first")
        rec = prev or {"version": 2, "task": args.task, "session_id": session,
                       "worktrees": [], "write_roots": [], "resources": [], "declared_at": time.time(),
                       "evidence": [], "history": [], "cause": None, "fix": {"cycles": 0, "edited": False}}
        if prev:
            rec["history"].append({k: prev.get(k) for k in ("size", "permissions", "declared_at")})
            widened = sorted(set(perms) - set(prev.get("permissions") or []))
            if widened:
                print("agentkeel: permissions widened: " + ", ".join(widened) + "; state the authorization in your update")
        if size != "no-code" and not rec.get("worktrees"):
            try:
                owned = workspace.create(cwd, args.task, session, path=args.path, branch=args.branch, base=args.base)
            except (ValueError, OSError, workspace.WorkspaceError) as exc:
                return fail(str(exc))
            rec["workspace"] = owned
            rec["worktrees"] = [owned["path"]]
        rec.update(size=size, kind=args.kind, permissions=perms, deliverable=deliverable,
                   write_roots=sorted(set(roots) | set(rec["write_roots"])), lifecycle="active")
        rec["scratch"] = os.path.join(os.path.realpath(tempfile.gettempdir()), "agentkeel-scratch", record._safe(session))
        os.makedirs(rec["scratch"], exist_ok=True)
        record.save(rec, environ)
    print(f"agentkeel: task '{args.task}', {size}; permissions {', '.join(perms)}")
    print("  worktree: " + (rec["worktrees"][0] if rec["worktrees"] else "none (no-code)"))
    print("  deliverable: " + deliverable)
    print("  scratch: " + rec["scratch"])
    return 0


def open_cmd(args, environ):
    perms = [p.strip() for p in (args.allow or "").split(",") if p.strip()]
    unknown = [p for p in perms if p not in record.PERMISSIONS]
    if not perms or unknown:
        return fail(f"--allow needs one or more of: {', '.join(record.PERMISSIONS)}"
                    + (f" (unknown: {', '.join(unknown)})" if unknown else ""))
    try:
        args.size = record.SIZE_ALIASES.get(args.size, args.size)
        rec = isolation.open_task(os.getcwd(), args.task, args.host, args.size, perms, base=args.base,
                                  branch=args.branch, path=args.path, environ=environ)
    except isolation.OpenError as exc:
        return fail(str(exc))
    argv = isolation.launch_argv(rec, environ)
    print(f"agentkeel: opened task '{rec['task']}' ({rec['size']}; {', '.join(rec['permissions'])})")
    print(f"  clone:   {rec['clone']} (branch {rec['branch']}, from {rec['base']} at {rec['base_sha'][:12]})")
    print(f"  scratch: {rec['scratch']}")
    print(f"  record:  {isolation.opened_path(rec['task'], environ)}")
    if sys.platform != "darwin":
        print("  note:    the session boundary is proven on macOS only. On this platform the read-only rules\n"
              "           for paths that do not exist yet (.git/commondir) are not proven; see docs/enforcement-design.md.")
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
    cmd = list(args.cmd or [])
    if cmd[:1] == ["--"]:
        cmd.pop(0)
    rec = record.load(record.session_from_env(environ), environ)
    if not rec or not cmd:
        return fail("declare a task, then run verify -- <command...>")
    cwd = os.path.realpath(os.getcwd())
    if cwd not in rec.get("worktrees", []) and rec.get("size") != "no-code":
        return fail("run verify at this task's worktree root")
    before, started = evidence.code_state(cwd), time.time()
    try:
        code = subprocess.call(cmd, env=environ)
    except OSError as exc:
        return fail(str(exc))
    after = evidence.code_state(cwd)
    result = "failed" if code else "passed" if before[1] and before == after else "stale"
    # Reload: the check may have triggered a host hook while it ran.
    rec = record.load(rec["session_id"], environ)
    rec["evidence"] = (rec.get("evidence") or [])[-(evidence.KEEP - 1):] + [{
        "command": shlex.join(cmd)[:300], "result": result, "reason": f"exit {code}; foreground verification",
        "head": before[0], "tree": before[1], "at": time.time(), "seconds": time.time() - started}]
    fix = rec.get("fix") or {"cycles": 0, "edited": False}
    if code and rec.get("kind") == "fix" and fix.get("edited"):
        fix.update(cycles=int(fix.get("cycles") or 0) + 1, edited=False)
        sys.stderr.write(f"agentkeel: fix cycle {fix['cycles']} of 3 failed\n")
    rec["fix"] = fix
    record.save(rec, environ)
    print(f"agentkeel: check {result} (exit {code})")
    return code


def cause(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        return fail("no task declared for this session")
    text = " ".join(args.text).strip()
    if not text:
        return fail('usage: task.py cause "X causes Y because Z"')
    rec["cause"] = text[:300]
    record.save(rec, environ)
    print(f"agentkeel: cause on record for '{rec.get('task')}': {rec['cause']}")
    return 0


def reopen(args, environ):
    """Human only (the guard refuses it from a session): reset a fix task's cycle count."""
    hits = []
    tasks = os.path.join(record.home(environ), "tasks")
    for name in sorted(os.listdir(tasks)) if os.path.isdir(tasks) else []:
        path = os.path.join(tasks, name)
        try:
            with open(path) as fh:
                rec = json.load(fh)
        except Exception:
            continue
        if isinstance(rec, dict) and rec.get("task") == args.task:
            hits.append((path, rec))
    if not hits:
        return fail(f"no task record named '{args.task}'")
    for path, rec in hits:
        fix = rec.get("fix") or {}
        fix.update({"cycles": 0, "edited": False, "reopened_at": int(time.time())})
        rec["fix"] = fix
        record.atomic_write_json(path, rec)
        print(f"agentkeel: '{args.task}' re-opened (session {rec.get('session_id')}): the fix cycles are reset to 0.")
    return 0


def handoff(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        return fail("no task declared for this session")
    problems = delivery.problems(rec)
    if problems:
        return fail("HTML handoff pending: " + "; ".join(problems))
    rec["html_checkpoint"] = delivery.checkpoint(rec)
    rec["lifecycle"] = "handoff"
    record.save(rec, environ)
    print("agentkeel: HTML handoff current: " + rec["deliverable"])
    return 0


def cancel(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        return fail("no task declared for this session")
    rec["lifecycle"] = "cancelled"
    record.save(rec, environ)
    print("agentkeel: cancelled, incomplete; worktree, resources and task record retained")
    return 0


def finish(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        return fail("no task declared for this session")
    try:
        shipping.finish(rec, environ, keep=args.keep)
    except (shipping.FinishError, workspace.WorkspaceError, OSError, ValueError) as exc:
        return fail(str(exc))
    print("agentkeel: " + rec["lifecycle"] + "; report: " + rec["deliverable"])
    return 0


def pr(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        return fail("no task declared for this session")
    try:
        print(shipping.pr(rec, args.title, args.body_file, environ))
    except (shipping.FinishError, workspace.WorkspaceError, OSError, ValueError) as exc:
        return fail(str(exc))
    return 0


def ship(args, environ):
    rec = record.load(record.session_from_env(environ), environ)
    if not rec:
        return fail("no task declared for this session")
    try:
        shipping.ship(rec, args.pr, environ)
    except (shipping.FinishError, workspace.WorkspaceError, OSError, ValueError) as exc:
        return fail(str(exc))
    print("agentkeel: merged and canonical main synchronized; refresh HTML then run finish")
    return 0


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
    except Exception as e:  # read-only: an unreadable worktree is a fact to report, never a crash
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
    out = {"repository": top, "task": None, "worktrees": [], "opened": [], "others": []}
    if rec:
        out["task"] = {"id": rec.get("task"), "size": rec.get("size"), "kind": rec.get("kind") or "feature",
                       "permissions": rec.get("permissions") or [], "deliverable": rec.get("deliverable"),
                       "cause": rec.get("cause"), "fix": rec.get("fix") or {}, "evidence": rec.get("evidence") or []}
        out["worktrees"] = [_worktree_facts(w, protected) for w in mine]
    out["guards"] = pol["guards"]
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
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    if getattr(args, "html", False):
        from agentkeel_core import statuspage
        others = statuspage.other_records(environ, rec)
        html = statuspage.render(out, rec, pol, others)
        folder = rec.get("scratch") if rec and rec.get("scratch") else os.path.join(
            os.path.realpath(tempfile.gettempdir()), "agentkeel-scratch")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "agentkeel-status.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"agentkeel status page: {path}")
        if getattr(args, "open", False):
            try:
                subprocess.Popen(["open", path] if sys.platform == "darwin" else ["xdg-open", path])
            except Exception as exc:
                print(f"  (could not open it: {exc})")
        return 0
    print(f"agentkeel status: {top}")
    t = out["task"]
    print(f"this session's task: {t['id']} ({t['size']}, {t.get('kind') or 'feature'}; {', '.join(t['permissions'])})" if t
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
    return 0


def mcp_cmd(args, environ):
    """Print a catalog entry for a server with no entry, from this task's unseen log: every tool
    unclassified (judged as a write), no target listed. The human sorts it and pastes it in."""
    session = record.session_from_env(environ)
    folder = mcp.scratch_of(record.load(session, environ), session)
    entry = mcp.draft(folder, args.server)
    if not entry:
        return fail(f"no call on the MCP server '{args.server}' is in this task's unseen log "
                    f"({os.path.join(folder or '(no session)', mcp.UNSEEN_LOG)}).\n"
                    "The guard notes a call there when the server has no catalog entry.")
    print(json.dumps(entry, indent=2))
    sys.stderr.write("agentkeel: paste it under \"mcp\" in agentkeel.json. Move each tool from unclassified to read,\n"
                     "write, paid, publish or store; list the targets, and set \"target_arg\" to the argument that\n"
                     "names one (without it the operations have no target).\n")
    return 0


def main(argv=None, environ=os.environ):
    p = argparse.ArgumentParser(prog="task.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="action")
    s = sub.add_parser("start")
    s.add_argument("task")
    s.add_argument("--size", required=True, choices=record.SIZES + tuple(record.SIZE_ALIASES))
    s.add_argument("--allow", required=True)
    s.add_argument("--kind", choices=record.KINDS, default="feature")
    s.add_argument("--deliverable", required=True)
    s.add_argument("--write-root", action="append")
    s.add_argument("--path")
    s.add_argument("--branch")
    s.add_argument("--base", default="main")
    o = sub.add_parser("open")
    o.add_argument("task")
    o.add_argument("--host", required=True, choices=isolation.HOSTS)
    o.add_argument("--size", required=True, choices=record.SIZES + tuple(record.SIZE_ALIASES))
    o.add_argument("--kind", choices=record.KINDS, default="feature")
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
    sub.add_parser("cancel")
    sub.add_parser("handoff")
    f = sub.add_parser("finish")
    f.add_argument("--keep", action="store_true", help="retain the worktree and runtime for a preview")
    prp = sub.add_parser("pr")
    prp.add_argument("--title", required=True)
    prp.add_argument("--body-file", required=True)
    sp = sub.add_parser("ship")
    sp.add_argument("--pr", type=int, required=True)
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    st.add_argument("--html", action="store_true")
    st.add_argument("--open", action="store_true")
    sub.add_parser("cause").add_argument("text", nargs="+")
    sub.add_parser("reopen").add_argument("task")
    m = sub.add_parser("mcp")
    m.add_argument("op", choices=("draft",))
    m.add_argument("server")
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--selftest"]:
        return selftest()
    args = p.parse_args(argv)
    handlers = {"init": init, "open": open_cmd, "import": import_cmd, "release": release_cmd,
                "start": start, "show": show, "verify": verify, "cancel": cancel,
                "handoff": handoff, "finish": finish, "pr": pr, "ship": ship, "status": status,
                "cause": cause, "reopen": reopen, "mcp": mcp_cmd}
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
        report = os.path.join(tmp, "reports", "result.html")
        ok = [run("start", "json-flag", "--size", "no-code", "--allow", "review", "--deliverable", report) == 0,
              run("show") == 0, run("handoff") != 0, run("cancel") == 0, run("show") == 0]
    print("task.py selftest:", "PASS" if all(ok) else f"FAIL {ok}")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
