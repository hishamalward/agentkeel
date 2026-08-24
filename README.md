# agentkeel

[![validate](https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml/badge.svg)](https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml)

A framework for shipping production code with AI coding agents: work priced by size, spec-first,
four gates with named owners, blast radius bounded by hooks.

AI coding agents now write code faster than anyone reviews it. The failures that follow are
rarely in the code. They are the missing gates: a task that quietly grew from a one-file fix into a
refactor, a plan reviewed three times before a line was written, a verification step that could
not fail, a commit that landed on `main` because nothing stood in the way. Writing rules into a
`CLAUDE.md` does not hold, because the session that drifts is the same session that read the
rules.

agentkeel is the practice that came out of shipping a real product solo with agents writing the
code, extracted and made enforceable. Three invariants sit above every rule: every write is
bounded before it happens, every claim carries its evidence, every loop has a cap and only a
human re-opens it. Work is sized once, as a declaration the hooks can read. A spec says who
verifies each success criterion. Four gates each name an owner. The write path is guarded by
hooks that run in the harness, outside the model's memory.

The result in practice: a plan gated once instead of three times, seven plan defects caught
before implementation against zero found in the code afterwards, and a `main` branch that stays
green because a commit on it is refused unless the work was declared small.

## The invariants

Every rule in this repo serves one of these, and a rule that serves none is deleted. The full
statement is in [`docs/invariants.md`](docs/invariants.md).

1. **Every write is bounded before it happens.** The spec names what may change and what must
   not; the tier declaration says how much process the change bought; the hooks refuse what falls
   outside. Scope discipline is this invariant applied to intent: do the literal ask, mention the
   adjacent problem in one line, do not fix it.
2. **Every claim carries its evidence.** No completion claim without fresh output pasted. Verify
   at the cheapest layer that can prove the change. A failed check stops the work and is reported;
   it is never worked around, and the check is never narrowed to pass.
3. **Every loop has a cap, and only the human re-opens it.** One plan gate per plan, one review
   round per scope, one verification pass per claim. A control that re-runs on its own output
   turns into a loop feeding itself.

And one pricing rule: **process is chosen once, by size.** Declare the tier before the first
write, and never let a task grow a tier on its own. If it turns out bigger, stop and say so.

## Tiering as state

The tier is not a sentence in the transcript. It is one command, and every guardrail keys off it:

```bash
.claude/hooks/tier.sh medium json-flag     # writes .claude/state/agentkeel-tier.json
```

| Tier | Trigger | What the declaration permits | What the hooks require |
|---|---|---|---|
| `small` | a direct ask, one file, under about an hour | explicit-path commits in the tree you are in | nothing else; the declaration expires (8 h by default) |
| `medium` | a feature spanning files | commits on a branch; one review round | the branch is not `main`; edits stay inside this worktree |
| `large` | a different session will execute, or the human asked for a spec | everything above, plus a plan and a whole-branch review | an approved spec before any edit outside `docs/`; the plan gated once |

No declaration means no writes. If `small` were the silent default, an undeclared session could
commit on `main`, which is the unsafe default the hooks exist to remove. Re-declaring is allowed
and recorded; deciding whether the task really grew is the human's job. Details:
[`docs/tiering.md`](docs/tiering.md).

## Spec first, and plans that never carry code

A `large` task starts with [`templates/spec.md`](templates/spec.md). The parts that matter:

- **Blast radius**: `Changes` (paths), `Must not change` (paths), and one named boundary with the
  nearest adjacent system.
- **Success criteria split by owner**: *AI-verifiable* criteria are a command and its expected
  output; *human-verifiable* criteria are a fact a person can check in under a minute.
- **Frontmatter** the hooks read: `status: draft | approved | superseded`, `approved_by`,
  `approved_on`. Until the spec says `approved`, the tier guard refuses edits outside `docs/`.
- **Rule change clause**: any rule the spec introduces names the rule it replaces, or says in one
  line why nothing existing covers it.

A plan, when a different session will execute the work, is a table
([`templates/plan.md`](templates/plan.md)): task, files it may touch, blocked by, the check that
proves it, and whether the check's scope fits inside the files the task touches. That last column
exists because it was the dominant plan defect in practice: a verification scoped wider than the
work it checks (a whole-file count behind a two-region edit; `npm run dev | head` as proof a server
started). Plans carry no code. If the deliverable is small enough that the plan would carry the
code, there is no plan.

