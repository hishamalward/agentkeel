# agentkeel: spec (step 1, revised; before the README)

Written 2026-08-23 from `docs/inventory.md` and a second, critical read of the sources. Nothing
below is code yet. Revision 2 replaces revision 1 (commit `fc1b1d6`) after the owner's ruling that
the base is the Listenality practice, that it should be improved rather than transcribed, and that
the resume follows the work, never the reverse.

## 0. Name

Three candidates were checked against PyPI and GitHub on 2026-08-23:

| Candidate | Reading | Availability | Decision |
|---|---|---|---|
| `shipgates` | the gates you pass to ship | PyPI free, no GitHub repo | rejected in round 1 |
| `gatehooks` | gates enforced by hooks | PyPI free, no GitHub repo | runner-up |
| `agentkeel` | the keel that keeps agent work upright (blast radius) and on course (spec first) | PyPI free, no GitHub repo | **chosen 2026-08-23** |

Repo: `github.com/hishamalward/agentkeel`, MIT, v0.1.0 at publish.

## 1. What this is, and the IP line restated

- A public framework for shipping production code with AI coding agents: work priced by size,
  spec-first with success criteria split by who verifies them, a small set of gates with named
  owners, blast radius bounded on every write path, and the sharpest rules enforced by hooks in
  the harness rather than by prose in a CLAUDE.md.
- **Provenance.** Extracted from the owner's personal repos (Listenality's `music_analytics`,
  `claude-sandbox`, ToilScan); `docs/inventory.md` is the audit trail, row by row. Elements written
  fresh from a principle rather than copied from a source are marked `fresh` in the inventory.

## 2. What is wrong with the practised framework, and what changes

This section is the argument. Each row is a proposed change; the README is written only after the
owner rules on them (§11). Evidence cites `music_analytics/CLAUDE.md` as MA:line.

### 2.1 The diagnosis

Read cold, the practised framework is 429 lines of CLAUDE.md, two hooks, six document houses, and
a set of rules that are each a scar from a named incident: 1.2M review tokens before a line of code
(MA:382-390), a 4105-line plan for 541 lines of shell (MA:392-403), seven plan defects and zero
implementation defects (MA:354-357), five of six port copies wrong (MA:110-113). Every rule is
honest and every rule earned its place. Three things are still wrong with it as a framework:

1. **The rules are reactions, not a design.** There is no statement of what the rules are *for*, so
   nothing decides which rule wins when two collide, and nothing prunes. The rule-hygiene rule
   (MA:50-53) exists precisely because accretion was the failure mode.
2. **The two hooks guard the least valuable part.** Both enforce loop caps on the plan-document
   machinery, which the framework's own text calls overhead when nothing is handed off (MA:405-412)
   and says the per-task review loop is what earns its cost (MA:388-390). Meanwhile the dangerous
   writes (a commit on main, an edit outside the worktree, a `git reset --hard`, a printed secret)
   have no hook at all. The plan-gate guard is also a regex over an English prompt (`gate a`,
   `scope audit`, `review the plan`); it is a heuristic and can be dodged by rewording.
3. **Too many registers.** `INDEX.md` routes readers across `CANON.md`, `DECISIONS.md`,
   `STATUS.md`, `PLAN.md`, specs, plans, handovers, audits and `design-exploration/`. A router is
   what you build when there are too many places to look. The handover template's best rule, "no
   derivable state, a second written copy is a lie waiting to happen" (template:12-15), applies to
   the registers themselves.

### 2.2 The changes, each with its argument

