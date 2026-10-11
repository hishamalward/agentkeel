# Guardrails

What each hook refuses, what it cannot see, and the test that proves each protection. The guarantee is "this agent's tool calls were checked", never "nothing else touched the tree".

## Hooks

Seven hooks and one command, Python 3.10+ and bash 3.2, no dependencies. A guard reads the tool call as JSON on stdin ([captured payloads](hook-payloads.md)), then allows it (exit 0) or blocks it with a reason the model reads (exit 2). The session-start and stop hooks only report.

1. **Tool call**: the host sends the call to the hook as JSON.
2. **Events**: `host.py` turns it into file edits, shell commands or dispatches.
3. **Judge**: each guard checks the events against the task record and `agentkeel.json`.
4. **Allow or refuse**: exit 0 inside the task; exit 2, with the reason, outside it.

| Hook or command | Runs on | Effect |
|---|---|---|
| `task-guard.py` | before every tool call, both hosts | writes, commits, moves and pushes outside the task record (the table below) |
| `secret-guard.py` | before a shell command | printing `.env*` (not `.env.example`), key files and credentials; bare `env` or `printenv`; `echo $SECRET_NAME`; `git show` or `diff` of `.env` |
| `plan-gate-guard.py` | before a subagent dispatch | a third gate dispatch for the same plan; on Codex, a third `plan_gate*` task name per task |
| `plan-size-guard.sh` | after a file edit | nothing; it reports a Working section over 300 lines |
| `verify-record.py` | after a tool completes | records verification evidence for the matching call; Codex results stay unrecorded because its hooks provide no exit status |
| `session-start.py` | session start, plugin only | nothing; it prints where the session is, the human's profile (`AGENTKEEL_HOME/profile.md`, at most 200 lines or 8,000 characters, as plain context that grants no permission), the task command's real path and the session id |
| `stop-report.py` | the end of every turn, both hosts | nothing; it reports to the human what the session's task still holds (each worktree: branch, merged or commits not merged, changed files; an opened clone: ready to release or why not), once per distinct report, and never removes anything |
| `task.py` | the agent runs it | nothing; it declares, shows, verifies and ends a task, reports status, and starts, reads, finishes, checks and indexes docs pages. `approve` and `reopen` are the human's. |

## Protections

Each row says what kind of protection it is: **prevents** (refused before it happens), **warns after**, **guidance only**, or **unsupported**. Test names are classes in `tests/`.

