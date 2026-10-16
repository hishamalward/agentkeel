# Enforcement design and limits

AgentKeel combines host hook checks with task records. The plugin runs in opted-in repositories; `task.py init` records opt-in outside the repository and preserves existing policy. A task record binds the host session to declared permissions, linked worktrees, report roots and a persistent HTML deliverable.

## Normal task isolation

Code tasks use linked worktrees. The task guard checks supported file-tool paths, parsed shell/Git actions and task permissions. The worktree keeps ordinary source edits off the shared checkout, but it shares the repository's Git object store and common metadata. `no-code` tasks do not create a worktree.

The report is stored outside repositories and disposable worktrees. Delivery checks validate path containment, HTML structure, nonempty title/body, freshness and unchanged-code checkpoints. The HTML is free form and is not interpreted as authorization. See [delivery checkpoints](delivery.md).

## Optional isolated clone

The human-operated legacy `open`, `import` and `release` commands use a separate clone and ask Claude Code or Codex to run it under host OS sandbox settings. In this mode, shell writes are intended to stay in the clone, scratch folder and declared caches; return and removal are explicit human operations. This mode is separate from normal `start` worktrees, has platform-specific evidence, and is not claimed as a universal sandbox guarantee. Do not infer that hooks or file-tool checks alone contain arbitrary shell effects.

## MCP calls

AgentKeel sends intercepted MCP calls to the MCPClerk bridge for a fail-closed judge decision. MCPClerk owns user/project catalogs and policy; AgentKeel task guard modes cannot override its refusal. If the bridge is missing or returns invalid data, the MCP call is blocked while ordinary coding work can continue. Older AgentKeel MCP policy must be explicitly migrated with `mcpclerk migrate-keel`, backed up, and removed from `agentkeel.json` and the user catalog under `AGENTKEEL_HOME` (default `~/.agentkeel`) before calls are allowed. Host-native permissions and trust remain separate. The bridge observes only intercepted calls and cannot prevent the same credentials being used through shell, scripts or browsers.

## Evidence and boundaries

Hooks operate on host-delivered events and parsed commands. A shell script, unparsed side effect, browser action, another process or untrusted environment can fall outside those events. The `verify` command runs in the foreground and records its exit status and code snapshot on both hosts; shell-hook observations are supplementary rather than authoritative. PR shipping checks exact PR evidence and any configured required check; local shipping refuses a configured `require_check_before_push` policy, otherwise requires the exact verified commit and fast-forwards only the canonical checkout's already-selected configured protected branch. Host permission prompts, branch protection and human review remain separate controls.

These limits describe what the current mechanisms observe. They are not promises that all writes or external effects are contained.