| # | Change | Deletes / adds | Argument |
|---|---|---|---|
| C1 | **Three invariants above every rule.** (I1) Every write is bounded before it happens. (I2) Every claim carries its evidence. (I3) Every loop has a cap, and only the human re-opens it. Plus one pricing rule: process is chosen once, by size. | Adds a one-page `docs/invariants.md`. Every rule in the framework cites the invariant it serves; a rule that serves none is deleted. | Gives the rules a reason to exist and a rule for deleting them. Scope discipline (MA:317-330) becomes I1 applied to intent, not a separate section. Verification layers (MA:34-48) become I2's "cheapest layer that can prove it". Loop caps (MA:23-32) are I3. |
| C2 | **The tier becomes machine-readable state, and the hooks key off it.** Declaring the tier is one command (`hooks/tier.sh small\|medium\|large <slug>`) that writes `.claude/state/agentkeel-tier.json` in the current worktree, with an expiry (default 8 h). | Adds `tier.sh` and `tier-guard.py`. Deletes nothing; makes the existing "state the tier in one line" (MA:5-9) count. | Today the tier is a sentence the agent says and nothing reads. Once it is state: `small` permits explicit-path commits in the main tree (the practice, MA:11-14) and nothing else; `medium`/`large` refuse any edit until the branch is not `main`; `large` refuses edits outside `docs/` until `docs/specs/<slug>-spec.md` carries `status: approved`. One declaration, every guardrail derived from it. This is the same shape as agent-slots' "one integer derives everything". Friction: one command per task, which the agent runs itself. |
| C3 | **Four gates, not six, under a strict definition.** A gate is a point where work cannot proceed until a named owner produces named evidence. G1 Spec approval (human) · G2 Plan gate (AI, once, only when a handoff plan exists) · G3 Review (AI, one round; two scopes: per task, and whole branch) · G4 Ship (human decides, AI supplies evidence). | Deletes "Verification" as a gate; it is the evidence rule (I2) every gate consumes. Merges per-task and whole-branch review into one gate with two scopes. | Revision 1 counted six by listing every loop. Verification is not a checkpoint with an owner, it is a property of every claim. The resume says five; the honest count is four plus one rule, and the owner has ruled the resume follows the work. |
| C4 | **Plans never carry code.** A plan is a task table: task, files it may touch, its check, and whether the check's scope is inside the files it touches. If the deliverable is small enough that the plan would carry the code, there is no plan. | Deletes the two-mode rule (MA:392-403). Keeps `plan-size-guard` with a lower threshold (300 lines) and a cleaner message: "a plan this long is carrying code; cut it to the table". | The size guard, the gate-once rule and the right-sizing rule are three workarounds for one cause: plans that transcribe implementation. Remove the cause and two of the three rules collapse into a table format. The "verification scoped wider than the work" defect (MA:359-367), six of seven plan defects, becomes a required column, not a paragraph of advice. |
| C5 | **Invert hook priority: write-path guards first.** `write-path-guard.py`: no commit or push to `main`/`master` unless the declared tier is `small`; no `Write`/`Edit` outside the worktree's git top-level (temp dirs allowed); no destructive git (`push --force`, `reset --hard`, `checkout -- .`, `clean -f`, `branch -D`) without `AGENTKEEL_ALLOW_DESTRUCTIVE=1`, which is echoed loudly. | Adds the hook the resume describes and the personal repos never had. | I1 has no teeth today. The plan-gate guard protects a token budget; this protects `main`, which auto-deploys (MA:198-200). |
| C6 | **A secret-printing guard.** `secret-guard.py` (PreToolUse `Bash`): refuse `cat`/`less`/`head` of `.env*` and key files, bare `env`/`printenv`, `echo $VAR` where VAR matches `KEY\|TOKEN\|SECRET\|PASSWORD`, and `git diff`/`show` of `.env*`. Override `AGENTKEEL_SHOW_SECRETS=1`, echoed. | Adds ~40 lines. Written fresh from the principle. | Cheapest hook in the set; the one whose absence is most embarrassing in a repo that calls itself a guardrail. The same instinct as mcpclerk's redaction: the secret may be used, it may not be shown. |
| C7 | **Keep `plan-gate-guard.py`, state its limits.** Detection stays a heuristic over the prompt; the README says so and shows the dodge. An explicit marker (`[plan-gate]` in the dispatch prompt) is added as the preferred, deterministic trigger. | Generalizes the existing hook; drops the retired path. | It is real practice with a real number behind it (MA:382-390). Honesty about the heuristic is worth more than pretending it is airtight. |
| C8 | **Three registers, not six.** `docs/specs/<slug>-spec.md` (what we intend; approved before build), `DECISIONS.md` (why; append-only, status index at top, rewrite-in-place of the index row is the only edit to an old entry), `docs/handovers/<slug>.md` (what cannot be derived: goal, ledger, what will bite, next). | Deletes `INDEX.md`, `CANON.md`, `STATUS.md`, `PLAN.md`, `WIP.md`, `audits/`, `design-exploration/` from the framework. A one-line scaling note says when a register may be split (CANON is what DECISIONS grows into past ~50 entries). | Each register is a place for drift and a maintenance rule to forget. Three files with three different verbs (intend, decide, resume) need no router. The artifact-house rules (MA:71-90) are Listenality doc management, not framework. |
| C9 | **The CLAUDE.md fragment fits in 60 lines.** `templates/CLAUDE.agentkeel.md` is the entire text a using repo pastes: the invariants, the tier command, the four gates, the hook list, the three registers. Everything else is a hook, a template, or a linked doc. | Adds the fragment; replaces the idea that the framework *is* the CLAUDE.md. | The session that drifts is the session that read 429 lines of instructions competing for attention. What must hold is in hooks; what must be remembered fits on one screen. |
| C10 | **Out, stated as out.** Model-vendor rulings (MA:414-416), product-specific verification layers (MA:38-46), the debugging standard (MA:342-350; real practice, different repo), stack tables, isolation (agent-slots owns it). | Deletes from the framework, keeps in the inventory as `out` with the reason. | A framework that carries everything the repo learned is a repo, not a framework. |

