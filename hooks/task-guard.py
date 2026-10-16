#!/usr/bin/env python3
"""agentkeel task guard (PreToolUse, matcher Write|Edit|NotebookEdit|Bash).

Invariant 1, every write is bounded before it happens. This one guard reads this session's task
record (hooks/task.py) and judges every operation in the tool call against it:

  file edits (Write, Edit, NotebookEdit)
    - agentkeel state, hook configuration and agentkeel.json are never edited by the agent
    - a task must be declared for this session
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
    - force push, reset --hard, whole-tree checkout or restore, clean -f, branch -D, stash
      drop/clear/pop: refused unless the command itself carries AGENTKEEL_ALLOW_DESTRUCTIVE=1
    - distribution builds, store submissions, deploy commands and paid jobs: need their own
      permission (classes and patterns in agentkeel_core/record.py, extended by agentkeel.json)

Exit 0 allows; exit 2 blocks with the reason on stderr. A payload that is not JSON allows: a
broken guard must never stop work on its own. What this cannot see is in the README's capability
table: shell writes that are not git, commands inside scripts, and anything outside this host.
"""
import json
import time
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import checks, clerk, evidence, gitops, host, record, shell  # noqa: E402

CONFIG_NAMES = ("agentkeel.json", "mcpclerk.json", ".mcp.json")  # native MCP config changes are human-managed
CONFIG_PARTS = ((".claude", "settings.json"), (".claude", "settings.local.json"), (".claude", "hooks"),
                (".codex", "hooks.json"), (".codex", "config.toml"), (".codex", "hooks"))
NPX = {"npx", "bunx", "pnpx"}
TOOL_ALIASES = {"eas-cli": "eas"}
DESTRUCTIVE_OVERRIDE = "AGENTKEEL_ALLOW_DESTRUCTIVE"


class Block(Exception):
    def __init__(self, msg, guard="task"):
        super().__init__(msg)
        self.guard = guard


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
    clerk_home = environ.get("MCPCLERK_HOME")
    if clerk_home and under(path, os.path.realpath(clerk_home)):
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
    f"  {TASK_CMD} start <task-id> --size no-code|small|large --allow <permissions> --deliverable <outside-repo.html> [--write-root <outside-repo-folder>] [--kind fix|feature|review|docs|chore]\n\n"
    "Permissions: review (write only --write-root folders), implement, merge, push,\n"
    "distribution-build, store-submission, paid-job, remote-write, publish. Size never grants a permission.\n"
    "State your reading in your first update; ask only if the request is unclear."
)


# ---- file edits -----------------------------------------------------------------------------

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
    own_clone = bool(rec.get("clone")) and root == os.path.realpath(rec["clone"])
    if not own_clone and gitops.is_primary(root) and (not owned_repos or gitops.common_dir(root) in owned_repos):
        raise Block(
            f"refusing to write {target}: {root} is the repository's shared checkout.\n"
            "Every code task, small ones included, works in its own managed worktree, so the shared checkout\n"
            "stays free for other agents' merges. Start a code task with task.py; it creates and records the worktree:\n"
            f"  {TASK_CMD} start {rec.get('task')} --size small --allow implement --deliverable <outside-repo.html>")
    if root not in (rec.get("worktrees") or []):
        raise Block(
            f"refusing to write {target}: it belongs to another worktree ({root}).\n"
            "Another agent may own it. Work only in this task's worktrees; if this one is yours,\n"
            "start a task with task.py so it creates and records the worktree.")
    if "implement" not in perms:
        raise Block(
            f"task '{rec.get('task')}' has permissions {', '.join(sorted(perms))}: it writes only its\n"
            "--write-root folders. If the human asked for code changes, re-declare with implement.")
    pol = record.policy(root)
    branch = gitops.current_branch(gitops.GitCall([], root, "", [], {}))
    if branch in pol["protected"]:
        raise Block(
            f"this worktree is on the protected branch '{branch}'. Every code task works on its own\n"
            "branch in its own managed worktree. Start the task with task.py so it creates and records one:\n"
            f"  {TASK_CMD} start {rec.get('task')} --size small --allow implement --deliverable <outside-repo.html>")
    if rec.get("kind") == "fix" and rel and not rel.startswith("docs/"):
        judge_fix(rec, environ)
    rec["code_changed_at"] = time.time()
    record.save(rec, environ)


def judge_fix(rec, environ):
    """The debugging guards, for a task declared --kind fix: a code edit needs one failed check
    and one cause line on record, and three edit-then-fail cycles end the guessing. The guard
    checks that the records exist, not that they are true; the method is the debugging skill."""
    fix = rec.get("fix") or {}
    failed = any(e.get("result") == "failed" for e in rec.get("evidence") or [])
    if not failed:
        raise Block(
            "kind fix: no code edit before a check has failed on record. Reproduce the bug first:\n"
            f"  {TASK_CMD} verify -- <the command that shows it>\n"
            "A check that exits non-zero is recorded as failed. A new test must fail on the old code\n"
            "before the fix (tests can encode the defect).", guard="fix")
    if not rec.get("cause"):
        raise Block(
            "kind fix: no code edit before the cause is on record, in one line:\n"
            f'  {TASK_CMD} cause "X causes Y because Z"\n'
            "The guard checks that it exists, not that it is true: trace the bad data to its origin first.",
            guard="fix")
    if int(fix.get("cycles") or 0) >= 3:
        raise Block(
            "kind fix: three edit-then-fail cycles are on record. A fourth fix is not the answer:\n"
            "question the design, say why the pattern may be wrong, and report. The human re-opens\n"
            f"the task with: {TASK_CMD} reopen {rec.get('task')}", guard="fix")
    fix["edited"] = True
    rec["fix"] = fix
    try:
        record.save(rec, environ)
    except Exception:
        pass


