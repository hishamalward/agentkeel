# Enforcement beyond tool calls: design

This page says what each layer can enforce today, on each host, and how AgentKeel closes its two
largest gaps: shell and script writes outside a task's boundary, and MCP calls that change, publish,
deploy or spend. It is built in 0.8.0 (`task.py open`, `import`, `release`, the hook launcher, the
evidence hooks and the four MCP adapters), and the live acceptance passed on both hosts. The
feasibility results come from throwaway repositories on macOS with Claude Code 2.1.292 and Codex
0.160.1 (2026-10-06); each one names what it proves and what it leaves open.

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
- **Cleanup**: `task.py release` (P4) deletes a clone only after these checks, made at the moment of
  deletion and under the lock that `import` also takes, so that no import runs at the same time:
  1. the folder is the one `task.py open` made: the record keeps its device and inode and a random
     id that `open` wrote into the clone's `.git`, and both must match, because a file system can
     give a new folder the old inode number (measured on Linux). A folder that is not proven to be
     the clone is never deleted, not even with `--discard`
  2. no process works in the clone, and the process list itself was read
  3. the clone's current tip is reachable from a ref in the shared repository: a branch, or
     `refs/agentkeel/accepted/<task>`; an earlier import of an older commit is not enough
  4. every branch and every stash entry in the clone is reachable there too, older entries included
  5. the clone has no modified, staged or untracked files

  If one check fails, or cannot be made, release refuses and names what is not preserved. A missing
  or corrupt `.git`, an unreadable ref and a failed process listing are failures, never "clean". The
  human's explicit discard is a separate command that says what it will delete.
- **Inspection runs nothing from the clone.** The agent can write its clone's `.git/config`, and a
  clean filter or `core.fsmonitor` there runs on `git add` or `git status` with the rights of whoever
  runs git; `core.hooksPath` does not stop them. So release and the evidence hooks read the clone's
  refs, `HEAD` and stash reflog as files, and compute its tree with git in a temporary git folder that
  holds only AgentKeel's config, with the clone's objects as a read-only alternate and no system or
  global config (`hooks/agentkeel_core/repostate.py`). A filter that `.gitattributes` names has no
  definition there, so git runs none.
- **Accepted work is kept apart from staging.** A successful import also writes
  `refs/agentkeel/accepted/<task>`. A later import that fails deletes only the staging ref, so
  accepted work never becomes disposable.

Measured: after the import of A, release was allowed. After commit B in the clone, release refused
("tip is not preserved in the shared repository"). A later import with the stale expected SHA A was
refused, and the accepted ref still pointed to A. After the import of B, release was allowed. An
untracked file then made it refuse again. With a planted clean filter and `core.fsmonitor` in the
clone, release and the evidence hooks (through `run.sh`) ran neither. A clone with no `.git`, a
corrupt `HEAD`, an unpreserved older stash entry or another folder at its path was kept.

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

Measured: the import of the expected SHA succeeded. These were refused before any fetch: a task
name aimed at `main` (`a:refs/heads/main`), a branch given as a refspec (`feat/a:refs/heads/main`), a
branch given as an option (`--upload-pack=...`), and a short SHA. After the clone's branch moved by
one commit, the import was refused with "SHA mismatch". A clone `.git` replaced by a pointer to
another repository made the fetch fail. A branch made into a symbolic ref to the right commit
imported that commit, which the SHA check allows. A clone with planted `core.fsmonitor`,
`core.hooksPath`, `uploadpack.packObjectsHook`, `core.sshCommand`, `core.gitProxy`, an
`include.path` file with its own hook settings, and three hooks ran none of them during the import;
the same planted config did run when the agent's own `git commit` ran inside the clone, which is
inside the sandbox. In every case, `main` and the shared branches did not change. These are
regression tests for this command, not a proof that any fetch from agent-controlled Git state is
safe.

### The write boundary of a task

| Writable | Why |
|---|---|
| the task's clone, including most of its `.git` | the work and its commits |
| the task's scratch folder, which is also its `TMPDIR` | test and build output, temporary files |
| declared caches (for example `~/.npm`) | listed in `agentkeel.json` under `"writable"`; nothing by default |

| Not writable | Why |
|---|---|
| the shared checkout and its `.git` (objects, refs, config, hooks) | other agents' work and the merge target |
| in the clone: `.git/config`, `.git/hooks`, `.git/commondir`, `.git/info/exclude`, `.gitmodules`, a root `HEAD` | the hosts run their own git in the clone, outside the sandbox (below) |
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
  `sandbox.enabled`, `failIfUnavailable: true`, `allowUnsandboxedCommands: false`,
  `filesystem.allowWrite` for the scratch folder and `filesystem.denyWrite` for the six guarded
  paths in the clone. The working folder (the clone) is writable by default.
