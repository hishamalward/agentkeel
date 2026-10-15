# Host behavior

AgentKeel currently provides plugin hooks for Claude Code and Codex. Install the plugin through each host's marketplace, opt the repository in with `task.py init`, and start a fresh session after plugin updates.

Claude Code loads the plugin hooks automatically. Codex skips hooks that the user has not trusted: open `/hooks` in the repository and trust AgentKeel's current hooks. A new or changed hook may need trust after an update. `init` reports host install, enablement and trust separately; some facts may be unknown when the host CLI or parser is unavailable.

SessionStart prints the current checkout, branch, task and other registered worktrees, then the installed `task.py` path and declaration command. For code tasks, `start` creates a linked worktree. The session must change into the printed directory before editing. `no-code` tasks have no worktree.

The legacy human-operated `open`, `import` and `release` commands launch an isolated clone session. That mode configures host OS sandboxing for shell writes, but evidence is platform-specific and does not establish a universal boundary. See [enforcement design](enforcement-design.md).

Host hooks enforce only supported events. Arbitrary shell/script effects, browser writes and alternate use of credentials may not pass through these hooks. See [guardrails](guardrails.md) for MCP's explicitly interim status and current limits.
