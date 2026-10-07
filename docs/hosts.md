# Hosts

AgentKeel runs the same guards on Claude Code and Codex. This page lists the facts per host that the guards depend on, and the live results that prove both hosts give the same decision.

## Facts per host

The guards read events, not tool names (`hooks/agentkeel_core/host.py`). Each row was checked against a captured payload (`tests/fixtures/`) or a live run on 2026-10-04, unless it says otherwise.

| Fact | Claude Code 2.1.289 | Codex CLI 0.160.0 |
|---|---|---|
| Project hook config | `.claude/settings.json` | `.codex/hooks.json` (also `config.toml`; both load) |
| Plugin manifest | `.claude-plugin/plugin.json`, hooks at `hooks/hooks.json` | `.codex-plugin/plugin.json` with `"hooks": "./hooks/hooks.json"` |
| Plugin root in a hook command | `${CLAUDE_PLUGIN_ROOT}` | `${PLUGIN_ROOT}` (and `CLAUDE_PLUGIN_ROOT`, per the docs) |
| Session id in the hook payload | `session_id` | `session_id` (the thread id) |
| Session id in the agent's shell | `CLAUDE_CODE_SESSION_ID` | `CODEX_THREAD_ID` |
| A subagent's tool calls carry | the parent's `session_id` | the parent's `session_id` |
| A subagent's shell sees | the parent's id | its own `CODEX_THREAD_ID` (so `task.py` there finds no task) |
| File edit | `Write` (`file_path`, `content`), `Edit` (`old_string`, `new_string`), `NotebookEdit` | `apply_patch`, the whole envelope in `tool_input.command`, paths relative to `cwd`; AgentKeel also reads a patch under the `Edit`/`Write` names, inside a shell `apply_patch` command, after an indented header, and in a second envelope |
| Shell | `Bash`, `tool_input.command` | `Bash`, `tool_input.command` |
| Subagent dispatch | `Agent`, readable `prompt` | `collaborationspawn_agent`, `task_name` readable, `message` encrypted; AgentKeel matches `^(Agent\|.*spawn_agent)$`, and a third `plan_gate*` dispatch was refused live before launch |
| Block | exit 2, reason on stderr, shown to the model | exit 2, reason on stderr, shown as `Command blocked by PreToolUse hook: <reason>` |
| Trust | project settings load when the folder is trusted | a new or changed non-managed hook is skipped until trusted (`/hooks`); `codex exec --dangerously-bypass-hook-trust` skips the check for one run |
| SessionStart context | stdout is added to the session | stdout is added as a developer instruction, which the model ranks above the user's prompt (verified) |
| Stop (a turn ends) | payload adds `stop_hook_active`, `last_assistant_message`; JSON on stdout with `systemMessage` shows a message to the human and does not block (documented) | payload adds `stop_hook_active`, `last_assistant_message`, `turn_id`, `model`; the output schema (`stop.command.output` in the 0.160.1 binary) accepts `systemMessage`, `continue`, `stopReason`, `suppressOutput`, `decision: "block"`, `reason` |
| Plugin skills | `skills/<name>/SKILL.md` in the plugin root, found without a manifest field (documented, not run live) | `"skills": "./skills/"` in `.codex-plugin/plugin.json`, as the installed OpenAI, PostHog and Sentry plugins do |
| Plugin hook trust | not checked | stored as `hooks.state."<plugin>@<marketplace>:hooks/hooks.json:<event>:<i>:<j>"`; `codex plugin remove` leaves these entries and an empty cache folder |
| Shell runner | the `Bash` tool's process | a background app-server daemon, often in a sandbox that cannot inspect processes or write outside the workspace; the workspace sandbox also refuses writes inside `.git`, so a commit needs a sandbox that allows it |

## Which tools reach the guard

The task guard receives every tool (`*`) on both hosts. In `host.py`, file edits, shell commands and dispatches are judged; known reads, planning, messaging and scheduling tools pass. Codex's hosted web tool is recognized by its exact names `webrun`, `web.run` and `web__run`. Unknown script-running tools remain refused. A scheduled prompt runs later as ordinary, judged tool calls.