- **Codex**: command-line overrides only, measured with no entry in `config.toml`:
  `-c permissions.<task>.extends=":workspace"`, `-c permissions.<task>.filesystem={...}` as one
  inline table (`":workspace_roots"` with `"."` and `".git"` set to `write`, the six guarded paths
  set to `read`, the scratch folder set to `write`, `":tmpdir"` and `":slash_tmp"` set to `read`),
  `-c shell_environment_policy.set.TMPDIR="<scratch>"`, `-P <task>` and `-C <clone>`. Dotted keys
  fail for paths that contain a dot, so the table form is required. A glob in this table accepts
  only `deny`, and a deny glob under the workspace root stops every folder rename and removal in
  it (measured), so the guarded paths are exact paths.

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

### The hosts run their own git in the clone

Both hosts run git in the working folder outside the sandbox, with that folder's own config:
Codex for its git information at each turn, Claude Code at the start of an interactive session
(both measured on 2026-10-06 with harmless markers). Git runs programs that its config names, and
the session writes most of its clone's `.git`. So the config a host's git reads must be fixed
before the session starts and stay out of the session's reach:

- `open` writes `diff.ignoreSubmodules=all` into the clone's config, and `submodule.<name>.ignore=all`
  for every submodule the repository names, so the host's git never runs inside a nested repository
  that the index lists. It makes `.gitmodules` exist in the work tree (empty and excluded when the
  repository has none), because git reads submodule settings from the work tree file first.
