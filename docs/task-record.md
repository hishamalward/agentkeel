# The task record

Before its first write, the agent declares its task in one command. The record answers three separate questions: how much process (size), which actions (permissions) and where (worktrees). The hooks read it on every tool call.

A repository opts in once, before any task: `task.py init` in the repository creates `agentkeel.json` when it is missing (it never changes an existing one), keeps one agentkeel block in `AGENTS.md` (the shared instructions for both hosts; never a `CLAUDE.md`), registers the opt-in for the repository and all its worktrees, and reports what the policy turns on, the human's profile (its path and line count, or none), and each host's install, enable and trust state. It does not commit.

Declare it from your reading of the human's request:

```
python3 "<task.py path printed at session start>" start <task-id> --size small|medium|large --allow <permissions> \
    [--write-root DIR]... [--worktree DIR]... [--resource NAME]...
```

Later examples abbreviate that command as `task.py`. A project install uses
`.claude/hooks/task.py`; a plugin uses the path printed at session start.

It writes `~/.agentkeel/tasks/<session-id>.json` (`AGENTKEEL_HOME` moves it). The guards read it on every tool call. Fields: `task`, `session_id`, `size`, `permissions`, `worktrees`, `write_roots`, `resources`, `evidence`, `history`.

## Three questions, answered separately

| Question | Values | Rule |
|---|---|---|
| Size | `small`, `medium`, `large` | how much process the task buys; it grants no action |
| Permissions | `review`, `implement`, `merge`, `push`, `distribution-build`, `store-submission`, `paid-job`, `remote-write`, `publish` | each action needs its own; "merge and push" means `implement,merge,push` |
| Resources | worktrees, write roots, named resources | where the task may write; everything else belongs to someone else |

| Size | Process | The hooks require |
|---|---|---|
| `small` | its own branch and worktree or isolated clone; no plan document, no subagents; one check; short report | a declared task; code edits off the protected branch |
| `medium` | as small, plus tests and one review round | the same |
| `large` | an approved boundary on the feature's state page; a plan table (its Working section) gated once; per-task and whole-branch review | no edit outside `docs/` before the boundary is approved; then only the approved boundary's `Changes` paths, in every repository the task spans (one page; `<repository>:<path>` entries for the others, see html-records.md) |

| Permission | Allows |
|---|---|
| `review` | writing the `--write-root` folders only (report folders outside any repository) |
| `implement` | editing the task's own worktrees or isolated clone, commits with explicit paths, local checks and local builds, local pushes between non-protected branches, files in the task's scratch; an isolated session's sandbox still limits these actions |
| `merge` | `gh pr merge` (together with `push`); moving a protected branch locally: a commit on it, `merge`, `merge --ff-only`, `reset`, `rebase`, `update-ref`, `fetch . x:main`, `branch -f` |
| `push` | every push to a remote, the task's own branch included; deploy commands (`railway up`, `vercel --prod`, `fly deploy`, `netlify deploy --prod`) |
| `distribution-build` | `eas build`, `xcodebuild archive`, `fastlane gym` and similar |
| `store-submission` | `eas submit`, `eas update`, `npm publish`, `fastlane deliver/pilot/supply`; MCP calls that change or submit products in the app stores (RevenueCat `submit_products_to_store` and its product store state operations), on a listed target |
| `paid-job` | the command patterns a repository lists in `agentkeel.json`; MCP calls that bill per call (DataForSEO `/live` and `task_post`, Sentry Seer analysis, which also needs its organization listed under `mcp`) |
| `remote-write` | MCP calls that change a guarded service (RevenueCat, PostHog, Sentry), only on a target `agentkeel.json` lists for it; a git push permission does not cover them, and `remote-write` never publishes or submits |
| `publish` | MCP calls that make something live for end users at once or send to them: a RevenueCat paywall published or unpublished, an experiment started or resumed; PostHog's publish, launch, ship, enable, roll-out and batch-run tools; on a listed target |

## Rules

