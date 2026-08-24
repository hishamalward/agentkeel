# Gates

A gate is a point where work cannot proceed until a named owner produces named evidence. Under
that definition there are four. Verification is not one of them; it is the evidence rule (I2)
that every gate consumes.

| # | Gate | Owner | Entry | Exit evidence | Enforced by |
|---|---|---|---|---|---|
| G1 | Spec approval | Human | tier `large`; spec `status: draft` | `status: approved`, `approved_by`, `approved_on`; the `D-NNN` entry appended | `tier-guard.py` refuses edits outside `docs/` until then |
| G2 | Plan gate | AI: one plan reviewer and one scope auditor, in parallel, once | a handoff plan exists | the plan table with every "check scope inside may-touch" cell `yes`; findings applied | `plan-gate-guard.py` refuses a second round; `plan-size-guard.sh` refuses a plan carrying code |
| G3 | Review | AI reviewer, one round per scope | per task: that task's diff; whole branch: all tasks done | findings applied; no second round without the human | none in v0.1 |
| G4 | Ship | Human decides; AI supplies the evidence | rebased on `main`; tests green on the branch | fast-forward merge; `main` always green; merge and push only when asked | `write-path-guard.py` refuses a commit on `main` outside tier `small`, and a push to `main` without `AGENTKEEL_ALLOW_PUSH_MAIN=1` |

## G1, spec approval

The human reads the spec and rules. The ruling is recorded twice, on purpose: in the spec's
frontmatter (which the hook reads) and as a `D-NNN` entry (which people read later, when they
want to know why). A spec is never edited after approval except to mark it `superseded`; a change
of mind is a new spec or a new decision entry.

## G2, plan gate

Only when a plan exists, and a plan exists only when a different session will execute the work.
Two agents, one round, in parallel: a plan reviewer (does each task make sense against the spec)
and a scope auditor (does each check fit inside the files its task touches). Findings are applied
and the work starts. The revised plan is not re-gated; the per-task review is the net for what the
single gate missed. Dispatch prompts carry `[plan-gate]` so the guard counts deterministically.

## G3, review

One round per scope. After each task, a review of that task's diff; after the last task, one
review of the whole branch. Reviewing a revision does not open a new round. In practice this is
where the implementation defects were found (all in failure paths, none visible in the plan), so
it is the gate that earns its cost. There is no hook on it in v0.1; a dispatch-count cap is the
obvious next one.

## G4, ship

The agent rebases onto `main`, runs the tests on the branch, and reports. The human decides.
`main` must always be green because in the practice this came from, every push to `main`
deployed. Conflicts are resolved on the branch; there is no integration branch; the merge is a
fast-forward. The hooks refuse the two ways this gets skipped: a commit straight onto `main` when
the work was not declared small, and a push that moves `main` without the override that shows the
human asked for it.
