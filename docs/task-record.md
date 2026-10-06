# The task record

Before its first write, the agent declares its task in one command. The record answers three separate questions: how much process (size), which actions (permissions) and where (worktrees). The hooks read it on every tool call.

A repository opts in once, before any task: `task.py init` in the repository creates `agentkeel.json` when it is missing (it never changes an existing one), keeps one agentkeel block in `AGENTS.md` (the shared instructions for both hosts; never a `CLAUDE.md`), registers the opt-in for the repository and all its worktrees, and reports what the policy turns on and each host's install, enable and trust state. It does not commit.

Declare it from your reading of the human's request:

```
.claude/hooks/task.py start <task-id> --size small|medium|large --allow <permissions> \
    [--write-root DIR]... [--worktree DIR]... [--resource NAME]...
```

It writes `~/.agentkeel/tasks/<session-id>.json` (`AGENTKEEL_HOME` moves it). The guards read it on every tool call. Fields: `task`, `session_id`, `size`, `permissions`, `worktrees`, `write_roots`, `resources`, `evidence`, `history`.

## Three questions, answered separately

| Question | Values | Rule |
|---|---|---|
| Size | `small`, `medium`, `large` | how much process the task buys; it grants no action |
| Permissions | `review`, `implement`, `merge`, `push`, `distribution-build`, `store-submission`, `paid-job`, `remote-write` | each action needs its own; "merge and push" means `implement,merge,push` |
| Resources | worktrees, write roots, named resources | where the task may write; everything else belongs to someone else |

| Size | Process | The hooks require |
|---|---|---|
| `small` | its own branch and worktree; no plan document, no subagents; one check; short report | a declared task; code edits off the protected branch |
| `medium` | as small, plus tests and one review round | the same |
| `large` | an approved boundary on the feature's state page; a plan table (its Working section) gated once; per-task and whole-branch review | no edit outside `docs/` before the boundary is approved; then only the approved boundary's `Changes` paths |

| Permission | Allows |
|---|---|
| `review` | writing the `--write-root` folders only (report folders outside any repository) |
| `implement` | editing the task's own worktrees, commits with explicit paths, local checks and local builds, local pushes between non-protected branches, files in the task's scratch |
| `merge` | `gh pr merge` (together with `push`); moving a protected branch locally: a commit on it, `merge`, `merge --ff-only`, `reset`, `rebase`, `update-ref`, `fetch . x:main`, `branch -f` |
| `push` | every push to a remote, the task's own branch included; deploy commands (`railway up`, `vercel --prod`, `fly deploy`, `netlify deploy --prod`) |
| `distribution-build` | `eas build`, `xcodebuild archive`, `fastlane gym` and similar |
| `store-submission` | `eas submit`, `eas update`, `npm publish`, `fastlane deliver/pilot/supply` |
| `paid-job` | the command patterns a repository lists in `agentkeel.json`; MCP calls that bill per call (DataForSEO `/live` and `task_post`, Sentry Seer analysis, which also needs its organization listed under `mcp`) |
| `remote-write` | MCP calls that change a guarded service (RevenueCat, PostHog, Sentry), only on a target `agentkeel.json` lists for it; a git push permission does not cover them |

## Rules

