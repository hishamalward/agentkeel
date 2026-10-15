# Guardrails

AgentKeel checks supported Claude Code and Codex hook events in opted-in repositories. The task guard applies the session's record and repository policy; separate guards cover secret patterns and fix-task workflow. MCP calls are judged through MCPClerk.

## Task and permissions

A task declares `no-code`, `small` or `large`, a kind, permissions, write roots, worktrees and a required persistent HTML deliverable. `start` creates the linked worktree for code tasks. Supported file writes must land in an owned worktree or declared report root; protected branches and remote actions require their matching permissions. Commits must name paths. The shipping module checks ready PR state and exact-SHA evidence before moving `main`.

The `fix` kind requires failed verification evidence and a recorded cause before code edits. It limits repeated edit/fail cycles; `reopen` is a human operation. See [Debugging](../skills/debugging/SKILL.md).

## Guard modes

`agentkeel.json` may set task, secret and fix guards to `block`, `warn` or `off`. A warning allows the intercepted operation and reports the warning. `off` disables that guard. Invalid mode values fail closed. MCPClerk decisions do not use these modes and cannot be softened by them.

## MCPClerk bridge

For intercepted MCP calls, AgentKeel asks MCPClerk to judge the server, tool and call context against its user/project catalog and policy. Missing MCPClerk, invalid responses and refusals block that MCP call. This does not block normal coding or other non-MCP task work. MCPClerk policy lives in the user catalog (`$MCPCLERK_HOME/mcp_catalog.json`, default `~/.mcpclerk/mcp_catalog.json`) and project `mcpclerk.json`.

Migration from older AgentKeel MCP policy is explicit: use `mcpclerk migrate-keel --scope project --file agentkeel.json --project PATH` and `mcpclerk migrate-keel --scope user --file OLD-CATALOG.json`, inspect and retain the generated backups, then remove legacy `mcp` and `guards.mcp_unknown` entries from project `agentkeel.json` and the legacy user catalog `mcp_catalog.json` under `AGENTKEEL_HOME` (default `~/.agentkeel`). The bridge refuses MCP calls while legacy policy remains, avoiding two active policy sources.

An MCP refusal applies to that intercepted call only. The same credentials may be used through shell commands, scripts or browsers, which these hooks do not inspect. A catalog entry is not a general credential boundary. Host-native permissions and trust remain separate from the MCPClerk judge.

## Limits

Hooks see supported host events and parsed shell command structures, not every process side effect. Shell scripts, arbitrary redirections and browser automation can write outside the checked events. Linked worktrees share Git internals. The legacy isolated-clone mode relies on host OS sandbox configuration; platform evidence is incomplete. Hook checks do not replace host permission prompts, CI, branch protection or human review.
