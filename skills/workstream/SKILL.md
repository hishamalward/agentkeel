---
name: workstream
description: "Open, list or close a git worktree per stream of work with scripts/workstream, attaching only the runtime resources the ask needs."
---

# Workstream

One stream of work gets one worktree, a sibling of the repository, on branch `<type>/<slug>`.
Nothing is declared or recorded; the worktree is the only state.

## When to create one

- Work where you were launched. If you are already inside a worktree, stay there. Several agents
  may share a tree; commit with explicit paths.
- Create a new tree only when the user asks for a new stream, or when you are on the protected
  branch (`main`) with code to change.
- Reviews, audits and questions never get a tree: no tracked edits, answer with HTML in the
  scratchpad or an artifact.

## Commands

```
scripts/workstream new <slug> [--type feat|fix|chore|docs|design|test|refactor] [--service NAME ...] [--prepare]
scripts/workstream ls
scripts/workstream done <slug> [--force]
```

`new` computes the path from the repository root (never from the shell cwd), so trees are never
nested. It attaches an AgentSlots slot only when you pass `--service` or `--prepare`; the default
is a bare tree. `done` releases the slot, then removes the tree and branch; it refuses a dirty
tree or unmerged commits unless `--force`.

## Choose resources from the ask

| The ask | Flags |
|---|---|
| docs, review, plan | no tree |
| web code, no schema or queue change | `--service web` |
| migrations, Prisma, data scripts | `--service web --service db` |
| background jobs, pg-boss | add `--service queue` (implies db) |
| mobile app, visual QA | add `--service mobile` (simulator lock) |
| fresh dependencies needed | add `--prepare` |

State the choice in your first update and why.

## Ship and close

`gh pr create`, wait for CI, `gh pr merge --auto --squash`. Never push `main`. After the PR
merges: `scripts/workstream done <slug>`.
