# Guardrails

AgentKeel checks supported Claude Code and Codex hook events in opted-in repositories. The task guard applies the session's record and repository policy; separate guards cover secret patterns, fix-task workflow and MCP calls.

## Task and permissions

A task declares `no-code`, `small` or `large`, a kind, permissions, write roots, worktrees and a required persistent HTML deliverable. `start` creates the linked worktree for code tasks. Supported file writes must land in an owned worktree or declared report root; protected branches and remote actions require their matching permissions. Commits must name paths. The shipping module checks ready PR state and exact-SHA evidence before moving `main`.

The `fix` kind requires failed verification evidence and a recorded cause before code edits. It limits repeated edit/fail cycles; `reopen` is a human operation. See [Debugging](../skills/debugging/SKILL.md).

## Guard modes

`agentkeel.json` may set guards to `block`, `warn` or `off`. Unknown MCP servers use `pass`, `warn` or `block`, with `pass` as the default. A warning allows the intercepted operation and reports the warning. `off` disables that guard. Invalid mode values fail closed for ordinary guards.

## MCP coverage (interim)

Current adapters classify cataloged operations for RevenueCat, PostHog, Sentry and DataForSEO by operation and target. Unknown operations on a cataloged server are refused. Servers without catalog entries pass by default unless `mcp_unknown` is set to warn or block. This adapter path is interim pending the Clerk phase; do not treat it as complete coverage.

An MCP refusal applies to that intercepted call only. The same credentials may be used through shell commands, scripts or browsers, which these adapters do not inspect. A catalog entry is not a general credential boundary.

## Limits

Hooks see supported host events and parsed shell command structures, not every process side effect. Shell scripts, arbitrary redirections and browser automation can write outside the checked events. Linked worktrees share Git internals. The legacy isolated-clone mode relies on host OS sandbox configuration; platform evidence is incomplete. Hook checks do not replace host permission prompts, CI, branch protection or human review.
