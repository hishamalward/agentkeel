# Task record and CLI

A task record binds one host session to its declared work, permissions, resources and HTML pages. It is stored outside the repository under `AGENTKEEL_HOME` (default `~/.agentkeel`). It is the agent's declaration, not human consent; host permission prompts still apply.

## Start a task

Run `task.py start` from the repository's shared checkout before the first write:

```text
python3 task.py start <kebab-case-id> --size no-code|small|large --allow <permissions> \
  [--deliverable <progress.html>] [--spec <spec.html>] [--kind feature|fix|review|docs|chore] \
  [--path DIR] [--branch NAME] [--base REF]
```

Coding-task pages belong in the worktree’s root-level `/doc`. Paths are worktree-relative; progress defaults to `doc/<task>-progress.html`. Optional `--spec` declares a separate specification/full plan. No-code has no worktree: it defaults to temporary HTML, or accepts local files in provider-managed storage via `--deliverable` and `--spec`. Its report folders cannot be inside a repository, the filesystem root, a home directory or AgentKeel state. See [HTML delivery](delivery.md) for the visual guidance and checkpoint lifecycle.

Without `--base`, creation uses the canonical checkout’s current configured protected branch. For `small` and `large`, AgentKeel creates and records a linked worktree and prints its path. Change into that path before editing. `no-code` records no worktree. `size` describes process, not authority. `medium` remains a temporary alias for `small`.

Permissions are `review`, `implement`, `merge`, `push`, `distribution-build`, `store-submission`, `paid-job`, `remote-write` and `publish`. Each action requires its own permission. `kind` describes the task; `fix` enables the debugging guards.

## Resume existing work

Use `resume` when returning to a linked worktree, including one created before Keel's current
ownership manifests. Run it in the returning host session, not under a copied session ID:

```sh
python3 "$TASK" resume android --worktree /path/to/existing-worktree --size large \
  --allow review,implement --deliverable doc/android-progress.html --spec doc/android-spec.html
```

If another session owns it, the refusal prints the exact `--from-session ID` arguments needed.
Repeat the command with those arguments only after confirming the named sessions have stopped
using that worktree and the user wants the handoff. Multiple legacy claims require all their IDs.
An old record's timestamp is not proof that the session ended. The new workspace manifest is
authoritative; old task records remain as history, but current guards refuse their writes,
commits, pushes and MCP actions. An already-running command cannot be revoked by a hook.
Use current plugin hooks in every participating session; start a fresh host session after upgrading.

Resume does not create branches, move HEAD, stage, commit, stash or change worktree files.
It starts with fresh verification, shipping state and HTML checkpoint requirements. Permissions
are declared anew from the user's request. Primary checkouts, detached/protected branches,
changed identities and unfinished Git operations are refused. Finish or cancel a different
current task before resuming this one.

An attached runtime must be released by its current owner before handoff, even if paused.
Keel does not rewrite Slots' resource ownership. Attach requested services in the returning
session after resume. No runtime marker means no Slots command is needed.

After verified shipping, `finish` releases optional runtime resources and ends the claim but
retains a resumed worktree, branch and files. Its committed pages remain in place.
The retained tree can be resumed again. New worktrees made by `start` still use normal removal.
`--keep` continues to retain an active preview and its ownership instead of ending the claim.

## Commands

- `verify -- <command...>` runs a foreground check and records its result against the worktree's code state.
- `handoff` validates the current HTML and saves a checkpoint. Code or page changes make a coding-task checkpoint stale; review/update the pages and hand off again.
- `pr --title TITLE --body-file FILE` opens a pull request for the task's candidate.
- `ship --pr NUMBER [--admin]` verifies the exact candidate and its checks, merges the PR through GitHub with an exact-head match, then pulls the canonical protected branch with `--ff-only`. It requires `merge` and `push`. `--admin` is only for an explicitly authorized administrator exception: it permits a missing review but still refuses requested changes, failed/pending checks and changed code. GitHub decides whether the account may merge. A queued merge stays pending; retries recognize an already-merged matching PR and resume synchronization without merging twice.
- `ship --local` verifies the exact committed candidate and current HTML, then fast-forwards the clean canonical checkout's current configured protected branch without network access. It requires `merge` and refuses when `require_check_before_push` is configured; use the PR route then.
- `finish [--keep] [--discard-ignored]` checks delivery and cleanup state. Before removing a new worktree it confirms declared pages are tracked and preserved in canonical `/doc`, retargets their paths and completes. Task status records shipping/cleanup; no post-deletion page rewrite is required. `--keep` retains the worktree/runtime for a preview. Ignored generated caches (`__pycache__`, `.pytest_cache`, `node_modules`, `.DS_Store`) may be removed with the owned tree; the canonical checkout’s `disposable_ignored` policy can name additional disposable paths; other ignored local files block cleanup. `--discard-ignored` explicitly discards all remaining ignored files, including `.env` or local data, and logs the choice; it never waives clean tracked/untracked state, tip preservation or process checks.
- `cancel` marks the task cancelled and keeps its worktree, resources and record. Starting another task archives the cancelled ownership in the task directory; status continues to show it.
- Human-only `discard TASK --worktree PATH` releases resources and removes that cancelled owned worktree, including ignored files and unmerged changes. It records the explicit discard and refuses an active task, changed identity or active process. It can find both current and archived cancelled records.
- `status [--json|--html]` reads current task/worktree facts. `show` prints this session's record.
- Human-only `init [--policy FILE]` activates the plugin for the current repository in private local state. Human-only `deactivate` removes that activation and policy. `cause` and human-only `reopen` support fix tasks.

The legacy human-operated `open`, `import` and `release` commands manage isolated clones. They are separate from the linked-worktree flow and their OS sandbox boundary is platform dependent.

## Repository policy

AgentKeel keeps repository policy in the Git common directory as `agentkeel-policy.json`, so the primary checkout and all linked worktrees use one private local policy. It is never a repository file and cannot be committed. The policy configures `protected_branches`, task/secret/fix guard modes, additional command patterns, `disposable_ignored` and optional `require_check_before_push`.

`init` creates the default `{}` policy without changing the worktree. `init --policy FILE` validates a JSON object and copies it into private Git metadata. It prints the exact stored path. Repeating `init` without `--policy` preserves the current policy. `deactivate` removes the private policy and the repository's entry from `AGENTKEEL_HOME/opted-in.json`; it also leaves repository files unchanged. MCP catalog and tool policy are managed by MCPClerk; see [guardrails](guardrails.md#mcpclerk-bridge) for explicit migration and legacy cleanup requirements.

The task record is not a security boundary around arbitrary processes. See [guardrails](guardrails.md) and [enforcement design](enforcement-design.md).

`disposable_ignored` lists additional generated files or directories safe to delete with an owned
worktree. Read from the canonical checkout, entries are exact paths relative to the worktree
root; directories include descendants. For example:

```json
{"disposable_ignored": [".venv", ".mypy_cache", "dist", ".coverage"]}
```

Only ignored files are eligible. `.venv` does not match `.venv-backup` or `other/.venv`.
Use no leading/trailing slash, empty/dot/parent segments, backslashes or globs; invalid entries
block normal cleanup. This adds to the built-in cache conventions and does not authorize
deletion of any other ignored data.
