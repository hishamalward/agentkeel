## agentkeel (kept between its markers by task.py init or install.py; full text: github.com/hishamalward/agentkeel)

Three rules govern the workflow. A rule that serves none of them is deleted.
1. Bound each write to the request. Do the literal ask. Mention adjacent problems; do not fix them.
2. Give evidence for claims. Run the check before claiming success. Report a failed check;
   never widen the scope or narrow the check to pass.
3. Cap loops: one plan gate per plan, one review round per scope, one verification pass per
   claim. Only the human re-opens a loop.

**Declare the task before the first write.** The guards read the record, not this text.
    python3 "<task.py path>" start <task-id> --size <size> --allow <permissions> [--write-root DIR]
Use the path printed at session start, or .claude/hooks/task.py for a project install.
Run it as shown, with nothing before python3. Below, task.py abbreviates that command.
State your reading of the request in the first update and proceed. Ask only for missing
information, unclear intent or an action beyond the granted scope. Size grants no permission.
- Small: own workspace, no plan or subagents, one check and a short report.
- Medium: tests and one review round. Large: approved boundary, plan gated once, reviews.
- Permissions: review (external report folders); implement (edits, explicit-path commits,
  local checks/builds and local pushes between feature branches); merge (move a protected
  branch); push (remote pushes/deploy commands); distribution-build; store-submission;
  paid-job; remote-write (guarded MCP changes); publish (guarded MCP publishing).
  MCP actions also require allowed targets where applicable. "Merge and push" grants both,
  not a distribution build. Finishing work and shipping remain separate decisions.
- Code belongs in the task's own worktree, or its clone from the human's task.py open.
  git worktree add ../<repo>-<task> -b feat/<task> records a new worktree automatically.
  Use the printed task scratch folder for temporary files, never another task's files.
When in doubt, pick the smaller size. If it grows, stop and let the human re-scope.
The main agent declares the task; subagents use it. A Codex subagent's shell has its own id,
so run task.py from the main agent. An opened isolated session is bound automatically.

**Gates**
- G1 Boundary, human: task.py approve <feature> in the human's terminal. The agent cannot
  add, change or remove approval data. A changed draft does not widen approved write paths.
- G2 Plan, AI, once: one plan reviewer and one scope auditor. Claude prompts use [plan-gate]
  and the page path; Codex dispatch task_name starts with plan_gate.
- G3 Review, AI: each task, then the whole branch, one round per scope.
- G4 Ship, human decides: green tests on the candidate, required checks before main moves.
  Already granted merge/push permission needs no repeated question.

**Docs** (agentkeel.json sets "docs": "html"): one authored page per document in flat docs/.
Use a project canon, one state page per feature, references, audits and mockups.
task.py new starts a page; task.py context reads it. Plan and progress go in Working.
task.py finish removes Working before main moves; unfinished outcomes stay in Remaining scope.
No decision log, Markdown twin or copied facts: link to the current owner.
A gated move names the full checked SHA, alone in its call: git merge --ff-only <full-sha>.

**Guards** refuse supported writes outside the task, protected-branch edits, commits without
paths, unauthorized shipping/builds/paid jobs, edits to hook config or task state, and a third
plan-gate dispatch. Guarded MCP calls need their permission and target. Destructive git and
secret printing have logged, single-command overrides: AGENTKEEL_ALLOW_DESTRUCTIVE=1 and
AGENTKEEL_SHOW_SECRETS=1. They do not grant shipping permission.
task.py verify runs a check; hooks record evidence. Codex results stay unrecorded; use CI to ship.

**Limits**: ordinary hooks do not see shell writes inside scripts or redirects. task.py open
adds an OS sandbox; Claude's per-user temp folder stays shared. Other MCP servers and browser
writes are unsupported. The task record declares scope; it is not proof of human consent.
Database, ports and queues belong to the repository's resource-isolation tooling.
