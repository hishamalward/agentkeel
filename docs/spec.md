# agentkeel: spec (step 1, before the README)

Written 2026-08-23 from `docs/inventory.md`. Nothing below is code yet. The README is written only
after the gate wording here is reconciled with the resume.

## 0. Name

Three candidates were checked against PyPI and GitHub on 2026-08-23:

| Candidate | Reading | Availability | Decision |
|---|---|---|---|
| `shipgates` | the gates you pass to ship | PyPI free, no GitHub repo | rejected in round 1 |
| `gatehooks` | gates enforced by hooks | PyPI free, no GitHub repo | runner-up |
| `agentkeel` | the keel that keeps agent work upright (blast radius) and on course (spec first) | PyPI free, no GitHub repo | **chosen 2026-08-23** |

Repo: `github.com/hishamalward/agentkeel`, MIT, v0.1.0 at publish.

## 1. What this is, in two sentences that must stay true

- A public framework for shipping production code with AI coding agents: spec-first design gates
  with verifiable success criteria split by owner, quality gates with explicit human or AI owners,
  blast-radius guardrails on write paths, enforced by hooks.
- Clean-room: extracted from personal repos only (`docs/inventory.md` is the audit trail). Nothing
  from Teranet.

## 2. README outline

The README is the product. Order and content:

1. **First 200 words: problem, approach, result.**
   - Problem: AI coding agents write code faster than anyone reviews it. The failures are not in
     the code; they are the missing gates: work that grew a tier on its own, a plan reviewed three
     times before a line was written, a verification that could not fail, a commit that landed on
     main because nothing stopped it. Prose rules in a CLAUDE.md do not hold, because the session
     that drifts is the session that wrote the prose.
   - Approach: size the work first; write a spec whose success criteria say who verifies each one;
     put a named owner on every gate; bound what a write path may touch; and enforce the sharpest
     rules in PreToolUse hooks that run in the harness, not in the model's memory.
   - Result: one number from practice for each of the three hooks (see §7, criterion 4), stated
     honestly; the process evidence already in the sources (eight task reviews plus a branch
     review found zero implementation defects and seven plan defects; a 4105-line plan for 541
     lines of shell is what the size guard exists for).
2. **The five parts** (one paragraph each, linking to the doc that owns it): tiering, spec
   template, gates with owners, blast-radius guardrails and hooks, `DECISIONS.md`.
3. **5-minute quickstart**: copy `hooks/` and `.claude/settings.json` into a repo, copy
   `templates/`, run `python3 -m unittest discover -s tests`, open Claude Code and watch the
   plan-gate guard refuse a second gate round.
4. **Worked example**: a small fictional feature ("add a `--json` flag to a CLI") followed
   end-to-end: tier declared (medium), spec with owner-split criteria, plan gated once (the hook
   refuses the second round, output shown), implementation in a worktree, the write-path guard
   blocking a `git commit` on main (output shown), verification evidence, ship. Run for real and
   pasted, not typed.
5. **Isolation pointer**: one paragraph, link to `agent-slots`.
6. **Relationship to other work**: `agent-slots` (runtime isolation), `toilscan` (write-safety
   pattern reused), `mcpclerk` (the same instinct at the MCP tool layer; link once it exists).
7. **Not yet**: plugin/marketplace packaging; a secret-printing guard; an MCP standards server;
   multi-repo rollout; per-user identity in hooks.
8. Install, tests, CI badge, licence.

House style: no em dashes (the rule is inherited from the source repos and kept).

## 3. Tiering (one page, `docs/tiering.md`)

| Tier | Trigger | Requires |
|---|---|---|
| Small | a direct ask, one file, under about an hour | inline; one verification pass; report |
| Medium | a feature spanning files | worktree, tests, implement, one review round |
| Large / handoff | a different session executes, or the human asked for a plan | spec with owner-split criteria, plan gated once, worktree, tests, per-task review, whole-branch review |

Rules carried verbatim (inventory 1.2-1.5, 1.8-1.9): declare the tier in one line first; the
declaration overrides any skill's own trigger to plan or spawn; when in doubt go smaller; a task
never grows a tier on its own; one plan gate per plan, one review round per task, one branch
review per branch, one verification pass per claim; a plan is a handoff artifact and is not
written when nothing is handed off; a plan is either code-carrying (small) or interface-carrying
(large), never both.

## 4. Spec template (`templates/spec.md`)

Sections, in order (inventory 3.1-3.4):

1. Problem (one paragraph) and the rulings already made.
2. Verified facts: a table of fact, value, how checked. Tasks are written against these.
3. Design.
4. **Blast radius**: `Changes` (file by file), `Must not change` (explicit list), and one explicit
   boundary against the nearest adjacent system.