MCP calls go through the [service adapters](enforcement-design.md#part-3-mcp-calls-with-consequences). Servers without an adapter remain unsupported. Any other tool whose name suggests a write (`write_stdin` among them) is refused as a visible gap.

## PostHog: one active connection, one known project

PostHog tools often use the connection's active project without naming it in the call.
To allow writes, AgentKeel needs three things: the project in `agentkeel.json`'s
`mcp.posthog.targets`, a connection pinned to that project, and the task's required permission
(`remote-write`, or `publish` for actions that publish). A login alone grants none of these.
This explains the existing target rule; it adds no new permission.

Use PostHog's supported `x-posthog-project-id` header with a literal project ID. Keep the
normal server URL, `https://mcp.posthog.com/mcp`. See PostHog's
[pinning options](https://posthog.com/docs/model-context-protocol/faq#advanced-configuration).
Pin to the project this repository uses, not to a hard-coded AgentKeel default. Prefer a
repository-scoped connection when different repositories use different PostHog projects.
User scope is suitable when the same project is intentionally used across your checkouts.

On Claude Code, inspect the existing entry with `claude mcp get posthog` before adding one.
Authenticate it with `claude mcp login posthog`; browser consent is the human step. Start a
fresh session after changing a pin. Claude's documented
[connection precedence](https://code.claude.com/docs/en/mcp#scope-hierarchy-and-precedence)
gives an explicit server priority over a plugin server at the same endpoint. The PostHog
plugin can stay installed for its skills. Confirm that only the intended connection is
active; do not leave two competing connections or edit the plugin cache to remove its server.
Using a query-string pin changes the endpoint, so prefer the header when overriding the
plugin's connection.

Check the active project's identity before a write. For acceptance, use one disposable write,
delete only what that test created, and verify a foreign-project call is refused. Keep host
authentication, connection targeting and task permissions separate when diagnosing a refusal.

`task.py init` currently reports AgentKeel installation and hook trust, but does not configure
MCP connections or check their project pins. Follow this setup explicitly; an `init` success
does not mean PostHog writes are ready.

## What it means for agents

- **One process, two ids.** When one agent runs inside the other (Codex started from a Claude Code shell), both session variables are set. `task.py` takes the variable of the nearest agent process above it; `AGENTKEEL_SESSION_ID` overrides both. The guards never guess: they read `session_id` from the payload.
- **Plan gates on Codex.** The dispatch message is encrypted before hooks see it, so the `[plan-gate]` marker cannot be read. A gate dispatch is named instead: a `task_name` starting `plan_gate` counts, per task, because the plan file is not visible either.
- **Codex subagents and `task.py`.** Declare the task and record evidence (`task.py verify`) from the main agent; a subagent's own shell has its own thread id.
- **A patch is judged on its result.** For a docs page, AgentKeel applies the patch to the current text and runs the same approval check a Claude `Edit` gets; a patch whose hunks do not fit an approved page is refused rather than guessed at.
- **Choosing the session inside a shell.** If both hosts' variables are set and the process tree is hidden, `task.py` refuses to guess. Only then use the session-start id inline: `AGENTKEEL_SESSION_ID=<id> python3 task.py ...`. The guard rejects another session's id, including inside shell wrappers, and rejects exporting it. Using the prefix by default can cause repeated host permission prompts.
- **Writing task records.** An ordinary session needs access to `AGENTKEEL_HOME` to declare its task. An isolated session opened with `task.py open` deliberately cannot write there: the launcher and hooks manage its record. Do not widen that sandbox to make `task.py start` work; use the [reopen procedure](task-record.md#changing-permissions).
- **Removing the Codex plugin fully.** After `codex plugin remove <plugin>@<marketplace>` and `codex plugin marketplace remove <marketplace>`, delete the `hooks.state."<plugin>@<marketplace>:..."` sections from `~/.codex/config.toml` and the empty cache folder; Codex leaves both.
- **The stop report uses the hosts' system-message channel.** `stop-report.py` prints only `{"systemMessage": ...}` and exits 0. It never sets `decision`, `continue` or `stopReason`. On 2026-10-07, Claude Code 2.1.292 displayed the resource report in a real interactive terminal, then returned to its idle prompt without another model turn. This proves text visibility, not pixel layout. Codex's schema accepts the same field. Its Stop hook was confirmed enabled and trusted in the pilot's interactive settings on 2026-10-07; visibility of the report itself remains unverified.
- **A new hook needs trust again on Codex.** Codex skips a plugin hook until the human trusts it, so each hook added to `hooks/hooks.json` (the Stop hook included) is skipped until the human trusts it in `/hooks`. `task.py init` counts the hooks in `hooks.json` and reports how many are trusted.
- **Trust is a human step on Codex.** `install.py --doctor` reads `~/.codex/config.toml` for the project's trust and for trust entries naming `.codex/hooks.json`; it does not recompute hashes.

## Live results

Run on 2026-10-04 with Claude Code 2.1.289 (`claude -p`, Sonnet) and Codex CLI 0.160.0 (`codex exec`) in two throwaway repositories with local bare remotes, each installed with `install.py --apply`. Both agents got the same steps, tried each once, and gave the same result at every step.

| Step | Claude Code | Codex |
|---|---|---|
| Create a file before a task is declared | refused: `no task is declared for this session` | refused, same text, through `apply_patch` |
| Declare a small `implement` task in the shared checkout | allowed; no worktree recorded | same |
| `git worktree add`, then create a file there | allowed | allowed |
| Commit with explicit paths in the worktree | allowed | allowed |
| `git push origin feat/parity && git push origin main` | refused at the first push: needs `push` | same |
| `cat .env` | refused by the secret guard | same |
| A subagent creates a file in the task's worktree | allowed | allowed |
| A subagent writes in the shared checkout | refused (Stage 1 run) | refused |
| A third plan-gate dispatch | refused (Stage 1 run, by marker) | refused before launch, by `plan_gate` task name |

- The Codex run used `--dangerously-bypass-hook-trust` for that run only. A separate Codex plugin run trusted its five hooks by hand in `/hooks`, with no bypass, and refused an undeclared write and a `cat .env`.
- The Claude plugin (`claude --plugin-dir`) refused an undeclared write in a repository with `agentkeel.json`, printed the real `task.py` path at session start, and did nothing in a repository without one.
- On 2026-10-05 both plugins were installed from GitHub (the `docs/docs-pass` branch) with the commands in the README, in a throwaway repository with `agentkeel.json`. The README's probe prompt was refused on both hosts and created no file: Claude Code (2.1.289, Sonnet) answered `PreToolUse:Write hook error: ... AGENTKEEL: no task is declared for this session`; Codex (0.160.0) answered `Command blocked by PreToolUse hook: AGENTKEEL: no task is declared for this session`. Each session-start message gave the real `task.py` path in the plugin cache. The update and removal commands ran clean on both. The Codex run used `--dangerously-bypass-hook-trust`; trusting plugin hooks by hand in `/hooks` was proven in an earlier run.
- On 2026-10-05 both hosts also ran the HTML record checks live: the details are on [HTML records](html-records.md#verification).

## Other hosts

Cursor, Copilot and others are unsupported until an adapter is implemented and tested. Where one loads `AGENTS.md`, it receives the shared instructions only; no action of theirs is checked. An adapter is a function in `host.py` that turns the host's payload into the same events, plus captured fixtures and a parity test.
