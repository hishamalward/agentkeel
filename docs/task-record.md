# Task record and CLI

A task record binds one host session to its declared work, permissions, resources and persistent HTML deliverable. It is stored outside the repository under `AGENTKEEL_HOME` (default `~/.agentkeel`). It is the agent's declaration, not human consent; host permission prompts still apply.

## Start a task

Run `task.py start` from the repository's shared checkout before the first write:

```text
python3 task.py start <kebab-case-id> --size no-code|small|large --allow <permissions> \
  --deliverable /absolute/path/report.html [--kind feature|fix|review|docs|chore] \
  [--write-root DIR]... [--path DIR] [--branch NAME] [--base REF]
```

`--deliverable` is required. Its parent is the default write root; otherwise the report must be within a repeated `--write-root`. Roots cannot be a repository, the filesystem root, a home directory or AgentKeel state. The HTML must be persistent and outside any disposable worktree.

Without `--base`, creation uses the canonical checkout’s current configured protected branch. For `small` and `large`, AgentKeel creates and records a linked worktree and prints its path. Change into that path before editing. `no-code` records no worktree. `size` describes process, not authority. `medium` remains a temporary alias for `small`.

Permissions are `review`, `implement`, `merge`, `push`, `distribution-build`, `store-submission`, `paid-job`, `remote-write` and `publish`. Each action requires its own permission. `kind` describes the task; `fix` enables the debugging guards.

## Commands

- `verify -- <command...>` runs a foreground check and records its result against the worktree's code state.
- `handoff` validates the current HTML and saves a checkpoint. A later code change with an unchanged report makes the checkpoint stale; update the report and hand off again.
- `pr --title TITLE --body-file FILE` opens a pull request for the task's candidate.
- `ship --pr NUMBER [--admin]` verifies the exact candidate and its checks, merges the PR through GitHub with an exact-head match, then pulls the canonical protected branch with `--ff-only`. It requires `merge` and `push`. `--admin` is only for an explicitly authorized administrator exception: it permits a missing review but still refuses requested changes, failed/pending checks and changed code. GitHub decides whether the account may merge. A queued merge stays pending; retries recognize an already-merged matching PR and resume synchronization without merging twice.
- `ship --local` verifies the exact committed candidate and current HTML, then fast-forwards the clean canonical checkout's current configured protected branch without network access. It requires `merge` and refuses when `require_check_before_push` is configured; use the PR route then.
- `finish [--keep] [--discard-ignored]` checks delivery and cleanup state. After worktree cleanup it may return `report_pending`; refresh the report to reflect cleanup and rerun `finish`. `--keep` retains the worktree/runtime for a preview. Ignored generated caches (`__pycache__`, `.pytest_cache`, `node_modules`, `.DS_Store`) may be removed with the owned tree; the canonical checkout’s `disposable_ignored` policy can name additional disposable paths; other ignored local files block cleanup. `--discard-ignored` explicitly discards all remaining ignored files, including `.env` or local data, and logs the choice; it never waives clean tracked/untracked state, tip preservation or process checks.
- `cancel` marks the task cancelled and keeps its worktree, resources and record. Starting another task archives the cancelled ownership in the task directory; status continues to show it.
- Human-only `discard TASK --worktree PATH` releases resources and removes that cancelled owned worktree, including ignored files and unmerged changes. It records the explicit discard and refuses an active task, changed identity or active process. It can find both current and archived cancelled records.
- `status [--json|--html]` reads current task/worktree facts. `show` prints this session's record.
- `init` opts the current repository into the plugin. `cause` and human-only `reopen` support fix tasks.

The legacy human-operated `open`, `import` and `release` commands manage isolated clones. They are separate from the linked-worktree flow and their OS sandbox boundary is platform dependent.

## Repository policy

`agentkeel.json` configures `protected_branches`, task/secret/fix guard modes, additional command patterns, `disposable_ignored` and optional `require_check_before_push`. `init` creates `{}` only when the file is absent, preserves existing policy, updates only the managed `AGENTS.md` block and registers the repository outside it. It never commits. MCP catalog and tool policy are managed by MCPClerk; see [guardrails](guardrails.md#mcpclerk-bridge) for explicit migration and legacy cleanup requirements.

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