5. **Verifiable success criteria, split by owner**:
   - *AI-verifiable*: each names the test that proves it and a pattern in the repo to copy.
   - *Human-verifiable*: each is a fact the human can check in under a minute (the "exit gates"
     of practice: "a real playlist appears in the Music app" becomes, for the example feature,
     "`cli --json` output parses with `jq .`").
6. Out of scope.
7. Residual risks.
8. Proposed `DECISIONS.md` entry, written now, appended at the approval commit.
9. **Rule change clause**: any rule this spec introduces names the rule it replaces, or states in
   one line why nothing existing covers it (inventory 3.14).

## 5. Gates, as actually practised

Derived from the personal repos (inventory §2). This is the table the resume wording is reconciled
against; it is not padded.

| # | Gate | Owner | Entry condition | Exit evidence | Enforcing hook |
|---|---|---|---|---|---|
| G1 | Spec approval | Human | Large tier; spec written "for ruling" | The human's ruling, recorded as a D-NNN entry | none (a human decision cannot be hooked) |
| G2 | Plan gate | AI (one plan reviewer + one scope auditor, in parallel, one round) | A handoff plan exists | The scope-audit table: every task, its verification, scopes match; findings applied | `plan-gate-guard` refuses a second round; `plan-size-guard` questions an oversized plan |
| G3 | Per-task review | AI reviewer | A task's implementation is complete | Review findings applied; one round only | none |
| G4 | Verification | AI runs, human reads | Any completion claim | Fresh command output pasted; a failed verification stops the work and is reported | none (evidence, not enforcement) |
| G5 | Whole-branch review | AI reviewer | All tasks complete | One review of the full diff | none |
| G6 | Ship | Human decides, AI provides evidence | Rebased on main, tests green on the branch | Fast-forward merge; main always green; merge and push only when asked | `write-path-guard` blocks a commit on main and an edit outside the worktree |

Six gates, two human-owned (G1, G6), four AI-owned. The resume says five; the practised count is
six because verification (G4) and per-task review (G3) are separate loops in practice (MA:27-30).
Reconciliation is the owner's call: either the resume says "six" or G3 and G5 are presented as one
"review" gate with two scopes, which gives five and is defensible. The repo publishes six.

## 6. Hooks to ship (`hooks/`)

Common contract (inventory 4.3, read from the two existing hooks, not from memory): JSON on stdin
with `tool_name` and `tool_input`; project root from `CLAUDE_PROJECT_DIR` (fallback `cwd`); exit 0
allows; exit 2 with a message on stderr blocks (PreToolUse) or feeds back (PostToolUse). Python
hooks target Python 3.10 (system `python3` on current macOS is older; the README says to point the
hook line at a 3.10+ interpreter); shell hooks are bash 3.2 clean (no associative arrays, no
`mapfile`, no `${v,,}`). Each hook has a `--selftest` that runs its payloads without the harness.

### 6.1 `plan-gate-guard.py` (PreToolUse, matcher `Agent`)

Generalized from MA-hook-gate. Counts gate dispatches per plan file in
`.claude/state/plan-gates.json`; allowance 2 per plan (one round of two agents); refuses beyond it.
Plan path pattern and gate words are constants at the top of the file, documented; the legacy
`superpowers/plans` path is dropped.

Test payloads (`tests/test_plan_gate_guard.py`):

- allow: `{"tool_name":"Agent","tool_input":{"prompt":"Review the plan docs/plans/json-flag-plan.md"}}` twice (state starts empty) → exit 0 both times.
- block: the same payload a third time → exit 2, stderr contains `PLAN GATE GUARD`.
- allow: `{"tool_name":"Agent","tool_input":{"prompt":"Implement task 3 of docs/plans/json-flag-plan.md"}}` → exit 0 (no gate word).
- allow: `{"tool_name":"Agent","tool_input":{"prompt":"Review the plan docs/plans/json-flag-plan.md against review-package-3.md"}}` → exit 0 (excluded: a task review).
- allow: `{"tool_name":"Bash","tool_input":{"command":"ls"}}` → exit 0 (wrong tool).
- allow: malformed stdin → exit 0 (a broken hook must never block work).

### 6.2 `plan-size-guard.sh` (PostToolUse, matcher `Write|Edit`)

Generalized from MA-hook-size: if the written file matches `*/docs/plans/*plan*.md` and exceeds
800 lines, exit 2 with the right-sizing question. The third-party plugin reference in the comment
is removed.

Test payloads (`tests/test_plan_size_guard.py`, which writes temp files and pipes JSON):

