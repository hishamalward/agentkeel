# Enforcement beyond tool calls: design

This page says what each layer can enforce today, on each host, and how AgentKeel closes its two
largest gaps: shell and script writes outside a task's boundary, and MCP calls that change, publish,
deploy or spend. Nothing on it is built. The feasibility results come from throwaway repositories
on macOS with Claude Code 2.1.290 and Codex 0.160.0 (2026-10-06); each one names what it proves and
what it leaves open.

## Who enforces what, today

| Layer | Claude Code | Codex | AgentKeel today |
|---|---|---|---|
| File tools (Edit, Write, `apply_patch`) | permission rules only; the sandbox does not cover them | `apply_patch` is a tool the hooks see | **prevents**: the task guard checks every path |
| Shell and its child processes (`>`, `sed -i`, python, node, nested scripts) | the OS sandbox covers them when it is on | the OS sandbox covers them; the permission profile sets the boundary | git commands and named file commands only; a write inside a script or a redirect is **not seen** |
| MCP calls | PreToolUse sees `mcp__<server>__<tool>` with its arguments and can block it | MCP tools are offered only inside the JavaScript `exec` tool; each nested call is dispatched as its own MCP call | **unsupported**: every MCP call passes |
| Hosted tools (web search) | not hooked | not hooked | unsupported |
| Hooks and local MCP servers | run outside the sandbox | hooks run outside the sandbox | not applicable |

On the founder's machine today: Claude Code has no `sandbox` settings in any scope. Codex runs with
`default_permissions = "ma-dev"`, a profile that extends `:workspace` and adds `":root" = "write"`
with five credential paths denied, so a Codex shell can write almost anywhere. Neither host limits a
shell write to the task.


## Part 2: shell and script isolation

The OS sandbox of each host is the enforcement. AgentKeel sets its write boundary to the task, keeps
its own control state out of reach, and proves the boundary on each host. A longer list of command
patterns is not isolation and is not claimed as such.

### A task works in its own independent clone

A commit in a linked worktree writes the shared `.git/objects`. Write access to that folder is also
the power to delete or overwrite any object in it, which damages every branch. Measured:

- Codex, a profile that grants only the worktree's metadata, its branch ref and its log: `git add`
  fails (`unable to index file`). Adding `.git/objects` makes the commit work, and the same sandboxed
  shell then deleted an existing shared object.
- Claude Code documents that in a linked worktree its sandbox allows writes to the whole shared `.git`
  except `hooks/` and `config`, so the objects are writable there by default.

So each task works in a clone with its own object store, made with `git clone --no-local`: no
alternates file, and no object file hard-linked to the source (measured: link count 1). A clone made
with `--shared` is not used. It borrows the source's objects, so a branch deletion and a prune in the
source can break the task's history. Measured: after the source deleted a branch, expired its reflog
and pruned, a `--shared` clone of that branch could not read its own `HEAD`, and a `--no-local` clone
could. Cost on the pilot repository: 5 seconds and 161 MB for the clone's `.git` (the source `.git`
is 225 MB), before the checkout and the dependency install that a worktree also needs.

The task's commits land in the clone. The shared repository, its objects, its refs and every other
task's folders stay outside the boundary.

### Every task size gets a clone, and the ownership records follow it

Isolation does not depend on task size: a small task also works in its own clone. Because a clone
does not appear in `git worktree list`, the ownership, resume and cleanup behavior change together:

- **Ownership**: the task record names the clone's path, its branch and the full SHA of its base.
  The session banner and the ownership checks read the task records, not `git worktree list`.
- **Resume**: a resumed or new session for the same task opens the same clone from the record.
- **Cleanup**: `task.py release` (P4) removes a clone only when its branch is imported or the human
  says to drop it, the clone is clean, and the record still names this task.

### The import into the shared repository

The work returns through one trusted operation, `task.py import`, run outside the sandbox. It accepts
nothing from the task's own files:

1. **The source comes from the task record**: the clone's path and branch as `task.py open`
   recorded them. No path, remote, `upload-pack` command, refspec, destination or option comes from
   the agent.
