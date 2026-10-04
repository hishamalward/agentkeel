# The invariants

Every rule in agentkeel serves one of these three. When two rules collide, the invariant decides.
When a rule serves none, it is deleted; that is the pruning rule the practice lacked.

## I1. Every write is bounded before it happens

The spec names what may change (`Changes`) and what must not (`Must not change`). The task record
says how much process the task bought (size), which actions it may take (permissions) and where
(resources). The hooks refuse what falls outside: a write with no task, a code edit on `main`, a
large-task edit before the spec is approved or outside its `Changes`, an edit outside the task's
worktrees, a destructive git command, moving or pushing `main` without the permission.

Applied to intent, I1 is scope discipline: do the literal ask, then stop. "Update the status
file" means update the status file, not also the plan, not also a tidy-up. An adjacent problem you
notice gets one line ("also noticed X, want it?"), never a fix. Each expansion is defensible on its
own, which is exactly why they accumulate, and the cost is that the human can never tell when a
task is finished. Finishing the work and shipping it are two decisions; the second is the human's.

## I2. Every claim carries its evidence

No completion claim without fresh output pasted. "Should work", "looks correct" and "probably
fine" mean the check was not run. Verify at the cheapest layer that can prove the change: a unit
test before an integration run, an integration run before a screenshot; hoisting logic into a
testable layer moves work from the expensive layer to the cheap one.

A failed check stops the work and is reported. It is never worked around: the scope is not
widened to satisfy the check, and the check is not narrowed to pass. This is the control that
caught the plan defects in practice, and it is the one an agent under pressure most wants to skip.

A check is scoped to the work it checks. A whole-file count behind a two-region edit, or `npm run
dev | head` as proof a server started, are checks that cannot pass or cannot fail; both are plan
defects.

## I3. Every loop has a cap, and only the human re-opens it

One plan gate per plan. One review round per scope (per task, then the whole branch). One
verification pass per claim. A retro or process suggestion is a proposal to the human, never
self-executed work.

The reason is not cost, although cost is where it shows. A control that re-runs on its own output
becomes a loop feeding itself: the later rounds find the defects the earlier rounds' revisions
introduced. The cap is what keeps a control a control.

## The pricing rule

Process is chosen once, by size, and size buys no permissions. Declare the task before the first
write; the record is state (`hooks/task.py`) and the hooks read it. When in doubt pick the smaller
size: upgrading is cheap and the human can always ask for more. A task never grows on its own; if
the work turns out bigger than declared, stop and say so, and the human re-scopes.
