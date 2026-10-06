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

### A task works in its own clone, not a linked worktree

A commit in a linked worktree writes the shared `.git/objects`. Write access to that folder is also
the power to delete or overwrite any object in it, which damages every branch. Measured:

- Codex, a profile that grants only the worktree's metadata, its branch ref and its log: `git add`
  fails (`unable to index file`). Adding `.git/objects` makes the commit work, and the same sandboxed
  shell then deleted an existing shared object.
- Claude Code documents that in a linked worktree its sandbox allows writes to the whole shared `.git`
  except `hooks/` and `config`, so the objects are writable there by default.

So the task's working copy is a clone made with `git clone --shared`: the clone's own `.git` is
writable, and it borrows the shared objects read-only through `objects/info/alternates`. A new object
lands in the clone. The shared repository, its objects, its refs and every other task's folders stay
outside the boundary.

The work returns to the shared repository through one judged step outside the sandbox: AgentKeel
fetches the task branch from the clone with `git -c core.hooksPath=/dev/null fetch`. The clone's
config and hooks are the agent's to edit, so the fetch must not run them. Measured: a clone with a
planted `core.fsmonitor`, `core.hooksPath`, `uploadpack.packObjectsHook`, `core.sshCommand` and
three hooks (`pre-upload-pack`, `post-checkout`, `reference-transaction`); the fetch brought the
commit and none of the seven ran.

What a clone changes: `git worktree list` no longer shows the task, so the session banner and the
ownership checks read AgentKeel's own task records instead. Merge and push stay judged git commands,
now run from the shared repository against the fetched branch.

### The write boundary of a task

| Writable | Why |
|---|---|
| the task's clone, including its `.git` | the work and its commits |
| the task's scratch folder | test and build output |
| declared caches (for example `~/.npm`) | listed in `agentkeel.json` under `"writable"`; nothing by default |

| Not writable | Why |
|---|---|
| the shared checkout, its `.git` (objects, refs, worktree metadata, config, hooks) | other agents' work and the merge target |
| other tasks' clones and scratch folders | isolation between tasks |
| `AGENTKEEL_HOME` (task records, approvals, opt-in registry) and the session's settings file | a record, approval or boundary the agent could write proves nothing |

### The boundary belongs to the session, set before its first command

One repository-local settings file is read by every session in that checkout, so changing it for task
B would widen or narrow task A's running boundary. The boundary is set per session instead, before
the session starts: `task.py open <task> --host claude|codex`, run by the human, creates the clone and
the scratch folder, writes the task record, writes the session's settings into `AGENTKEEL_HOME`, and
starts the host in the clone with them.

- **Claude Code**: `claude --settings <AGENTKEEL_HOME>/sessions/<task>.json`, holding
  `sandbox.enabled`, `failIfUnavailable: true`, `allowUnsandboxedCommands: false` and
  `filesystem.allowWrite` for the scratch folder. The working folder (the clone) is writable by
  default. Nothing changes in user or project settings.
- **Codex**: a named permission profile that extends `:workspace`, adds the scratch folder, sets the
  clone's `.git` to `write` (a specific rule overrides the built-in `.git` protection; measured), and
  sets `":tmpdir"` and `":slash_tmp"` to `read`. It is selected with `-P` and the session starts with
  `-C <clone>`. Open: whether the profile can be passed for one session only (`-c` or a `-p` layer
  file) instead of being written into the user's `config.toml`.

Measured on both hosts, from inside one task's clone: a write to the clone and to its scratch
folder, `git add` and a signed `git commit` succeed. A shell write to another task's folder, to
another task's scratch, to the shared checkout, to a shared object and to the shared `main` ref, a
`git push` to the shared `main`, and a symlink that points out of the clone all fail before the file
changes. Measured on Claude Code only, still to repeat on Codex: a Python write and a Node write to
another task's clone, and a write to the session's settings file or to `.claude/settings.local.json`,
fail the same way.

### Temporary folders

- **Codex**: the profile closes `/tmp` and `$TMPDIR` (measured). Tools then write temporary files in
  the task's scratch folder; the session sets `TMPDIR` to it.
- **Claude Code**: limit. Sandboxed commands write to a per-user temp folder (`/tmp/claude-501`)
  that every Claude Code session of the same user shares. Denying it breaks signed commits and Claude
  Code's own working-folder tracking (measured). `CLAUDE_CODE_TMPDIR` set at launch did not change it
  in the test. Until a per-session temp folder is proven, AgentKeel reports this shared allowance
  instead of claiming isolation of temporary files between Claude Code sessions.

### task.py is not exempted from the sandbox

`task.py verify -- <command>` runs an arbitrary command, so exempting `task.py`, or Python in general,
would let any test script run outside the boundary. Instead:

- **Commands stay sandboxed.** `verify` runs its command inside the sandbox like any other command.
- **Control state is written only by trusted code outside the sandbox**: `task.py open` (run by the
  human before the session) and the hooks, which both hosts run outside the sandbox from the
  installed plugin, a folder the session cannot write. No session command is exempted.
- **Evidence is recorded by the PostToolUse hook**, which sees the command that ran and its result, not
  by the command itself. Open: confirm that both hosts give the hook the exit status; if one does not,
  evidence on that host is reported as unrecorded.
- **The interpreter and the helper come from outside the task's reach.** The hook commands name the
  plugin's own files; a task's clone, `PATH` entries or `PYTHONPATH` inside the clone cannot replace
  them.

Acceptance adds: a `verify` command that writes into another task's clone fails before the file
changes; a normal test run passes and its evidence is recorded; a replaced `task.py` or `python3` in
the clone, and a `PYTHONPATH` that points into the clone, change nothing that a hook writes.

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
  dispatch with the resolved tool name and arguments, and Codex applied its own approval check to each
  one (all four refused under `approval_policy = "never"`; the server received nothing). So the
  dispatch layer sees each nested call individually. Codex documents that PreToolUse supports
  code-mode nested calls. Open: a run with a hook the founder has trusted, to show that the hook itself
  receives each nested call and that its refusal stops it. Codex skips any hook a person has not
  reviewed and trusted, so this test needs one trust step by the founder.
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
action are refused, and the server's record shows zero calls for each refusal. A batch with one
refused part is refused whole. No real service is called and nothing is charged.

## Build order

1. Finish the two open feasibility checks: the Codex trusted-hook run for nested MCP calls, and the
   PostToolUse exit status for evidence on both hosts.
2. Shell isolation for both hosts: `task.py open`, task clones, session settings, the judged fetch,
   evidence by hook.
3. The four adapters, after step 1 shows an interception path on each host.

This is integration work across both hosts, not a hook patch. An estimate in days waits for step 1.

## Decisions for the founder

1. **`remote-write`**, scoped to service and target, separate from `push`, with paid, deploy and
   publish still granted separately.
2. **Browser automation**: explicitly unsupported for remote changes in this version; local QA stays.
3. **Commits**: in a task-owned clone, with the shared `.git` read-only. No writable shared `.git`,
   no prompt per commit.
4. **Settings**: per session, written by `task.py open`. No user-scope change on Claude Code. On Codex,
   a user-scope profile only if a per-session one proves impossible, shown as an exact diff first.

## Not in this design

Other hosts, a new approval service, and proof of who approved. The task record still describes the
scope; it is not the human's consent. A gateway process is not excluded: it enters if Codex's hooks
cannot see nested MCP calls.