2. **The expected commit is a full SHA** that the human approved or that the evidence names.
3. **A fixed execution**: `/usr/bin/git` with an empty environment (`PATH=/usr/bin:/bin`, `HOME`,
   `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`), `core.hooksPath=/dev/null`, `--no-tags`,
   `--no-recurse-submodules`.
4. **Into a staging ref only**: `refs/agentkeel/import/<task>`. Nothing else moves.
5. **The staged commit must equal the expected SHA**, or the staging ref is deleted and the import is
   refused.
6. **Moving `main` and shipping stay separate**, separately authorized operations.

Measured: the import of the expected SHA succeeded. After the clone's branch moved by one commit,
the same import was refused with "SHA mismatch", and `main` and the task branch did not change. A
clone with seven planted routes (`core.fsmonitor`, `core.hooksPath`, `uploadpack.packObjectsHook`,
`core.sshCommand` and three hooks) ran none of them during the fetch. These results are regression
tests for this command, not a proof that any fetch from agent-controlled Git state is safe. Still to
test: a replaced clone path or branch in the record, an unauthorized destination, and injected
execution config; each must fail or leave the accepted commit unchanged.

### The write boundary of a task

| Writable | Why |
|---|---|
| the task's clone, including its `.git` | the work and its commits |
| the task's scratch folder, which is also its `TMPDIR` | test and build output, temporary files |
| declared caches (for example `~/.npm`) | listed in `agentkeel.json` under `"writable"`; nothing by default |

| Not writable | Why |
|---|---|
| the shared checkout and its `.git` (objects, refs, config, hooks) | other agents' work and the merge target |
| other tasks' clones and scratch folders | isolation between tasks |
| `AGENTKEEL_HOME` (task records, approvals, opt-in registry, session settings) | a record, approval or boundary the agent could write proves nothing |
| host settings (`.claude/`, `.codex/`, `~/.codex/config.toml`) | the boundary must not edit itself |

### The boundary belongs to the session, set before its first command

One repository-local settings file is read by every session in that checkout, so changing it for task
B would change task A's running boundary. The boundary is set per session instead, before the session
starts: `task.py open <task> --host claude|codex`, run by the human, creates the clone and the
scratch folder, writes the task record, and starts the host in the clone with that session's
boundary. Nothing changes in user or project settings on either host.

- **Claude Code**: `claude --settings <AGENTKEEL_HOME>/sessions/<task>.json`, holding
  `sandbox.enabled`, `failIfUnavailable: true`, `allowUnsandboxedCommands: false` and
  `filesystem.allowWrite` for the scratch folder. The working folder (the clone) is writable by
  default.
- **Codex**: command-line overrides only, measured with no entry in `config.toml`:
  `-c permissions.<task>.extends=":workspace"`, `-c permissions.<task>.filesystem={...}` as one
  inline table (`":workspace_roots"` with `"."` and `".git"` set to `write`, the scratch folder set to
  `write`, `":tmpdir"` and `":slash_tmp"` set to `read`), `-c shell_environment_policy.set.TMPDIR=
  "<scratch>"`, `-P <task>` and `-C <clone>`. Dotted keys fail for paths that contain a dot, so the
  table form is required.

Measured on both hosts, two sessions for two tasks at the same time: each wrote its own scratch
folder and was refused at the other's.

Measured on both hosts, from inside one task's clone: a write to the clone and to its scratch folder,
`git add` and a signed `git commit` succeed. These fail before the file changes:

- a shell, Python and Node write to another task's clone
- a write to another task's scratch, to the shared checkout, to a shared object and to the shared
  `main` ref, and a `git push` to the shared `main`
- a symlink that points out of the clone
- a write to the host's settings (`.claude/settings.local.json` and the session settings file on
  Claude Code; the clone's `.codex/` and `~/.codex/config.toml` on Codex)
- on Codex, a test script and a `python3` placed first on `PATH` inside the clone, both aimed at
  another task's clone (still to repeat on Claude Code)

### Temporary folders

