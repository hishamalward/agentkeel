# HTML records in your repository

In a repository that opts in, every work record is one authored HTML page in a flat `docs/` folder, in the present tense. This page is the contract for those records. AgentKeel's own documentation is Markdown and does not use it. A large task's boundary on its state page is what the human approves. The docs check runs before an agent's push to `main` and before a local move to a known commit, and CI runs it for everyone.

HTML records are included in the published 0.8.0 release. This is a behavior reference;
an adopting repository keeps its implementation and release status on its own state pages.

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
| `index.html` | derived by `task.py index` (see [the index](#the-index)); never committed |

The date is the family's creation date and never changes; related files reuse it, so a family sorts together. Names are lowercase kebab-case, the kind last. No subfolders. A repository can list legacy paths in `"docs_legacy"` (globs): those files stay as history, the check skips them, and the index links them.

### The page contract

- A `<title>`, readable semantic HTML for the content, and stable `id`s on sections worth linking.
- A state page keeps a fixed **State now** block: implementation, release and external checks, each with its source and date. It is `<section class="state-now" id="state-now">` with one `<dt>`/`<dd>` pair per line (the starter's form), or a section headed "State now" that holds a two-column table, one row per line.
- **Remaining scope** holds outstanding outcomes from the start of phased work and is updated in place as phases land.
- A **Working** section, `<section data-keel-transient="working">`, holds this phase's plan table, progress and next action. It is overwritten, never appended, and removed before `main` moves (`task.py finish <page>`).
- A **boundary**, `<section data-keel-boundary>`, holds what the human agreed: outcome, constraints, acceptance checks, and for a large task its `data-keel-changes` and `data-keel-must-not` path lists. At most one per page; static HTML only.

### Approval of a boundary

The human runs `task.py approve <feature|page>` in their own terminal. It writes `<meta name="keel-approval" content="sha256:<digest> by <name> on <date>">` in the head and keeps a copy of the approved boundary in `AGENTKEEL_HOME/approvals/`. The digest covers the page's file name and the boundary's HTML source with line endings normalised, so changed words, link targets or list structure all need approval again; edits elsewhere on the page do not.

- The agent may edit anything on the page, the boundary included, as a draft. It cannot add, change or remove the approval, or rename or delete an approved page.
- A large task's write limits come from the approved boundary. When the draft differs, the kept copy still rules; a widened draft grants nothing.
- An empty or missing Changes list grants no path outside `docs/`. Wide access is explicit: `*` grants every path.
- The docs gate refuses a checked move or push while a boundary is unapproved, changed,
  missing its approval, duplicated, malformed or dropped. The limitations below name moves
  that can only be checked later.

#### One boundary across repositories

A large task may use one state page across its declared worktrees. The guard uses the page in
the edited repository when present, otherwise the task's page in another declared worktree.

| Path entry | Applies to |
|---|---|
| `hooks/` | the page's own repository, identified by its Git common directory |
| `agentkeel:hooks/` | the declared repository named `agentkeel` |
| `secrets:prod.yml` | a literal path if `secrets` is not a declared repository name |

The repository name comes from the folder containing its common Git directory. Worktrees
therefore share one name; a bare repository drops its `.git` suffix. The same scoping applies
to Changes and Must not change. To protect a path in several repositories, list it for each one.

An ambiguous repository name grants no prefixed Changes paths; its Must-not entries apply in
both repositories. A repository name containing a colon cannot be addressed. A repository with
no matching Changes entries grants no writes outside `docs/`. Refusals explain the required
path spelling.

### Reading a page

`task.py context <page>` prints the page as structured text: headings, list items, table rows, link targets, section ids and the marked sections. Styles and scripts are skipped, nothing runs, and nothing is written. Agents read with it and edit the HTML itself.

### Claims the check proves

In a State now line, text of the form `merged <full-sha> into <ref>` (a 40 or 64 hex commit id; `<ref>` a branch such as `main`) is a claim git can check. Each run judges it again, with read-only plumbing only (`cat-file`, `rev-parse`, `merge-base --is-ancestor`), so nothing refreshes the index or runs a filter:

| Result | When | Effect |
|---|---|---|
| proven | the commit is an ancestor of `<ref>` (`refs/heads/<ref>` or `refs/remotes/origin/<ref>`, either one), or, when `<ref>` is one of the repository's protected branches, of the candidate commit being checked (the page lands on that branch only with the candidate, so the claim is true once it lands); with no `--rev`, the candidate is `HEAD` | none |
| contradiction | the commit exists here and is an ancestor of none of them | the docs check fails |
| unknown | the commit is not in the object store (a shallow clone), the ref does not resolve and the candidate does not hold the commit, the history is shallow, or the text names a branch or a short id instead of a full commit id (`merged feat/x into main`) | a warning; it never fails |

The id's case, a trailing comma and the `origin/` or `refs/heads/` form of the ref do not change the judgement. A branch name is never evidence: a branch moves and can be deleted, a commit id cannot. A merged commit stays proven after its branch gains commits or is deleted. Any other text, an authored outside fact such as "App Store review pending", is not a claim and is never touched.

### The docs check

One validator, `hooks/agentkeel_core/pages.py`, runs in three places on the candidate commit, compared with what `main` holds now:

- `task.py check [--rev R] [--base B]`, by hand.
- The task guard, before an agent's push to a protected branch and before a local move whose new commit is known (`merge --ff-only`, `reset`, `update-ref`, `fetch .`, `push .`). The move names its commit by full SHA and runs alone in its call, so the commit checked is the commit that lands: `git merge --ff-only <full-sha>`. A branch name, `HEAD` or an earlier command in the same call is refused. When the check cannot run, the move is refused.
- CI: the `docs` job of `templates/ci/required-checks.yml` runs on every push and pull request, docs-only changes included, and `agentkeel-required` is red unless it succeeds.

It fails on: a misnamed file or a subfolder in `docs/`; a committed index; two state pages for one feature or two project canons; a page with no title; a Working section; a boundary that is unapproved, changed, malformed or scripted; approval data with no boundary; an approved page dropped or renamed; a local link or anchor that does not resolve; a `DECISIONS.md` or a path listed under `"retired"`; a State now claim that git contradicts. An unknown claim is printed as a warning.

### Starting a page

`task.py new state|reference|audit|mockup|project <family>` writes a starter page in the task's own worktree (it needs `implement`), and `keel.css` when missing. A large task's state page starts with a boundary. A feature that already has a state page is refused: edit it. A later page of a family reuses the family's first date, so its files sort together; the page itself shows the day it was created.

### The index

`task.py index [--full]` writes `docs/index.html` and prints a text index for the agent.
Both are regenerated from the working folder. The HTML index is a local output, never committed;
there is no hand-kept index or separate status page:

- Each family under one heading, qualifiers included, the project canon first. Each page shows its kind, title, boundary state and a working tag; each state page shows its State now lines as the page says them now.
- The legacy files (`"docs_legacy"` globs) grouped by folder. In `index.html` each is a link with its title: the first Markdown heading, or the HTML `<title>`, else the file name. The text lists each folder with its file count; `--full` also lists every file with its title.

The index code lives in `pages.py`, so a repository's clean checkout runs it from its CI copy without the plugin: `python3 .github/agentkeel/pages.py index --root .` (`--full` too).

## Current limitations and open decisions

- The approval digest detects a change; it does not prove who approved. The guard sees the agent's tool calls, so a shell write could forge a meta and its digest. Stronger provenance needs a human-controlled channel.
- A local move whose new commit is not known in advance (a commit on `main`, a non-fast-forward merge, a rebase) is checked when it is pushed and in CI, not before the move.
- With an unprotected `main` (GitHub Free, private repository), a human push can move `main` before CI runs; a red docs job then stops the deploy (Railway waits for CI) but does not undo the push.
- Retiring an approved page is a human act: the check refuses a candidate that drops one.
- CI runs a copy of `pages.py` in `.github/agentkeel/`; update it when agentkeel is updated.

## Verification

- **Regression coverage**: `test_pages.py` covers names, links, anchors, Working sections,
  boundary states and digests, base comparison, retired logs and context. `DocsGate`,
  `LargeAndBoundaryApproval` and the host parity tests cover the guard.
- **Claude Code, live** (`claude -p`, throwaway repo, project install, 2026-10-05): an Edit adding a `keel-approval` meta was refused with the G1 reason; a push to `main` of a commit with a Working section was refused; `task.py finish` removed the section; a push of the literal SHA of the finished commit moved `main`; `task.py context` read the page.
- **Found live and fixed**: `git push origin $(git rev-parse HEAD):main` was read as a push to a branch named `$`, so neither the docs check nor the push gate ran. A command substitution now stays one opaque word, an unknown destination counts as any branch, and the live rerun refused all three forms. The regression test fails against the Stage 2 code.
- **Codex, live** (`codex exec` 0.160.0, same page, `--dangerously-bypass-hook-trust` for this run only; the normal-trust path was proven in Stage 2): an `apply_patch` adding an approval was refused; a push of a commit with a Working section was refused with the docs-check reason; `context` read the Working section another session wrote. Codex's workspace sandbox refuses writes inside `.git`, so that commit was made outside Codex.
- **Layout**: on 2026-10-05, pages built on this `keel.css` (AgentKeel's own docs before they became Markdown) were checked at 1280 px and 390 px wide with no horizontal overflow.
- **Independent review at 5d17846, four findings, fixed**: an HTML asset crashed the check and the guard allowed the move; a call could move a branch after the guard read it; an empty Changes list granted every path; a family's later pages took a new date and index group. Each has a regression test that fails on 5d17846 (`StageTwoBReviewFindings`, `EmptyChangesList`, `test_a_family_keeps_its_first_date_and_one_index_group`), and the reviewer closed all four at 03ff775: 214 tests, the original probes and eight full-SHA move checks.
- **Hosted CI, 2026-10-07**: the pilot's
  [docs-only run](https://github.com/hishamalward/music_analytics/actions/runs/37661206770)
  passed its docs and required checks with app tests skipped. The
  [merged pilot run](https://github.com/hishamalward/music_analytics/actions/runs/37659383111)
  passed docs, web and mobile checks. These close the earlier hosted-CI gap.
