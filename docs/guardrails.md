# Guardrails

## The pattern on every write path

Reused from [toilscan](https://github.com/hishamalward/toilscan)'s `apply` path, where it is
enforced in code:

1. **Read-only by default.** The default invocation previews; nothing is written until the caller
   authorizes it explicitly (a flag, an approval, a declared tier).
2. **Explicit authorization to apply**, per operation, never "apply all" by default.
3. **Stable IDs** for the things being written, so a re-run recognizes what it already did.
4. **Atomic writes**: write to a temp file beside the target, then rename. A crash leaves the old
   file or the new file, never half of one.
5. **A recoverable journal** of what was written, so the last apply can be undone.
6. **Never commit to `main`** outside tier `small`; **never edit outside your worktree**; **never
   print a secret**.

The hooks in this repo enforce item 6 and the tier half of item 2. Items 1, 3, 4 and 5 are how to
build a tool that writes; the hooks cannot enforce them from outside and the README does not
claim they do.

## What the hooks see, and what they cannot

Hooks run on tool calls. They see the call as JSON (`docs/hook-payloads.md`), not the filesystem
and not the process that results. So the guarantee is "the agent's tool calls were bounded", not
"nothing else touched the tree". Concretely:

| Guard | Sees | Does not see |
|---|---|---|
| `tier-guard.py` | `Write`, `Edit`, and `git commit` inside `Bash` | `sed -i`, redirects, `mv`, a script that writes |
| `write-path-guard.py` | git commit/push/destructive commands; `Write`/`Edit` paths | a `cd` into another repo before the git command; non-git shell writes |
| `secret-guard.py` | shell commands that print env files, key files, the environment, secret-named variables | a program that reads and prints the value; a secret in a file under a name the list does not know |
| `plan-gate-guard.py` | `Agent` dispatches naming a plan file, with the `[plan-gate]` marker or the gate words | a dispatch worded to avoid the heuristic |
| `plan-size-guard.sh` | the line count of a plan file after a write | a plan split across files |

Every override is an environment variable the hook echoes to stderr when used. The transcript
therefore shows every time a guard was stepped around, and by which name.

## Isolation is a different problem

A git worktree isolates the filesystem and nothing else. The database, the ports, the job queue
and the simulator stay shared, and two agents on one machine will collide there first. That is
runtime isolation and it lives in [agent-slots](https://github.com/hishamalward/agent-slots),
where one integer derives a worktree, a database, two ports and a queue schema. agentkeel does not
duplicate it.
