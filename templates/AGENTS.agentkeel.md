## agentkeel (installed by install.py between its markers; full text: github.com/hishamalward/agentkeel)

Three rules sit above every other rule here. A rule that serves none of them is deleted.
1. Every write is bounded before it happens. Do the literal ask. Mention an adjacent problem in
   one line; do not fix it.
2. Every claim carries its evidence. Run the check, show the output, then say it passes. A failed
   check stops the work and is reported. Never widen the scope or narrow the check to pass.
3. Every loop has a cap, and only the human re-opens it: one plan gate per plan, one review round
   per scope, one verification pass per claim.

**Declare the task before the first write. The guards read the record, not this text.**
    .claude/hooks/task.py start <task-id> --size <size> --allow <permissions> [--write-root DIR]
Read the size and permissions from the human's request, state your reading in your first update,
and proceed. Ask only when information is missing, the request is unclear, or an action would go
past it. Size and permissions are separate: changing one never changes the other.
- Size (how much process): small = own branch and worktree, no plan or subagents, one check;
  medium = tests and one review round; large = an approved boundary, a plan gated once, reviews.
- Permissions (which actions): review (writes only --write-root report folders, outside the
  repo), implement (edit, commit with explicit paths, local checks and builds), merge (move a
  protected branch), push (any push), distribution-build, store-submission, paid-job. "Merge and
  push" grants both and never a distribution build. Finishing work and shipping it are separate.
- Worktrees: every code task works in its own worktree, never the shared checkout.
  `git worktree add ../<repo>-<task> -b feat/<task>` records it. Temp files go in the scratch
  folder that `task.py start` prints.
When in doubt, pick the smaller size. A task never grows on its own: stop and say so.
The main agent declares the task; subagents work under it (a Codex subagent's own shell cannot
see the record, so run task.py from the main agent).

**Gates** (work stops until the named owner produces the named evidence):
- G1 Boundary approval, human: the human runs `task.py approve <feature>` in their own terminal.
  You cannot add, change or remove an approval.
- G2 Plan gate, AI, once: one plan reviewer and one scope auditor, prompts marked `[plan-gate]`.
- G3 Review, AI, one round per scope: each task, then the whole branch.
- G4 Ship, human decides: tests green on the branch, required checks before main moves.

**Docs** (where agentkeel.json has "docs": "html"): one authored HTML page per document, in flat
docs/, in the present tense: the project canon, one state page per feature, references, audits,
mockups. `task.py new` starts a page; `task.py context <page>` reads one. Plan and progress go in
the page's Working section; `task.py finish` removes it before main moves, and unfinished work
goes in Remaining scope. No decision log, no Markdown twin, no copied facts: link to the owner.
Move main by the checked commit's full SHA, alone in its call: `git merge --ff-only <full-sha>`.

**The guards refuse** (exit 2, with the reason): a write with no task for this session; a write
outside the task's worktrees and write roots; code edits on a protected branch; a commit without
explicit paths; moving or pushing a protected branch without merge or push; builds, submissions
and paid jobs without their permission; edits to hook config or agentkeel state; destructive git
(override: prefix that one command with AGENTKEEL_ALLOW_DESTRUCTIVE=1, logged); printing secrets
(override: AGENTKEEL_SHOW_SECRETS=1, logged); a third plan-gate dispatch.
`task.py verify -- <cmd>` records a check's result against HEAD.

**Limits**: the guards see this agent's tool calls, not the filesystem. Shell writes that are not
git, commands inside scripts, and other tools are not seen. The task record is your declaration,
not the human's consent. Database, ports and queues are agent-slots' job.
