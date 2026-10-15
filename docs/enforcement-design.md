# Enforcement design and limits

AgentKeel combines host hook checks with task records. The plugin runs in opted-in repositories; `task.py init` records opt-in outside the repository and preserves existing policy. A task record binds the host session to declared permissions, linked worktrees, report roots and a persistent HTML deliverable.

## Normal task isolation

Code tasks use linked worktrees. The task guard checks supported file-tool paths, parsed shell/Git actions and task permissions. The worktree keeps ordinary source edits off the shared checkout, but it shares the repository's Git object store and common metadata. `no-code` tasks do not create a worktree.

The report is stored outside repositories and disposable worktrees. Delivery checks validate path containment, HTML structure, nonempty title/body, freshness and unchanged-code checkpoints. The HTML is free form and is not interpreted as authorization. See [delivery checkpoints](delivery.md).

## Optional isolated clone

The human-operated legacy `open`, `import` and `release` commands use a separate clone and ask Claude Code or Codex to run it under host OS sandbox settings. In this mode, shell writes are intended to stay in the clone, scratch folder and declared caches; return and removal are explicit human operations. This mode is separate from normal `start` worktrees, has platform-specific evidence, and is not claimed as a universal sandbox guarantee. Do not infer that hooks or file-tool checks alone contain arbitrary shell effects.

## MCP calls

The current MCP adapter uses a catalog to classify supported operations by permission and target. It currently includes RevenueCat, PostHog, Sentry and DataForSEO, with user/project configuration layered over plugin defaults. Unknown server behavior is controlled by `mcp_unknown`. This adapter implementation is interim pending the Clerk phase. It guards intercepted MCP calls only; it cannot prevent using the same credentials through shell, scripts or browsers.

## Evidence and boundaries

Hooks operate on host-delivered events and parsed commands. A shell script, unparsed side effect, browser action, another process or untrusted environment can fall outside those events. The `verify` command runs in the foreground and records its exit status and code snapshot on both hosts; shell-hook observations are supplementary rather than authoritative. Shipping also checks exact PR evidence and any configured required check. Host permission prompts, branch protection and human review remain separate controls.

These limits describe what the current mechanisms observe. They are not promises that all writes or external effects are contained.
