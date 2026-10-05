# Gates

A gate is a point where work cannot proceed until a named owner produces named evidence. Under
that definition there are four. Verification is not one of them; it is the evidence rule (I2)
that every gate consumes.

| # | Gate | Owner | Entry | Exit evidence | Enforced by |
|---|---|---|---|---|---|
| G1 | Spec approval | Human | size `large`; spec `status: draft` | `status: approved`, `approved_by`, `approved_on` in frontmatter; the `D-NNN` entry appended | `task-guard.py` refuses edits outside `docs/` until then, and refuses the agent writing the approval |
| G2 | Plan gate | AI: one plan reviewer and one scope auditor, in parallel, once | a handoff plan exists | the plan table with every "check scope inside may-touch" cell `yes`; findings applied | `plan-gate-guard.py` refuses a third dispatch; `plan-size-guard.sh` reports a plan over 300 lines after the write |
| G3 | Review | AI reviewer, one round per scope | per task: that task's diff; whole branch: all tasks done | findings applied; no second round without the human | guidance only |
| G4 | Ship | Human decides; AI supplies the evidence | tests green on the branch | `main` moved and pushed only within the task's permissions | `task-guard.py` refuses moving `main` without `merge` and pushing it without `push`; tests before `main` moves need a required CI check |

## G1, spec approval

The human reads the spec and rules. The ruling is recorded twice, on purpose: in the spec's
frontmatter (which the hook reads) and as a `D-NNN` entry (which people read later, when they
want to know why). The human records it with `task.py approve <task-id>` in a terminal of their own;
the guard refuses that command from the agent, and any agent edit that marks a spec approved or
changes an approved one other than to mark it `superseded`. A spec is never edited after approval except to mark it `superseded`; a change
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
it is the gate that earns its cost. No hook enforces it yet; a dispatch-count cap is the obvious
next one.

## G4, ship

The agent runs the tests on the branch and reports. The human decides, and the request sets the
scope: "merge and push" is the `merge` and `push` permissions for that task, and the agent does
both without asking again. `main` must always be green because in the practice this came from,
every push to `main` deployed. Conflicts are resolved on the branch; there is no integration
branch. The hooks refuse moving `main` without `merge` (a commit on it, a merge, a
fast-forward, a reset, an update-ref) and pushing it without `push`. They cannot prove the tests
passed: that needs a required check on the candidate commit before `main` moves, with deployment
waiting for it, which is CI's job: [`required-checks.md`](required-checks.md) has the template and
the settings.
