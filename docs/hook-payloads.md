# Hook payloads

Fixtures under `tests/fixtures/claude/` and `tests/fixtures/codex/` capture the host event shapes used by the adapters. Paths and sensitive identifiers are scrubbed. The fixtures are the contract exercised by tests; host versions can change their payloads, so update fixtures and parity tests when observed behavior changes.

Claude Code supplies JSON on stdin to configured hooks. PreToolUse hooks can block supported operations with exit status 2. Stop hooks may return a structured decision with `decision: "block"` and a reason. The payload's `stop_hook_active` indicates a retry; the task lifecycle itself is read from the persisted AgentKeel record. A task marked `cancelled` is retained without a delivery block.

Codex supplies hook event JSON on stdin and consumes hook output according to its hook protocol. In particular, command exit status is not reliably exposed as verification evidence. See the fixtures and [host notes](hosts.md) for the observed support and limits.
