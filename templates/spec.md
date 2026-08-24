---
slug: <kebab-case-slug>
tier: large
status: draft            # draft | approved | superseded   (tier-guard reads this)
approved_by:
approved_on:
supersedes:              # a D-NNN or a spec slug, if any
---

# <slug>: spec

## 1. Problem, and the rulings already made

One paragraph: what is wrong or missing, for whom, and what "done" changes. Then the decisions
the human has already made that this spec must respect (cite D-NNN).

## 2. Verified facts

Tasks are written against these, not against assumptions.

| Fact | Value | How checked |
|---|---|---|
| | | |

## 3. Design

What will exist when this is done. Interfaces, data, the order things happen in. No code.

## 4. Blast radius

- **Changes** (paths that may change):
- **Must not change** (paths that must be byte-identical after this work):
- **Boundary**: the nearest adjacent system and the one rule about it (e.g. "reads the queue
  table, never writes it").

## 5. Success criteria, split by owner

**AI-verifiable** (a command and its expected output; each becomes a check in the plan):

| # | Criterion | Command | Expected |
|---|---|---|---|
| A1 | | | |

**Human-verifiable** (a fact the human can check in under a minute):

| # | Criterion | How to check |
|---|---|---|
| H1 | | |

## 6. Out of scope

What this deliberately does not do, so nobody has to guess.

## 7. Residual risks

What could still go wrong after every criterion passes, and what would catch it.

## 8. Decision entry

The `D-NNN` entry for `DECISIONS.md`, written now, appended when this spec is approved:

> **D-NNN: <title>** (<date>). Status: Active. Decision: ... Why: ... Replaces: ...

## 9. Rule change clause

Any rule this spec introduces names the rule it replaces, or states in one line why nothing
existing covers it. If this spec introduces no rule, say "none".
