# Inventory: where every framework element comes from

> **Revision note (2026-08-23, spec rev 2).** Dispositions below are the extraction audit and stand. `docs/spec.md` §2 then proposes changes to the framework itself (rules dropped, hooks added); where a row says `verbatim` or `generalize` but §2 drops the element (INDEX, CANON, two-mode plans, verification as a gate), §2 wins once the owner rules on it.


Clean-room audit for `agentkeel`, written 2026-08-23 before any README or hook. Every element the
public repo may contain is listed here with its source line, whether it is general or specific to
the Listenality product, and what happens to it. Nothing marked **unsure** ships. Nothing here
comes from Teranet: the four source trees below were grepped for the word and it does not appear
in any of them.

Sources read in full (paths abbreviated below):

| Key | Path |
|---|---|
| MA | `~/music_analytics/CLAUDE.md` (428 lines) |
| MA-hook-gate | `~/music_analytics/.claude/hooks/plan-gate-guard.py` (100 lines) |
| MA-hook-size | `~/music_analytics/.claude/hooks/plan-size-guard.sh` (46 lines) |
| MA-settings | `~/music_analytics/.claude/settings.json` (hook wiring) |
| MA-skill | `~/music_analytics/.claude/skills/systematic-debugging/SKILL.md` (51 lines) |
| MA-spec-* | `~/music_analytics/docs/specs/` (6 md files; read for shape only) |
| MA-plan-* | `~/music_analytics/docs/plans/` (sampled: `_handover-template.md`, `2026-07-29-isolation-machinery.md`, `2026-07-29-isolation-machinery-scope-audit.md`, plus the listing) |
| MA-dec | `~/music_analytics/docs/DECISIONS.md` (header lines 1-31, status index, one entry) |
| MA-index | `~/music_analytics/docs/INDEX.md` (lines 1-50) |
| SB | `~/claude-sandbox/CLAUDE.md` (171 lines) |
| TS | `~/public_repos/toilscan` (README, `skills/scan/scripts/manage_backlog.py`, `toilscan_common.py`, `.github/workflows/validate.yml`) |

