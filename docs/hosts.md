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
| Plugin hook trust | not checked | stored as `hooks.state."<plugin>@<marketplace>:hooks/hooks.json:<event>:<i>:<j>"`; `codex plugin remove` leaves these entries and an empty cache folder |
| Shell runner | the `Bash` tool's process | a background app-server daemon, often in a sandbox that cannot inspect processes or write outside the workspace; the workspace sandbox also refuses writes inside `.git`, so a commit needs a sandbox that allows it |

## Which tools reach the guard

The task guard is configured for every tool (`*`) on both hosts, and decides in `host.py`: file edits, shell and dispatches are judged; reads, planning, messaging and scheduling tools pass (a scheduled prompt runs later as ordinary, judged tool calls); MCP tools pass and are outside agentkeel; any other tool whose name suggests a write (`write_stdin` among them) is refused as a visible gap.

## What it means for agents

- **One process, two ids.** When one agent runs inside the other (Codex started from a Claude Code shell), both session variables are set. `task.py` takes the variable of the nearest agent process above it; `AGENTKEEL_SESSION_ID` overrides both. The guards never guess: they read `session_id` from the payload.
- **Plan gates on Codex.** The dispatch message is encrypted before hooks see it, so the `[plan-gate]` marker cannot be read. A gate dispatch is named instead: a `task_name` starting `plan_gate` counts, per task, because the plan file is not visible either.
- **Codex subagents and `task.py`.** Declare the task and record evidence (`task.py verify`) from the main agent; a subagent's own shell has its own thread id.
- **A patch is judged on its result.** For a docs page, AgentKeel applies the patch to the current text and runs the same approval check a Claude `Edit` gets; a patch whose hunks do not fit an approved page is refused rather than guessed at.
- **Choosing the session inside a shell.** When the agent's shell cannot tell which session runs it (both hosts' variables set, a sandbox that hides the process tree), `task.py` refuses rather than guess, because a guess can act on another session's task record. The session-start message prints the session's id; only after `task.py` refuses does the agent give it inline (giving it by default makes every declaration a command that no host permission rule matches), `AGENTKEEL_SESSION_ID=<id> python3 task.py ...`, and the guard, which sees the true id in the payload, refuses any other value (also inside `bash -c`, `sh -c`, `env` and `eval`) and any `export` of it (an exported id would reach every process the shell starts, other agents included). Keep `AGENTKEEL_HOME` writable from the agent's sandbox (Codex `workspace-write` blocks writes outside the workspace; add the folder or use a profile that allows it).
- **Removing the Codex plugin fully.** After `codex plugin remove <plugin>@<marketplace>` and `codex plugin marketplace remove <marketplace>`, delete the `hooks.state."<plugin>@<marketplace>:..."` sections from `~/.codex/config.toml` and the empty cache folder; Codex leaves both.
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
