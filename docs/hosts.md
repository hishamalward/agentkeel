# Host behavior

AgentKeel currently provides plugin hooks for Claude Code and Codex. Install the plugin through each host's marketplace, opt the repository in with `task.py init`, and start a fresh session after plugin updates.

Claude Code loads configured plugin hooks automatically. Codex skips hooks that the user has not trusted: open `/hooks` in the repository and trust AgentKeel's current hooks. A new or changed hook may need trust after an update. `init` reports host install, enablement and trust separately; some facts may be unknown when the host CLI or parser is unavailable. These configuration checks do not prove that a Stop hook ran in the current session. AgentKeel reports Stop enforcement as unverified here; `task.py handoff` and `task.py finish` enforce the HTML checkpoint.

SessionStart prints the current checkout, branch, task and other registered worktrees, then the installed `task.py` path and declaration command. For code tasks, `start` creates a linked worktree. The session must change into the printed directory before editing. `no-code` tasks have no worktree.

The legacy human-operated `open`, `import` and `release` commands launch an isolated clone session. That mode configures host OS sandboxing for shell writes, but evidence is platform-specific and does not establish a universal boundary. See [enforcement design](enforcement-design.md).

Host hooks enforce only supported events, and a hook's registered or trusted state is not runtime confirmation that the event reached it. The Stop report is best-effort: an internal error exits without blocking the host. Use `task.py handoff` and `task.py finish` as the authoritative HTML checks. Arbitrary shell/script effects, browser writes and alternate use of credentials may not pass through these hooks. MCPClerk's call judge is separate from host-native permissions, approvals and trust. See [guardrails](guardrails.md) for the MCP bridge behavior and limits.
