# Tiering

Declare before the first write, in one command:

```bash
.claude/hooks/tier.sh small|medium|large <slug>
```

It writes `.claude/state/agentkeel-tier.json` at the top of the current worktree: tier, slug,
branch, declared time, expiry (`AGENTKEEL_TIER_TTL_HOURS`, default 8). Every guard reads it.

| Tier | Trigger | Process | The hooks require |
|---|---|---|---|
| `small` | a direct ask, one file, anything finishable inside roughly an hour | inline, in the tree you are in; no plan, no worktree, no subagents; one verification pass; report | a live declaration |
| `medium` | a feature spanning files | branch or worktree, tests, implement, one review round | the branch is not `main`; writes stay inside this worktree |
| `large` | a different session will execute the work, or the human asked for a spec or a plan | spec approved by the human; plan as a table, gated once; per-task review; whole-branch review; ship | an approved spec before any edit outside `docs/`; the plan gated once |

Rules:

- **No declaration, no writes.** If `small` were the silent default, an undeclared session could
  commit on `main`. The safe default is refusal with a one-line instruction.
- **The declaration overrides any skill's own trigger** to brainstorm, plan or spawn subagents by
  default. Process is chosen here, once, by size.
- **When in doubt, smaller.** Upgrading later is cheap; the human can always ask for more.
- **A task never grows a tier on its own.** If it turns out bigger, stop and say so. Re-declaring
  is permitted and recorded (`previous` in the state file, a note on stderr); deciding whether the
  task really grew is the human's job.
- **`small` in a shared tree means explicit paths**: `git commit -m "..." -- <paths>`. A bare
  `git commit` commits the whole index, including whatever another agent had staged.
- **Expiry** exists so that yesterday's `small` cannot grant today's commit on `main`.
- **`branch` in the state file is informational.** The guards read the live branch of the tree the
  call runs in, so declaring on `main` and then creating the branch is fine.
