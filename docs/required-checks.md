# Checks and shipping

AgentKeel does not ship a generic CI template. Configure the repository's own CI and branch protection, and require its checks before accepting merges.

`task.py ship --pr NUMBER` requires a ready pull request based on current `main`, an approved review decision where applicable, and successful checks attached to the exact task candidate. If `require_check_before_push` is set in `agentkeel.json`, AgentKeel also verifies that named check on the exact SHA before pushing it to `main`. Shipping requires both `merge` and `push` permissions.

The task's `verify -- COMMAND` records a local foreground check against unchanged worktree code. Codex hooks do not receive command exit status, so use CI as shipping evidence when local results cannot be recorded. A report describes what was verified; it does not replace CI or branch protection.
