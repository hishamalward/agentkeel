# HTML delivery checkpoints

Present the work in self-contained, visually designed HTML with concrete mockups and visual explanations. Choose the presentation freely; no template or fixed section structure is required. Prefer two pages: the specification/full plan and current progress, results, verification and remaining work. Overwrite progress in place; update the spec when agreed scope or decisions change, keeping both consistent.

Coding-task artifacts stay inside the owned worktree. HTML goes in its root-level `/doc` folder. `--deliverable` names the progress page, defaulting to `doc/<task>-progress.html`. Optional `--spec` names a separate specification page. Relative paths resolve from the task worktree, even when declaring from the shared checkout. Escaping paths and symlink escapes are refused. Keel does not create page content.

No-code tasks have no worktree and do not edit repository files. Their HTML defaults to a session-specific temporary folder. `--deliverable` and `--spec` can name local HTML files in temporary or provider-managed storage outside the repository. Provider URLs alone cannot be checked: use the provider’s local artifact file. Temporary storage may be cleared by the OS/provider; export a report if you need to retain it.

Each declared page must be a readable, nonempty `.html` or `.htm` file with real `html`, `title` and `body` tags and nonempty title/body content. A separate spec is preferred, not mandatory. Handoff validates both declared files without imposing a section schema or judging visual quality.

For coding tasks, commit the pages with the work, run `verify` against the committed candidate, then `handoff`. Handoff records both page digests and the worktree’s content snapshot. Code or page changes invalidate that checkpoint; review/update the pages as needed and run handoff again. A verification run or rebase that leaves file contents unchanged does not force a cosmetic rewrite. Exact-SHA verification remains a separate shipping requirement.

Shipping can merge a remote PR through GitHub (`ship --pr NUMBER`, with `--admin` only for an explicitly authorized administrator exception) or local-only fast-forward (`ship --local`). Both require the exact verified commit and current HTML. The local path makes no network calls, requires `merge`, and only advances a clean canonical checkout already on its configured protected branch with no `require_check_before_push`. PR shipping also requires `push` and review/check gates. Administrator shipping permits missing review only; requested changes and failed/pending checks still refuse. Already-merged matching PRs resume synchronization on retry. A queued merge is not completion.

After shipping, `finish` checks that declared pages are tracked and preserved byte-for-byte in the canonical checkout before removing a newly created worktree. It retargets the task’s page paths there and completes. Resumed worktrees retain their pages and files in place. Shipping and cleanup outcomes are recorded in task status; do not edit shared-main HTML or rewrite deleted pages to complete cleanup. No-code skips shipping and leaves its files at their declared locations.

No-code and older external-report records retain timestamp freshness checks: update progress after the latest evidence or outcome, then hand off. Existing coding records with external pages can finish under their original contract; redeclare them with `/doc` paths to adopt this flow.

Stop blocks once for missing/stale HTML when invoked; it does not repeat if the host says it is already retrying. A cancelled task is retained without requiring a report update. Session start and status report live Stop enforcement as unverified: registration/trust is not proof that the host honors its decision. On an internal exception Stop logs the error and allows the turn to end without marking the task complete. `handoff` and `finish` remain explicit gates.

HTML is neither authorization nor a security boundary. Keep sensitive information out of committed pages and verify claims against their evidence.