| Protection | Kind | Tested in |
|---|---|---|
| No write without a task declared by this session; another session cannot reuse it | prevents | NoTask, SessionBinding |
| Writes only in the task's worktrees, its write roots and its own scratch; a review writes only its report folder, outside any repository | prevents | WriteRoots, ReviewFindings |
| File-tool code edits only in the task's own worktree or isolated clone, never the shared checkout or a protected branch | prevents | Branches, StageReviewFindings |
| Commits name their paths, so another agent's staged files never ride along | prevents | Commits |
| A protected branch moves locally (commit, merge, reset, rebase, `update-ref`, `fetch .`) only with `merge` | prevents | Shipping |
| Every remote push needs `push`; local pushes between unprotected branches need `implement`. `gh pr merge` needs `merge` and `push` and is refused under the CI push gate | prevents | Shipping, StageReviewFindings |
| Force push, remote branch delete, `reset --hard`, whole-tree checkout or restore, `clean -f`, `branch -D`, `stash drop/clear/pop` | prevents, with a logged override | Destructive |
| `eas build/submit/update`, `npm publish`, deploy commands and repository-listed paid jobs only with their permission (also through `npx`, `pnpm exec`; a `--dry-run` is not the action) | prevents, for the listed shapes | CommandClasses |
| Hook config, `agentkeel.json` and AgentKeel state are not editable by the agent's file tools | prevents | ProtectedConfig |
| A large task edits nothing outside `docs/` before its boundary is approved, then only the approved Changes paths; an empty Changes list grants nothing; the agent cannot add, change or remove an approval | prevents | LargeAndBoundaryApproval, EmptyChangesList |
| An agent's push to `main`, and a local move to a known commit, land only a commit whose docs check passes, named by full SHA, alone in its call; an error while checking the move refuses it | prevents, for those moves; a commit on `main`, a rebase or a non-fast-forward merge is checked later, at the push and in CI ([limits](html-records.md#current-limitations-and-open-decisions)) | DocsGate, StageTwoBReviewFindings |
| An agent ships to `main` only a commit whose required check passed (`require_check_before_push`) | prevents, for a full-SHA push alone in its call; other forms and `gh pr merge` are refused | PushGate |
| A printed secret | prevents, for the listed shapes | `test_secret_guard.py` |
| A third plan-gate dispatch | prevents: Claude uses `[plan-gate]` and the plan path (with a heuristic fallback); Codex uses a `plan_gate*` task name | `test_plan_gate_guard.py` |
| A Working section over 300 lines | warns after | `test_plan_size_guard.py` |
| Worktrees and clones a task leaves behind | reports after each turn, never removes; an unreadable worktree is reported as unreadable | StopReport |
| The same protections on Codex (`apply_patch`, shell, subagents) | prevents | SameDecision, CapturedShapes |
| An unknown host tool that may write (Codex `write_stdin` included) | prevents: refused with a reason; MCP servers follow the [MCP catalog](#mcp-catalog) instead | ConfiguredRoute |
| One review round per scope (G3) | guidance only |  |
| Cursor, Copilot and other hosts | unsupported: no adapter; a host that loads `AGENTS.md` receives the shared instructions only |  |
| In a session started with `task.py open`: a shell write outside the task's clone, scratch folder and declared caches, from any command, script or child process | prevents, by the host's OS sandbox (Claude Code `--settings`, Codex permission profile) | Open, ImportAndRelease; live on both hosts |
| `task.py open`, `import`, `release` and `reopen` are the human's commands | prevents | Open, ImportAndRelease, FixGuards |
| A `fix` task edits no code before a failed check and a cause line are on record, and stops after three edit-then-fail cycles | prevents | FixGuards |
| Any guard can be set to `warn` or `off` in `agentkeel.json` | configurable | GuardModes |
| An MCP server in the [catalog](#mcp-catalog) (shipped: RevenueCat, PostHog, Sentry, DataForSEO; any other added in `agentkeel.json`): a remote change needs `remote-write` and a listed target, a billed call needs `paid-job` and a listed target when it names one, a call that publishes to end users needs `publish`, a call that changes or submits store products needs `store-submission`, a tool not listed by name is refused | prevents, also for Codex calls inside `exec` | Adapters, Generic, Merge; live on both hosts |
| An MCP server with no catalog entry | `guards.mcp_unknown`: passes (the default), warns or is refused; each tool is noted once per task, argument names only | UnknownServers |
| A plugin hook's interpreter or imports redirected by the environment | prevents: the hooks run through `run.sh` (recorded interpreter, `-I`, emptied environment) | HookLauncher |
| A test run's result is recorded by the hooks, bound to `HEAD` and the tree; only an unambiguous foreground success on unchanged code is "passed" | records; Codex runs stay unrecorded | Evidence |
| Shell writes that are not git and commands inside scripts, in a session not started with `task.py open`; browser automation | unsupported |  |

## Guard modes

`agentkeel.json` sets each guard's mode:

```
{ "guards": { "task": "block", "secret": "block", "plan_gate": "block", "plan_size": "block", "fix": "block" } }
```

| Mode | Effect |
|---|---|
| `block` | the call is refused with the reason (the default) |
| `warn` | the call runs; the refusal text goes to the human and the agent as a system message marked "(warn mode, the call ran)" |
| `off` | the guard is silent |

A missing key or an unknown value means `block`. Each guard reads only its own key: `task` does not soften `secret`. Shipping has no mode: it is a permission.

`mcp_unknown` has modes of its own, for an MCP server with no [catalog](#mcp-catalog) entry: `pass` (the default when the key is missing, so the host's own servers such as `ide` or `claude-in-chrome` keep working), `warn` (the call runs, with the system message) and `block` (refused, with how to add the server). An unknown value means `block`.

## The fix guards

A task declared `--kind fix` gets three refusals. They apply to code edits (Edit, Write, `apply_patch`); a path under `docs/` is exempt. Mode key: `fix`.

1. **No failed check yet.** The message asks the agent to reproduce the bug first with `task.py verify -- <command>`. A run that exits non-zero records a "failed" entry itself.
2. **No cause on record.** The message asks for `task.py cause "X causes Y because Z"`. The guard checks that a cause line exists, not that it is true.
3. **Three cycles used.** An edit, then a failed check, is one cycle. The fourth edit is refused until the human runs `task.py reopen <task>` in a terminal of their own. A session that runs it is refused.

The method is the `debugging` skill: reproduce, find the cause, change one thing, check.

## MCP catalog

The catalog says, per service, which tools are reads and which change, bill, publish or submit. It is
three layers, merged in this order, the most specific last:

1. the plugin's `hooks/agentkeel_core/mcp_catalog.json`: RevenueCat, PostHog, Sentry and DataForSEO
2. the human's `~/.agentkeel/mcp_catalog.json` (`AGENTKEEL_HOME` moves it), optional, for every repository
3. the project's `agentkeel.json` `"mcp"` block

An entry, in any layer, may carry:

| Field | Meaning |
|---|---|
| `servers` | the server names the host gives the service (`mcp__<server>__<tool>`); default: the service key |
| `read`, `write`, `paid`, `publish`, `store` | exact tool names per class; the permission each class needs is in the [task record](task-record.md#size-kind-permissions-resources) |
| `unclassified` | tools not sorted yet (what `task.py mcp draft` writes): judged as `write`, and without `target_arg` they pass only with `"targets": ["*"]` |
| `targets` | the targets a call may change (`"*"` for any) |
| `target_arg` | the argument that names the target; absent, the service's operations have no target and need only the permission |
| `note` | documentation |

Lists merge by union, so a project can add a tool to PostHog's `read` list; `targets`, `target_arg`
and `note` come from the most specific layer that sets them. A tool listed in more than one class
takes the class that asks the most (store, publish, paid, write, then read), so a layer can add a
name but cannot turn a listed write into a read. The four shipped services keep their own target
logic (RevenueCat `project_id`, the Sentry organization, the PostHog pin, DataForSEO's billed paths);
any other service is generic: its lists, and its `target_arg`.

A call on a server with no entry follows `guards.mcp_unknown` ([guard modes](#guard-modes)). In
every mode the guard appends one line per tool, once per task, to `mcp-unseen.jsonl` in the task's
scratch folder: `{"server", "tool", "args_keys", "ts"}`, the argument names and never their values.
`task.py mcp draft <server>` prints an entry from it, every tool under `unclassified`, with
`"servers": [<server>]` and `"targets": []`. The human moves each tool to its class, lists the
targets, sets `target_arg`, and pastes the entry under `"mcp"` in `agentkeel.json`.

## Blind spots

Hooks see a tool call, not the filesystem and not the process it starts.

| Guard | Sees | Does not see |
|---|---|---|
| `task-guard.py` | file-tool paths; every simple command in a shell line; every git call with its options and aliases | `sed -i`, redirects, `mv`; a script or npm script that writes or runs git |
| `secret-guard.py` | commands that print env files, key files, the environment or secret-named variables | a program that reads and prints a value; a secret in a file with a name it does not know |
| `plan-gate-guard.py` | dispatches that name a plan, with the marker or the gate words | a dispatch worded to avoid the heuristic |
| `plan-size-guard.sh` | the Working section's length after a write | a plan split across pages |

Wrapper commands (`sudo`, `env`, `nice`, `timeout`, `caffeinate`, `rtk`) are stripped before a command is judged. `rtk` is unwrapped, so the shipping checks fire under an `rtk` prefix. Hook order matters: an `rtk` rewrite hook must run after AgentKeel's PreToolUse guard, or the guard sees the rewritten command.

## Where a refusal comes from

Every refusal names what decided it, and the smallest step that resolves it is that decider's. The
hooks never override a host's decision.

| The message says | Decided by | Resolution |
|---|---|---|
| `AGENTKEEL: ... needs the '<permission>' permission; task '<id>' has ...` | the task's own permissions | when the request grants the action, re-declare with `task.py start ... --allow <full set>`; isolated sessions use the [reopen procedure](task-record.md#changing-permissions) |
| `AGENTKEEL: refusing to write <path>: it belongs to ...` or `... is not one of task '<id>'s worktrees` | ownership of worktrees and write roots | work in the task's worktree, or add one with `--worktree` |
| `AGENTKEEL: <service> <name> is not an action agentkeel's <service> adapter knows` | the [MCP catalog](#mcp-catalog) (exact names: the plugin's `mcp_catalog.json`, `~/.agentkeel/mcp_catalog.json`, `agentkeel.json` `"mcp"`) | the human runs it, or lists the name in their catalog layer |
| `AGENTKEEL: the MCP server <server> (tool <tool>) has no entry in agentkeel's MCP catalog` | `guards.mcp_unknown` set to `block` (or `warn`, as a message) | the human adds the server under `"mcp"` in `agentkeel.json`; `task.py mcp draft <server>` prints a start |
| `AGENTKEEL: ... targets '<x>', which agentkeel.json does not list` or `... connection is not pinned` | `agentkeel.json` targets and the host's own connection entry | list the target, or pin the connection on the host (`x-posthog-project-id`) |
| `AGENTKEEL: size large needs an approved boundary` | the human's approval of the page | `task.py approve <task>`, run by the human |
| `AGENTKEEL: agentkeel cannot read the tool '<name>' and it may write` | a tool name the hooks do not know | a release lists the tool; until then use a tool the hooks read |
| `Operation not permitted`, `EPERM`, a sandbox or trust prompt | the host's sandbox or hook trust | the session's profile from `task.py open`; trust in the host's `/hooks` |
| "denied by the ... classifier", a permission prompt | the host's own permission system | the host's permission rules or the human's answer; not a hook's to change |
| HTTP 401 or 403, "needs authentication" | the remote service | sign in on the host (`/mcp`) or fix the credential |

## Overrides

Two overrides exist, each written as a prefix on the one command it applies to, so it applies once and the transcript shows it. Each use goes to `~/.agentkeel/overrides.jsonl`. A variable set in the host's own environment is not an override. Shipping has no override: it is a permission.

```
AGENTKEEL_ALLOW_DESTRUCTIVE=1 git reset --hard
AGENTKEEL_SHOW_SECRETS=1 cat .env
```

## Guidance for tools that write

For tools you build, use this pattern, taken from [toilscan](https://github.com/hishamalward/toilscan)'s `apply` path:

1. Preview by default. Nothing is written until the caller authorizes it.
2. Authorize each operation, never "apply all" by default.
3. Give stable IDs to what is written, so a re-run knows what it already did.
4. Write atomically: a temp file beside the target, then a rename.
5. Keep a journal of what was written, so the last apply can be undone.
6. Never move or push `main` without permission, never edit outside the task's worktrees, never print a secret.

The hooks check the supported operations described above, including shipping permissions.
They cannot enforce a tool's internal preview, journal or atomic-write design, or inspect all
secret reads and shell writes. Those are tool design responsibilities, not hook guarantees.

## Isolation is a different problem

A git worktree isolates files and nothing else. The database, the ports, the job queue and the simulator stay shared, and two agents on one machine collide there first. [AgentSlots](https://github.com/hishamalward/agentslots) handles that: one number gives each task a worktree, a database, two ports and a queue schema, with an exclusive simulator lock when needed.
