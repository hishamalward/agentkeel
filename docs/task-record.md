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

For `small` and `large`, AgentKeel creates and records a linked worktree and prints its path. Change into that path before editing. `no-code` records no worktree. `size` describes process, not authority. `medium` remains a temporary alias for `small`.

Permissions are `review`, `implement`, `merge`, `push`, `distribution-build`, `store-submission`, `paid-job`, `remote-write` and `publish`. Each action requires its own permission. `kind` describes the task; `fix` enables the debugging guards.

## Commands

- `verify -- <command...>` runs a foreground check and records its result against the worktree's code state.
- `handoff` validates the current HTML and saves a checkpoint. A later code change with an unchanged report makes the checkpoint stale; update the report and hand off again.
- `pr --title TITLE --body-file FILE` opens a pull request for the task's candidate.
- `ship --pr NUMBER` checks the ready PR and successful checks against the exact candidate, pushes that SHA to `main`, and synchronizes the canonical checkout. It requires `merge` and `push`.
- `finish [--keep]` checks delivery and cleanup state. After worktree cleanup it may return `report_pending`; refresh the report to reflect cleanup and rerun `finish`. `--keep` retains the worktree/runtime for a preview.
- `cancel` marks the task cancelled and keeps its worktree, resources and record.
- `status [--json|--html]` reads current task/worktree facts. `show` prints this session's record.
- `init` opts the current repository into the plugin. `cause` and human-only `reopen` support fix tasks. `mcp draft SERVER` prints a catalog entry from this task's unseen-tool log.

The legacy human-operated `open`, `import` and `release` commands manage isolated clones. They are separate from the linked-worktree flow and their OS sandbox boundary is platform dependent.

## Repository policy

`agentkeel.json` configures `protected_branches`, per-guard modes, additional command patterns, MCP service entries and optional `require_check_before_push`. `init` creates `{}` only when the file is absent, preserves existing policy, updates only the managed `AGENTS.md` block and registers the repository outside it. It never commits. The `mcp_unknown` guard defaults to `pass`; other guards default to `block`.

The task record is not a security boundary around arbitrary processes. See [guardrails](guardrails.md) and [enforcement design](enforcement-design.md).
