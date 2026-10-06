# Guardrails

What each hook refuses, what it cannot see, and the test that proves each protection. The guarantee is "this agent's tool calls were checked", never "nothing else touched the tree".

## Hooks

Six hooks and one command, Python 3.10+ and bash 3.2, no dependencies. A guard reads the tool call as JSON on stdin ([captured payloads](hook-payloads.md)), then allows it (exit 0) or blocks it with a reason the model reads (exit 2). The session-start and stop hooks only report.

1. **Tool call**: the host sends the call to the hook as JSON.
2. **Events**: `host.py` turns it into file edits, shell commands or dispatches.
3. **Judge**: each guard checks the events against the task record and `agentkeel.json`.
4. **Allow or refuse**: exit 0 inside the task; exit 2, with the reason, outside it.

| Hook | Runs on | Refuses |
|---|---|---|
| `task-guard.py` | before every tool call, both hosts | writes, commits, moves and pushes outside the task record (the table below) |
| `secret-guard.py` | before a shell command | printing `.env*` (not `.env.example`), key files and credentials; bare `env` or `printenv`; `echo $SECRET_NAME`; `git show` or `diff` of `.env` |
| `plan-gate-guard.py` | before a subagent dispatch | a third gate dispatch for the same plan; on Codex, a third `plan_gate*` task name per task |
| `plan-size-guard.sh` | after a file edit | nothing; it reports a Working section over 300 lines |
| `session-start.py` | session start, plugin only | nothing; it prints where the session is, the human's profile (`AGENTKEEL_HOME/profile.md`, at most 200 lines or 8,000 characters, as plain context that grants no permission), the task command's real path and the session id |
| `stop-report.py` | the end of every turn, both hosts | nothing; it reports to the human what the session's task still holds (each worktree: branch, merged or commits not merged, changed files; an opened clone: ready to release or why not), once per distinct report, and never removes anything |
| `task.py` | the agent runs it | nothing; it declares, shows, verifies and ends a task, reports status, and starts, reads, finishes, checks and indexes docs pages. `approve` is the human's. |

## Protections

Each row says what kind of protection it is: **prevents** (refused before it happens), **warns after**, **guidance only**, or **unsupported**. Test names are classes in `tests/`.

