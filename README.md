# agentkeel

[![validate](https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml/badge.svg)](https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml)

A framework for shipping production code with AI coding agents: work priced by size, actions
granted by permission, spec-first, four gates with named owners, blast radius bounded by hooks.

AI coding agents write code faster than anyone reviews it. The failures that follow are rarely
in the code. They are the missing gates: a one-file fix that quietly became a refactor, a plan
reviewed three times before a line was written, a check that could not fail, a commit that landed
on `main` because nothing stood in the way, a build nobody asked for. Rules in an instruction
file do not hold, because the session that drifts is the session that read them.

agentkeel is the practice from shipping a real product solo with agents writing the code,
extracted and made enforceable. Three invariants sit above every rule: every write is bounded
before it happens, every claim carries its evidence, every loop has a cap and only a human
re-opens it. Each task is declared once, as a record the hooks read: its size (how much process),
its permissions (which actions), and its resources (which worktrees and folders). A spec says who
verifies each success criterion. Four gates each name an owner. Four hooks and one command guard
the write path from inside the harness, outside the model's memory.

What it does today, stated by kind of protection, is in the [capability table](#what-it-protects-and-what-it-does-not).
Version 0.3 supports Claude Code and Codex, from one core: both hosts give the same decision and
the same refusal text for the same task and the same act ([verified live](#verified-live)).

## The invariants

Every rule in this repo serves one of these, and a rule that serves none is deleted. The full
statement is in [`docs/invariants.md`](docs/invariants.md).

1. **Every write is bounded before it happens.** The spec names what may change and what must
   not; the task record says what the task may do and where; the hooks refuse what falls outside.
   Scope discipline is this invariant applied to intent: do the literal ask, mention the adjacent
   problem in one line, do not fix it.
2. **Every claim carries its evidence.** No completion claim without fresh output pasted. Verify
   at the cheapest layer that can prove the change. A failed check stops the work and is reported;
   it is never worked around, and the check is never narrowed to pass.
3. **Every loop has a cap, and only the human re-opens it.** One plan gate per plan, one review
   round per scope, one verification pass per claim. A control that re-runs on its own output
   turns into a loop feeding itself.

And one pricing rule: **process is chosen once, by size, and size buys no permissions.** If the
work turns out bigger than declared, stop and say so.

## The task record: size, permissions, resources

One command, run by the agent before its first write, from its reading of the human's request:

```bash
.claude/hooks/task.py start json-flag --size medium --allow implement,merge,push
```

| Question | Answers | What the hooks do with it |
|---|---|---|
| **Size**: how much process? | `small`: own branch and worktree, no plan or subagents, one check. `medium`: tests, one review round. `large`: approved spec, plan table gated once, per-task and branch review | `large`: no edit outside `docs/` until the spec is approved, then only its `Changes` paths |
| **Permissions**: which actions? | `review` (write only the `--write-root` report folders, which lie outside any repository), `implement` (edit, commit, local checks and builds), `merge` (move a protected branch locally), `push` (any push to a remote, and deploy commands); a PR merge needs both `merge` and `push`, `distribution-build`, `store-submission`, `paid-job` | each action is refused without its permission; "merge and push" grants both and never a distribution build |
| **Resources**: where? | the worktree it was declared in, any worktree it creates with `git worktree add`, and `--write-root` folders | writes outside them are refused; another agent's worktree is never writable |

The record is bound to the agent session (the host's session id; a subagent's tool calls carry
its parent's on both hosts), stored
in `~/.agentkeel/tasks/` (`AGENTKEEL_HOME`), and never editable by the agent's file tools. A
second session cannot reuse it. Changing the size never changes the permissions; widening the
permissions is said out loud on stderr and kept in the record's history. The agent states its
reading of the request in its first update and proceeds; it asks only when something is missing,
unclear, or past the request. Details: [`docs/task-record.md`](docs/task-record.md).

The record is the agent's declaration, not the human's consent: the agent writes it. What it buys
is that every action is checked against one stated scope, and a mismatch is refused before it
happens. Where consent itself must be enforced, use the host's own permission prompts.

## Spec first, and plans that never carry code

A `large` task starts with [`templates/spec.md`](templates/spec.md). The parts that matter:

- **Blast radius**: `Changes` (paths), `Must not change` (paths), and one named boundary with the
  nearest adjacent system.
- **Success criteria split by owner**: *AI-verifiable* criteria are a command and its expected
  output; *human-verifiable* criteria are a fact a person can check in under a minute.
- **Frontmatter** the hooks read: `status: draft | approved | superseded`, `approved_by`,
  `approved_on`, all inside the leading `---` block (a `status: approved` line pasted into the
  body approves nothing). Until then the task guard refuses edits outside `docs/`; after it, edits
  outside the `Changes` list. The agent cannot write the approval or change an approved spec: the
  human runs `task.py approve <task-id>` in a terminal of their own.
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
| G1 | Spec approval | Human | size `large`; spec `status: draft` | `status: approved`, `approved_by`, `approved_on` in frontmatter; a `D-NNN` entry | `task-guard.py` refuses non-doc edits before it, and refuses the agent writing the approval |
| G2 | Plan gate | AI: one plan reviewer and one scope auditor, in parallel, once | a handoff plan exists | the plan table with every scope column `yes`; findings applied | `plan-gate-guard.py` refuses a third dispatch (heuristic; see the table below); `plan-size-guard.sh` reports a plan over 300 lines after the write |
| G3 | Review | AI reviewer, one round per scope | per task: the task's diff; whole branch: all tasks done | findings applied; no second round without the human | guidance only |
| G4 | Ship | Human decides; AI supplies the evidence | tests green on the branch | `main` moves only with the merge permission, is pushed only with the push permission | `task-guard.py`; tests before `main` moves: the required-checks template ([`docs/required-checks.md`](docs/required-checks.md)), which is CI's job, not a hook's |

Two gates are human-owned (G1, G4), two are AI-owned (G2, G3). [`docs/gates.md`](docs/gates.md)
has a paragraph per gate.

## Guardrails and hooks

Four hooks and one command, no dependencies, Python 3.10+ and bash 3.2. Each hook runs in the
harness before or after a tool call, reads the call as JSON on stdin (shapes captured in
[`docs/hook-payloads.md`](docs/hook-payloads.md)), and allows (exit 0) or blocks with a reason the
model sees (exit 2). A hook that cannot parse its input allows: a broken guard must never stop
work on its own. The shared reader in `hooks/agentkeel_core/` splits a command line into every
simple command (after `&&`, `;`, `|`, newlines, line continuations, `$(...)`, `bash -c` and
`bash -lc`, `bash <<EOF`, `env -S`, `eval`, `cd`), follows a `git checkout` earlier in the line,
and reads every git global option (`-C`, `-c`, `--git-dir`, `GIT_DIR`) and alias, including one
defined earlier in the same line, so the second push in a line is judged like the first.

Guards never read a host's tool names. `agentkeel_core/host.py` turns each host's call into the
same events first: a file edit (Claude Code's `Write`/`Edit`/`NotebookEdit`, every path in a
Codex `apply_patch`, both ends of a move), a shell command (`Bash` on both), or a subagent
dispatch (`Agent`; Codex's `spawn_agent`). A tool that may write but has no adapter is refused
with a reason, never silently allowed. The shapes are pinned by real captured payloads in
`tests/fixtures/`; facts per host are in [`docs/hosts.md`](docs/hosts.md).

| Hook | Event | Refuses |
|---|---|---|
| `task.py` | (the command) | declares, shows, records a check (`verify -- <cmd>`), ends a task; `approve` is the human's |
| `task-guard.py` | PreToolUse, every tool (`*`) on both hosts | everything in the first block of the table below; reads, planning and messaging tools pass |
| `secret-guard.py` | PreToolUse `Bash` | printing `.env*` (not `.env.example`), key files, credentials; bare `env`/`printenv`; `echo $ANY_KEY_OR_TOKEN`; `git show`/`diff` of `.env` |
| `plan-gate-guard.py` | PreToolUse `Agent` (Codex: `spawn_agent`) | a third gate dispatch for the same plan, counted per repository under a file lock; on Codex, whose dispatch message is encrypted, a `task_name` starting `plan_gate` counted per task |
| `plan-size-guard.sh` | PostToolUse `Write\|Edit` (Codex: `apply_patch`) | reports a `docs/plans/*plan*.md` over 300 lines (the write has happened) |
| `session-start.py` | SessionStart, plugin only | prints the task command with this install's real path |

Two overrides exist, both written on the command itself so they apply once and show in the
transcript, and both logged to `~/.agentkeel/overrides.jsonl`: `AGENTKEEL_ALLOW_DESTRUCTIVE=1 git
reset --hard` and `AGENTKEEL_SHOW_SECRETS=1 cat .env`. A variable set in the harness's own
environment is not an override. There is no override for shipping: that is a permission.

## What it protects, and what it does not

The guards see the agent's tool calls, not the filesystem, so the guarantee is "this agent's tool
calls were checked", never "nothing else touched the tree". Each row is labelled by what it is.

| Protection | Kind | Tested in |
|---|---|---|
| No write without a task declared by this session; a second session cannot reuse it | prevents | `test_task_guard.py` (NoTask, SessionBinding) |
| Writes only inside the task's worktrees, write roots and its own scratch (its scratch folder, or a temp path naming its session); another task's temp files are not writable; a review writes only its report folder, and a write root never reaches into a repository; `git worktree add` claims only a path that does not exist yet | prevents | WriteRoots, ReviewFindings |
| Code edits only in the task's own linked worktree, never the shared checkout (whatever branch it is on), and never on a protected branch (`main`, `master`, or `agentkeel.json`), at every size | prevents | Branches, StageReviewFindings |
| Commits name their paths (`-- <paths>`), so another agent's staged files never ride along | prevents | Commits |
| `main` moves locally (commit, merge, ff, reset, rebase, update-ref, `fetch .:main`) only with `merge` | prevents | Shipping |
| Every push to a remote only with `push`, including `+main`, compound lines, `-C`, `-c`, aliases and `remote.*.push` config; `gh pr merge` only with `merge` and `push` | prevents | Shipping, ReviewFindings, StageReviewFindings |
| Force push, remote branch delete, `reset --hard`, whole-tree checkout or restore, `clean -f`, `branch -D`, `stash drop/clear/pop` (the stash is shared by every worktree) | prevents, with a logged one-command override | Destructive |
| `eas build`, `eas submit`, `eas update`, `npm publish`, deploy commands, repo-defined paid jobs only with their permission (also through `npx`, `pnpm exec`, `npm exec`; a `--dry-run` is not the action) | prevents, for the listed command shapes | CommandClasses |
| Hook config, `agentkeel.json` and agentkeel state not editable by the agent's file tools | prevents | ProtectedConfig |
| A large task edits nothing outside `docs/` before approval, then only its `Changes` list; the agent cannot approve a spec or change an approved one (except to mark it superseded) | prevents, for the agent's file tools and `task.py` | LargeAndSpecApproval, StageReviewFindings |
| A printed secret | prevents, for the listed shapes | `test_secret_guard.py` |
| A third plan-gate dispatch | prevents when the prompt carries `[plan-gate]`; heuristic otherwise | `test_plan_gate_guard.py` |
| A plan over 300 lines | warns after the write | `test_plan_size_guard.py` |
| An agent ships to `main` only a commit whose required check passed (`require_check_before_push` in `agentkeel.json`) | prevents, for agent pushes and `gh pr merge`; refuses when GitHub cannot be asked | `test_task_guard.py` (PushGate); live on a throwaway GitHub repository |
| One review round per scope (G3) | guidance only | |
| Shell writes that are not git (`sed -i`, `>`, `rm`), commands inside scripts or npm scripts, other tools and hosts | unsupported | |
| The same protections on Codex (file edits through `apply_patch`, shell, subagents) | prevents, as above | `test_hosts.py` (SameDecision, CapturedShapes) |
| A tool that may write but has no adapter (Codex `write_stdin` included) | prevents: every tool reaches the guard, and an unreadable writer is refused with a reason | `test_hosts.py` (ConfiguredRoute) |
| MCP tools | unsupported: they pass; an MCP server that writes files is outside agentkeel | |
| Cursor and other hosts | guidance only: they read `AGENTS.md`, no adapter | |

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

Two ways in. A **project install** puts the hooks in the repository, for everyone who opens it:

```bash
git clone https://github.com/hishamalward/agentkeel
python3 agentkeel/install.py path/to/your-repo            # preview: lists every change, makes none
python3 agentkeel/install.py path/to/your-repo --apply    # hooks, settings for both hosts, AGENTS.md
python3 agentkeel/install.py path/to/your-repo --doctor   # what is installed and trusted (--live proves it)
```

The installer copies the hooks into `.claude/hooks/`, merges its entries into
`.claude/settings.json` (Claude Code) and `.codex/hooks.json` (Codex) without touching your other
hooks or settings, and writes the instruction fragment into `AGENTS.md` between markers.
`--host claude` or `--host codex` limits it to one. It never creates a `CLAUDE.md`: Claude Code
reads `AGENTS.md` only when no `CLAUDE.md` exists, so creating one would hide the instructions. If
your repo has one, or a `.codex/config.toml` that already defines hooks of the same name, the
installer says so and leaves it alone. `--uninstall` reverses all of it: a file you have not
edited since goes back to its original bytes, and edits you made after install are kept.

A **plugin** carries the same hooks in your agent instead: `.claude-plugin/` and `.codex-plugin/`
share one `hooks/hooks.json`. Plugin hooks run in every repository, so they act only where an act
lands in a repository that opted in with an `agentkeel.json` at its root (the target decides, not
the folder the session started in), and a session-start hook tells the agent the task command's
real path. An opt-in is remembered in `~/.agentkeel/opted-in.json`, so deleting the file from a
shell does not switch the guards off; to opt out, delete the file and remove its entry there. Use
one way per repository, not both.

Installed is not active. Codex runs a new project hook only after you trust it (`/hooks` in
Codex); `--doctor` shows what is missing. Then ask for a one-line edit before declaring anything;
it must be refused with `no task is declared for this session` (`--doctor --live` does this for
you, one short session per host).

## Verified live

Run 2026-10-04 with Claude Code 2.1.289 (`claude -p`, Sonnet) and Codex CLI 0.160.0 (`codex exec`,
low reasoning) in two throwaway repositories with local bare remotes, each installed with
`install.py --apply`. Both models got the same eight steps, were told to attempt each once and to
quote the hook, and gave the same result at every step. The Codex run used
`--dangerously-bypass-hook-trust` instead of trusting the hooks by hand, and ran inside a Claude
Code shell, so both hosts' session variables were set; `task.py` picked Codex's.

| Step | Claude Code | Codex |
|---|---|---|
| create `notes.txt` before declaring a task (file tool) | refused: `no task is declared for this session` | refused, same text (through `apply_patch`) |
| `task.py start parity --size small --allow implement` in the shared checkout | allowed; no worktree recorded, the note names the command | same |
| `git worktree add ../wt -b feat/parity`, then create `../wt/notes.txt` | allowed | allowed |
| `git add notes.txt && git commit -m notes -- notes.txt` in the worktree | allowed | allowed |
| `git push origin feat/parity && git push origin main` | refused at the first push: `a push to 'feat/parity' needs the 'push' permission` | same |
| `cat .env` | refused by the secret guard | same |
| a subagent creates a file in the task's worktree | allowed | allowed |
| a subagent writes in the shared checkout (separate Codex run) | (Stage 1 run: refused) | refused: `... is the repository's shared checkout` |
| a third `plan_gate*` subagent dispatch (separate Codex run) | (Stage 1 run: refused by marker) | refused before launch: `PLAN GATE GUARD: refusing a further gate dispatch for task:gates` |

Also live: the Claude plugin (`claude --plugin-dir`) refused an undeclared write in a repository
with `agentkeel.json` and named its real `task.py` path at session start, and did nothing in a
repository without one. The Codex plugin manifest is not yet tested in a live session.

One difference found: inside a Codex subagent, `CODEX_THREAD_ID` is the subagent's own id, so
`task.py show` and `task.py verify` run by a Codex subagent find no task, while its tool calls are
still judged against the parent's record. Declare the task and record evidence from the main
agent. The v0.1 worked example (tier model) is kept in
[`docs/learning/worked-example-v0.1.md`](docs/learning/worked-example-v0.1.md).

## Relationship to other work

- [agent-slots](https://github.com/hishamalward/agent-slots): runtime isolation for several agents
  on one machine. agentkeel is the process side; agent-slots is the resource side.
- [toilscan](https://github.com/hishamalward/toilscan): the write-safety pattern in
  `docs/guardrails.md` is its `apply` path, generalized.
- mcpclerk (in progress): the same instinct at the MCP tool layer, where the write path is a tool
  call rather than a file: allowlist, approval, quotas, an audit log that verifies.
## Not yet

- A live test of the Codex plugin install, and of the required-checks template on a real hosted
  repository (the template and its selector are tested locally; see
  [`docs/required-checks.md`](docs/required-checks.md)).
- A cap on the review gate (G3).
- Ownership-aware cleanup of a finished task's worktrees and slots; a session-start banner.

## Install and test

Python 3.10 or newer for the Python hooks (macOS's `/usr/bin/python3` may be older; point the hook
lines at a 3.10+ interpreter if so), bash 3.2 or newer for the shell hook.

```bash
python3 -m unittest discover -s tests -v
```

CI runs the same suite on macOS and Linux, on Python 3.10 and 3.13, plus every hook's `--selftest`.

For whoever owns this next: [docs/learning/how-it-works.html](docs/learning/how-it-works.html) is the
v0.1 tour, and [docs/spec.md](docs/spec.md) the v0.1 contract; [`DECISIONS.md`](DECISIONS.md) D-004 to
D-010 record what v0.2 and v0.3 changed and why.

## License

MIT. See [`LICENSE`](LICENSE).
