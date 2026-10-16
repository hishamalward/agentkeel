# Checks and shipping

AgentKeel does not ship a generic CI template. Configure the repository's own CI and branch protection, and require its checks before accepting merges.

`task.py ship --pr NUMBER` requires a ready pull request based on the canonical checkout's current branch, which must be configured as protected, an approved review decision where applicable, and successful checks attached to the exact task candidate. If `require_check_before_push` is set in `agentkeel.json`, AgentKeel also verifies that named check on the exact SHA before pushing it to that protected branch. PR shipping requires both `merge` and `push` permissions.

`task.py ship --local` is a separate no-network route for repositories without `require_check_before_push`. When that policy names a check, local shipping refuses before changing task state or Git refs and directs the caller to PR shipping. It requires a clean, idle canonical checkout whose current branch is configured as protected, the exact committed candidate to pass `verify`, and a current HTML report. It fast-forwards that branch to the candidate and requires `merge` permission. Neither route silently selects a different protected branch; if the canonical checkout is on an unconfigured branch, shipping stops.

The task's `verify -- COMMAND` records a local foreground check against unchanged worktree code. Codex hooks do not receive command exit status, so use CI as shipping evidence when local results cannot be recorded. A report describes what was verified; it does not replace CI or branch protection.