### 2.3 What this does to the two sentences in §1

Sentence one is still true and gets more precise: "a small set of gates with named owners" is four,
and "enforced by hooks" is now four hooks on the write path plus two on the plan loop. Sentence two
is unchanged.

## 3. README outline

1. **First 200 words: problem, approach, result.** Problem: agents write code faster than anyone
   reviews it; the failures are the missing gates (work that grew on its own, a plan reviewed three
   times before a line was written, a check that could not fail, a commit that landed on main
   because nothing stopped it); prose rules do not hold because the session that drifts wrote the
   prose. Approach: three invariants; size declared as state; a spec whose criteria say who
   verifies them; four gates with owners; the write path guarded by hooks. Result: the numbers from
   practice (seven plan defects, zero implementation defects; 4105 lines for 541) and the numbers
   from the worked example run.
2. **The invariants** (one paragraph each) and the pricing rule.
3. **Tiering as state**: the table in §4 and the one command.
4. **The spec template** and the plan table.
5. **The four gates** (table, §6).
6. **Guardrails and hooks**: what each blocks, what it cannot, the override and how loudly it is
   logged. Isolation pointer to `agent-slots` in one paragraph.
7. **The three registers**, with the `DECISIONS.md` convention and one example entry.
8. **5-minute quickstart**: copy `hooks/`, `templates/`, `.claude/settings.json`; paste the
   fragment into CLAUDE.md; run the tests; open Claude Code; declare a tier; watch a commit on main
   get refused.
9. **Worked example**: a fictional "add `--json` to a CLI" at tier medium, then a second pass at
   tier large: tier declared, edit refused until the worktree exists, spec approved, plan gated once
   (second round refused, output shown), review, commit on main refused, ship. Run for real, pasted.
10. **Relationship to other work**: `agent-slots` (runtime isolation), `toilscan` (write-safety
    pattern), `mcpclerk` (same instinct at the tool layer).
11. **Not yet** (§10). Install, tests, CI badge, licence.

House style: no em dashes.

## 4. Tiering (`docs/tiering.md`, one page)

| Tier | Trigger | What the declaration permits | What the hooks require |
|---|---|---|---|
| small | a direct ask, one file, under about an hour | explicit-path commits in the tree you are in | nothing else; a declaration older than the expiry is stale |
| medium | a feature spanning files | commits on a branch; one review round | branch is not `main`; edits only inside this worktree |
| large | a different session executes, or the human asked for a spec | everything above plus a plan and a whole-branch review | an approved spec before any edit outside `docs/`; the plan gated once |

