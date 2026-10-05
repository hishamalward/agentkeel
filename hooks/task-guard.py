#!/usr/bin/env python3
"""agentkeel task guard (PreToolUse, matcher Write|Edit|NotebookEdit|Bash).

Invariant 1, every write is bounded before it happens. This one guard reads this session's task
record (hooks/task.py) and judges every operation in the tool call against it:

  file edits (Write, Edit, NotebookEdit)
    - agentkeel state, hook configuration and agentkeel.json are never edited by the agent
    - a task must be declared for this session
    - the agent cannot create, change or delete a page's approval (the human's `task.py approve`),
      nor rename or delete an approved page; a large task writes nothing outside docs/ until its
      state page's boundary is approved, then only the approved boundary's Changes list
    - the task's --write-root folders (report folders outside any repository) are writable
    - otherwise the target must be inside one of the task's own linked worktrees (never the
      shared checkout), the task must have `implement`, and the branch must not be protected
    - temp files outside any repository: only the task's scratch (its scratch folder, or a temp
      path naming its session), with `implement`

  shell commands (Bash): every simple command and every git operation in the line, not the first
    - commit: needs `implement` in a worktree the task owns, and explicit paths
    - a protected branch moves locally (commit on it, merge, ff, reset, update-ref, fetch x:main):
      needs `merge`
    - every push to a remote: needs `push`; `gh pr merge` needs `merge` and `push`
    - in a repository with "docs": "html", main moves (a push, or a local move whose new commit is
      known) only to a commit whose docs check passes: no Working section, approved boundaries
    - force push, reset --hard, whole-tree checkout or restore, clean -f, branch -D, stash
      drop/clear/pop: refused unless the command itself carries AGENTKEEL_ALLOW_DESTRUCTIVE=1
    - distribution builds, store submissions, deploy commands and paid jobs: need their own
      permission (classes and patterns in agentkeel_core/record.py, extended by agentkeel.json)
    - `task.py approve` is the human's command and is refused here

Exit 0 allows; exit 2 blocks with the reason on stderr. A payload that is not JSON allows: a
broken guard must never stop work on its own. What this cannot see is in the README's capability
table: shell writes that are not git, commands inside scripts, and anything outside this host.
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import checks, gitops, host, pages, patch as patchmod, record, shell  # noqa: E402

CONFIG_NAMES = ("agentkeel.json",)
CONFIG_PARTS = ((".claude", "settings.json"), (".claude", "settings.local.json"), (".claude", "hooks"),
                (".codex", "hooks.json"), (".codex", "config.toml"), (".codex", "hooks"))
NPX = {"npx", "bunx", "pnpx"}
TOOL_ALIASES = {"eas-cli": "eas"}
DESTRUCTIVE_OVERRIDE = "AGENTKEEL_ALLOW_DESTRUCTIVE"


class Block(Exception):
    pass


def block(msg):
    sys.stderr.write("AGENTKEEL: " + msg.rstrip() + "\n")
    return 2


def under(path, root):
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep)


def temp_roots(environ):
    roots = {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders", "/private/var/folders"}
    for var in ("TMPDIR", "TMP", "TEMP"):
        if environ.get(var):
            roots.add(environ[var])
    return {os.path.realpath(r) for r in roots}


def nearest_dir(path):
    d = os.path.dirname(path)
    while d and not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return d or os.sep


def is_config(path, environ):
    if under(path, record.home(environ)):
        return True
    parts = path.split(os.sep)
    if os.path.basename(path) in CONFIG_NAMES:
        return True
    for a, b in CONFIG_PARTS:
        for i in range(len(parts) - 1):
            if parts[i] == a and parts[i + 1] == b:
                return True
    return False


# The command as it really is for this install (a project copy or a plugin folder).
TASK_CMD = 'python3 "%s"' % os.path.join(os.path.dirname(os.path.abspath(__file__)), "task.py")

NO_TASK = (
    "no task is declared for this session.\n\n"
    "Declare it in one command, from your reading of the human's request, then retry:\n"
    f"  {TASK_CMD} start <task-id> --size small|medium|large --allow <permissions>\n\n"
    "Permissions: review (write only --write-root folders), implement, merge, push,\n"
    "distribution-build, store-submission, paid-job. Size never grants a permission.\n"
    "State your reading in your first update; ask only if the request is unclear."
)


# ---- file edits -----------------------------------------------------------------------------

def new_content(ev):
    """The whole new text of the edited file when it can be known, else None."""
    if ev.full_text is not None:
        return ev.full_text
    if ev.change is not None:
        if ev.change.kind == "delete":
            return None
        return patchmod.apply(record.read(ev.source_path or ev.path), ev.change)
    if ev.edit:
        old = record.read(ev.path)
        if old is None:
            return None
        a, b = str(ev.edit.get("old_string") or ""), str(ev.edit.get("new_string") or "")
        return old.replace(a, b) if ev.edit.get("replace_all") else old.replace(a, b, 1)
    return None


def judge_edit(ev, rec, environ):
    target = ev.path
    if is_config(target, environ):
        raise Block(
            f"refusing to edit {target}.\n"
            "agentkeel state, hook configuration and agentkeel.json change only through the\n"
            "installer or by the human. If the human asked for this change, tell them the exact\n"
            "edit and let them make it.")
    if not rec:
        raise Block(NO_TASK)
    root = gitops.toplevel(nearest_dir(target))
    root = os.path.realpath(root) if root else None
    rel = os.path.relpath(target, root).replace(os.sep, "/") if root else None
    perms = set(rec.get("permissions") or [])
    # Page approval and a large task's blast radius hold everywhere, write roots included.
    if rel and re.match(r"^docs/[^/]+\.html$", rel) or ev.source_path and re.search(r"/docs/[^/]+\.html$", ev.source_path):
        judge_page_edit(ev, rel or target)
    large = bool(rel) and rec.get("size") == "large" and not rel.startswith("docs/")
    if root is None:
        # Write roots are report folders outside any repository. Inside a repository they grant
        # nothing: source is written only through the task's own worktree, by the rules below.
        if any(under(target, r) for r in rec.get("write_roots") or []):
            return
        if "implement" in perms and own_scratch(target, rec, environ):
            return
        raise Block(
            f"refusing to write {target}: it is not in this task's worktrees, write roots or scratch.\n"
            f"Task '{rec.get('task')}' owns: {', '.join(rec.get('worktrees') or []) or '(no worktree)'}"
            f"{'; write roots: ' + ', '.join(rec.get('write_roots')) if rec.get('write_roots') else ''}"
            f"{'; scratch: ' + rec['scratch'] if rec.get('scratch') else ''}.\n"
            "Temp files go in the task's scratch folder. If this path is really part of the task,\n"
            "re-declare with --write-root <folder>.")
    owned_repos = {gitops.common_dir(w) for w in rec.get("worktrees") or [] if os.path.isdir(w)}
    if gitops.is_primary(root) and (not owned_repos or gitops.common_dir(root) in owned_repos):
        raise Block(
            f"refusing to write {target}: {root} is the repository's shared checkout.\n"
            "Every code task, small ones included, works in its own worktree, so the shared checkout\n"
            "stays free for other agents' merges:\n"
            f"  git worktree add ../{os.path.basename(root)}-{rec.get('task')} -b feat/{rec.get('task')}\n"
            "then work there (the new worktree is recorded as this task's automatically).")
    if root not in (rec.get("worktrees") or []):
        raise Block(
            f"refusing to write {target}: it belongs to another worktree ({root}).\n"
            "Another agent may own it. Work only in this task's worktrees; if this one is yours,\n"
            "re-declare with --worktree <path>.")
    if "implement" not in perms:
        raise Block(
            f"task '{rec.get('task')}' has permissions {', '.join(sorted(perms))}: it writes only its\n"
            "--write-root folders. If the human asked for code changes, re-declare with implement.")
    pol = record.policy(root)
    branch = gitops.current_branch(gitops.GitCall([], root, "", [], {}))
    if branch in pol["protected"]:
        raise Block(
            f"this worktree is on the protected branch '{branch}'. Every code task works on its own\n"
            "branch in its own worktree:\n"
            f"  git worktree add ../<repo>-{rec.get('task')} -b feat/{rec.get('task')}\n"
            "then work there (the new worktree is recorded as this task's automatically).")
    if large:
        judge_large_path(rel, root, rec)


def own_scratch(target, rec, environ):
    """A temp path this task owns: its scratch folder, or a temp path naming its session (Claude
    Code's own scratchpad does). Another task's temp files are not scratch."""
    if rec.get("scratch") and under(target, rec["scratch"]):
        return True
    if not any(under(target, t) for t in temp_roots(environ)):
        return False
    return str(rec.get("session_id")) in target.split(os.sep)


def judge_page_edit(ev, rel):
    """The same rule on every host: a page's approval metadata is the human's. The agent edits a
    page freely, boundary included (a changed boundary keeps main from moving until approved
    again), but cannot create, change or remove the approval, or rename or delete an approved
    page. A patch is judged on the text it produces."""
    before = record.read(ev.source_path or ev.path)
    held = pages.approval_metas(before)
    deleting = ev.change is not None and ev.change.kind == "delete"
    if held and (deleting or ev.source_path):
        raise Block(
            f"refusing to {'delete' if deleting else 'rename'} {rel}: its boundary is approved, and dropping\n"
            "that approval is the human's decision. Stop and tell them.")
    if deleting:
        return
    text = new_content(ev)
    if text is None:
        if held:
            raise Block(
                f"refusing this edit to {rel}: its result cannot be read, and the page carries an approval\n"
                "that must stay unchanged. Make the edit with Write, Edit or a patch that fits.")
        return
    if pages.approval_metas(text) != held:
        raise Block(
            f"refusing to {'change' if held else 'add'} the approval of {rel}: approval is the human's ruling\n"
            "(gate G1). Ask them to approve the boundary; they run, in their own terminal:\n"
            f"  {TASK_CMD} approve {rel}")


def approved_boundary(root, rec):
    """(page name, the approved boundary's HTML) for a large task, else Block with the reason.
    When the page's boundary was edited after approval, the approved version (kept by approve in
    AGENTKEEL_HOME) still sets the limits: a widened draft grants nothing."""
    import glob
    task = rec.get("task", "")
    found = sorted(glob.glob(os.path.join(root, "docs", f"[0-9][0-9][0-9][0-9][0-9][0-9]-{task}-state.html")))
    ask = (f"Approval is the human's: they run\n  {TASK_CMD} approve {task}\n"
           "Edits under docs/ are allowed meanwhile.")
    if len(found) != 1:
        raise Block(
            f"size large needs an approved boundary before any edit outside docs/. There is "
            f"{'no' if not found else 'more than one'} state page for '{task}'\n"
            f"(docs/YYMMDD-{task}-state.html). Start it with: {TASK_CMD} new state {task}\n" + ask)
    name, text = os.path.basename(found[0]), record.read(found[0]) or ""
    state, why = pages.boundary_state(name, text)
    if state == "approved":
        return name, pages.sections(text, "boundary")[0]
    got = pages.approval(text) if state == "changed" else None
    if got:
        kept = record.read(record.approved_boundary_path(got[0]))
        if kept is not None and pages.digest(name, kept) == got[0]:
            return name, kept
    raise Block(f"size large needs an approved boundary before any edit outside docs/.\n"
                f"docs/{name}: {why or 'it has no boundary section'}.\n" + ask)


def judge_large_path(rel, root, rec):
    name, boundary = approved_boundary(root, rec)
    changes, must_not = pages.blast_radius(boundary)
    if record.matches(rel, must_not):
        raise Block(f"{rel} is listed under 'Must not change' in the approved boundary of {name}.")
    if changes and not record.matches(rel, changes):
        raise Block(
            f"{rel} is outside the Changes list of the approved boundary of {name} ({', '.join(changes)}).\n"
            "Stop and tell the human: the blast radius grew, and re-scoping is theirs.")


# ---- shell commands -------------------------------------------------------------------------

def normalise(argv):
    argv = list(argv)
    if argv and os.path.basename(argv[0]) in NPX:
        argv = [a for a in argv[1:] if not a.startswith("-")] or argv
    elif argv and os.path.basename(argv[0]) in ("pnpm", "yarn", "npm", "bun") and argv[1:2] in (["dlx"], ["exec"], ["x"]):
        argv = [a for a in argv[2:] if a != "--" and not a.startswith("-")] or argv
    if argv:
        tool = os.path.basename(argv[0])
        if "@" in tool[1:]:
            tool = tool[0] + tool[1:].split("@", 1)[0]  # eas-cli@latest -> eas-cli
        argv[0] = TOOL_ALIASES.get(tool, tool)
    return argv


def is_task_approve(argv):
    for i, tok in enumerate(argv):
        if os.path.basename(tok) == "task.py" and "approve" in argv[i + 1:i + 4]:
            return True
    return False


def need(rec, perm, what):
    if not rec:
        raise Block(NO_TASK)
    if perm not in (rec.get("permissions") or []):
        raise Block(
            f"{what} needs the '{perm}' permission; task '{rec.get('task')}' has "
            f"{', '.join(rec.get('permissions') or []) or 'none'}.\n"
            "Finishing work and shipping it are separate decisions. If the human's request\n"
            f"included this, re-declare with --allow ...,{perm} and say so in your update;\n"
            "otherwise stop and report that the work is ready.")


def judge_git(sc, rec, environ, session, line):
    argv = list(sc.argv)
    for var, opt in (("GIT_DIR", "--git-dir"), ("GIT_WORK_TREE", "--work-tree")):
        if sc.env.get(var):
            argv[1:1] = [opt, sc.env[var]]
    call = gitops.parse(argv, sc.cwd)
    if not call:
        return
    call.config = {**line["aliases"], **call.config}
    call, shell_text = gitops.expand_alias(call)
    if shell_text:
        judge_command(shell_text, call.cwd, rec, environ, session, line)
        return
    top = gitops.toplevel(call)
    root = os.path.realpath(top) if top else None
    pol = record.policy(root)
    protected = pol["protected"]
    if call.sub == "config":
        names = [a for a in call.args if not a.startswith("-")]
        if len(names) >= 2 and names[0].lower().startswith("alias."):
            line["aliases"][names[0].lower()] = " ".join(names[1:])
    ops = gitops.ops_for(call, protected, branch=line["branches"].get(root))
    switched = gitops.switched_to(call)
    if switched:
        line["branches"][root] = switched
    for op in ops:
        if op.kind == "destructive":
            if sc.env.get(DESTRUCTIVE_OVERRIDE) == "1":
                record.log_override(DESTRUCTIVE_OVERRIDE, sc.text(), session, environ)
                continue
            raise Block(
                f"refusing {op.name}.\n"
                "This discards work that may not be yours, in a tree other agents may share.\n"
                f"If the human asked for exactly this, prefix the command with {DESTRUCTIVE_OVERRIDE}=1;\n"
                "the override is logged and visible in the transcript.")
    for op in ops:
        if op.kind == "worktree" and rec and not os.path.lexists(op.path):
            # the worktree does not exist yet (PreToolUse); resolve its parent the way git will
            path = os.path.join(os.path.realpath(nearest_dir(op.path + os.sep + "x")), "") \
                if os.path.exists(op.path) else \
                os.path.join(os.path.realpath(os.path.dirname(op.path)), os.path.basename(op.path))
            path = path.rstrip(os.sep)
            if path not in rec.get("worktrees", []):
                rec.setdefault("worktrees", []).append(path)
                record.save(rec, environ)
        elif op.kind == "commit":
            if not rec:
                raise Block(NO_TASK)
            moves_protected = any(o.kind == "move" for o in ops)
            if root not in (rec.get("worktrees") or []) and not (moves_protected and "merge" in rec.get("permissions", [])):
                raise Block(
                    f"refusing a commit in {root}: it is not one of task '{rec.get('task')}'s worktrees.\n"
                    "Another agent may own it.")
            if "implement" not in rec.get("permissions", []) and not moves_protected:
                need(rec, "implement", "a commit")
            if not op.explicit:
                raise Block(
                    "refusing a commit that does not name its paths.\n"
                    "A bare `git commit` (or -a) commits whatever is staged, including another agent's\n"
                    "work. Name the paths: git commit -m '...' -- <path> [<path>...]")
            if rec.get("size") == "large" and root and not all(p.startswith("docs/") for p in op.paths):
                approved_boundary(root, rec)
        elif op.kind == "move":
            need(rec, "merge", f"moving the protected branch '{op.targets[0] if op.targets else '?'}' ({op.name})")
            if op.source and root:
                sha = gitops.run_git(call, "rev-parse", "--verify", "--quiet", f"{op.source}^{{commit}}")
                docs_gate(root, sha, op.targets[0] if op.targets else "main", None, environ)
        elif op.kind == "push":
            hits = [t for t in op.targets if t in protected or t == "*"]
            if op.local:
                if hits:
                    need(rec, "merge", f"moving '{hits[0]}' with a local push")
                    for dst in hits:
                        if dst != "*" and op.sources.get(dst) and root:
                            sha = gitops.run_git(call, "rev-parse", "--verify", "--quiet", f"{op.sources[dst]}^{{commit}}")
                            docs_gate(root, sha, dst, None, environ)
                else:
                    need(rec, "implement", "a local push between branches")
            else:
                where = (hits[0] if hits[0] != "*" else "every branch") if hits else ", ".join(op.targets)
                need(rec, "push", f"a push to '{where}'")
                if hits and pol["require_check"]:
                    if line.get("earlier"):
                        raise Block(
                            f"refusing a push to '{where}' that shares its call with other commands: an earlier\n"
                            "command can move the branch after this check reads it, so the commit checked would\n"
                            "not be the commit sent. Run the push alone, in its own call.")
                    if not op.explicit or "*" in hits:
                        raise Block(
                            f"refusing a push that reaches '{where}' without naming what it sends (a bare push,\n"
                            "--all, a configured or wildcard refspec): the commit that lands cannot be proven.\n"
                            "Name the tested commit: git push origin <full-tested-sha>:main")
                    for dst in hits:
                        src = op.sources.get(dst) or "HEAD"
                        if not FULL_SHA_RE.match(src):
                            raise Block(
                                f"refusing to push '{src}' to '{dst}': a branch name or HEAD can move while the check\n"
                                "is read (another agent shares the branches), so the commit checked may not be the\n"
                                "commit sent. Push the tested commit by its full SHA: git push origin <full-sha>:main")
                        sha = gitops.run_git(call, "rev-parse", "--verify", "--quiet", f"{src}^{{commit}}")
                        require_green(root, op.remote, sha, pol["require_check"], dst, environ)
                        docs_gate(root, sha, dst, op.remote, environ)
                elif hits and root:
                    if "*" in hits and pages.enabled(pages.FsTree(root)):
                        raise Block("refusing a push whose destination is not named (--all, a wildcard, a variable or\n"
                                    "a $(...)): it may reach main, and the docs check needs the commit that lands.\n"
                                    "Name both ends: git push origin <full-sha>:main")
                    for dst in hits:
                        if dst == "*":
                            continue
                        src = op.sources.get(dst) or "HEAD"
                        sha = gitops.run_git(call, "rev-parse", "--verify", "--quiet", f"{src}^{{commit}}")
                        docs_gate(root, sha, dst, op.remote, environ)


def docs_gate(root, sha, dst, remote, environ):
    """In a repository with "docs": "html", main moves only to a commit whose docs check passes,
    judged against what main holds now (the remote's copy when pushing). The same check runs in
    CI (agentkeel-required); this one stops the agent before its own push or local move."""
    if not sha:
        if pages.enabled(pages.FsTree(root)):
            raise Block(f"cannot tell which commit would land on '{dst}', so its docs check cannot run.\n"
                        "Name the commit: git push origin <full-sha>:main")
        return
    try:
        cand = pages.GitTree(root, sha)
    except ValueError:
        return
    base = None
    for ref in ([f"refs/remotes/{remote}/{dst}"] if remote and remote != "." else []) + [f"refs/heads/{dst}"]:
        b = gitops.run_git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if b:
            base = pages.GitTree(root, b)
            break
    problems = pages.check(cand, base)
    if problems:
        shown = "\n".join(f"  - {p}" for p in problems[:8]) + (f"\n  ... and {len(problems) - 8} more" if len(problems) > 8 else "")
        raise Block(f"refusing to move '{dst}' to {sha[:12]}: its docs check fails.\n{shown}\n"
                    f"Run `{TASK_CMD} check --rev {sha[:12]}` to see it; fix the pages, commit, and ship that commit.")


FULL_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def require_green(root, remote, sha, name, dst, environ):
    """The push gate: the exact commit that lands on a protected branch passed the required check."""
    if not sha:
        raise Block(f"cannot tell which commit would land on '{dst}', so its '{name}' check cannot be\n"
                    "verified. Push an explicit branch or commit (git push origin <branch>:main).")
    state, detail = checks.conclusion(root, remote, sha, name, environ)
    if state != "success":
        raise Block(
            f"refusing to ship {sha[:12]} to '{dst}': {detail}.\n"
            "This repository requires the check to pass on the exact commit before main moves.\n"
            "Push the branch, wait for the check to pass on it, then move main to that same commit.")


SESSION_CLAIM_RE = re.compile(r"\b" + record.SESSION_VAR + r"""=((?:\\.|"[^"]*"|'[^']*'|[^\s;&|()`])*)""")


def judge_session_text(command, session):
    """Every literal `AGENTKEEL_SESSION_ID=value` in the line, wrappers and quoting included: one
    that is not the caller's own id is refused, whatever the parser makes of the line around it."""
    for m in SESSION_CLAIM_RE.finditer(command or ""):
        value = re.sub(r"""[\\"']""", "", m.group(1))
        if value != session:
            raise Block(
                f"refusing {record.SESSION_VAR}={value or '(empty)'}: it is not this session's id, and a task\n"
                "record belongs to the session that declared it. Use the id printed at session start.")


def judge_session_claim(sc, session):
    """`AGENTKEEL_SESSION_ID` names the session task.py acts for. Only the caller's own id may be
    given, and only inline (VAR=id command), so it cannot reach another agent's process."""
    if record.SESSION_VAR in sc.env and sc.env[record.SESSION_VAR] != session:
        raise Block(
            f"refusing {record.SESSION_VAR}={sc.env[record.SESSION_VAR]}: it is not this session's id, and a task\n"
            "record belongs to the session that declared it. Use the id printed at session start.")
    if sc.name in ("export", "declare", "typeset", "set", "setenv") and any(
            a.split("=", 1)[0] == record.SESSION_VAR for a in sc.argv[1:]):
        raise Block(
            f"refusing to export {record.SESSION_VAR}: an exported id reaches every process this shell\n"
            "starts, other agents included. Give it inline, to the one command: "
            f"{record.SESSION_VAR}=<id> python3 task.py ...")


def judge_command(command, cwd, rec, environ, session, line=None):
    line = line if line is not None else {"branches": {}, "aliases": {}}
    judge_session_text(command, session)
    for sc in shell.commands(command, cwd):
        argv = normalise(sc.argv)
        if not argv:
            continue
        judge_session_claim(sc, session)
        if is_task_approve(sc.argv):
            raise Block(
                "`task.py approve` is the human's command (gate G1): an approval the agent can\n"
                "produce is not the human's consent. Ask the human to run it in their own terminal.")
        if argv[0] == "git" or "--dry-run" in argv:
            if argv[0] == "git":
                judge_git(sc, rec, environ, session, line)
            line["earlier"] = line.get("earlier", 0) + 1
            continue
        texts = {" ".join(argv), " ".join([os.path.basename(sc.argv[0])] + sc.argv[1:])}
        root = gitops.toplevel(sc.cwd)
        pol = record.policy(os.path.realpath(root) if root else None)
        for perm, patterns in pol["commands"].items():
            if any(re.search(p, t) for p in patterns for t in texts):
                need(rec, perm, f"`{' '.join(sc.argv)[:60]}`")
        if pol["require_check"] and argv[:3] == ["gh", "pr", "merge"]:
            raise Block(
                "refusing `gh pr merge`: GitHub writes a new commit for --merge, --squash and --rebase,\n"
                "and no check has run on it, so the tested commit is not the one main receives.\n"
                "Ship the tested commit itself, in its own call: git push origin <tested-sha>:main\n"
                "(it must already contain main; GitHub then marks the pull request merged).")
        line["earlier"] = line.get("earlier", 0) + (sc.name not in ("cd", "pushd", "popd"))


def decide(payload, environ=os.environ):
    cwd = payload.get("cwd") or environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    session = payload.get("session_id")
    rec = record.load(session, environ) if session else None
    try:
        for ev in host.events(payload, cwd):
            if ev.kind == "edit":
                judge_edit(ev, rec, environ)
            elif ev.kind == "command":
                judge_command(ev.command, cwd, rec, environ, session)
            elif ev.kind == "gap":
                raise Block(
                    f"agentkeel cannot read the tool '{ev.tool}' and it may write, so it is refused rather\n"
                    "than silently allowed. Use a tool agentkeel reads (file edits, apply_patch, shell),\n"
                    "or tell the human this tool needs an adapter.")
    except Block as b:
        return block(str(b))
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
    if record.plugin_inactive(sys.argv, payload):
        return 0
    try:
        return decide(payload)
    except Exception as exc:  # never block on our own failure
        sys.stderr.write(f"task-guard: internal error, allowing: {exc}\n")
        return 0


def selftest():
    import subprocess
    import time
    here = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = os.path.realpath(tmp)
        repo = os.path.join(tmp, "repo")
        env = {**os.environ, "AGENTKEEL_HOME": os.path.join(tmp, "home"), "GIT_AUTHOR_NAME": "t",
               "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "commit", "-q", "--allow-empty", "-m", "init"], check=True, env=env)

        def run(tool, tool_input, expect):
            payload = {"tool_name": tool, "cwd": repo, "session_id": "s1", "tool_input": tool_input}
            out = subprocess.run([sys.executable, here], input=json.dumps(payload), text=True,
                                 capture_output=True, env=env)
            ok = out.returncode == expect
            print(("PASS" if ok else "FAIL"), tool, tool_input, "->", out.returncode)
            return ok

        src = os.path.join(repo, "src.py")
        results = [run("Write", {"file_path": src, "content": ""}, 2)]
        record.atomic_write_json(os.path.join(tmp, "home", "tasks", "s1.json"), {
            "version": 1, "task": "x", "session_id": "s1", "size": "small", "permissions": ["implement"],
            "worktrees": [repo], "write_roots": [], "declared_at": int(time.time())})
        results += [run("Write", {"file_path": src, "content": ""}, 2),  # on main
                    run("Bash", {"command": "git push origin feat/x && git push origin main"}, 2),
                    run("Bash", {"command": "git status"}, 0)]
    print("task-guard selftest:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