- **Codex**: the session closes `/tmp` and `$TMPDIR` and points `TMPDIR` at the task's scratch
  folder. A signed commit works this way (measured); with the temp folders closed and `TMPDIR` not
  moved, the SSH signer fails with `failed to write commit object`.
- **Claude Code**: limit. Sandboxed commands write to a per-user temp folder (`/tmp/claude-501`)
  that every Claude Code session of the same user shares. Denying it breaks signed commits and Claude
  Code's own working-folder tracking (measured). `CLAUDE_CODE_TMPDIR` set at launch did not change it
  in the test. AgentKeel reports this shared allowance instead of claiming isolation of temporary
  files between Claude Code sessions.

### task.py is not exempted from the sandbox

`task.py verify -- <command>` runs an arbitrary command, so exempting `task.py`, or Python in general,
would let any test script run outside the boundary. Instead:

- **Commands stay sandboxed.** `verify` runs its command inside the sandbox like any other command.
- **Control state is written only by trusted code outside the sandbox**: `task.py open` and
  `task.py import` (run by the human) and the hooks, which both hosts run outside the sandbox from the
  installed plugin. No session command is exempted.
- **The interpreter and the helper come from outside the task's reach.** The hook commands name the
  plugin's own files and a fixed interpreter path; a task's clone, `PATH` entries or `PYTHONPATH`
  inside the clone cannot replace them.

### Test evidence is bound to the completed run and the exact code

A hook writes the evidence, and it records "passed" only when all of these hold:

- **Start and completion are paired.** The PreToolUse event records the command, `HEAD` and a hash of
  the working tree; the completion event for the same call closes it.
- **The exit status is the real one.** Measured on Claude Code: a foreground success arrives as
  `PostToolUse` with no exit field, and a failure as `PostToolUseFailure` with "Exit code 1". A
  background command returns at once with only a `backgroundTaskId`, and its later `exit 3` reached
  no hook. So a background or still-running command is recorded as unrecorded, never passed. Codex:
  to measure in the trusted-hook run.
- **The code did not move.** If `HEAD` or the working-tree hash differs between start and completion,
  the run is recorded as stale.
- **Shipping accepts only clean, current evidence**: a passed run whose `HEAD` is the candidate's full
  SHA, with a clean tree. Missing completion, a missing exit status, a dirty tree or another commit
  means no evidence. A resumed shell process follows the same rule.

## Part 3: MCP calls with consequences

### What the pilot repository uses (sessions from 2026-07-28 to 2026-10-06)

| Server | Calls | Consequential actions seen |
|---|---|---|
| playwright (Codex), claude-in-chrome (Claude) | about 400 each | page JavaScript, form filling, clicks and navigation in signed-in pages |
| revenuecat (Codex) | about 110 | 2026-09-19 to 09-21: products, entitlements, offerings and packages created, attached, archived and deleted; a webhook integration created |
| posthog | 21 | two project settings updates (2026-10-04) |
| sentry | 10 | four issues set to resolved (2026-10-04) |
| dataforseo (Codex) | 17 | seven `api_request` calls, four to `/live` endpoints that bill per request (2026-10-01) |
| mobbin, expo, others | small | reads (`expo` listed builds; none started) |


### Interception comes first

An adapter has value only if every call it guards passes through it before the server receives it.

- **Claude Code, measured.** A synthetic MCP server records every call it receives; a session hook
  refuses one tool. Direct calls and two calls made in parallel in one message all reached the hook
  with their arguments. The refused calls reached the server zero times; the allowed reads reached it.
- **Codex, partly measured.** Codex 0.160.0 offered the test server's tools only inside the
  JavaScript `exec` tool. A direct call, a call by a name built at run time
  (`["mcp","akprobe","write_thing"].join("__")`) and two parallel calls each appeared as a separate MCP
  dispatch with the resolved tool name and arguments. In that run Codex's own approval check refused
  all four first, so the run does not show what the hook does. Codex documents that PreToolUse
  supports code-mode nested calls.