Rules kept verbatim from practice: declare first; the declaration overrides any skill's own
trigger to plan or spawn; when in doubt go smaller; a task never grows a tier on its own (the hook
allows a re-declaration but records it; deciding is the human's).

## 5. Spec template (`templates/spec.md`) and plan table (`templates/plan.md`)

Spec sections: problem and rulings already made; verified facts (fact, value, how checked);
design; **blast radius** (`Changes`: paths; `Must not change`: paths; one named boundary with the
nearest adjacent system); **success criteria split by owner** (AI-verifiable: a command and its
expected output; human-verifiable: a fact checkable in under a minute); out of scope; residual
risks; the `DECISIONS.md` entry written now and appended at approval; rule-change clause (any rule
introduced names the rule it replaces). Frontmatter: `slug`, `tier`, `status: draft | approved |
superseded`, `approved_by`, `approved_on`. `tier-guard.py` reads `status`.

Plan table columns: `#` · task · may touch (paths) · blocked by · check (command) · check scope ⊆
may touch (yes/no; "no" is a plan defect). No prose ordering, no code.

## 6. Gates

| # | Gate | Owner | Entry | Exit evidence | Enforced by |
|---|---|---|---|---|---|
| G1 | Spec approval | Human | tier large; spec `status: draft` | `status: approved`, `approved_by`, a D-NNN entry | `tier-guard.py` refuses non-doc edits before it |
| G2 | Plan gate | AI (one reviewer + one scope auditor, in parallel, once) | a handoff plan exists | the plan table with every scope column `yes`; findings applied | `plan-gate-guard.py` refuses a second round; `plan-size-guard.sh` refuses a plan carrying code |
| G3 | Review | AI reviewer, one round | per task: the task's diff; whole branch: all tasks done | findings applied; no second round without the human | none (a cap on dispatch count is possible later; not v0.1) |
| G4 | Ship | Human decides; AI supplies the evidence | rebased on main, tests green on the branch | fast-forward merge; main always green; merge and push only when asked | `write-path-guard.py` refuses commit/push on main outside tier small |

The evidence rule (I2) sits under all four: no completion claim without fresh output pasted; a
failed check stops the work and is reported, never worked around (MA:378-380).

## 7. Hooks (`hooks/`)

Common contract, read from the existing hooks and to be confirmed by capturing one real payload
per tool before writing (`Bash` in particular: `tool_input.command`, `cwd`): JSON on stdin with
`tool_name`, `tool_input`, `cwd`; project root `CLAUDE_PROJECT_DIR` (fallback `cwd`); exit 0
allows; exit 2 with stderr blocks (PreToolUse) or feeds back (PostToolUse); a malformed payload
never blocks. Python 3.10+; shell hooks bash 3.2 clean. Each hook has `--selftest`. Overrides are
environment variables that the hook echoes when used, so an override is always visible in the
transcript.

| Hook | Event / matcher | Blocks | Allows | Tests (block + allow) |
|---|---|---|---|---|
| `tier.sh` | (not a hook; the command) | | writes `.claude/state/agentkeel-tier.json` `{tier, slug, declared_at, expires_at}` | round-trip; bad tier name; expiry |
| `tier-guard.py` | PreToolUse `Write\|Edit\|Bash(git commit)` | no declaration or expired; `medium`/`large` on `main`; `large` editing outside `docs/` before spec approved | `small` anywhere; `medium` on a branch; `large` on a branch with approved spec; any edit under `docs/` | 7 payloads |
| `write-path-guard.py` | PreToolUse `Bash\|Write\|Edit` | commit/push on `main` unless tier `small`; edit outside git top-level (temp allowed); destructive git without override | the rest; override echoed | 9 payloads |
| `secret-guard.py` | PreToolUse `Bash` | `cat .env`, `printenv`, `echo $API_KEY`, `git show HEAD:.env` and kin | `cat .env.example`; override echoed | 6 payloads |
| `plan-gate-guard.py` | PreToolUse `Agent` | third gate dispatch for the same plan (heuristic or `[plan-gate]` marker) | task reviews, implementers, first round | 6 payloads (from revision 1) |
| `plan-size-guard.sh` | PostToolUse `Write\|Edit` | `docs/plans/*plan*.md` over 300 lines | anything else | 4 payloads |

Budget check: five hooks plus the tier command, roughly 400 lines of Python and shell, tests in
`unittest`, no dependencies. If the two weekends run short, `secret-guard.py` is the one to drop to
v0.2, because the other four are the invariants' teeth and it is a courtesy.

## 8. Registers

- `docs/specs/<slug>-spec.md`: §5.
- `DECISIONS.md`: header with the convention; a status index table (D, short decision, status);
  entries `## D-NNN: title (date)` with `Status`, `Decision`, `Why`, `Replaces` (a rule or D-NNN,
  or "nothing existing covers this"). Append-only below the index; the index row is the one place
  rewritten in place. Example entry: D-001, "plans never carry code", replacing the two-mode rule.
- `docs/handovers/<slug>.md`: the template as practised (goal, status, shape in a paragraph,
  ledger, what will bite, not built in order, in flight, blocked, decided, open questions,
  verification protocol), with its "no derivable state" rule kept verbatim.

## 9. Success criteria (verbatim from the work order, plus two)

- hook tests pass on macOS and Linux in CI (block and allow cases for each hook);
- the worked example in the README can be followed end-to-end by a reader with Claude Code and
  produces the gate behaviour described;
- `docs/inventory.md` marks every published element's source, and nothing marked "unsure" shipped;
- the README's first 200 words state problem, approach, result.

Added: every number in the README is measured in the worked example or cited to an inventory row;
and `templates/CLAUDE.agentkeel.md` is at most 60 lines, checked by a test.

## 10. Blast radius, and not yet

New repo only. Nothing in `music_analytics`, `claude-sandbox`, `toilscan`, `agent-slots` or the
resume is modified by this work. Not yet: plugin/marketplace packaging (only if under an hour);
per-file enforcement of the spec's `Changes` list (v0.2: the hook can read the approved spec and
refuse edits outside its blast radius, which is I1 fully mechanised); a dispatch-count cap for G3;
a multi-repo rollout; per-user identity in hooks; an MCP standards server.

## 11. Rulings (recorded 2026-08-23)

1. **C2, tier as state: yes, for all tiers.** If `small` were the silent default, an undeclared
   session could commit on `main`, which is the unsafe default the hooks exist to remove. One
   command per task, run by the agent.
2. **C3, four gates: yes.** Verification is the evidence rule, not a gate. The resume follows.
3. **C4, plans never carry code, size guard at 300 lines: yes.**
4. **C6, secret guard: in v0.1.**
5. **C8, three registers, INDEX and CANON dropped: yes.**
6. **Lineage: the README says nothing about any work version.** This is new work based on the
   owner's personal practice.
