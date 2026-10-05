## agentkeel (installed by install.py between its markers; full text: github.com/hishamalward/agentkeel)

Three invariants sit above every rule here. A rule that serves none of them is deleted.
1. Every write is bounded before it happens. Do the literal ask; mention an adjacent problem in
   one line, never fix it.
2. Every claim carries its evidence. Run the check, paste the output, then say it passes. A
   failed check stops the work and is reported; never widen scope or narrow the check to pass.
3. Every loop has a cap, and only the human re-opens it. One plan gate per plan, one review round
   per scope, one verification pass per claim.

**Before the first write, declare the task. The guards read the record, not this text.**
    .claude/hooks/task.py start <task-id> --size <size> --allow <permissions> [--write-root DIR]
Read size and permissions from the human's request, state your reading in your first update,
and proceed. Ask only when information is missing, the request is unclear, or an action would
go past it. They are separate questions; changing one never changes the other.
- Size (how much process): small = its own branch and worktree, no plan or subagents, one check;
  medium = tests and one review round; large = an approved spec, a plan table gated once, reviews.
- Permissions (what actions): review (writes only --write-root report folders, outside the repo), implement (edit, commit
  with explicit paths, local checks and builds), merge (move a protected branch), push (any push),
  distribution-build, store-submission, paid-job. "Merge and push" grants both; it never grants
  a distribution build. Finishing work and shipping it are separate decisions.
- Resources: every code task gets its own worktree, never the shared checkout; `git worktree
  add` records it. Temp files go in the scratch folder `task.py start` prints.
When in doubt pick the smaller size. A task never grows on its own: stop and say so.

**Gates** (work stops until a named owner produces named evidence):
- G1 Spec approval, human: the human runs `task.py approve <task-id>` in their own terminal.
  The agent cannot approve a spec or change an approved one, by edit or by command.
- G2 Plan gate, AI, once: one plan reviewer plus one scope auditor, prompts marked `[plan-gate]`.
- G3 Review, AI, one round per scope: per task, then the whole branch.
- G4 Ship, human decides: tests green on the branch, required checks before main moves.

**What the guards refuse** (exit 2 with the reason): a write with no task for this session; a
write outside the task's worktrees and write roots; code edits on a protected branch; a commit
without explicit paths; moving or pushing a protected branch without merge or push permission;
builds, submissions and paid jobs without their permission; edits to hook config or agentkeel
state; destructive git (override: prefix that one command with AGENTKEEL_ALLOW_DESTRUCTIVE=1,
logged); printing secrets (override: AGENTKEEL_SHOW_SECRETS=1, logged); a third plan-gate
dispatch. `task.py verify -- <cmd>` records a check's result against HEAD.

**Limits**: the guards see this agent's tool calls, not the filesystem. Shell writes that are
not git, commands inside scripts, and other tools are not seen; the task record is the agent's
declaration, not the human's consent. Database, ports and queues are agent-slots' job.