Dispositions: **verbatim** (publish as written, product names stripped), **generalize** (keep the
rule, remove the Listenality-specific paths, numbers or tools), **fresh** (write from the principle;
no source text is reused), **out** (real practice, but outside this repo's scope), **superseded**
(older practice that later practice replaced; do not publish), **unsure** (origin cannot be placed;
must not ship).

## 1. Tiering

| # | Element | Where it exists today | General? | Disposition |
|---|---|---|---|---|
| 1.1 | Three tiers: small (inline), medium (worktree + tests + one review), large/handoff (plan machinery) | MA:5-17 | General | verbatim |
| 1.2 | Tier is declared in one line before work and overrides any skill or plugin's own trigger to plan or spawn | MA:7-9 | General | verbatim |
| 1.3 | When in doubt pick the smaller tier; a task never grows a tier on its own, the human re-scopes | MA:19-21 | General ("founder" becomes "the owner") | verbatim |
| 1.4 | Loop caps: one plan gate per plan, one review round per task, one whole-branch review per branch, one verification pass per claim | MA:23-32 | General | verbatim |
| 1.5 | Retro and process suggestions are proposals, never self-executed | MA:31-32 | General | verbatim |
| 1.6 | Verify at the cheapest layer that can prove the change (four named layers) | MA:34-48 | Layers are Listenality-specific (shared package, smoke script, RNTL, simulator) | generalize to the principle plus a generic four-layer example |
| 1.7 | Design-before-implementation check for non-trivial features: restate, 2-3 approaches, wait for approval; skip for obvious single-file changes | SB:73-81 | General | verbatim |
| 1.8 | Small vs large plan mode: small carries the code (transcribers), large carries interfaces and constraints; never both; a plan longer than the code it describes is the signal | MA:392-403 | General; the 4105-lines-for-541 figure is process evidence from practice, not product content | verbatim |
| 1.9 | A plan is a handoff artifact; if the same session executes, write a task list instead | MA:405-412 | General | verbatim |
| 1.10 | Sonnet-class floor for implementers and reviewers | MA:414-416 | A model-vendor ruling, dated | out (mention as an example of a dated ruling in DECISIONS, nothing more) |

## 2. Gates as actually practised

The resume wording says "five quality gates with explicit human or AI owners". That count and that
table describe the Teranet framework, which is not a source. What the personal repos actually
practise is below; the owner is stated in prose in the sources ("founder", "gate agent",
"implementer", "reviewer"), never as a table. `agentkeel` writes the table from this practice and
does not pad it to five.

| # | Gate | Where it exists today | Owner in practice | Disposition |
|---|---|---|---|---|
| 2.1 | Spec approval: a design is written "for ruling" and the human rules before code; rulings are recorded as D-NNN | MA-spec-* (`never-repeat-spec.md:1` "design for ruling", `play-tracking-repeat-plays-spec.md:1` "proposal, not ruled", `model-fallback-spec.md:16` "the rulings this spec is built on", `:557` proposed decision entry); MA:16-17 | Human | verbatim pattern, fresh text |
| 2.2 | Plan gate: one round of plan review plus scope audit in parallel, then execute; never re-gate a revision | MA:382-390; MA-hook-gate:1-100; MA-plan-* scope audit (`2026-07-29-isolation-machinery-scope-audit.md:1-30`) | AI (two reviewer agents); hook-enforced | verbatim (hook generalized, see 4.1) |
| 2.3 | Scope audit produces an artifact: a table of every task, its verification, and whether the scopes match; "can this verification pass when its task alone is done correctly?" | MA:352-367; MA-plan scope audit:26-30 | AI | verbatim |
| 2.4 | Per-task review: one review round per task; the net for what the single plan gate misses | MA:27-28, 388-390 | AI reviewer | verbatim |
| 2.5 | Verification before claiming done: fresh evidence, run the command, read the output; "should work" means unverified | MA:340; SB:91; MA:29-30 | AI, evidence shown to human | verbatim |
| 2.6 | If a verification fails, stop and report; never widen scope to satisfy a check, never narrow the check to pass | MA:378-380 | AI stops, human decides | verbatim |
| 2.7 | Whole-branch review: one per branch | MA:27-28 | AI | verbatim |
| 2.8 | Ship: rebase onto main, staleness check, tests green on the branch, fast-forward merge; main is always green; merge and push only when asked | MA:198-222, 325 | Human (decision), AI (evidence) | generalize (drop Railway, `node_modules` staleness specifics, slot teardown) |
| 2.9 | Exit gates listed per spec, numbered, each a checkable fact | MA-spec `2026-07-12-phase-8.6-finalize-cleanup-design.md:180-188` | Human (accepts) | verbatim shape, fresh example |

Honest gap: the sources do not contain a gate-owner table. Owners are recoverable from prose and
from the hook (which only fires on `Agent` dispatches, i.e. AI-owned gates). The table in
`docs/spec.md` is the first time this is written down as a table; it is derived, not copied.

## 3. Spec, plan, handover and decision conventions

| # | Element | Where it exists today | General? | Disposition |
|---|---|---|---|---|
| 3.1 | Spec sections: context/problem, verified facts, principles, design, blast radius, verifiable success criteria, out of scope, residual risks, proposed decision entry | MA-spec `2026-07-29-multi-agent-isolation-design.md:8-695` headings; `model-fallback-spec.md:16-633` headings | General shape; all content Listenality-specific | shape verbatim, content fresh |
| 3.2 | Blast radius section shape: "Changes" (file by file), "Tables", "Must not change" (explicit list), an explicit boundary against an adjacent system | `model-fallback-spec.md:428-463` | General shape | shape verbatim, content fresh |
| 3.3 | Success criteria are numbered, each names the test that proves it and a pattern to copy | `model-fallback-spec.md:465-475` | General | shape verbatim |
| 3.4 | Success criteria split by who verifies (human-verifiable vs AI-verifiable) | Not present as a split in the sources. Practice: specs list "Verification" (AI) and "Exit gates" (human) separately, `2026-07-12-...design.md:168-188` | General | generalize: the split exists implicitly; the template makes it explicit |
| 3.5 | Verified ground truth table at the top of a plan: fact, value, how checked; tasks written against measured facts, not spec prose | MA-plan `2026-07-29-isolation-machinery.md:21-45` | General; rows are Listenality-specific | shape verbatim, rows fresh |
| 3.6 | Plan header: goal, architecture, tech stack, spec link, handover link | MA-plan `2026-07-29-isolation-machinery.md:5-20` | General | verbatim minus the third-party plugin header line (`:3`), which is dropped |
| 3.7 | Task ordering as dependencies (`blockedBy`), not prose | MA:366-367 | General | verbatim |
| 3.8 | Handover template: goal, status, spec; shape in one paragraph; current state in code (ledger); what will bite; not built in build order; in flight; blocked; decided (do not re-litigate); open questions; verification protocol | MA-plan `_handover-template.md:1-53`; MA-spec isolation `:452-466` | General | verbatim minus the `spec 4.7` and `agent-stop.sh` references |
| 3.9 | "No derivable state" rule for handovers: derive state from the system, write down only intent | `_handover-template.md:12-16`; MA-spec isolation `:45-53` (principle 2) | General | verbatim |
| 3.10 | Docs houses: `docs/specs/` (decisions before a build), `docs/plans/` (plans and handovers only), `docs/audits/` (findings about what exists); content type picks the house, never format | MA:71-90 | General | verbatim (drop `design-exploration/`, which is product-design specific) |
| 3.11 | Index rule: `docs/INDEX.md` is the router, tiered (source of truth, working state, audits, archive); updating it is a required step in the same change | MA:57-69; MA-index:1-25 | General | generalize (drop the monorepo note and the product routes) |
| 3.12 | `DECISIONS.md`: append-only history, not current state; each entry has a Status (Active, Superseded by D-NNN, Reopened by D-NNN, Parked); a status index table at the top; fully superseded entries move to an archive stub | MA-dec:1-31; MA:298-303 | General | verbatim header convention, fresh example entry |
| 3.13 | `CANON.md`: a present-tense register of current positions, rewritten in place, separate from DECISIONS | MA:298-303; MA-index:33 | General but a second file the prompt did not ask for | out for v0.1 (one sentence in the DECISIONS section pointing at the pattern) |
| 3.14 | "Any new rule names the rule it replaces or states in one line why nothing existing covers it" | MA:50-53 | General | verbatim |
| 3.15 | Slug naming: one kebab-case slug derives branch, handover and worktree names; branch types are the commit types | MA:161-166 | General (the `ma-` worktree prefix is not) | generalize |
| 3.16 | Older planning files `PLAN.md` / `STATUS.md` / `WIP.md` with editing rules | SB:131-146 | Replaced by the per-stream handover (MA-spec isolation `:45-53` explains why `WIP.md` failed) | superseded |

## 4. Hooks

| # | Element | Where it exists today | General? | Disposition |
|---|---|---|---|---|
| 4.1 | Plan-gate guard: PreToolUse on `Agent`; counts gate dispatches per plan file in `.claude/state/plan-gates.json`; refuses (exit 2) past the allowance of one round (2 agents); excludes task reviews and branch reviews by pattern | MA-hook-gate:1-100; wired at MA-settings `PreToolUse.matcher: Agent` | General mechanism; the regexes assume `docs/plans/*.md` and the words "gate a/b", "scope audit", "plan review" | generalize: keep mechanism and state file, make the plan path and gate words configurable, drop the `superpowers/plans` legacy path |
| 4.2 | Plan-size guard: PostToolUse on `Write|Edit`; if a `docs/plans/*plan*.md` exceeds 800 lines, exit 2 with the right-sizing question | MA-hook-size:1-46; MA-settings `PostToolUse.matcher: Write|Edit` | General; the comment cites a third-party plugin by name (`:4`) | generalize: drop the plugin reference, keep the number and the message |
| 4.3 | Hook payload shape, as consumed by the two hooks: JSON on stdin with `tool_name` and `tool_input` (`tool_input.prompt` for Agent, `tool_input.file_path` for Write/Edit); project root from `CLAUDE_PROJECT_DIR`; exit 2 plus stderr blocks (PreToolUse) or feeds back (PostToolUse) | MA-hook-gate:40-57; MA-hook-size:14-17, 46 | General (harness contract) | verbatim; `tool_input.command` for Bash is not consumed by any existing hook and is captured for real in step 2 before the write-path guard is written |
| 4.4 | Write-path guard (block commits to main; block edits outside the worktree) | Does not exist in any personal repo. The rules exist as prose: MA:183-185 (explicit-path commits in a shared tree), MA:229 (never nest a worktree), MA:325 (do not merge or push unless asked), SB:153-154 (worktrees in `.claude/worktrees/`, list before branching). The resume attributes an enforcing hook to the Teranet plugin, which is not a source | General principle | **fresh**: written from the principle, no reference to any Teranet code |
| 4.5 | Never print secrets | SB:157-162 (no secrets in code, `.env.example` only, PAT in env) ; MA:427 | General | verbatim as a rule; **no hook in v0.1** (the resume's "secret-printing" hook is Teranet's; writing one fresh is more than an hour and is listed under "not yet") |
| 4.6 | Hook tests: none exist in the sources | n/a | n/a | fresh: block and allow payloads per hook, run by `unittest` in CI (pattern from TS `validate.yml:31-39`) |

## 5. Blast-radius guardrails on write paths

| # | Element | Where it exists today | General? | Disposition |
|---|---|---|---|---|
| 5.1 | Scope discipline: do the literal ask, then stop; adjacent problems get one line, never a fix; nothing unprompted (no memories, docs, scripts, refactors) | MA:317-330 | General ("founder ruling, 2026-07-31" is process history, publishable) | verbatim |
| 5.2 | Surgical changes: every changed line traces to the request; mention unrelated issues, do not fix them | MA:338; SB:89 | General; this quartet (think, simplicity, surgical, verify) reads like a widely circulated CLAUDE.md snippet, origin not certain but certainly not Teranet | **fresh** (rewrite the four principles in the repo's own words rather than republish text of uncertain provenance) |
| 5.3 | Explicit-path commits in a tree you do not own; a bare `git commit` commits the whole index | MA:183-185, 374-376 | General | verbatim |
| 5.4 | Never point a local server at production; local backend only | MA:186-187 | General principle, product-specific ruling | generalize |
| 5.5 | Never nest a worktree in a worktree; sibling directory always | MA:229 | General | verbatim |
| 5.6 | `git check-ignore -v` before assuming a file is tracked | MA:369-372 | General; the example paths are Listenality's | generalize |
| 5.7 | Stop rule: three failed fixes means question the design, not a fourth fix | SB:95, 110; MA:350; MA-skill:40-45 | General | verbatim |
| 5.8 | Stop rule: a failed verification stops the work; report, do not work around | MA:378-380 | General | verbatim (also gate 2.6) |
| 5.9 | Anti-rationalization table ("this is too simple to need a design", "one more fix attempt") | SB:97-110 | General | verbatim (house style: no em dashes) |
| 5.10 | Write safety pattern: read-only preview by default; apply is explicitly authorized; stable IDs; optimistic conflict checks; atomic per-file replacement; recoverable transaction journal; exclusive lock; a new run refuses to start while a journal exists | TS README:46-49, 249-250, 265; `manage_backlog.py:681` (`exclusive_lock`), `:721-764` (journal recovery), `:764` (`apply_transaction`), `:932` (`preview_or_apply`); `toilscan_common.py:310-331` (`atomic_write_*`) | General; own public MIT code | verbatim pattern; described, not vendored |
| 5.11 | Per-operation caps on writes | Not in the personal sources as a rule (ToilScan caps by design: one backlog, one checkpoint per repo, but no numeric cap). The resume's "per-operation blast-radius caps (`--dev-mode`)" is Teranet work | General principle | fresh, stated as a pattern with no code; flagged in the README as "from principle, not from a shipped hook" |
| 5.12 | Security rules: no credentials in code, `.env.example` only, tokens in env, permissions scoped to the repo | SB:157-162 | General | verbatim |
| 5.13 | Collisions must be loud; absence of configuration preserves today's behaviour; a lock file is a claim, not an authority | MA-spec isolation `:42-60` (principles 1-5) | General | verbatim (principle 1, "a worktree is filesystem isolation only", goes in the isolation pointer, 6.1) |

## 6. Isolation

| # | Element | Where it exists today | General? | Disposition |
|---|---|---|---|---|
| 6.1 | A worktree is not isolation: it fixes the filesystem and leaves database, ports, queue and simulator shared; one integer derives the rest | MA:131-133; MA-spec isolation `:42-45` | General statement; the machinery is `agent-slots` | one paragraph plus a link to `agent-slots`; nothing duplicated |
| 6.2 | Two tiers of isolation (code tier: worktree only; stack tier: slot) and "concurrency prices the protocol" | MA:136-145 | General | out (belongs to `agent-slots`; one sentence in the pointer at most) |
| 6.3 | Worktree conventions: `.claude/worktrees/` not committed; `git worktree list` before branching; `claude --worktree <name>` | SB:153-155, 170-171 | General | verbatim |

## 7. Debugging and other practice that is real but out of scope

| # | Element | Where it exists today | Disposition |
|---|---|---|---|
| 7.1 | Systematic debugging skill (investigate, compare, hypothesize, fix; the 3-fix rule) | MA-skill:1-51; SB:93-95 | out (the 3-fix stop rule alone is kept, 5.7) |
| 7.2 | Root cause before fixes; one hypothesis, one change; instrument boundaries before guessing | MA:342-350 | out (debugging, not gating) |
| 7.3 | Standard stack tables, multi-user pattern, testing strategy | SB:14-67 | out (stack choices, not framework) |
| 7.4 | Artifact house `design-exploration/` | MA:80-90 | out (product design) |
| 7.5 | Partnership paragraph ("say so if you disagree") | MA:418-420 | verbatim, one line in the README's principles |

## 8. Provenance summary

- Rows: 56 (1.1-1.10, 2.1-2.9, 3.1-3.16, 4.1-4.6, 5.1-5.13, 6.1-6.3, 7.1-7.5).
- verbatim: 34 · generalize: 9 · fresh: 6 (2.1 text, 3.1-3.3 content, 4.4, 4.6, 5.2, 5.11) · out: 8 · superseded: 1 · **unsure: 0**.
- The one provenance doubt (5.2, the four code-quality principles) is resolved by rewriting fresh
  rather than republishing, so nothing ships under "unsure".
- Two things the resume attributes to the framework are **not** in the personal sources and are
  written fresh from the principle: the write-path hook (4.4) and per-operation caps (5.11). The
  secret-printing hook (4.5) is not written at all in v0.1 and is listed under "not yet".
- Teranet: zero mentions in any source read; no Teranet path was opened.