| Protection | Kind | Tested in |
|---|---|---|
| No write without a task declared by this session; another session cannot reuse it | prevents | NoTask, SessionBinding |
| Writes only in the task's worktrees, its write roots and its own scratch; a review writes only its report folder, outside any repository | prevents | WriteRoots, ReviewFindings |
| Code edits only in the task's own linked worktree, never the shared checkout, never on a protected branch | prevents | Branches, StageReviewFindings |
| Commits name their paths, so another agent's staged files never ride along | prevents | Commits |
| A protected branch moves locally (commit, merge, reset, rebase, `update-ref`, `fetch .`) only with `merge` | prevents | Shipping |
| Every push only with `push`, including `+main`, compound lines, `-C`, `-c`, aliases and `remote.*.push`; `gh pr merge` only with `merge` and `push` | prevents | Shipping, StageReviewFindings |
| Force push, remote branch delete, `reset --hard`, whole-tree checkout or restore, `clean -f`, `branch -D`, `stash drop/clear/pop` | prevents, with a logged override | Destructive |
| `eas build/submit/update`, `npm publish`, deploy commands and repository-listed paid jobs only with their permission (also through `npx`, `pnpm exec`; a `--dry-run` is not the action) | prevents, for the listed shapes | CommandClasses |
| Hook config, `agentkeel.json` and AgentKeel state are not editable by the agent's file tools | prevents | ProtectedConfig |
| A large task edits nothing outside `docs/` before its boundary is approved, then only the approved Changes paths; an empty Changes list grants nothing; the agent cannot add, change or remove an approval | prevents | LargeAndBoundaryApproval, EmptyChangesList |
| An agent's push to `main`, and a local move to a known commit, land only a commit whose docs check passes, named by full SHA, alone in its call; an error while checking the move refuses it | prevents, for those moves; a commit on `main`, a rebase or a non-fast-forward merge is checked later, at the push and in CI ([limits](html-records.md#current-limitations-and-open-decisions)) | DocsGate, StageTwoBReviewFindings |
| An agent ships to `main` only a commit whose required check passed (`require_check_before_push`) | prevents, for a full-SHA push alone in its call; other forms and `gh pr merge` are refused | PushGate |
| A printed secret | prevents, for the listed shapes | `test_secret_guard.py` |
| A third plan-gate dispatch | prevents with the `[plan-gate]` marker; heuristic without it | `test_plan_gate_guard.py` |
| A Working section over 300 lines | warns after | `test_plan_size_guard.py` |
| Worktrees and clones a task leaves behind | reports after each turn, never removes; an unreadable worktree is reported as unreadable | StopReport |
| The same protections on Codex (`apply_patch`, shell, subagents) | prevents | SameDecision, CapturedShapes |
| A tool that may write but has no adapter (Codex `write_stdin` included) | prevents: it is refused with a reason | ConfiguredRoute |
| One review round per scope (G3) | guidance only |  |
| Cursor, Copilot and other hosts | unsupported: no adapter; a host that loads `AGENTS.md` receives the shared instructions only |  |
| In a session started with `task.py open`: a shell write outside the task's clone, scratch folder and declared caches, from any command, script or child process | prevents, by the host's OS sandbox (Claude Code `--settings`, Codex permission profile) | Open, ImportAndRelease; live on both hosts |
| `task.py open`, `import` and `release` are the human's commands | prevents | Open, ImportAndRelease |
| A guarded MCP server (RevenueCat, PostHog, Sentry, DataForSEO): a remote change needs `remote-write` and a listed target, a billed call needs `paid-job` and a listed target when it names one, a tool not listed by name is refused | prevents, also for Codex calls inside `exec` | Adapters; live on both hosts |
| A plugin hook's interpreter or imports redirected by the environment | prevents: the hooks run through `run.sh` (recorded interpreter, `-I`, emptied environment) | HookLauncher |
| A test run's result is recorded by the hooks, bound to `HEAD` and the tree; only an unambiguous foreground success on unchanged code is "passed" | records; Codex runs stay unrecorded | Evidence |
| Shell writes that are not git and commands inside scripts, in a session not started with `task.py open`; other MCP servers; browser automation | unsupported |  |

## Blind spots

Hooks see a tool call, not the filesystem and not the process it starts.

| Guard | Sees | Does not see |
|---|---|---|
| `task-guard.py` | file-tool paths; every simple command in a shell line; every git call with its options and aliases | `sed -i`, redirects, `mv`; a script or npm script that writes or runs git |
| `secret-guard.py` | commands that print env files, key files, the environment or secret-named variables | a program that reads and prints a value; a secret in a file with a name it does not know |
| `plan-gate-guard.py` | dispatches that name a plan, with the marker or the gate words | a dispatch worded to avoid the heuristic |
| `plan-size-guard.sh` | the Working section's length after a write | a plan split across pages |

## Overrides

Two overrides exist, each written as a prefix on the one command it applies to, so it applies once and the transcript shows it. Each use goes to `~/.agentkeel/overrides.jsonl`. A variable set in the host's own environment is not an override. Shipping has no override: it is a permission.

```
AGENTKEEL_ALLOW_DESTRUCTIVE=1 git reset --hard
AGENTKEEL_SHOW_SECRETS=1 cat .env
```

## The pattern on every write path

A tool that writes follows this pattern, taken from [toilscan](https://github.com/hishamalward/toilscan)'s `apply` path:

1. Preview by default. Nothing is written until the caller authorizes it.
2. Authorize each operation, never "apply all" by default.
3. Give stable IDs to what is written, so a re-run knows what it already did.
4. Write atomically: a temp file beside the target, then a rename.
5. Keep a journal of what was written, so the last apply can be undone.
6. Never move or push `main` without permission, never edit outside the task's worktrees, never print a secret.

The hooks enforce item 6 and the permission half of item 2. Items 1, 3, 4 and 5 are how to build a tool that writes; a hook cannot enforce them from outside.

## Isolation is a different problem

A git worktree isolates files and nothing else. The database, the ports, the job queue and the simulator stay shared, and two agents on one machine collide there first. [agent-slots](https://github.com/hishamalward/agent-slots) handles that: one number gives each agent a worktree, a database, two ports and a queue schema.
