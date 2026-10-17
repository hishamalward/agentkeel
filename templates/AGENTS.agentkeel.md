## AgentKeel (managed by task.py init)

Declare the task from the user's request before writing:
    python3 "<task.py path>" start <task-id> --size no-code|small|large --allow <permissions> [--deliverable <progress.html>] [--spec <spec.html>]
Use the path printed at session start. Size grants no permission. Medium aliases small.
No-code owns report folders only. New coding tasks get a worktree created by Keel.
Change into the printed worktree. Optional --path, --branch and --base select its location and base.
To return to existing work, use resume <task-id> --worktree <path> with --size, --allow and --deliverable.
It preserves files, index and branch, resets verification, and retains the worktree at finish.
If prior owners are reported, repeat --from-session ID for each after confirming they stopped using it.
Release any attached runtime through its current owner before handoff. Never impersonate its session.
Do not write code in the canonical shared checkout. Cancel preserves unfinished work and ownership records.

The user is highly visual. Present the work in self-contained, visually designed HTML with concrete mockups and visual explanations. Choose the presentation freely; no template or fixed section structure is required.

For coding tasks, keep task artifacts inside the task’s worktree, with HTML pages in its root-level `/doc` folder. No-code tasks do not get a worktree: their HTML lives in temporary or provider-managed storage outside the repository. Prefer two HTML pages: one for the specification and full plan, and one for current progress, results, verification and remaining work. Overwrite the progress page in place so it reflects the current state, rather than accumulating chronological updates. Revise the specification when agreed scope or decisions change, keeping both pages consistent.

Coding paths are relative to the worktree; progress defaults to doc/<task>-progress.html.
No-code defaults to temporary HTML; --deliverable and --spec may name provider-managed HTML files.
Declared pages must exist. Commit coding-task pages with the work, verify the committed candidate,
then run handoff to acknowledge the current pages. A changed page or code snapshot needs handoff again.
Missing/stale HTML blocks one normal Stop continuation; explicit handoff and finish refuse until current.
Cancelling marks the task incomplete.

Permissions: review, implement, merge, push, distribution-build, store-submission, paid-job,
remote-write, publish. Declare only what the user authorized; re-declaration is not consent.
For fix tasks, use --kind fix. Record a failing check with verify and a cause with cause before
editing code. After three failed edit/check cycles, report the evidence; only the human reopens.

Run verify -- <command> at the worktree root. It records foreground exit and code identity.
Use the repository's required checks. A passing check on different code is stale.
Run pr --title <title> --body-file <file> to push the tested commit and open the PR.
Run ship --pr <number> after review/checks: GitHub merges the exact tested PR head, then Keel
pulls --ff-only in the clean canonical checkout's current configured protected branch. Add --admin
only for an explicitly authorized administrator exception; requested changes and failed/pending
checks still refuse. Queued merges stay pending; retry resumes an already-merged matching PR.
Or run ship --local to fast-forward
that same branch without network access; it requires merge permission and no configured
require_check_before_push policy. Use PR shipping when that policy names a check. Dirty, ahead, diverged,
unconfigured or busy canonical state stays sync_pending; never reset or autostash.
Run finish after shipping. It releases optional Slots resources, checks ownership/preservation/processes,
and removes newly created worktrees only after confirming their pages are preserved in canonical /doc.
Resumed trees remain. Shipping and cleanup outcomes live in task status; do not edit shared-main HTML
or rewrite pages after deletion. --keep retains a preview explicitly. Failed stages remain retryable.
AgentSlots is optional: dependencies and requested runtime only. No runtime means no Slots call.

MCP calls use the separate MCPClerk policy bridge. Missing MCPClerk or a refusal blocks only the MCP call; it does not stop ordinary coding, and task guard settings cannot soften a Clerk decision. Install it as `~/.local/bin/mcpclerk` or set the absolute `AGENTKEEL_MCPCLERK` executable path. Host-native permissions and trust remain separate. MCPClerk owns user `mcp_catalog.json` and project `mcpclerk.json`; migrate old AgentKeel policy explicitly with `mcpclerk migrate-keel`, keep the backup, then remove legacy MCP keys from `agentkeel.json` and the old user catalog before making MCP calls.

Use the smallest change that solves the request, reuse existing code, and test meaningful behavior.
When Ponytail is active, its coding principles replace these general coding preferences.
The debugging skill and task/ownership/HTML checks still apply.
Hooks catch supported tool operations; shell scripts and browser side effects can escape them.
The human-only open/import/release commands retain the stronger independent-clone boundary.
Status --html shows derived facts; it does not replace the task's review report.