def own_scratch(target, rec, environ):
    """A temp path this task owns: its scratch folder, or a temp path naming its session (Claude
    Code's own scratchpad does). Another task's temp files are not scratch."""
    if rec.get("scratch") and under(target, rec["scratch"]):
        return True
    if not any(under(target, t) for t in temp_roots(environ)):
        return False
    return str(rec.get("session_id")) in target.split(os.sep)


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


def human_task_command(argv):
    """Human-only task commands that this guard still reserves."""
    for i, tok in enumerate(argv):
        if os.path.basename(tok) == "task.py":
            for word in ("open", "import", "release", "reopen", "discard"):
                if word in argv[i + 1:i + 4]:
                    return word
    return None


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
    try:
        judge_git_ops(call, ops, root, pol, rec, environ, line)
    except Block:
        raise
    except Exception as exc:
        if any(o.kind in ("move", "push") for o in ops):
            raise Block(f"cannot check this {call.sub} ({type(exc).__name__}: {exc}); a branch move that\n"
                        "agentkeel cannot judge is refused, not allowed. Report this to the agentkeel maintainers.")
        raise


def judge_git_ops(call, ops, root, pol, rec, environ, line):
    protected = pol["protected"]
    for op in ops:
        if op.kind == "worktree":
            raise Block(
                "refusing manual `git worktree add`: its new tree would not have a Keel ownership manifest.\n"
                "Use task.py start from the repository checkout; it creates the branch and linked worktree,\n"
                "records ownership, and keeps task writes inside that tree.")
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
            rec["code_changed_at"] = time.time()
            record.save(rec, environ)
        elif op.kind == "move":
            need(rec, "merge", f"moving the protected branch '{op.targets[0] if op.targets else '?'}' ({op.name})")
        elif op.kind == "push":
            hits = [t for t in op.targets if t in protected or t == "*"]
            if op.local:
                if hits:
                    need(rec, "merge", f"moving '{hits[0]}' with a local push")
                else:
                    need(rec, "implement", "a local push between branches")
            else:
                where = (hits[0] if hits[0] != "*" else "every branch") if hits else ", ".join(op.targets)
                need(rec, "push", f"a push to '{where}'")
                if hits:
                    need(rec, "merge", f"moving the protected branch '{where}' with a remote push")
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
        human = human_task_command(sc.argv)
        if human == "discard":
            raise Block("`task.py discard` is the human's command: it deletes cancelled task work, including unmerged changes. "
                        "Report the exact task and worktree path for the human to discard explicitly.")
        if human == "open":
            raise Block(
                "`task.py open` is the human's command: it sets the write boundary of a new session,\n"
                "and a boundary the agent chooses for itself proves nothing. Ask the human to run it.")
        if human in ("import", "release"):
            raise Block(
                f"`task.py {human}` is the human's command: it moves work into the shared repository or\n"
                "deletes a task's clone. Tell the human the full commit id to import, or that the task\n"
                "is ready to release.")
        if human == "reopen":
            raise Block(
                "`task.py reopen` is the human's command: after three failed fixes only the human\n"
                "re-opens the loop. Report why the design may be wrong and wait.")
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
                "refusing raw `gh pr merge` with a configured required check.\n"
                "Use task.py ship --pr NUMBER to verify the exact candidate and checks before merging;\n"
                "add --admin only for an explicitly authorized administrator exception.")
        line["earlier"] = line.get("earlier", 0) + (sc.name not in ("cd", "pushd", "popd"))


def judge_mcp(ev, cwd, rec, payload, environ):
    """Delegate every intercepted MCP call to the installed MCPClerk judge."""
    try:
        host_name = evidence.host_of(payload)
        project_root = gitops.toplevel(cwd) if cwd and os.path.isdir(cwd) else None
        project_dir = os.path.realpath(project_root) if project_root else cwd
        if clerk.has_legacy_policy(cwd, environ):
            raise Block(
                "legacy AgentKeel MCP policy found; MCPClerk is the sole MCP policy authority. The human must run "
                "`mcpclerk migrate-keel`, then remove the project's `mcp` and `guards.mcp_unknown` policy "
                "and the legacy `~/.agentkeel/mcp_catalog.json`; this MCP call is refused until migration is complete.",
                guard="mcpclerk")
        result = clerk.judge(ev.tool, ev.args, host_name, cwd, project_dir,
                             list((rec or {}).get("permissions") or []), environ)
    except Block:
        raise
    except clerk.ClerkError as error:
        raise Block(str(error), guard="mcpclerk") from None
    except Exception:
        raise Block("MCP policy check failed; refusing this MCP call.", guard="mcpclerk") from None
    if not result["allowed"]:
        raise Block(result["reason"], guard="mcpclerk")
    if (result["classification"] == "unknown" and
            result["reason"] == "unknown MCP server; warning policy allows it"):
        sys.stdout.write(json.dumps({"systemMessage": result["reason"]}) + "\n")


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
            elif ev.kind == "mcp":
                judge_mcp(ev, cwd, rec, payload, environ)
            elif ev.kind == "gap":
                raise Block(
                    f"agentkeel cannot read the tool '{ev.tool}' and it may write, so it is refused rather\n"
                    "than silently allowed. Use a tool agentkeel reads (file edits, apply_patch, shell),\n"
                    "or tell the human this tool needs an adapter.")
    except Block as b:
        return record.soften(b.guard, "AGENTKEEL: " + str(b), cwd)
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