## The four gates

A gate is a point where work cannot proceed until a named owner produces named evidence.
Verification is not a gate; it is the evidence rule every gate consumes.

| # | Gate | Owner | Entry | Exit evidence | Enforced by |
|---|---|---|---|---|---|
| G1 | Spec approval | Human | tier `large`; spec `status: draft` | `status: approved`, `approved_by`, a `D-NNN` entry | `tier-guard.py` refuses non-doc edits before it |
| G2 | Plan gate | AI: one plan reviewer and one scope auditor, in parallel, once | a handoff plan exists | the plan table with every scope column `yes`; findings applied | `plan-gate-guard.py` refuses a second round; `plan-size-guard.sh` refuses a plan carrying code |
| G3 | Review | AI reviewer, one round per scope | per task: the task's diff; whole branch: all tasks done | findings applied; no second round without the human | none in v0.1 |
| G4 | Ship | Human decides; AI supplies the evidence | rebased on `main`, tests green on the branch | fast-forward merge; `main` always green; merge and push only when asked | `write-path-guard.py` refuses a commit on `main` outside tier `small` and a push to `main` without an explicit override |

Two gates are human-owned (G1, G4), two are AI-owned (G2, G3). [`docs/gates.md`](docs/gates.md)
has a paragraph per gate.

## Guardrails and hooks

Six small programs, no dependencies, Python 3.10+ and bash 3.2. Each runs in the harness before or
after a tool call, reads the call as JSON on stdin (shapes captured in
[`docs/hook-payloads.md`](docs/hook-payloads.md)), and either allows (exit 0) or blocks with a
reason the model sees (exit 2). A hook that cannot parse its input allows: a broken guard must
never stop work on its own. Every override is an environment variable that the hook echoes to
stderr when used, so an override is always visible in the transcript.

| Hook | Event | Blocks | Cannot see | Override |
|---|---|---|---|---|
| `tier.sh` | (the command) | writes the declaration | | |
| `tier-guard.py` | PreToolUse `Write\|Edit\|Bash` | any write with no declaration or an expired one; `medium`/`large` writes while on `main`; `large` writes outside `docs/` before the spec is approved | shell writes that are not `git commit` (a `sed -i` is invisible to it); edits under `docs/` are always allowed | declare a tier |
| `write-path-guard.py` | PreToolUse `Bash\|Write\|Edit` | `git commit` on `main` unless tier is `small`; `git push` to `main`; destructive git (`push --force`, `reset --hard`, `checkout -- .`, `clean -f`, `branch -D`); `Write`/`Edit` outside the worktree's git top-level (temp directories allowed) | writes done by shell commands other than git; a second repo the command `cd`s into | `AGENTKEEL_ALLOW_PUSH_MAIN=1`, `AGENTKEEL_ALLOW_DESTRUCTIVE=1`, `AGENTKEEL_EXTRA_WRITE_ROOTS=/path:/path` |
| `secret-guard.py` | PreToolUse `Bash` | printing `.env*` (not `.env.example`), key files, `~/.aws/credentials`; bare `env` / `printenv`; `echo $ANY_KEY_OR_TOKEN`; `git show`/`diff` of `.env` | a secret read by a program rather than printed by the shell (the point is showing, not using) | `AGENTKEEL_SHOW_SECRETS=1` |
| `plan-gate-guard.py` | PreToolUse `Agent` | a third gate dispatch naming the same plan file | a re-worded dispatch, because detection is a heuristic over the prompt; the `[plan-gate]` marker is the deterministic path | edit `.claude/state/plan-gates.json`, deliberately |
| `plan-size-guard.sh` | PostToolUse `Write\|Edit` | a `docs/plans/*plan*.md` over 300 lines | a plan split across files | none; cut the plan |

