## agentkeel (paste into CLAUDE.md; hooks in .claude/hooks; full text: github.com/hishamalward/agentkeel)

Three invariants sit above every rule here. A rule that serves none of them is deleted.
1. Every write is bounded before it happens. Do the literal ask; mention an adjacent problem in
   one line, never fix it. Do not merge or push unless asked.
2. Every claim carries its evidence. No "should work": run the check, paste the output, then say
   it passes. A failed check stops the work and is reported; never widen scope or narrow the check
   to make it pass.
3. Every loop has a cap, and only the human re-opens it. One plan gate per plan, one review round
   per scope, one verification pass per claim.

**Before the first write, declare the tier. It is state, and the hooks read it.**
    .claude/hooks/tier.sh small|medium|large <slug>
- small: a direct ask, one file, under about an hour. Inline, in the tree you are in, explicit
  path commits (git commit -m "..." -- <paths>). No plan, no worktree, no subagents.
- medium: a feature spanning files. Branch or worktree, tests, implement, one review round.
- large: a different session executes, or the human asked for a spec. Spec approved before any
  edit outside docs/; plan as a table, gated once; per-task review; whole-branch review; ship.
When in doubt pick the smaller tier. A task never grows a tier on its own: if it turns out bigger,
stop and say so. Re-declaring is recorded; deciding is the human's.

**Gates** (a point where work stops until a named owner produces named evidence):
- G1 Spec approval, human: docs/specs/<slug>-spec.md with `status: approved` and a D-NNN entry.
- G2 Plan gate, AI, once: one plan reviewer plus one scope auditor in parallel, prompts marked
  `[plan-gate]`; every plan row's check must be scoped inside the files the task touches.
- G3 Review, AI, one round per scope: per task, then the whole branch.
- G4 Ship, human decides: rebased on main, tests green on the branch, fast-forward merge.
Verification is not a gate; it is the evidence every gate consumes.

**What the hooks refuse** (exit 2 with the reason; overrides are env vars echoed on use):
- any write with no tier declared or an expired one; medium/large writes while on main; large
  writes outside docs/ before the spec is approved (tier-guard)
- git commit on main unless tier small; git push that moves main (AGENTKEEL_ALLOW_PUSH_MAIN=1);
  destructive git (AGENTKEEL_ALLOW_DESTRUCTIVE=1); edits outside this worktree
  (AGENTKEEL_EXTRA_WRITE_ROOTS=/path) (write-path-guard)
- printing secrets: cat .env, printenv, echo $API_KEY (AGENTKEEL_SHOW_SECRETS=1) (secret-guard)
- a third plan-gate dispatch for the same plan (plan-gate-guard)
- a plan over 300 lines: plans never carry code (plan-size-guard, after the write)

**Registers**: docs/specs/<slug>-spec.md (intend), DECISIONS.md (decide, append-only, status
index rewritten in place), docs/handovers/<slug>.md (resume; no derivable state). Any new rule
names the rule it replaces, or says in one line why nothing existing covers it.

**Isolation is not this file's job.** A worktree isolates the filesystem only; database, ports
and queues are agent-slots' problem.
