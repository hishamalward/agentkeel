# Project canon

The rules that apply to AgentKeel now, each with its reason. When a rule here and another page disagree, this page wins and the other page is wrong.

A subject's detail lives on its own page, and this page links to it. The instructions an adopting repository's agents read are the [`AGENTS.md` fragment](../templates/AGENTS.agentkeel.md). Git keeps every earlier version of this page.

## Invariants

Every rule serves one of these three. When two rules collide, the invariant decides. A rule that serves none is deleted.

### I1. Every write is bounded before it happens

The task record names size, permissions and workspaces. For large work, the approved boundary
lists allowed and excluded paths. Hooks refuse supported tool actions outside those limits;
`task.py open` adds OS sandbox protection for shell writes. This invariant is the design goal,
not a claim of coverage for unsupported tools or servers. See the [limits](../README.md#limits).

Applied to intent, I1 is scope discipline: do the literal ask, then stop. An adjacent problem gets one line ("also noticed X, want it?"), never a fix. Each expansion looks reasonable alone, which is why they pile up, and then nobody can tell when a task is finished. Finishing the work and shipping it are two decisions, and the second is the human's.

### I2. Every claim carries its evidence

No completion claim without fresh output. "Should work" means the check did not run. Verify at the cheapest layer that can prove the change: a unit test before an integration run, an integration run before a screenshot.

A failed check stops the work and is reported. Never widen the scope to satisfy a check, and never narrow a check to pass. A check fits the work it checks: a whole-file count behind a two-line edit cannot fail, so it proves nothing.

### I3. Every loop has a cap, and only the human re-opens it

One plan gate per plan. One review round per scope (each task, then the whole branch). One verification pass per claim. A process suggestion is a proposal to the human, never work the agent starts on its own.

The reason is not cost. A control that re-runs on its own output feeds itself: later rounds find the defects that earlier rounds introduced. The cap keeps a control a control.

### The pricing rule

Process is chosen once, by size, and size buys no permissions. When in doubt, pick the smaller size: moving up is cheap. A task never grows on its own. If the work is bigger than declared, stop and say so; the human re-scopes.

## Gates

A gate is a point where work stops until a named owner produces named evidence. There are four. Verification is not a gate: it is the evidence rule (I2) that every gate uses.

1. **G1 Boundary approval** (human, large tasks): the human approves the task's boundary.
2. **G2 Plan gate** (AI, once): two reviewers check a handoff plan.
3. **G3 Review** (AI, one round per scope): each task's diff, then the whole branch.
4. **G4 Ship** (human decides): tests are green on the commit that lands.

| Gate | Starts when | Ends with | Enforced by |
|---|---|---|---|
| G1 Boundary approval (human) | a large task's state page has an unapproved boundary | the page's `keel-approval` digest matches its boundary | `task-guard.py` refuses edits outside `docs/` and refuses the agent writing an approval; the docs check holds `main` |
| G2 Plan gate (AI, once) | a handoff plan exists in the page's Working section | every row's check fits inside the files its task touches; findings applied | `plan-gate-guard.py` refuses a third dispatch; `plan-size-guard.sh` reports a Working section over 300 lines |
| G3 Review (AI, one round per scope) | a task's diff is ready; later, the whole branch | findings applied; no second round without the human | guidance only |
| G4 Ship (human decides) | tests are green on the branch | `main` moved and pushed within the task's permissions | `task-guard.py`; tests before `main` moves need a [required CI check](required-checks.md) |

### G1, boundary approval

The human reads the boundary on the feature's state page (outcome, constraints, acceptance checks, and the Changes and Must-not lists) and runs `task.py approve <feature>` in their own terminal. The command writes a digest of the boundary into the page. The agent cannot run it, and cannot add, change or remove an approval.

The rest of the page stays editable, the boundary included, as a draft. The write limits keep using the approved version, and `main` does not move until the human approves the new boundary. Detail: [approval of a boundary](html-records.md#approval-of-a-boundary).

### G2, plan gate

A handoff plan is the Working section of the feature's state page. Two agents check it once,
in parallel: a plan reviewer checks the tasks against the boundary; a scope auditor checks
that each verification fits its task. Apply the findings and start work. Do not re-gate a
revision. Claude dispatch prompts include `[plan-gate]` and the page path. Codex dispatches
use a `task_name` beginning `plan_gate`, because its prompt is not readable by the hook.

### G3, review

One review of each task's diff, then one review of the whole branch. A review of a revision does not open a new round. In practice, this gate finds the implementation defects (all in failure paths, none visible in the plan). No hook enforces it yet.

### G4, ship

The agent runs the tests on the branch and reports. The human decides, and the request sets the permissions: "merge and push" grants `merge` and `push` for that task, and the agent does both without asking again. Conflicts are resolved on the branch. The hooks cannot prove the tests passed; a required check on the candidate commit does, with the deploy waiting for it.

## Rules

Each rule has one home. Where a feature owns the detail, the rule links to its page.

### The task record answers three separate questions

Size buys process, permissions name actions, workspaces say where. The record belongs to one
session and lives outside the repository. Every code task uses its own worktree, or the isolated
clone created by `task.py open`, small tasks included. *Why:* a task's size must not grant actions
the human did not request. Detail: [the task record](task-record.md).

### Every git operation in a command line is judged

The guard splits a command line into simple commands (after `&&`, `;`, pipes, `$(...)`, `bash -c`, `eval`) and reads each git call with its options and aliases. *Why:* a guard that read only the first command let `git push origin feat && git push origin main` through.

### A checked move lands the commit that was checked

The guard checks a move of a protected branch whose new commit is known before it runs: an agent's push, and a local `merge --ff-only`, `reset`, `update-ref`, `fetch .` or `push .`. Where that move is gated (a push gated on CI, or a local move in a repository with HTML docs), it names the commit by its full SHA and runs alone in its call. *Why:* a branch name can move between the check and the move, by another agent or by an earlier command in the same call.

A move whose new commit is not known in advance (a commit made on `main`, a rebase, a non-fast-forward merge) needs the `merge` permission, and its docs check runs later: at the push and in CI ([limits](html-records.md#current-limitations-and-open-decisions)).

### A check that fails to run refuses the move

When the guard checks a move or push of a protected branch and the check itself raises an error, the move is refused. Elsewhere, a hook that cannot read its input allows, so a broken guard never stops ordinary work. *Why:* an HTML asset once crashed the docs check, and the old rule then allowed the move.

### Overrides are written on the command, apply once, and are logged

`AGENTKEEL_ALLOW_DESTRUCTIVE=1` and `AGENTKEEL_SHOW_SECRETS=1` count only as a prefix on the one command, and each use goes to `AGENTKEEL_HOME/overrides.jsonl`. Shipping has no override; it is a permission. *Why:* an override read from the hook's environment would be permanent and silent.

### Plans never carry code

A plan is a table: task, files it may touch, blocked by, check, and whether the check fits inside the files. If the plan would need the code to be clear, the work is small enough to need no plan. *Why:* a plan that copied the implementation did the work twice (the worst case was a 4105-line plan for 541 lines of shell).

### One instruction file, and claims labelled by kind

The installer previews by default, writes its fragment into `AGENTS.md` between markers, never creates a `CLAUDE.md`, and restores original bytes on `--uninstall`. Each protection is labelled prevents, warns after, guidance only or unsupported, with its test ([guardrails](guardrails.md#protections)). *Why:* Claude Code loads `AGENTS.md` only when no `CLAUDE.md` exists, and guidance shown as a guarantee is a false claim.

### Guards read host-neutral events

Claude Code and Codex calls become the same events before any guard runs. Unknown host tools
that may write are refused. MCP calls use the four service adapters; other MCP servers pass
through without enforcement. A plugin acts only in opted-in repositories. Opt-in is remembered
across worktrees, so deleting `agentkeel.json` alone does not turn it off. *Why:* a Codex patch
once passed guards that read only Claude tool names. Detail: [hosts](hosts.md).

### Tests before main is a required CI check

Ordinary branch pushes are backups. Ready PRs run the relevant tests and docs check on their exact head, which must contain fetched current main. Ship only by fast-forwarding the exact tested SHA after rechecking main. One check, `agentkeel-required`, reports for ready PRs and main pushes, and the deploy waits for it. Main reruns the docs check and reuses successful same-SHA PR app-test evidence from the expected workflow and repository; missing or uncertain evidence runs the needed app tests on main. Docs-only changes skip app tests. The managed `AGENTS.md` block carries this workflow instruction. *Why:* branch backups need no test run, while a ready candidate needs evidence before main moves and deployment needs a check that fails closed. Detail: [required checks](required-checks.md).

### Documentation has one current owner per fact

AgentKeel writes two kinds of documents, for two readers.

| | AgentKeel's own docs | The records AgentKeel creates in your repository |
|---|---|---|
| Reader | someone deciding whether to use AgentKeel | the people and agents working in that repository |
| Format | Markdown in `docs/`, rendered by GitHub; `README.md` is the front door | authored HTML in a flat `docs/` folder: a project canon, one state page per feature, references, audits, mockups |
| Checked by | `tests/test_repo_contract.py`: every relative link and anchor resolves | the docs check (`pages.py`), before an agent moves `main` and in CI |
| Published | on GitHub, as Markdown | nowhere automatically; the HTML opens from a clone |

Each page has one source and says what is true now; Git keeps the history, so there is no decision log. The README introduces and links; it does not repeat the rules. AgentKeel's brand assets are the `docs/261005-brand-*-asset` files (the mark, a one-color mark, the icon, and light and dark banners with a PNG fallback); a page links an asset and never copies it. *Why:* the same detail copied into a spec, a plan, a handover and a decision entry drifted apart. Detail: [HTML records](html-records.md).
