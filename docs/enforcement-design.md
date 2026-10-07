# Enforcement: boundaries and evidence

This page says what each layer can enforce today, on each host, and how AgentKeel closes its two
largest gaps: shell and script writes outside a task's boundary, and MCP calls that change, publish,
deploy or spend. It is built in 0.8.0 (`task.py open`, `import`, `release`, the hook launcher, the
evidence hooks and the four MCP adapters), and the live acceptance passed on both hosts. The
feasibility results come from throwaway repositories on macOS with Claude Code 2.1.292 and Codex
0.160.1 (2026-10-06); each one names what it proves and what it leaves open.

## What enforces each boundary

| Layer | Claude Code | Codex | AgentKeel today |
|---|---|---|---|
| File tools (Edit, Write, `apply_patch`) | permission rules only; the sandbox does not cover them | `apply_patch` is a tool the hooks see | **prevents**: the task guard checks every path |
| Shell and its child processes (`>`, `sed -i`, python, node, nested scripts) | the OS sandbox covers them when enabled | the OS sandbox covers them under the session profile | `task.py open` configures that sandbox; ordinary sessions have command checks only |
| MCP calls | PreToolUse receives tool names and arguments | measured nested calls inside `exec` reach PreToolUse individually | adapters check RevenueCat, PostHog, Sentry and DataForSEO; other servers pass through without enforcement |
| Hosted tools (web search) | known read tools pass | exact supported web-tool names pass | read access is allowed; browser writes remain unsupported |
| Hooks and local MCP servers | run outside the sandbox | hooks run outside the sandbox | not applicable |

Installing the plugin does not turn an existing session into an isolated one. Ordinary sessions
use their host's existing sandbox settings. Use `task.py open` when the task needs the filesystem
boundary described below. The macOS live results are evidence for the named host versions;
Linux isolation remains unverified.


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

### Every isolated task size gets a clone

When opened with `task.py open`, a small task gets the same isolation as a large one. Ordinary
sessions continue to use linked worktrees. Because a clone
does not appear in `git worktree list`, the ownership, resume and cleanup behavior change together:

- **Ownership**: the task record names the clone's path, its branch and the full SHA of its base.
  The session banner and the ownership checks read the task records, not `git worktree list`.
- **Reopen**: `task.py open` refuses a task that is already open. Preserve and import its work,
  end its session and release its clone before opening that task again.
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
- **Inspection runs nothing from the clone.** A clean filter or `core.fsmonitor` in repository
  config can run on `git add` or `git status` with the caller's rights; `core.hooksPath` does not
  stop them. The sandbox protects the clone's config, and inspection also avoids trusting it.
  Release and the evidence hooks read the clone's
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
  `-c shell_environment_policy.set.TMPDIR="<scratch>"`,
  `-c default_permissions="agentkeel-<task>"` and `-C <clone>`. Dotted keys
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
- a test script and a `python3` placed first on `PATH` inside the clone, both aimed at
  another task's clone (measured on both hosts)

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
  environment (`env -i` with a fixed `PATH` and an explicit allowlist for host, session and
  authentication variables), and names the plugin script by its absolute path. If `init` has
  not recorded an interpreter, the launcher checks Python in fixed system/install directories.
  Measured, with the plain form `python3 <script>`:
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
  `run_in_background` not set, `interrupted` false and no `backgroundTaskId`. The shared hook config
  does not register `PostToolUseFailure`, so a failed run stays pending and counts as unrecorded.
  A command that printed "all tests passed, exit
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
- **The rule depends on the host version.** Unit tests cover the known payloads. The live probes
  above checked success, failure, timeout and background runs on the named versions. There is no
  automatic live compatibility test at each session start; host upgrades need fresh acceptance.
- **The code did not move.** If `HEAD` or the working-tree hash differs between start and completion,
  the run is recorded as stale.
- **Shipping uses CI evidence.** Local evidence is a record, not a shipping gate. When
  `require_check_before_push` is configured, the push gate requires a passed GitHub check on the
  exact full SHA being pushed. Local output or a passed run on another SHA cannot substitute.

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
  is not a boundary (aliases and built names pass it). Repeat the recording-server acceptance
  when upgrading hosts. If interception fails, that host version's MCP protection is unverified;
  a different enforcement route would need a separate design and test.

### The adapter

An adapter binds one server's tools to the task's permissions and to its allowed targets. It reads the
tool name and the arguments, never the tool's description or annotations.

