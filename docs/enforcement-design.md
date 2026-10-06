# Enforcement beyond tool calls: design

This page says what each layer can enforce today, on each host, and how AgentKeel closes its two
largest gaps: shell and script writes outside a task's boundary, and MCP calls that change, publish,
deploy or spend. It is the design to review before the build. Nothing on it is built yet.

## Who enforces what, today

| Layer | Claude Code | Codex | AgentKeel today |
|---|---|---|---|
| File tools (Edit, Write, `apply_patch`) | permission rules only; the sandbox does not cover them | `apply_patch` is a tool the hooks see; sandbox coverage is not documented | **prevents**: the task guard checks every path |
| Shell and its child processes (`>`, `sed -i`, python, node, nested scripts) | the OS sandbox covers them (Seatbelt on macOS, bubblewrap on Linux), when it is on | the OS sandbox covers them in `workspace-write`, when it is on | git commands and named file commands only; a write inside a script or a redirect is **not seen** |
| MCP calls | PreToolUse sees `mcp__<server>__<tool>` with its arguments and can block it before it runs | PreToolUse sees MCP tools by the same name; in the observed sessions most calls go through the JavaScript `exec` tool (`tools.mcp__x__y(...)`) | **unsupported**: every MCP call passes |
| Hosted tools (web search) | not hooked | not hooked | unsupported |
| Hooks and local MCP servers themselves | run outside the sandbox | not documented | not applicable |

Facts observed on the founder's machine on 2026-10-06: Claude Code has no `sandbox` settings in any
scope, and Codex has `approval_policy = "never"` and no `sandbox_mode`; a Codex shell wrote to a
folder under the home folder, outside its workspace. So today nothing below the tool calls limits a
shell write. Sources: code.claude.com/docs/en/sandboxing, /permissions, /hooks, /plugins-reference;
learn.chatgpt.com/docs/agent-approvals-security, /config-file/config-reference, /hooks.

## Part 2: shell and script isolation

The OS sandbox of each host is the enforcement. AgentKeel's job is to set its write boundary to the
task, keep its own control state out of reach, and prove the boundary on each host. A longer list
of command patterns is not isolation and is not claimed as such.

### The write boundary of a task

| Writable | Why |
|---|---|
| the task's worktrees | the work itself |
| the task's scratch folder and the system temp folder | test and build output |
| `<common>/.git/objects`, `<common>/.git/worktrees/<this worktree>`, the task branch's ref and log | a commit in a linked worktree writes here |
| declared caches (for example `~/.npm`, a test cache) | listed in `agentkeel.json` under `"writable"`; nothing by default |

| Not writable | Why |
|---|---|
| the shared checkout and other worktrees | other agents' work and the merge target |
| `<common>/.git/refs/heads/<protected>`, `packed-refs`, `config`, `hooks/` | moving `main` stays a judged git command |
| `AGENTKEEL_HOME` (task records, approvals, opt-in registry) | a record or approval the agent could write proves nothing |
| host settings and hook config | the sandbox already protects `.claude/`; Codex keeps `.codex` and `.agents` read-only |

`task.py` is the one narrow trusted operation: it writes task state, so it runs outside the
sandbox. The guard gains a rule that `task.py` runs alone in its call, because an excluded
command joined to another (`task.py ...; sed -i ...`) would take the other command out of the
sandbox too. Today no such rule exists.

### Claude Code

- `task.py init` proposes, and the human applies, these user-scope settings (a plugin cannot ship
  sandbox settings; project settings cannot hold against a looser user setting):
  `sandbox.enabled: true`, `allowUnsandboxedCommands: false` (the agent cannot retry outside),
  `failIfUnavailable: true` (no silent unsandboxed fallback), and `excludedCommands` for `task.py`.
- `task.py start` writes the task's boundary into the repository's `.claude/settings.local.json`
  (`sandbox.filesystem.allowWrite` and `denyWrite`). Claude Code applies filesystem-list edits to
  the running session, so the next shell command has the task's boundary. The file is git-ignored
  and stays local.
- The default session folder (often the shared checkout) is writable by default; `denyWrite` on the
  shared checkout overrides it, because the narrower rule wins.

### Codex

- `workspace-write` makes the session's own folder writable and adds `writable_roots`; it has no
  deny list. So a Codex session for a task starts in the task's worktree (`codex -C <worktree>`),
  not in the shared checkout, with the scratch folder as an extra root.