- **No record, no writes.** A record belongs to one session. A second session, or a record file copied under another name, grants nothing. A subagent's tool calls carry its parent's session on both hosts (in Codex its own shell has its own id, so run task.py from the main agent).
- **Size never grants a permission.** Re-declaring with a different size keeps the permissions exactly as given. Widening the permissions is printed on stderr and kept in `history`; say it in your next update.
- **State your reading, then proceed.** The record is your interpretation of the request. Ask only when information is missing, the request is unclear, or an action would go past it.
- **When in doubt, smaller.** A task never grows on its own: if it turns out bigger, stop and say so; re-scoping is the human's.
- **Scratch**: each record has a scratch folder (`$TMPDIR/agentkeel-scratch/<session>`, printed by `task.py start`). Temp paths that name the session (Claude Code's own scratchpad does) are scratch too. Any other temp file belongs to someone else.
- **Write roots are report folders outside any repository.** `task.py start` refuses one inside a repository, and the guard ignores one there. A report that must land in the repository (an audit under `docs/`) needs `implement` in the task's own worktree or isolated clone, under the normal write rules.
- **Every code task has its own worktree or isolated clone**, even when you are the only agent. File-tool code edits in the shared checkout are refused on every branch, and `task.py start` there records no worktree. Create one with `git worktree add ../<repo>-<task> -b feat/<task>` (recorded as the task's automatically), or have the human use `task.py open` for an isolated clone.
- **Explicit-path commits**: `git commit -m "..." -- <paths>`. A bare `git commit` commits the whole index, including what another agent staged. Finishing a merge is the one exception (git refuses a partial commit then).
- **A new task in the same session starts fresh.** Only re-declaring the same task id keeps its worktrees, write roots and evidence.
- **Evidence**: `task.py verify -- <command>` runs a check; the hooks record its result, not the command. The guard notes the start with `HEAD` and a tree id, read without running anything the repository's config names; the PostToolUse hook records "passed" only for a foreground success that Claude Code reports with `interrupted` false, on unchanged code. A background run, an interrupted run, a run where the code moved, and every Codex run (no exit status reaches its hooks) are unrecorded or stale. A failure leaves the run pending. It is a record, not a gate: shipping is gated by the CI required check.
- **The human approves a boundary**: `task.py approve <feature|page>` writes the page's `keel-approval` meta (a digest of the boundary, the approver from git `user.name`, the date) and keeps the approved boundary in `AGENTKEEL_HOME/approvals/`. The guard refuses it when the agent runs it, and refuses an agent edit that adds, changes or removes the approval, or that renames or deletes an approved page. The human runs it in a terminal of their own.
- **`task.py status [--json]`** prints derived facts and changes nothing. It works with or without a session, so a human runs it in their own terminal too. It shows this session's task, if any, and for each of its worktrees that still exists: the branch, the tip, how many commits are not in the protected branch, whether the tip is in it ("merged"), and how many files are changed or untracked. A worktree is read without running anything its repository's config names; one that cannot be read says so and is never called clean. Then the tasks opened in their own clones for this repository, each "ready to release" or with what `release` would refuse on; the repository's other worktrees, each "foreign: task <id>" or "no task record"; and each state page's State now with the result of each claim ([claims](html-records.md#claims-the-check-proves)).
- **`task.py end`** drops the record and lists what the task owned. It does not remove the task's worktrees or slots. While the record exists, the stop hook reports at the end of each turn what the task still holds: each worktree that still exists (its branch, whether its tip is merged into a protected branch and so can be removed, or how many commits are not, and how many files are changed or untracked), and for a session opened with `task.py open`, whether its clone is ready to release or why not. It speaks once per distinct report and removes nothing. Ordinary worktree cleanup needs authorization; an isolated clone is removed by the human with `task.py release`.

## Changing permissions

In an ordinary session, use the same declaration command when the user's request changes:

```text
task.py start <task> --size <size> --allow <the full set>
```

The full set replaces the old permissions: leaving one out revokes it for the next call. The
same task keeps its identity, worktrees, report folders, resources, evidence and history.
Declare permissions already granted by the request without asking again. Do not edit record
files by hand.

An isolated session opened with `task.py open` cannot write its task records or widen its
sandbox. To change its permissions or writable paths, the human preserves and imports the work,
ends the session, releases its clone, then opens the task with the new settings. Import alone
does not close the existing task. This is a limit of the current isolated workflow.

## The human's profile

`profile.md` in `AGENTKEEL_HOME` (default `~/.agentkeel/profile.md`) holds the human's standing preferences for every session on both hosts. In a repository that opted in, the session-start message prints it after the lines that say where the session is and before the task instructions, under one heading line with its path and line count. The agent follows it. It is plain text for the session: it grants no permission and changes no guard. At most 200 lines or 8,000 characters are printed, and one line says so when it is cut. A missing or empty file prints nothing. A session opened in its own clone gets it too.

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

`commands` adds regular expressions to a permission's built-in list. They match the command's
words, both as typed and with `npx`/`bunx` removed.

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
