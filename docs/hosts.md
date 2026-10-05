# Hosts

agentkeel's guards read events, not tool names (`hooks/agentkeel_core/host.py`). This page is the
per-host fact sheet those events are built on. Every row was checked against a captured payload
(`tests/fixtures/`) or a live run on 2026-10-04 unless it says otherwise.

| Fact | Claude Code 2.1.289 | Codex CLI 0.160.0 |
|---|---|---|
| Project hook config | `.claude/settings.json` | `.codex/hooks.json` (also `config.toml`; both load) |
| Plugin manifest | `.claude-plugin/plugin.json`, hooks at `hooks/hooks.json` | `.codex-plugin/plugin.json` with `"hooks": "./hooks/hooks.json"` |
| Plugin root in a hook command | `${CLAUDE_PLUGIN_ROOT}` | `${PLUGIN_ROOT}` (and `CLAUDE_PLUGIN_ROOT`, per the docs) |
| Session id in the hook payload | `session_id` | `session_id` (the thread id) |
| Session id in the agent's shell | `CLAUDE_CODE_SESSION_ID` | `CODEX_THREAD_ID` |
| A subagent's tool calls carry | the parent's `session_id` | the parent's `session_id` |
| A subagent's shell sees | the parent's id | its own `CODEX_THREAD_ID` (so `task.py` there finds no task) |
| File edit | `Write` (`file_path`, `content`), `Edit` (`old_string`, `new_string`), `NotebookEdit` | `apply_patch`, the whole envelope in `tool_input.command`, paths relative to `cwd`; agentkeel also reads a patch under the `Edit`/`Write` names, inside a shell `apply_patch` command, after an indented header, and in a second envelope |
| Shell | `Bash`, `tool_input.command` | `Bash`, `tool_input.command` |
| Subagent dispatch | `Agent`, readable `prompt` | `collaborationspawn_agent`, `task_name` readable, `message` encrypted; agentkeel matches `^(Agent\|.*spawn_agent)$` and a third `plan_gate*` dispatch was refused live before launch |
| Block | exit 2, reason on stderr, shown to the model | exit 2, reason on stderr, shown as `Command blocked by PreToolUse hook: <reason>` |
| Trust | project settings load when the folder is trusted | a new or changed non-managed hook is skipped until trusted (`/hooks`); `codex exec --dangerously-bypass-hook-trust` skips the check for one run |
| SessionStart context | stdout is added to the session | stdout is added as a developer instruction, which the model ranks above the user's prompt (verified) |
| Plugin hook trust | | stored as `hooks.state."<plugin>@<marketplace>:hooks/hooks.json:<event>:<i>:<j>"`; `codex plugin remove` leaves these entries and an empty cache folder |
| Shell runner | the `Bash` tool's process | a background app-server daemon, often in a sandbox that cannot inspect processes or write outside the workspace |

## Which tools reach the guard

The task guard is configured for every tool (`*`) on both hosts, and decides in `host.py`: file
edits, shell and dispatches are judged; reads, planning, messaging and scheduling tools pass (a
scheduled prompt runs later as ordinary, judged tool calls); MCP tools pass and are outside
agentkeel; any other tool whose name suggests a write (`write_stdin` among them) is refused as a
visible gap.

## Consequences

- **One process, two ids.** When one agent runs inside the other (Codex started from a Claude Code
  shell), both session variables are set. `task.py` takes the variable of the nearest agent
  process above it; `AGENTKEEL_SESSION_ID` overrides both. The guards never guess: they read
  `session_id` from the payload.
- **Plan gates on Codex.** The dispatch message is encrypted before hooks see it, so the
  `[plan-gate]` marker cannot be read. A gate dispatch is named instead: a `task_name` starting
  `plan_gate` counts, per task, because the plan file is not visible either.
- **Codex subagents and `task.py`.** Declare the task and record evidence (`task.py verify`) from
  the main agent; a subagent's own shell has its own thread id.
- **A patch is judged on its result.** For a spec, agentkeel applies the patch to the current text
  and runs the same approval check a Claude `Edit` gets; a patch whose hunks do not fit a spec is
  refused rather than guessed at.
- **Choosing the session inside a shell.** When the agent's shell cannot tell which session runs
  it (both hosts' variables set, a sandbox that hides the process tree), `task.py` refuses rather
  than guess, because a guess can act on another session's task record. The session-start
  message prints the session's id; the agent then gives it inline,
  `AGENTKEEL_SESSION_ID=<id> python3 task.py ...`, and the guard, which sees the true id in the
  payload, refuses any other value and any `export` of it (an exported id would reach every
  process the shell starts, other agents included). Keep `AGENTKEEL_HOME` writable from the agent's sandbox (Codex `workspace-write`
  blocks writes outside the workspace; add the folder or use a profile that allows it).
- **Removing the Codex plugin fully.** After `codex plugin remove <plugin>@<marketplace>` and
  `codex plugin marketplace remove <marketplace>`, delete the `hooks.state."<plugin>@<marketplace>:..."`
  sections from `~/.codex/config.toml` and the empty cache folder; Codex leaves both.
- **Trust is a human step on Codex.** `install.py --doctor` reads `~/.codex/config.toml` for the
  project's trust and for trust entries naming `.codex/hooks.json`; it does not recompute hashes.

## Other hosts

Cursor, Copilot and others read `AGENTS.md`, so they get the instructions. They have no adapter
here, so for them agentkeel is guidance only. An adapter is a function in `host.py` that turns the
host's payload into the same events, plus captured fixtures and a parity test.