What the hooks cannot do is stated in the table because it matters more than what they can: they
see tool calls, not the filesystem, so the guarantee is "the agent's tool calls were bounded", not
"nothing else touched the tree". [`docs/guardrails.md`](docs/guardrails.md) has the full
write-safety pattern (read-only preview by default, explicit authorization to apply, stable IDs,
atomic writes, a recoverable journal), reused from [toilscan](https://github.com/hishamalward/toilscan).

**Isolation is a different problem.** A git worktree isolates the filesystem and nothing else: the
database, the ports, the job queue and the simulator stay shared. That is runtime isolation, and
it lives in [agent-slots](https://github.com/hishamalward/agent-slots), where one integer derives a
worktree, a database, two ports and a queue schema. agentkeel assumes you have it or do not need it.

## The three registers

Three files with three different verbs. No router, no index; if the docs need a router there are
too many docs.

| Register | Verb | Path | Rule |
|---|---|---|---|
| Spec | intend | `docs/specs/<slug>-spec.md` | approved before build; never edited after approval except to mark it superseded |
| Decisions | decide | `DECISIONS.md` | append-only entries; a status index at the top is the one thing rewritten in place |
| Handover | resume | `docs/handovers/<slug>.md` | no derivable state: nothing that `git` or a status script can answer; goal, ledger, what will bite, what is next |

The `DECISIONS.md` convention, with one real entry, is in this repo's own
[`DECISIONS.md`](DECISIONS.md): `D-NNN`, date, status, decision, why, and what it replaces (a rule,
a `D-NNN`, or "nothing existing covers this"). When the log grows past about fifty entries, split
the status index into its own present-tense register; not before.

## Quickstart (5 minutes)

```bash
git clone https://github.com/hishamalward/agentkeel
cd your-repo
mkdir -p .claude/hooks .claude/state docs/specs docs/plans docs/handovers
cp ../agentkeel/hooks/* .claude/hooks/
cp ../agentkeel/.claude/settings.json .claude/settings.json     # or merge the "hooks" block into yours
cp ../agentkeel/templates/*.md docs/                            # spec, plan, handover templates
cat ../agentkeel/templates/CLAUDE.agentkeel.md >> CLAUDE.md      # 60 lines at most
for h in .claude/hooks/*.py; do python3 "$h" --selftest; done   # every hook proves itself
```

Then open Claude Code in the repo and ask for a small change without declaring a tier. The first
`Write` is refused with the one line that tells the agent what to run. Declare `small`, and it goes
through. Ask it to commit on `main` after declaring `medium`, and that is refused too.

## Worked example, run for real

Captured 2026-08-23 with Claude Code 2.1.241, driven non-interactively (`claude -p`) in a
throwaway repo containing a 12-line `cli.py` word counter, with the hooks wired exactly as in
[`.claude/settings.json`](.claude/settings.json) and the 45-line fragment as the whole `CLAUDE.md`.
Every quoted block below is a hook's actual stderr from those runs; nothing was typed. The task
throughout: add a `--json` flag.

**1. An undeclared write is refused.** Prompt: "change the default output line so it ends with a
period; just edit the file directly, before anything else." The first `Edit`:

```
TIER GUARD: no tier declared for this worktree.

Declare it first, in one command, then retry:
  .claude/hooks/tier.sh small|medium|large <slug>
```

The agent ran `.claude/hooks/tier.sh medium cli-period` (as the prompt asked it to) and tried the
edit again:

```
TIER GUARD: tier medium was declared for 'cli-period' but this tree is on 'main'.
medium and large work happens on a branch, usually in its own worktree:
  git worktree add ../<repo>-cli-period -b feat/cli-period
then declare the tier again inside that worktree. If this really is a one-file fix,
declare small instead; that is recorded.
```

It re-declared `small` (`tier.sh` printed `re-declared medium -> small` and kept `previous` in
the state file), and the one-line edit went through.

**2. Medium: branch, implement, one review, and a ship attempt.** Prompt: add `--json`, tier
medium. The agent declared `medium`, ran `git checkout -b feat/json-flag`, edited `cli.py`,
verified (`parsed: {'lines': 20, 'words': 69, 'chars': 687}` pasted from a real run), dispatched
one review round (PASS; one adjacent issue noted in a line and not fixed), and committed with
`git commit -m "..." -- cli.py`. Then, as instructed, it tried
`git checkout main && git merge --ff-only feat/json-flag && git push origin main`:

```
WRITE PATH GUARD: refusing a push that moves main.
Finishing the work and shipping it are two decisions; the second is the human's.
When asked, run it with AGENTKEEL_ALLOW_PUSH_MAIN=1 so the override is on record.
```

PreToolUse refused the compound command before any of it ran: the checkout and the merge did not
happen either. `main` stayed where it was, and the agent's report ended with "G4 is your call".

**3. Large: no edit outside `docs/` before the spec is approved.** Same feature, tier `large`,
slug `json-flag`. The first edit attempt:

```
TIER GUARD: tier large requires an approved spec before any edit outside docs/.
docs/specs/json-flag-spec.md does not exist.
Write the spec from templates/spec.md, get the human's ruling, set
`status: approved` with `approved_by` and `approved_on` in its frontmatter,
and append the D-NNN entry. Edits under docs/ are allowed meanwhile.
```

The agent wrote the spec from the template (allowed: it is under `docs/`), left it
`status: draft`, tried the edit once more, was refused again with `has status 'draft'`, and
stopped: the ruling is the human's. (The first time this step ran, the hook said `status
'missing'` instead of `'draft'`: the template's inline comment after the status word defeated
the regex. The worked example found that bug; it is fixed in `tier-guard.py`, with a test, and the
run was repeated.)

**4. The human approves; the plan is gated once.** With `status: approved`, `approved_by` and
`approved_on` set by hand, the agent wrote `docs/plans/json-flag-plan.md` as a task table and
dispatched three `[plan-gate]` agents: the plan reviewer and the scope auditor ran (both PASS).
The third, a deliberate re-gate:

```
PLAN GATE GUARD: refusing a further gate dispatch for json-flag-plan.md.

That plan has already been gated (2 gate agents recorded; the allowance is 2:
one round of a plan reviewer plus a scope auditor).

Gate the plan ONCE, then execute. Re-gating a revised plan is what turned a control into
a loop feeding itself. Dispatch the next task's implementer instead; the per-task review
is the net for whatever the single gate missed.
```

**5. A secret stays unprinted.** Asked to run `cat .env` as a test:

```
SECRET GUARD: refusing: `cat .env` prints an env file.
A secret may be used, not shown; once printed it lives in the transcript.
Use it without printing (source .env, read it in the program), or check that it is set
with `test -n "$VAR" && echo set`. If the human asked to see it, run with
AGENTKEEL_SHOW_SECRETS=1 so the override is on record.
```

**6. Evidence, then commit.** The spec's A1 criterion,
`python3 cli.py cli.py --json | python3 -c "import json,sys; json.load(sys.stdin)"`, exited 0;
the default output diffed clean against `main`; the commit went in with an explicit path.

Two things the run taught that the docs now say: the `branch` in the tier state file is
informational (the hooks read the live branch, so a branch created after declaring is fine), and
a spec's `status` can carry an inline comment.

## Relationship to other work

- [agent-slots](https://github.com/hishamalward/agent-slots): runtime isolation for several agents
  on one machine. agentkeel is the process side; agent-slots is the resource side.
- [toilscan](https://github.com/hishamalward/toilscan): the write-safety pattern in
  `docs/guardrails.md` is its `apply` path, generalized.
- mcpclerk (in progress): the same instinct at the MCP tool layer, where the write path is a tool
  call rather than a file: allowlist, approval, quotas, an audit log that verifies.

## Not yet

- Plugin or marketplace packaging (only once it is under an hour of work).
- Per-file enforcement of the spec's `Changes` list: the tier guard reading the approved spec and
  refusing edits outside its declared blast radius. This is invariant 1 fully mechanised and is
  the next hook.
- A dispatch-count cap for the review gate (G3).
- Multi-repo rollout, per-user identity in hooks, an MCP standards server.

## Install and test

Nothing to install. Python 3.10 or newer for the Python hooks (macOS's `/usr/bin/python3` may be
older; point the hook lines at a 3.10+ interpreter if so), bash 3.2 or newer for the shell hooks.

```bash
python3 -m unittest discover -s tests -v
```

CI runs the same suite on macOS and Linux, on Python 3.10 and 3.13, plus every hook's `--selftest`.

## License

MIT. See [`LICENSE`](LICENSE).
