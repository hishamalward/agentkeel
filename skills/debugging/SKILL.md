---
name: debugging
description: "Use for any task declared with --kind fix, or any bug: find the root cause, record a failing check first, change one thing at a time."
---

# Debugging

## The five rules

1. Root cause before fixes. No fix without knowing why the bug happens.
2. A bug across components is instrumented at each boundary before anyone guesses.
3. One hypothesis, one change. Verify, then take the next.
4. Record a failing check before the fix: a test that fails for the stated cause. Run the new
   check against the old code and watch it fail, or it is decoration (a suite can pass because
   of the bug).
5. Three failed fixes mean the design is questioned. Do not try a fourth.

## What the guards enforce

When the task is declared `--kind fix`:

- No code edit until the evidence list holds one `task.py verify` run that failed.
- No code edit until `task.py cause "<one line>"` is recorded.
- The fourth edit-then-failed-verify cycle is refused until the human runs
  `task.py reopen <task>`.

## What only you can judge

A hook cannot check these two:

- Is the stated cause the real cause? Trace the bad data back to where it starts.
- Was each boundary instrumented?

## The cause line

One sentence: "X causes Y because Z". Example: "The retry loop causes duplicate rows because
it re-sends before the first insert commits."
