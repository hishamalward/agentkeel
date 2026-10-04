# Guardrails

## The pattern on every write path

Reused from [toilscan](https://github.com/hishamalward/toilscan)'s `apply` path, where it is
enforced in code:

1. **Read-only by default.** The default invocation previews; nothing is written until the caller
   authorizes it explicitly (a flag, an approval, a declared permission).
2. **Explicit authorization to apply**, per operation, never "apply all" by default.
3. **Stable IDs** for the things being written, so a re-run recognizes what it already did.
4. **Atomic writes**: write to a temp file beside the target, then rename. A crash leaves the old
   file or the new file, never half of one.
5. **A recoverable journal** of what was written, so the last apply can be undone.
6. **Never move or push `main`** without the merge or push permission; **never edit outside your
   task's worktrees**; **never print a secret**.

The hooks in this repo enforce item 6 and the permission half of item 2. Items 1, 3, 4 and 5 are how to
build a tool that writes; the hooks cannot enforce them from outside and the README does not
claim they do.

## What the hooks see, and what they cannot

Hooks run on tool calls. They see the call as JSON (`docs/hook-payloads.md`), not the filesystem
and not the process that results. So the guarantee is "the agent's tool calls were bounded", not
"nothing else touched the tree". Concretely:

| Guard | Sees | Does not see |
|---|---|---|
| `task-guard.py` | `Write`, `Edit`, `NotebookEdit` paths; every simple command in a `Bash` line (after `&&`, `;`, pipes, newlines, `$(...)`, `bash -c`, `eval`, `cd`), every git operation in it with its global options and aliases | `sed -i`, redirects, `mv`, a script or npm script that writes or runs git; variables and globs (not expanded) |
| `secret-guard.py` | shell commands that print env files, key files, the environment, secret-named variables | a program that reads and prints the value; a secret in a file under a name the list does not know |
| `plan-gate-guard.py` | `Agent` dispatches naming a plan file, with the `[plan-gate]` marker or the gate words | a dispatch worded to avoid the heuristic |
| `plan-size-guard.sh` | the line count of a plan file after a write | a plan split across files |

The README's capability table labels each protection as prevents, warns after, guidance only or
unsupported.

Two overrides exist (`AGENTKEEL_ALLOW_DESTRUCTIVE=1`, `AGENTKEEL_SHOW_SECRETS=1`). Each is written
on the command it applies to, so it applies once and the transcript shows it, and each use is
appended to `~/.agentkeel/overrides.jsonl`. Shipping has no override: it is a permission.

## Isolation is a different problem

A git worktree isolates the filesystem and nothing else. The database, the ports, the job queue
and the simulator stay shared, and two agents on one machine will collide there first. That is
runtime isolation and it lives in [agent-slots](https://github.com/hishamalward/agent-slots),
where one integer derives a worktree, a database, two ports and a queue schema. agentkeel does not
duplicate it.
