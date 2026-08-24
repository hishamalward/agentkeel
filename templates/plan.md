# <slug>: plan

Written only because a different session will execute this work. If the same session that
designed it will build it, delete this file and go straight to the task list with per-task review.

Spec: `docs/specs/<slug>-spec.md` (must be `status: approved`).
Gate: one round, one plan reviewer plus one scope auditor in parallel, dispatched with
`[plan-gate]` in the prompt. Not re-gated after revision.

A plan carries no code. Every row's check must be scoped inside the files the row may touch; a
"no" in the last column is a plan defect, and it was the dominant defect in practice.

| # | Task | May touch | Blocked by | Check (command) | Expected | Check scope inside "may touch"? |
|---|---|---|---|---|---|---|
| T1 | | | | | | yes / no |
| T2 | | | T1 | | | |

After every task: one review round of that task's diff (G3). After the last task: one review of
the whole branch (G3), then ship (G4).
