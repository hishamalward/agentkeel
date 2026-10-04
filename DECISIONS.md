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
| D-002 | The tier is state, for all tiers | Superseded by D-004 |
| D-003 | Four gates; verification is a rule, not a gate | Active |
| D-004 | The task record: size, permissions and resources, bound to one session | Active |
| D-005 | Judge every git operation in a command line, not the first | Active |
| D-006 | Overrides are written on the command, apply once, and are logged | Active |
| D-007 | Install into AGENTS.md, never CLAUDE.md; claims labelled by kind | Active |

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

**Status**: Superseded by D-004 (2026-10-04).
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

## D-004: The task record: size, permissions and resources, bound to one session (2026-10-04)

**Status**: Active.
**Decision**: `hooks/task.py start` writes one record per agent session to
`~/.agentkeel/tasks/<session-id>.json`: the size (small, medium, large), the permissions (review,
implement, merge, push, distribution-build, store-submission, paid-job) and the resources
(worktrees, write roots). Size buys process and never an action. Every code task, small
included, edits off the protected branch in its own worktree. The record has no expiry; it
belongs to the session that wrote it. Specs are approved by the human with `task.py approve`,
which the guard refuses from the agent, and an approval only counts inside the frontmatter with
an approver and a date.
**Why**: One tier answered three questions, which created permissions nobody granted: `small`
allowed a bare commit on `main`, and any session could reuse an unexpired tier file for eight
hours. Two independent reviews (2026-10-04) reproduced both, plus an approval read from a code
block. In the practice this came from, the most repeated corrections were about actions taken
without being asked (a build when only a push was asked for) and cleanup of other agents' work,
which are permission and resource questions, not size.
**Replaces**: D-002 (the tier as state), `tier.sh`, `tier-guard.py`, the eight-hour expiry, the
"small means explicit-path commits in the tree you are in" rule, and `AGENTKEEL_EXTRA_WRITE_ROOTS`
(now `--write-root`). State moves from `.claude/state/` to `AGENTKEEL_HOME`, out of the agent's
file-tool reach.

## D-005: Judge every git operation in a command line, not the first (2026-10-04)

**Status**: Active.
**Decision**: `hooks/agentkeel_core/` reads a command line as a list of simple commands (split on
`&&`, `;`, `|`, newlines, `$(...)`, `bash -c`, `eval`; heredoc bodies skipped; `cd` followed) and
reads each git invocation with its global options (`-C`, `-c`, `--git-dir`) and one level of
alias. Each becomes operations (push targets, a protected branch moved locally, a commit and
whether it names its paths, a destructive act) that `task-guard.py` judges against the record.
A merge or fast-forward into a protected branch is a ship action that needs `merge`.
**Why**: The v0.1 guard matched one regex per line, so `git push origin feat && git push origin
main`, `git push origin +main`, `git -c x=y push origin main` and `git merge --ff-only` on `main`
all passed. Each now has a test that fails against the v0.1 guard.
**Replaces**: `write-path-guard.py`, whose rules move into `task-guard.py`.

## D-006: Overrides are written on the command, apply once, and are logged (2026-10-04)

**Status**: Active.
**Decision**: The two overrides (`AGENTKEEL_ALLOW_DESTRUCTIVE=1`, `AGENTKEEL_SHOW_SECRETS=1`) count
only as a prefix on the command they apply to, and each use is appended to
`AGENTKEEL_HOME/overrides.jsonl`. A variable in the harness's own environment is not an override.
Pushing `main` has no override; it is the `push` permission.
**Why**: The documented `AGENTKEEL_ALLOW_PUSH_MAIN=1 git push origin main` never worked: the hook
read its own environment, not the command's. Reading the hook's environment instead would make an
override permanent and silent.
**Replaces**: `AGENTKEEL_ALLOW_PUSH_MAIN` and the environment-variable form of the other two.

## D-007: Install into AGENTS.md, never CLAUDE.md; claims labelled by kind (2026-10-04)

**Status**: Active.
**Decision**: `install.py` previews by default, merges hook entries into `.claude/settings.json`
without touching other entries, writes the fragment into `AGENTS.md` between markers, never
creates a `CLAUDE.md`, and reverses with `--uninstall`. It reports "configured, not yet verified"
and the one test that proves the hooks loaded. The README's capability table labels every
protection as prevents, warns after, guidance only or unsupported, with the test that covers it.
**Why**: Claude Code loads `AGENTS.md` only when no `CLAUDE.md` exists, so the v0.1 quickstart
(`>> CLAUDE.md`) hid the instructions from every other agent and from Claude itself in repos
that use `AGENTS.md`. The v0.1 README presented guidance as guarantees (the plan-size check runs
after the write; G3 had no hook; G4 did not check tests).
**Replaces**: the copy-by-hand quickstart and `templates/CLAUDE.agentkeel.md` (now
`templates/AGENTS.agentkeel.md`); the repo's own inert `.claude/settings.json` (now
`templates/claude-hooks.json`).

