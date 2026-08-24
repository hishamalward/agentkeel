# Decisions (history, not current state)

Append-only. Entries record what was decided, when, and why, including positions later reversed.
The **status index** below is the one thing rewritten in place; an entry's body is never edited
after it is appended. When a decision is reversed: append the new `D-NNN`, set the old entry's
status line, update its index row, all in one change. Any decision that introduces a rule names
the rule it replaces, or says why nothing existing covers it. When this log grows past about
fifty entries, split the status index into its own present-tense register; not before.

## Status index

| D | Decision (short) | Status |
|---|---|---|
| D-001 | Plans never carry code | Active |
| D-002 | The tier is state, for all tiers | Active |
| D-003 | Four gates; verification is a rule, not a gate | Active |

## D-001: Plans never carry code (2026-08-23)

**Status**: Active.
**Decision**: A plan is a task table (task, files it may touch, blocked by, check, expected,
check scope inside may-touch). It never contains implementation. If the deliverable is small
enough that the plan would have to carry the code, there is no plan.
**Why**: In practice a plan that transcribed the implementation made implementers into
transcribers whose transcription was then reviewed, so the work happened twice; the worst case was
a 4105-line plan for 541 lines of shell. Three rules (right-size the plan, two plan modes, gate
once) were workarounds for that one cause.
**Replaces**: the "small mode carries the code, large mode carries interfaces, never both" rule.
`plan-size-guard.sh` now enforces this with a 300-line limit and the message "a plan this long is
carrying code".

## D-002: The tier is state, for all tiers (2026-08-23)

**Status**: Active.
**Decision**: The tier is declared with `hooks/tier.sh`, written to `.claude/state/`, and read by
the guards. No declaration means no writes, at every tier.
**Why**: A tier stated in a sentence is read by nobody. If `small` were the silent default, an
undeclared session could commit on `main`, which is the unsafe default the hooks exist to remove.
The cost is one command per task, which the agent runs itself.
**Replaces**: "state the tier in one line" as prose only. The prose stays; the state is new.

## D-003: Four gates; verification is a rule, not a gate (2026-08-23)

**Status**: Active.
**Decision**: A gate is a point where work cannot proceed until a named owner produces named
evidence. Four qualify: spec approval (human), plan gate (AI, once), review (AI, one round per
scope), ship (human). Verification is the evidence rule every gate consumes.
**Why**: Listing every loop as a gate produced six and made "gate" mean "step". The strict
definition gives each gate an owner and an exit, which is what makes it enforceable.
**Replaces**: nothing existing covers this; earlier counts (five, six) were descriptions, not
definitions.
