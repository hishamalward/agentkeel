#!/usr/bin/env python3
"""agentkeel task guard (PreToolUse, matcher Write|Edit|NotebookEdit|Bash).

Invariant 1, every write is bounded before it happens. This one guard reads this session's task
record (hooks/task.py) and judges every operation in the tool call against it:

  file edits (Write, Edit, NotebookEdit)
    - agentkeel state, hook configuration and agentkeel.json are never edited by the agent
    - a task must be declared for this session
    - the agent cannot approve a spec or change an approved one; a large task writes nothing
      outside docs/ before its spec is approved, then only its Changes list (write roots included)
    - the task's --write-root folders are writable
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
from agentkeel_core import gitops, record, shell  # noqa: E402

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


NO_TASK = (
    "no task is declared for this session.\n\n"
    "Declare it in one command, from your reading of the human's request, then retry:\n"
    "  .claude/hooks/task.py start <task-id> --size small|medium|large --allow <permissions>\n\n"
    "Permissions: review (write only --write-root folders), implement, merge, push,\n"
    "distribution-build, store-submission, paid-job. Size never grants a permission.\n"
    "State your reading in your first update; ask only if the request is unclear."
)


# ---- file edits -----------------------------------------------------------------------------

def new_content(tool, tool_input, target):
    if tool == "Write":
        return str(tool_input.get("content", ""))
    if tool == "Edit":
        old = record.read(target)
        if old is None:
            return None
        a, b = str(tool_input.get("old_string", "")), str(tool_input.get("new_string", ""))
        return old.replace(a, b) if tool_input.get("replace_all") else old.replace(a, b, 1)
    return None


def judge_edit(tool, tool_input, cwd, rec, environ):
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return
    target = os.path.realpath(os.path.join(cwd, os.path.expanduser(str(raw))))
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
    # Spec approval and a large task's blast radius hold everywhere, write roots included.
    if rel and re.match(r"^docs/specs/[^/]+\.md$", rel):
        judge_spec_edit(tool, tool_input, target, rel)
    large = bool(rel) and rec.get("size") == "large" and not rel.startswith("docs/")
    if any(under(target, r) for r in rec.get("write_roots") or []):
        if large and root in (rec.get("worktrees") or []):
            judge_large_path(rel, root, rec)
        return
    if root is None:
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


def judge_spec_edit(tool, tool_input, target, rel):
    text = new_content(tool, tool_input, target)
    before = record.read(target)
    was_approved = record.approval(before or "")[0]
    if was_approved and text is not None and (record.frontmatter(text) or {}).get("status") != "superseded":
        raise Block(
            f"refusing to edit {rel}: it is an approved spec, and an approved spec changes only\n"
            "to be marked superseded. A changed scope is a new spec or a new decision, ruled by\n"
            "the human. Stop and tell them what changed.")
    if text is not None and record.approval(text)[0] and not was_approved:
        raise Block(
            f"refusing to mark {rel} approved: spec approval is the human's ruling (gate G1).\n"
            "Ask the human to approve it. They run, in their own terminal:\n"
            f"  .claude/hooks/task.py approve {rel}")


def judge_large_path(rel, root, rec):
    spec = record.spec_path(root, rec.get("task", ""))
    text = record.read(spec)
    if text is None:
        raise Block(
            f"size large needs an approved spec before any edit outside docs/.\n"
            f"{os.path.relpath(spec, root)} does not exist. Write it from templates/spec.md, then\n"
            "ask the human to approve it. Edits under docs/ are allowed meanwhile.")
    ok, why = record.approval(text)
    if not ok:
        raise Block(
            f"size large needs an approved spec before any edit outside docs/.\n"
            f"{os.path.relpath(spec, root)} {why}. Approval is the human's: they run\n"
            f"  .claude/hooks/task.py approve {rec.get('task')}\n"
            "Edits under docs/ are allowed meanwhile.")
    changes, must_not = record.blast_radius(text)
    if record.matches(rel, must_not):
        raise Block(f"{rel} is listed under 'Must not change' in the approved spec.")
    if changes and not record.matches(rel, changes):
        raise Block(
            f"{rel} is outside the approved spec's Changes list ({', '.join(changes)}).\n"
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
                spec = record.read(record.spec_path(root, rec.get("task", "")))
                if not record.approval(spec or "")[0]:
                    raise Block("size large: no commit outside docs/ before the spec is approved.")
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


def judge_command(command, cwd, rec, environ, session, line=None):
    line = line if line is not None else {"branches": {}, "aliases": {}}
    for sc in shell.commands(command, cwd):
        argv = normalise(sc.argv)
        if not argv:
            continue
        if is_task_approve(sc.argv):
            raise Block(
                "`task.py approve` is the human's command (gate G1): an approval the agent can\n"
                "produce is not the human's consent. Ask the human to run it in their own terminal.")
        if argv[0] == "git":
            judge_git(sc, rec, environ, session, line)
            continue
        if "--dry-run" in argv:
            continue
        texts = {" ".join(argv), " ".join([os.path.basename(sc.argv[0])] + sc.argv[1:])}
        root = gitops.toplevel(sc.cwd)
        for perm, patterns in record.policy(os.path.realpath(root) if root else None)["commands"].items():
            if any(re.search(p, t) for p in patterns for t in texts):
                need(rec, perm, f"`{' '.join(sc.argv)[:60]}`")


def decide(payload, environ=os.environ):
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    cwd = payload.get("cwd") or environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    session = payload.get("session_id")
    rec = record.load(session, environ) if session else None
    try:
        if tool in ("Write", "Edit", "NotebookEdit"):
            judge_edit(tool, tool_input, cwd, rec, environ)
        elif tool == "Bash":
            judge_command(str(tool_input.get("command", "")), cwd, rec, environ, session)
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
