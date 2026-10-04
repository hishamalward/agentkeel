# The task record

Declare before the first write, in one command, from your reading of the human's request:

```bash
.claude/hooks/task.py start <task-id> --size small|medium|large --allow <permissions> \
    [--write-root DIR]... [--worktree DIR]... [--resource NAME]...
```

It writes `~/.agentkeel/tasks/<session-id>.json` (`AGENTKEEL_HOME` moves it). The guards read it
on every tool call. Fields: `task`, `session_id`, `size`, `permissions`, `worktrees`,
`write_roots`, `resources`, `evidence`, `history`.

## Three questions, answered separately

| Question | Values | Rule |
|---|---|---|
| Size | `small`, `medium`, `large` | how much process the task buys; it grants no action |
| Permissions | `review`, `implement`, `merge`, `push`, `distribution-build`, `store-submission`, `paid-job` | each action needs its own; "merge and push" means `implement,merge,push` |
| Resources | worktrees, write roots, named resources | where the task may write; everything else belongs to someone else |

| Size | Process | The hooks require |
|---|---|---|
| `small` | its own branch and worktree; no plan document, no subagents; one check; short report | a declared task; code edits off the protected branch |
| `medium` | as small, plus tests and one review round | the same |
| `large` | an approved spec; a plan table gated once; per-task and whole-branch review | no edit outside `docs/` before the spec is approved; then only its `Changes` paths |

| Permission | Allows |
|---|---|
| `review` | writing the `--write-root` folders only (a report page, an audit) |
| `implement` | editing the task's worktrees, commits with explicit paths, local checks and local builds, pushing its own branch, scratch files in temp folders outside any repository |
| `merge` | moving a protected branch locally: a commit on it, `merge`, `merge --ff-only`, `reset`, `rebase`, `update-ref`, `fetch . x:main`, `branch -f` |
| `push` | pushing to a protected branch; deploy commands (`railway up`, `vercel --prod`, `fly deploy`, `netlify deploy --prod`) |
| `distribution-build` | `eas build`, `xcodebuild archive`, `fastlane gym` and similar |
| `store-submission` | `eas submit`, `eas update`, `npm publish`, `fastlane deliver/pilot/supply` |
| `paid-job` | the command patterns a repository lists in `agentkeel.json` |

## Rules

- **No record, no writes.** A record belongs to one session. A second session, or a record file
  copied under another name, grants nothing. Subagents share their parent's session.
- **Size never grants a permission.** Re-declaring with a different size keeps the permissions
  exactly as given. Widening the permissions is printed on stderr and kept in `history`; say it
  in your next update.
- **State your reading, then proceed.** The record is your interpretation of the request. Ask
  only when information is missing, the request is unclear, or an action would go past it.
- **When in doubt, smaller.** A task never grows on its own: if it turns out bigger, stop and say
  so; re-scoping is the human's.
- **Every code task has its own worktree**, even when you are the only agent: `git worktree add
  ../<repo>-<task> -b feat/<task>` (recorded as the task's automatically). The protected branch
  stays clean for merges.
- **Explicit-path commits**: `git commit -m "..." -- <paths>`. A bare `git commit` commits the
  whole index, including what another agent staged. Finishing a merge is the one exception (git
  refuses a partial commit then).
- **A new task in the same session starts fresh.** Only re-declaring the same task id keeps its
  worktrees, write roots and evidence.
- **Evidence**: `task.py verify -- <command>` runs a check and records its exit code against
  `HEAD` and whether the tree was dirty. It is a record, not a gate.
- **The human approves specs**: `task.py approve <task-id>` sets `status: approved`,
  `approved_by` (git `user.name`) and `approved_on`. The guard refuses it when the agent runs it,
  and refuses an agent edit that would mark a spec approved. In Claude Code the human runs it as
  `! .claude/hooks/task.py approve <task-id>`.
- **`task.py end`** drops the record and lists what the task owned.

## The repository policy file

`agentkeel.json` at the repository root is optional and is never editable by the agent's file
tools:

```json
{
  "protected_branches": ["main", "release"],
  "commands": { "paid-job": ["^npx tsx scripts/eval-"] }
}
```

`commands` adds regular expressions to a permission's built-in list; they are matched against the
command's words, both as typed and with `npx`/`bunx` removed.