- `workspace-write` keeps `.git` read-only, and a linked worktree's git directory resolves into the
  common `.git`. So a commit inside the sandbox fails. Two ways remain, and the choice is the
  founder's (decision 3): add the common `.git` as a writable root (commits work, and `main`'s ref
  becomes writable by a shell write, which the git guard does not see), or keep `.git` read-only
  and let commits run through Codex's approval (one question per commit).
- `approval_policy = "never"` with no sandbox mode gives no shell boundary at all. `init` reports
  it and proposes `sandbox_mode = "workspace-write"`; the human applies it.

### Acceptance (disposable repositories, both hosts)

Inside the task's worktree, these succeed: a redirect, `sed -i`, a Python write, a Node write, a
nested script, the unit tests, a local build. Each of the same five, aimed at the shared checkout, at
another worktree, at `AGENTKEEL_HOME`, and through a symlink that points out of the worktree, fails
before the file changes. A script that runs `git update-ref refs/heads/main` or writes
`.git/refs/heads/main` fails. Each result says which layer refused it: the host sandbox or
AgentKeel's hook.

## Part 3: MCP calls with consequences

### What the pilot repository uses (sessions from 2026-07-28 to 2026-10-06)

| Server | Calls | Consequential actions seen |
|---|---|---|
| playwright (Codex), claude-in-chrome (Claude) | about 400 each | arbitrary page JavaScript (`browser_run_code_unsafe`, `javascript_tool`), form filling: unknown by nature |
| revenuecat (Codex) | about 110 | 2026-09-19 to 09-21: products, entitlements, offerings and packages created, attached, archived and deleted; a webhook integration created |
| posthog | 21 | two project settings updates (2026-10-04) |
| sentry | 10 | four issues set to resolved (2026-10-04) |
| dataforseo (Codex) | 17 | seven `api_request` calls, four to `/live` endpoints that bill per request (2026-10-01) |
| mobbin, expo, others | small | reads (`expo` listed builds; none started) |

### The adapter

An adapter binds one server's tools to the task's permissions and to its target resource. It reads
the tool name and the arguments, never the tool's description or annotations (hooks do not see
annotations, and a description proves nothing).

- **Classes**: read (passes), remote-write (creates, updates, archives, deletes, resolves, sets
  settings), paid (bills per call), deploy, publish. An action the adapter does not know is refused
  in a guarded server, never assumed to be a read.
- **Permissions**: paid maps to `paid-job`, deploy to `distribution-build`, publish to
  `store-submission`. Remote writes have no fitting permission today: the RevenueCat calls are the
  demonstrated gap, so this design adds one, `remote-write` (decision 1).
- **Targets**: `agentkeel.json` names the allowed target per server (for example a RevenueCat
  project id, a PostHog project id). A remote write to any other target is refused.
- **Generic tools**: PostHog's `exec` is classified by its command verb, DataForSEO's
  `api_request` by method and path (`/live` is paid; `appendix/user_data` is a read).
- **First adapters**: revenuecat, posthog, sentry, dataforseo. Every other server stays
  explicitly unsupported and is listed as such in `init`'s report.

### Interception, per host

- **Claude Code**: the existing PreToolUse hook. A refusal blocks the call before it runs.
- **Codex**: to be proven first. If Codex fires PreToolUse for a `tools.mcp__x__y(...)` call made
  inside `exec`, the same adapter applies. If it fires only for `exec`, parsing JavaScript is not
  enforcement; the fallback is to refuse `exec` code that names a guarded server, and to state the
  limit (code can build a tool name at run time).

### Acceptance

A synthetic MCP server that records every call it receives stands in for each guarded server. On
both hosts: reads pass; a permitted remote write to the owned target passes; a remote write under
a review task, a write to another target, a paid call without `paid-job`, a deploy without its
permission, and an unknown action are refused, and the server's record shows zero calls for each
refusal. A batched call with one refused part is refused whole. No real service is called and
nothing is charged.

## Decisions for the founder

1. **A `remote-write` permission** for changes to remote services (the RevenueCat case). The
   alternative is to reuse `push`, which today means a git push only.
2. **Browser automation** (playwright, claude-in-chrome; about 800 calls, mostly visual QA). Keep
   it explicitly unsupported, or guard only form filling and arbitrary page code. Guarding all of
   it would stop the QA loop.
3. **Codex commits under the sandbox**: a writable common `.git`, or an approval per commit.
4. **User settings**: the sandbox settings for both hosts live in the founder's user scope. `init`
   proposes them; the founder applies them.

## Not in this design

Other hosts, a new approval service, a tool gateway process, and proof of who approved. The task
record still describes the scope; it is not the human's consent.