- **Classes**: read (passes), remote-write (creates, updates, archives, deletes, resolves, changes
  settings), paid (bills per call), publish (makes something live for end users at once or sends to
  them), store (changes or submits products in the app stores). Each adapter lists its operations by exact name
  (`hooks/agentkeel_core/mcp_catalog.py`, taken from each server's own catalog). A name it does not
  list is refused, however it is spelled: `get_` or `list` in a name does not make it a read.
- **Permissions keep their meaning.** Remote writes need `remote-write`, scoped to
  a service and a target. Paid calls need `paid-job`. Publishing needs `publish`, and the store
  operations need `store-submission`; `remote-write` alone never publishes or submits, and
  `store-submission` is not permission to publish anywhere else. `review` alone grants no remote write.
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
  the exact server the call came from (`hooks/agentkeel_core/mcp_connection.py`), never from a
  file the session could have written: on Claude Code, for the host's project directory
  (`CLAUDE_PROJECT_DIR`; the hook's cwd follows `cd` and is not it), the project's entry in
  `~/.claude.json`, then the project's `.mcp.json` and that one only for a server the human
  approved for the project (`enabledMcpjsonServers`), then the user's entry, and a plugin's own
  `.mcp.json` for `mcp__plugin_<plugin>_<server>__*`; on Codex `[mcp_servers.<server>]` in
  `~/.codex/config.toml` with `http_headers` and `env_http_headers`. Custom host roots
  (`CLAUDE_CONFIG_DIR` and `CODEX_HOME`) are respected. `.mcp.json` joins the
  configuration files the session cannot write. A pin counts only on a `posthog.com` URL, and
  only when every pin the entry carries names the same project; a configuration file that exists
  and does not parse, a missing project directory, or plugin installs that disagree mean "not
  pinned". A write passes when the pin is a listed project; it is refused with the reason when the
  connection is pinned to another project or not pinned at all (the refusal says how to pin), and
  an explicit project id that differs from the pin is refused too. `switch <id>`, `switch-project`
  and `switch-organization` change the connection's active project, so they are remote writes to
  the target they name. Reads pass either way, and `"*"` allows every project. Listing a project
  in `agentkeel.json` alone enables nothing: the pin must exist on the host, and the host reads it
  at launch, so a pin added mid-session takes effect at the next session.
- **Generic tools**: PostHog's `exec` is classified by its command verb and the listed tool that
  `call` names (`--json` and `--confirm` skipped), DataForSEO's `api_request` by method and path
  segments (a `live` or `task_post` segment is paid; a GET with an `appendix` or `user_data` segment
  is a read).
- **Supported adapters**: revenuecat, posthog, sentry, dataforseo. Other servers pass through
  without enforcement. `init` reports plugin/policy setup, not an MCP coverage inventory.
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

## Implementation and live acceptance (0.8.0)

The four choices above were approved on 2026-10-06: `remote-write` scoped to service and target,
remote browser activity unsupported with local QA kept, an independent clone for every task size,
and per-session settings on both hosts. Regression coverage lives in
`tests/test_isolation.py` and `tests/test_mcp.py`. Important implementation choices:

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

The PostHog connection pin (2026-10-07), against the real server pinned to one project in the
host's own configuration, the task allowing `remote-write` and `agentkeel.json` listing that
project:

| Check | Claude Code | Codex |
|---|---|---|
| The project read names the pinned project | yes, live: `projects-get` listed Listenality, project 644556 | yes, live: `project-get` |
| `switch 999` is refused by the guard, and the pinned server does not offer it | guard run against the real entries; switch was not called in the live session | yes, live (the server answered "Unknown command: switch" before the guard treated it as a write) |
| A write on the active project under the pin | allowed, live: annotation 479636 created and deleted; server returned `deleted: true` | allowed, live: one disposable annotation created and deleted at once |
| The same write through the host's unpinned entry (the plugin's) | refused, says how to pin | (one entry, pinned) |
| `project-settings-update` naming another project; an unknown tool name | refused, live: project 999999999 mismatched pin 644556; both calls stopped at PreToolUse | refused, live, 0 calls |

Claude's pinned user-scope connection was authenticated with `claude mcp login posthog`, which
also works when an existing session's `/mcp` view shows only the plugin connection. The live
check used the candidate hooks through session-only settings, with no hook bypass flag; the
old installed AgentKeel plugin was disabled only for that test session to avoid running two
guard versions. The test fixture and its task records were removed; no persistent host settings
changed during acceptance. The two turns cost at most $0.34 in total.

The Stop report was shown live in Claude Code 2.1.292's interactive terminal on 2026-10-07,
against candidate `c7f7589`. One review task held a disposable worktree; after the reply, the UI
printed `Stop says: agentkeel: task 'stop-ui-probe' still holds` and the resource details, then
returned to an idle prompt without another model turn. The session used candidate hooks through
session-only settings, private task state and no MCP servers or hook bypass. Its displayed
estimated cost was $0.14. The session exited and its fixtures were removed. This proves text
visibility, not pixel layout, and does not count toward the five real-session observation.

Not shown live: the Stop report in Codex's interactive view (the founder's 2026-10-07 screenshot
confirms the hook is enabled and trusted, but does not show its report;
`codex exec` prints no system messages), and `import` and `release` of these clones (the guard
refuses them from an agent session, as designed; the unit tests run them through the real commands).

**Open: shipping from an isolated session.** Inside the sandbox the agent cannot move the shared
`main` or push from the shared checkout, so a task opened with `task.py open` ships through the
human's `import` and merge. A session that is not opened works as before, with the guards only. A
trusted ship step that the hooks run for a task with `merge` and `push` is a later decision.

## Not in this design

Other hosts, a new approval service, and proof of who approved. The task record still describes the
scope; it is not the human's consent. A gateway process is not excluded: it enters if a later Codex
version stops sending nested MCP calls to hooks.