- The sandbox keeps `.git/config`, `.git/hooks`, `.git/commondir`, `.git/info/exclude`,
  `.gitmodules` and a `HEAD` at the clone's root read-only to the session, on both hosts. Without a
  root `HEAD` the clone's root can never pass for a git directory of its own, whatever the session
  does to `.git`, so git never reads a config beside it (the one route the review found after the
  lab; Codex's own git also passes `safe.bareRepository=explicit`, which refuses that layout). The
  host itself already refuses to rename or replace the `.git` folder.

Measured with `codex sandbox` (the same sandbox a session gets, no model) through the candidate's
own `open` and profile: 27 ways a session could have put a program into what the host's git reads,
by editing, renaming, linking, redirecting or nesting, each ended with "Operation not permitted" or
with git ignoring the nested repository, and the host-side `git status` ran nothing. Commits,
branches, merges, stash, rebase, cherry-pick, fetch and reset work as before, and commits stay
signed. The regression tests (`HostGitRunsNothing`) fail on 0.7.1. The stop report costs about a
second per worktree at the end of each turn on a 2,400-file repository (it reads the tree again
without the repository's config); a 60 s timeout ends it without blocking. What the session cannot do any
more: change its clone's git config (`git push -u` and `git branch -D` print a warning), add a hook,
or edit `.gitmodules` and `.git/info/exclude`. A repository whose `.gitmodules` differs between
branches cannot switch between them inside an isolated task.

Open: the rules are proven on macOS. On Linux, Codex expands path rules against existing files, and
a rule for a path that does not exist yet (`.git/commondir`) is not proven there; `open` says so and
the isolated-task boundary on Linux stays unverified.

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
- **Control state is written only by trusted code outside the sandbox**: `task.py open`,
  `task.py import` and `task.py release` (run by the human) and the hooks, which both hosts run
  outside the sandbox from the installed plugin. No session command is exempted.
- **The hook's interpreter cannot be redirected.** A hook command names a verified absolute
  interpreter (Python 3.10 or later, recorded by `init`), runs it in isolated mode (`-I`, which
  ignores `PYTHONPATH`, the other `PYTHON*` variables and the user site folder) under an emptied
  environment (`env -i` with only `HOME` and a fixed `PATH`), and names the plugin script by its
  absolute path. Measured, with the plain form `python3 <script>`:
  - on Claude Code, a `json.py` planted in the clone and an `export PYTHONPATH` in the agent's shell
    did not reach the hook
  - on Codex, a `PYTHONPATH` that the Codex process inherited did redirect the hook: a planted
    `json.py` loaded in every hook run

  - on Codex, with the hardened form trusted beside the plain one and the same inherited
    `PYTHONPATH`: both hardened runs used the recorded interpreter in isolated mode, saw no
    `PYTHONPATH` and loaded the standard library; all 5 loads of the planted module came from
    non-isolated processes, none from a hardened run

  So the plain form is not safe, and the hardened form is required. A plugin's `hooks.json` cannot hold a per-machine interpreter
  path, so the plugin's hook command is a fixed `/bin/sh` launcher in the plugin that reads the
  recorded interpreter path from `AGENTKEEL_HOME` and runs it this way. The whole launch chain (the
  plugin scripts, the launcher, the recorded interpreter path and the interpreter itself) stays
  outside every task's write boundary, and the build tests the final launcher, not only this direct
  command.

Measured on Claude Code: a test script and a `python3` placed first on `PATH` inside the clone, both
aimed at another task's clone, were refused, as on Codex.

### Test evidence is bound to the completed run and the exact code

A hook writes the evidence. It records "passed" only for a completion it can identify, and each host
adapter names the exact events and fields it trusts:

- **Start and completion are paired** by the tool call's id. The PreToolUse event records the command,
  `HEAD` and a hash of the working tree, read without the repository's config (see Cleanup above). A
  state that cannot be read makes the run unrecorded.
- **Claude Code** (measured on 2.1.290): a foreground Bash command that ends with exit status 0 sends
  `PostToolUse` with `tool_response.interrupted` false and no `backgroundTaskId`. A non-zero exit
  sends `PostToolUseFailure` with "Exit code N" (exit 3, exit 4 and a timeout, "Exit code 143", all
  did). So the adapter records "passed" only for `PostToolUse` paired with its PreToolUse, with
  `run_in_background` not set, `interrupted` false and no `backgroundTaskId`. It records "failed" for
  `PostToolUseFailure`. Everything else is unrecorded. A command that printed "all tests passed, exit
  code 0" and then exited 4 arrived as `PostToolUseFailure`: the event decides, never the output.
- **A background command** returns at once with a `backgroundTaskId`, and its later exit reached no
  hook. It is unrecorded, never passed.
- **Codex** (measured on 0.160.0): hooks cannot record test evidence. `PostToolUse` for a shell
  command carries the call id and the output text but no exit status, so `true`, `exit 3` and
  `exit 4` arrive the same. A command that is still running sends no completion event. The session
  file does hold an exit code, but inside the output of the model-written `exec` code, so the model
  controls it. On Codex, local evidence is therefore unrecorded, and evidence for shipping comes from
  the CI required check that AgentKeel's push gate already uses: an absent, pending or failed check,
  or a check on another SHA, refuses shipping, and no transcript or success text replaces it.
- **The rule is a host fact, so it is tested.** An adapter self-test runs a success, a failure, a
  timeout and a background command on the installed host version and refuses to record evidence if
  the events differ from the rule.
- **The code did not move.** If `HEAD` or the working-tree hash differs between start and completion,
  the run is recorded as stale.
- **Shipping accepts only clean, current evidence**: a passed run whose `HEAD` is the candidate's full
  SHA, with a clean tree. Missing completion, a failure, a dirty tree or another commit means no
  evidence. A resumed shell process follows the same rule.

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
- **Codex, measured** (0.160.0, a test hook the founder trusted, the test tools set to `approve` so
  that only the hook could refuse). The tools are offered only inside the JavaScript `exec` tool, and
  PreToolUse fired for each nested call with its resolved name and arguments. The allowed read
  reached the hook and the server. The forbidden write, the write by a name built at run time and the
  write inside `Promise.all` each reached the hook, returned its refusal, and reached the server zero
  times. In that `Promise.all` run the permitted read did not run either; that is one observation,
  not a promise that parallel calls are all-or-nothing. Each refusal must still show zero calls at
  the server.
- **Codex trust covers the hook command, not the script.** The saved trust is a hash of the hook
  definition; changing the script file needed no new review. The plugin's script files must
  therefore stay outside every session's write boundary, which the task profile already ensures.
- **If a later Codex version stops sending nested calls to hooks**, matching the `exec` source text
  is not a boundary (aliases and built names pass it). The adapter self-test then fails, and the
  options are Codex's per-tool `approval_mode`, a gateway process, or refusing `exec` in guarded mode.

### The adapter

An adapter binds one server's tools to the task's permissions and to its allowed targets. It reads the
tool name and the arguments, never the tool's description or annotations.

- **Classes**: read (passes), remote-write (creates, updates, archives, deletes, resolves, changes
  settings), paid (bills per call), publish (makes something live for end users at once or sends to
  them), store (changes or submits products in the app stores). Each adapter lists its operations by exact name
  (`hooks/agentkeel_core/mcp_catalog.py`, taken from each server's own catalog). A name it does not
  list is refused, however it is spelled: `get_` or `list` in a name does not make it a read.
- **Permissions keep their meaning.** Remote writes need a new permission, `remote-write`, scoped to
  a service and a target. Paid calls need `paid-job`. Publishing needs `publish`, and the store
  operations need `store-submission`; `remote-write` alone never publishes or submits, and
  `store-submission` is not permission to publish anywhere else. A review task can change nothing.
  The adapter sorts by the operation's name: a generic update that can also turn something on
  through a field (PostHog's `update-feature-flag` with `active`) stays a remote write.
- **Targets**: `agentkeel.json` names the allowed targets per server (for example one RevenueCat
  project, one PostHog project). A remote write to any other target is refused, even with
  `remote-write`. A paid call that names a target (a Sentry organization) is held to the same list:
  `paid-job` is permission to spend, not permission for every organization. A paid call with no
  target at all (DataForSEO) needs only `paid-job`. PostHog's tools act on the server's active
  project and do not name it (only `project-settings-update` carries a supported selector, `id`;
  an invented `project_id` on another tool never establishes a target or overrides that
  selector). The target of such a call is the project the host's own connection is pinned to.
  PostHog documents the pin ([connection pinning](https://posthog.com/docs/model-context-protocol/faq#advanced-configuration)):
  the header `x-posthog-project-id: <id>` or `?project_id=<id>` on the server's URL, and a pinned
  connection no longer offers `switch-project`. The guard reads the pin from the host's entry for
  the exact server the call came from (`hooks/agentkeel_core/mcp_connection.py`): on Claude Code
  the project's entry in `~/.claude.json`, then the project's `.mcp.json`, then the user's entry,
  and a plugin's own `.mcp.json` for `mcp__plugin_<plugin>_<server>__*`; on Codex
  `[mcp_servers.<server>]` in `~/.codex/config.toml` with `http_headers` and `env_http_headers`.
  A pin counts only on a `posthog.com` URL. A write passes when the pin is a listed project; it
  is refused with the reason when the connection is pinned to another project or not pinned at
  all (the refusal says how to pin). Reads pass either way, and `"*"` allows every project.
  Listing a project in `agentkeel.json` alone enables nothing: the pin must exist on the host.
- **Generic tools**: PostHog's `exec` is classified by its command verb and the listed tool that
  `call` names (`--json` and `--confirm` skipped), DataForSEO's `api_request` by method and path
  segments (a `live` or `task_post` segment is paid; a GET with an `appendix` or `user_data` segment
  is a read).
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

## What is built (0.7.1)

The four choices above were approved on 2026-10-06: `remote-write` scoped to service and target,
remote browser activity unsupported with local QA kept, an independent clone for every task size,
and per-session settings on both hosts. Every feasibility probe is now a test in
`tests/test_isolation.py` or `tests/test_mcp.py`. Where the build differs from the text above:

- **Codex profile selection.** `codex` and `codex exec` have no `-P` (only `codex sandbox` has it),
  so the session selects its profile with `-c default_permissions="agentkeel-<task>"`. Found in the
  live run.
- **No `PostToolUseFailure` entry.** Codex documents no such event, and both hosts read one hooks
  file. On Claude Code a failure sends no `PostToolUse`, so the run stays pending, which counts as
  unrecorded, never passed.
- **`publish` exists; `deploy` does not.** RevenueCat's paywall publish and experiment start, and
  PostHog's publish, launch, ship, enable, roll-out and batch-run tools, need `publish`; RevenueCat's
  store operations need `store-submission`. No adapter has a deploy action yet.
- **Project installs.** Their hook scripts live in `.claude/hooks/` inside the repository, and Codex
  trusts a hook's command, not its script, so the Codex task profile keeps `.claude` read-only.

Live acceptance of 0.8.0 (2026-10-06), both hosts, sessions started from `task.py open` with the
branch's hooks and synthetic recording servers:

| Check | Claude Code | Codex |
|---|---|---|
| `verify` result | passed | unrecorded (no exit status) |
| Signed commit in the clone | pass | pass |
| Paid call on the listed organization; allowed write; paid call with no target | reach the server | reach the server |
| Paid call on another organization; unknown name | refused, 0 calls | refused, 0 calls |
| Publish and store calls under `remote-write` alone | refused, 0 calls | refused, 0 calls |
| Publish and store calls under `publish` and `store-submission` | reach the server | reach the server |
| Publish call on another project; a plain write under `publish` alone | refused, 0 calls | refused, 0 calls |
| The session edits its clone's config, adds a `commondir`, writes `.gitmodules` | refused by the sandbox | refused by the sandbox |
| A planted program run by anything outside the sandbox | none | none |
| The human's profile reaches the session | yes | yes |
| The stop report runs at the end of the turn | yes (its state file) | yes (its state file) |

Not shown live: the stop report's message in the hosts' interactive views (`claude -p` and
`codex exec` print no system messages), and `import` and `release` of these clones (the guard
refuses them from an agent session, as designed; the unit tests run them through the real commands).

**Open: shipping from an isolated session.** Inside the sandbox the agent cannot move the shared
`main` or push from the shared checkout, so a task opened with `task.py open` ships through the
human's `import` and merge. A session that is not opened works as before, with the guards only. A
trusted ship step that the hooks run for a task with `merge` and `push` is a later decision.

## Not in this design

Other hosts, a new approval service, and proof of who approved. The task record still describes the
scope; it is not the human's consent. A gateway process is not excluded: it enters if a later Codex
version stops sending nested MCP calls to hooks.