- **No record, no writes.** A record belongs to one session. A second session, or a record file copied under another name, grants nothing. A subagent's tool calls carry its parent's session on both hosts (in Codex its own shell has its own id, so run task.py from the main agent).
- **Size never grants a permission.** Re-declaring with a different size keeps the permissions exactly as given. Widening the permissions is printed on stderr and kept in `history`; say it in your next update.
- **State your reading, then proceed.** The record is your interpretation of the request. Ask only when information is missing, the request is unclear, or an action would go past it.
- **When in doubt, smaller.** A task never grows on its own: if it turns out bigger, stop and say so; re-scoping is the human's.
- **Scratch**: each record has a scratch folder (`$TMPDIR/agentkeel-scratch/<session>`, printed by `task.py start`). Temp paths that name the session (Claude Code's own scratchpad does) are scratch too. Any other temp file belongs to someone else.
- **Write roots are report folders outside any repository.** `task.py start` refuses one inside a repository, and the guard ignores one there: repository files are written only through the task's own worktree, under every rule above. A review that must land in the repository (an audit under `docs/`) is an `implement` task in its own worktree.
- **Every code task has its own worktree**, even when you are the only agent, and the guard enforces it: the shared checkout never takes code edits, whatever branch it is on, and `task.py start` there records no worktree. `git worktree add ../<repo>-<task> -b feat/<task>` (recorded as the task's automatically). The protected branch stays clean for merges.
- **Explicit-path commits**: `git commit -m "..." -- <paths>`. A bare `git commit` commits the whole index, including what another agent staged. Finishing a merge is the one exception (git refuses a partial commit then).
- **A new task in the same session starts fresh.** Only re-declaring the same task id keeps its worktrees, write roots and evidence.
- **Evidence**: `task.py verify -- <command>` runs a check; the hooks record its result, not the command. The guard notes the start with `HEAD` and a tree id, read without running anything the repository's config names; the PostToolUse hook records "passed" only for a foreground success that Claude Code reports with `interrupted` false, on unchanged code. A background run, an interrupted run, a run where the code moved, and every Codex run (no exit status reaches its hooks) are unrecorded or stale. A failure leaves the run pending. It is a record, not a gate: shipping is gated by the CI required check.
- **The human approves a boundary**: `task.py approve <feature|page>` writes the page's `keel-approval` meta (a digest of the boundary, the approver from git `user.name`, the date) and keeps the approved boundary in `AGENTKEEL_HOME/approvals/`. The guard refuses it when the agent runs it, and refuses an agent edit that adds, changes or removes the approval, or that renames or deletes an approved page. The human runs it in a terminal of their own.
- **`task.py end`** drops the record and lists what the task owned. It does not remove the task's worktrees or slots: cleanup that knows which task owns what is not built yet.

## The repository policy file

`agentkeel.json` at the repository root is optional and is never editable by the agent's file tools:

```
{
  "protected_branches": ["main", "release"],
  "commands": { "paid-job": ["^npx tsx scripts/eval-"] },
  "writable": ["~/.npm"],
  "mcp": { "revenuecat": { "targets": ["proj1a2b3c"] }, "sentry": { "targets": ["my-org"] } }
}
```

`writable` adds caches that a session opened with `task.py open` may write besides its clone and
scratch folder. `mcp` lists, per guarded service, the targets a `remote-write` task may change
and a `paid-job` call may name (`"*"` for any) and, under `"servers"`, other names the host gives that service's server.

## A task in its own clone

`task.py open <task> --host claude|codex --size S --allow P` (the human's command, in the shared
checkout) makes `../<repo>-<task>` with `git clone --no-local` (its own object store), a branch
`feat/<task>`, a scratch folder outside `AGENTKEEL_HOME`, and an opened-task record. It starts the
host in the clone with that session's sandbox boundary. The session start binds the session to the
task, so the agent does not run `task.py start`. `task.py import <task> --sha <full id>` fetches the
clone's branch with a fixed git and accepts it as `refs/agentkeel/accepted/<task>` only if it is
exactly that commit; nothing else moves. `task.py release <task>` deletes the clone, scratch folder
and records. It refuses while a process works in the clone, while its tip, a branch, a stash entry
or a changed, staged or untracked file is not preserved in the shared repository, and while any of
this cannot be read; `--discard` deletes anyway. It never deletes a folder that is not proven to be
the clone `open` made (its inode and the id `open` wrote into its `.git`), not even with `--discard`. `import` and `release` take the same lock.

`commands` adds regular expressions to a permission's built-in list; they are matched against the command's words, both as typed and with `npx`/`bunx` removed.
