## Workstreams and reports

<!-- Paste into AGENTS.md or CLAUDE.md. Replace ../ma-<slug> with your sibling prefix. -->

- Work where you were launched. Create a worktree only when the user asks for a new stream,
  or when you are on `main` with code to change.
- New stream: `scripts/workstream new <slug> [--type feat] [--service NAME ...] [--prepare]`.
  It creates the sibling `../ma-<slug>` on branch `<type>/<slug>` from `main`, computes the
  path from the repository root (never from the shell cwd), and attaches runtime resources only
  for the services you name. Default is a bare tree with no slot.
- Several agents may share one worktree. There is no owner, no task record and no handoff.
  Commit with explicit paths, never `git commit -a`.
- `scripts/workstream ls` shows every tree with its branch and slot. `scripts/workstream done
  <slug>` releases the slot and removes the tree and branch; it refuses dirty trees or commits
  not on `main` unless `--force`.
- Reviews, audits and questions: no tree, no tracked edits. Reply with HTML in the scratchpad or
  an artifact.
- Coding work keeps its spec and progress pages in the tree's root-level `doc/`. Rewrite
  progress in place.
- Ship: `gh pr create`, wait for CI, then `gh pr merge --auto --squash`. Never push `main`.
  After the PR merges, run `scripts/workstream done <slug>`.
- Bugs: find the root cause, record a failing check first, change one thing at a time.