- allow: 799-line `docs/plans/x-plan.md` → exit 0.
- block: 801-line `docs/plans/x-plan.md` → exit 2, stderr contains `PLAN SIZE GUARD` and `801`.
- allow: 5000-line `docs/specs/x-spec.md` → exit 0 (not a plan).
- allow: payload without `file_path` → exit 0.

### 6.3 `write-path-guard.py` (PreToolUse, matcher `Bash|Write|Edit`)

Written fresh from the principle (inventory 4.4). Two checks:

1. **No commits on main.** If `tool_name == "Bash"` and `tool_input.command` contains a
   `git commit` (or `git merge` / `git push` targeting main is out of v0.1 scope; commit only),
   resolve the current branch of the directory the command runs in (`git rev-parse
   --abbrev-ref HEAD` in `cwd` or `CLAUDE_PROJECT_DIR`); if it is `main` or `master`, exit 2.
   Override: `AGENTKEEL_ALLOW_MAIN=1` in the environment, and the hook prints that the override
   was used.
2. **No edits outside the worktree.** If `tool_name` is `Write` or `Edit`, resolve
   `tool_input.file_path` (relative paths against `cwd`); if it does not lie under the git
   top-level of `CLAUDE_PROJECT_DIR`, exit 2. Paths under the system temp directory are allowed
   (scratch is not a write path).

Before writing it, step 2 captures one real PreToolUse payload for `Bash` with a one-line hook that
dumps stdin to a file, so `tool_input.command` and `cwd` are confirmed rather than assumed.

Test payloads (`tests/test_write_path_guard.py`, using a temp git repo):

- block: on `main`, `{"tool_name":"Bash","tool_input":{"command":"git commit -m x"}}` → exit 2, stderr contains `WRITE PATH GUARD` and `main`.
- allow: on `feat/x`, same payload → exit 0.
- allow: on `main`, same payload with `AGENTKEEL_ALLOW_MAIN=1` → exit 0, stderr notes the override.
- allow: on `main`, `{"tool_name":"Bash","tool_input":{"command":"git status"}}` → exit 0.
- block: `{"tool_name":"Edit","tool_input":{"file_path":"/etc/hosts"}}` → exit 2.
- allow: `{"tool_name":"Write","tool_input":{"file_path":"<repo>/src/a.py"}}` → exit 0.
- allow: `{"tool_name":"Write","tool_input":{"file_path":"<tmpdir>/scratch.txt"}}` → exit 0.
- allow: malformed stdin → exit 0.

### 6.4 Wiring (`.claude/settings.json` example)

PreToolUse: `Agent` → `plan-gate-guard.py`; `Bash|Write|Edit` → `write-path-guard.py`.
PostToolUse: `Write|Edit` → `plan-size-guard.sh`. Commands use `"$CLAUDE_PROJECT_DIR"/hooks/...`.

## 7. Success criteria (verbatim from the work order)

- hook tests pass on macOS and Linux in CI (block and allow cases for each hook);
- the worked example in the README can be followed end-to-end by a reader with Claude Code and
  produces the gate behaviour described;
- `docs/inventory.md` marks every published element's source, and nothing marked "unsure" shipped;
- the README's first 200 words state problem → approach → result.

Plus one this spec adds: every number in the README is either measured in the worked example run
or cited to the inventory row it came from.

## 8. Blast radius

New repo only: `~/public_repos/agentkeel`. Nothing in `music_analytics`, `claude-sandbox`,
`toilscan` or `agent-slots` is modified. No Teranet path is read. The resume is not edited by this
work; reconciliation of §5 is a separate decision for the owner.

## 9. Not yet

Plugin/marketplace packaging (only if under an hour once hooks exist); secret-printing guard; MCP
standards server; multi-repo rollout tooling; per-user identity; `CANON.md` as a second register;
the systematic-debugging skill (real practice, different repo).

## 10. Repo layout at v0.1.0

```
README.md
LICENSE
DECISIONS.md              the convention and one example entry
docs/
  inventory.md            this audit
  spec.md                 this file
  tiering.md
  gates.md                the table in §5 with a paragraph per gate
  guardrails.md           blast-radius pattern, write-safety pattern (ToilScan), isolation pointer
  learning/defending-the-framework.md
  post-draft.md
templates/
  spec.md
  plan.md
  handover.md
hooks/
  plan-gate-guard.py
  plan-size-guard.sh
  write-path-guard.py
tests/
  test_plan_gate_guard.py
  test_plan_size_guard.py
  test_write_path_guard.py
.claude/settings.json     example wiring
.github/workflows/validate.yml   macOS + Linux, Python 3.10 and latest, unittest
```
