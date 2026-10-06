# HTML records in your repository

In a repository that opts in, every work record is one authored HTML page in a flat `docs/` folder, in the present tense. This page is the contract for those records. AgentKeel's own documentation is Markdown and does not use it. A large task's boundary on its state page is what the human approves. The docs check runs before an agent's push to `main` and before a local move to a known commit, and CI runs it for everyone.

## State now

| | |
|---|---|
| Implementation | On `main` since `ef79009`; pushed to GitHub on 2026-10-05 (at `fc72847`). |
| Release | Not in a published release yet; the last release, `v0.1.0`, predates it. AgentKeel's own docs are Markdown (see the [canon](canon.md#documentation-has-one-current-owner-per-fact)). |
| External checks | Live Claude Code and Codex runs on 2026-10-05 (see Verification). No hosted run of the CI docs job yet. |

## Current behavior and constraints

A repository opts in with `"docs": "html"` in `agentkeel.json` (the agent's file tools cannot edit that file). Its documentation is then authored HTML: each page is the one source of its content, committed and opened directly from disk. There is no Markdown twin, no renderer and no decision log.

### One flat folder, stable names

| File | Owns |
|---|---|
| `YYMMDD-project-reference.html` | the project canon: repo-wide rules that apply now, each with its reason; one per repository |
| `YYMMDD-<feature>-state.html` | one feature, in the present tense: behavior, constraints, remaining scope, limitations, verification; one per feature |
| `YYMMDD-<family>[-<qualifier>]-reference.html` | a shared rule or runbook with its own subject |
| `...-audit.html` | findings and evidence at a stated revision; it never outranks the state page |
| `...-mockup.html` | a design exploration; bespoke layout welcome |
| `...-asset.<ext>` | a supporting file; an HTML asset is checked like a page (links, Working section) |
| `keel.css` | the shared look; pages link `./keel.css` and may add their own styles |
| `index.html` | derived by `task.py index`; never committed |

The date is the family's creation date and never changes; related files reuse it, so a family sorts together. Names are lowercase kebab-case, the kind last. No subfolders. A repository can list legacy paths in `"docs_legacy"` (globs) while it migrates.

### The page contract

- A `<title>`, readable semantic HTML for the content, and stable `id`s on sections worth linking.
- A state page keeps a fixed **State now** block: implementation, release and external checks, each with its source and date.
- **Remaining scope** holds outstanding outcomes from the start of phased work and is updated in place as phases land.
- A **Working** section, `<section data-keel-transient="working">`, holds this phase's plan table, progress and next action. It is overwritten, never appended, and removed before `main` moves (`task.py finish <page>`).
- A **boundary**, `<section data-keel-boundary>`, holds what the human agreed: outcome, constraints, acceptance checks, and for a large task its `data-keel-changes` and `data-keel-must-not` path lists. At most one per page; static HTML only.

### Approval of a boundary

The human runs `task.py approve <feature|page>` in their own terminal. It writes `<meta name="keel-approval" content="sha256:<digest> by <name> on <date>">` in the head and keeps a copy of the approved boundary in `AGENTKEEL_HOME/approvals/`. The digest covers the page's file name and the boundary's HTML source with line endings normalised, so changed words, link targets or list structure all need approval again; edits elsewhere on the page do not.

- The agent may edit anything on the page, the boundary included, as a draft. It cannot add, change or remove the approval, or rename or delete an approved page.
- A large task's write limits come from the approved boundary. When the draft differs, the kept copy still rules; a widened draft grants nothing.
- An empty or missing Changes list grants no path outside `docs/`. Wide access is explicit: `*` grants every path.
- `main` does not move while any boundary is unapproved, changed since approval, missing its approval, duplicated, malformed, or dropped by renaming or deleting an approved page.

### Reading a page

`task.py context <page>` prints the page as structured text: headings, list items, table rows, link targets, section ids and the marked sections. Styles and scripts are skipped, nothing runs, and nothing is written. Agents read with it and edit the HTML itself.

### The docs check

One validator, `hooks/agentkeel_core/pages.py`, runs in three places on the candidate commit, compared with what `main` holds now:

- `task.py check [--rev R] [--base B]`, by hand.
- The task guard, before an agent's push to a protected branch and before a local move whose new commit is known (`merge --ff-only`, `reset`, `update-ref`, `fetch .`, `push .`). The move names its commit by full SHA and runs alone in its call, so the commit checked is the commit that lands: `git merge --ff-only <full-sha>`. A branch name, `HEAD` or an earlier command in the same call is refused. When the check cannot run, the move is refused.
- CI: the `docs` job of `templates/ci/required-checks.yml` runs on every push and pull request, docs-only changes included, and `agentkeel-required` is red unless it succeeds.

It fails on: a misnamed file or a subfolder in `docs/`; a committed index; two state pages for one feature or two project canons; a page with no title; a Working section; a boundary that is unapproved, changed, malformed or scripted; approval data with no boundary; an approved page dropped or renamed; a local link or anchor that does not resolve; a `DECISIONS.md` or a path listed under `"retired"`.

### Starting a page

`task.py new state|reference|audit|mockup|project <family>` writes a starter page in the task's own worktree (it needs `implement`), and `keel.css` when missing. A large task's state page starts with a boundary. A feature that already has a state page is refused: edit it. A later page of a family reuses the family's first date, so its files sort together; the page itself shows the day it was created. `task.py index` groups each family's pages, qualifiers included, under one heading.

## Remaining scope

- **Stage 3, music_analytics pilot.** Reconcile CANON, the decision log and the active specs, plans and handovers into a project canon and state pages; repair references; retire the old files at one cutover. Depends on this stage merging.
- **Retrieval.** Compare plain source search with Graphify on ten real questions before adopting a graph backend. Depends on the pilot's pages.
- **Diagrams.** Archify as an optional diagram renderer inside a page, only if a page needs one.

## Current limitations and open decisions

- The approval digest detects a change; it does not prove who approved. The guard sees the agent's tool calls, so a shell write could forge a meta and its digest. Stronger provenance needs a human-controlled channel.
- A local move whose new commit is not known in advance (a commit on `main`, a non-fast-forward merge, a rebase) is checked when it is pushed and in CI, not before the move.
- With an unprotected `main` (GitHub Free, private repository), a human push can move `main` before CI runs; a red docs job then stops the deploy (Railway waits for CI) but does not undo the push.
- Retiring an approved page is a human act: the check refuses a candidate that drops one.
- CI runs a copy of `pages.py` in `.github/agentkeel/`; update it when agentkeel is updated.

## Verification

- **Unit suite**: 214 tests pass, hook self-tests included (`python3 -m unittest discover -s tests`), on the Stage 2b branch. `test_pages.py` covers names, links, anchors, Working sections, boundary states and digests, base comparison, retired logs and context; `DocsGate`, `LargeAndBoundaryApproval` and the host parity tests cover the guard.
- **Claude Code, live** (`claude -p`, throwaway repo, project install, 2026-10-05): an Edit adding a `keel-approval` meta was refused with the G1 reason; a push to `main` of a commit with a Working section was refused; `task.py finish` removed the section; a push of the literal SHA of the finished commit moved `main`; `task.py context` read the page.
- **Found live and fixed**: `git push origin $(git rev-parse HEAD):main` was read as a push to a branch named `$`, so neither the docs check nor the push gate ran. A command substitution now stays one opaque word, an unknown destination counts as any branch, and the live rerun refused all three forms. The regression test fails against the Stage 2 code.
- **Codex, live** (`codex exec` 0.160.0, same page, `--dangerously-bypass-hook-trust` for this run only; the normal-trust path was proven in Stage 2): an `apply_patch` adding an approval was refused; a push of a commit with a Working section was refused with the docs-check reason; `context` read the Working section another session wrote. Codex's workspace sandbox refuses writes inside `.git`, so that commit was made outside Codex.
- **Layout**: on 2026-10-05, pages built on this `keel.css` (AgentKeel's own docs before they became Markdown) were checked at 1280 px and 390 px wide with no horizontal overflow.
- **Independent review at 5d17846, four findings, fixed**: an HTML asset crashed the check and the guard allowed the move; a call could move a branch after the guard read it; an empty Changes list granted every path; a family's later pages took a new date and index group. Each has a regression test that fails on 5d17846 (`StageTwoBReviewFindings`, `EmptyChangesList`, `test_a_family_keeps_its_first_date_and_one_index_group`), and the reviewer closed all four at 03ff775: 214 tests, the original probes and eight full-SHA move checks.
- Not run: the CI `docs` job on GitHub.