- **Still to measure on Codex**, with a test hook the founder has trusted and the test server's tools
  set to `approve` so that the hook, not the host's approval check, is the layer that refuses: a
  permitted read reaches both the hook and the server; the forbidden direct, built-name and parallel
  calls reach the hook, return its refusal, and reach the server zero times.
- **If the Codex hook does not see nested calls**, matching the `exec` source text is not a boundary
  (aliases and built names pass it). The options are Codex's own per-tool `approval_mode`, which is
  static and not task-aware, a gateway process in front of the guarded servers, or refusing `exec` in
  guarded mode. A gateway is then in scope, because it is the only mechanism left.

### The adapter

An adapter binds one server's tools to the task's permissions and to its allowed targets. It reads the
tool name and the arguments, never the tool's description or annotations.

- **Classes**: read (passes), remote-write (creates, updates, archives, deletes, resolves, changes
  settings), paid (bills per call), deploy, publish. An action the adapter does not know is refused in
  a guarded server, never assumed to be a read.
- **Permissions keep their meaning.** Remote writes need a new permission, `remote-write`, scoped to
  a service and a target. Paid calls need `paid-job`. Deploy and publish each need their own grant:
  `distribution-build` is not permission to deploy, and `store-submission` is not permission to
  publish anywhere else. A review task can change nothing.
- **Targets**: `agentkeel.json` names the allowed targets per server (for example one RevenueCat
  project, one PostHog project). A remote write to any other target is refused, even with
  `remote-write`.
- **Generic tools**: PostHog's `exec` is classified by its command verb, DataForSEO's `api_request`
  by method and path (`/live` is paid; `appendix/user_data` is a read).
- **First adapters**: revenuecat, posthog, sentry, dataforseo. Every other server stays explicitly
  unsupported and is listed as such in `init`'s report.
- **What an adapter does not protect.** A refusal stops that MCP call only. The same credentials used
  from a shell (`curl`), a script or a browser are outside the adapter, and the documentation says so.

### Browser automation

Clicks, navigation and form submits in a signed-in page can change remote state as surely as page
JavaScript, so guarding only forms and scripts would be incomplete. In this version, authenticated
remote browser activity is explicitly unsupported, and AgentKeel claims no browser enforcement. Local
visual QA against a local or disposable target stays available.


### Acceptance

The synthetic recording server stands in for each guarded server, on both hosts and through every
supported dispatch path (direct, nested, built name, parallel): reads pass; a permitted remote write
to the owned target passes; a remote write under a review task, a write to another target, a paid call
without `paid-job`, a deploy without its grant, a publish under `store-submission` alone and an unknown
action are refused, and the server's record shows zero calls for each refusal.

A batch means one tool call that carries several actions: the hook sees it whole before dispatch, and
one refused part refuses the whole batch. Separate parallel calls are not a batch: each forbidden call
must reach the server zero times, and its permitted siblings may run.

## Build order

1. Finish the feasibility checks:
   - the Codex trusted-hook run: nested MCP calls, and completion events with their exit status
   - the import contract's hostile cases (replaced path or branch, unauthorized destination,
     injected config)
   - on Claude Code, the test-script and `PATH` substitution probes
2. Shell isolation for both hosts: `task.py open`, independent clones, session-only boundaries,
   `task.py import`, evidence by hook, and the ownership, resume and cleanup changes.
3. The four adapters, after step 1 shows an interception path on each host.

This is integration work across both hosts, not a hook patch. An estimate in days waits for step 1.

## Decisions for the founder

1. **`remote-write`**, scoped to service and target, separate from `push`, with paid, deploy and
   publish still granted separately.
2. **Browser automation**: explicitly unsupported for remote changes in this version; local QA stays.
3. **Commits**: in an independent task clone, with the shared `.git` read-only. No writable shared
   `.git`, no prompt per commit.
4. **Settings**: per session on both hosts, written by `task.py open`; measured without a user-scope
   change.

## Not in this design

Other hosts, a new approval service, and proof of who approved. The task record still describes the
scope; it is not the human's consent. A gateway process is not excluded: it enters if Codex's hooks
cannot see nested MCP calls.
