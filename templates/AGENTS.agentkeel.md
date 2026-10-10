## agentkeel (kept between its markers by task.py init or install.py; full text: github.com/hishamalward/agentkeel)

Three rules govern the workflow; a rule serving none goes.
1. Bound each write to the request. Do the literal ask; mention adjacent problems, do not fix them.
2. Give evidence for claims: run the check before claiming success. Report a failed check;
   never widen the scope or narrow the check.
3. Cap loops: one plan gate per plan, one review round per scope, one verification pass per
   claim. Only the human re-opens a loop.

**Declare the task before the first write.** The guards read the record, not this text.
    python3 "<task.py path>" start <task-id> --size small|large --allow <permissions> [--kind <kind>] [--deliverable <page>]
Use the path printed at session start (.claude/hooks/task.py in a project install); run it
as shown. State your reading of the request in the first update and proceed. Ask only for missing
information, unclear intent or an action beyond scope. Size and kind grant nothing.
- Small: own worktree, no plan or subagents, one check, short report (medium = small).
- Large: approved boundary, plan gated once, reviews.
- Kind: feature (default), fix, review, docs, chore. Fix: no code edit before a failed check
  (task.py verify -- <cmd>) and a cause line (task.py cause "X causes Y because Z") are on
  record; the fourth edit-then-fail cycle waits for the human's task.py reopen. Skill: debugging.
- Permissions: review (report folders); implement (edits, explicit-path commits, local
  checks, feature-branch pushes); merge (move a protected branch); push (remote pushes,
  deploys); distribution-build; store-submission; paid-job; remote-write, publish (MCP;
  need targets).
- Code belongs in the task's own worktree (git worktree add ../<repo>-<task> -b feat/<task>
  records it) or its clone from the human's task.py open. Temp files: the task's printed
  scratch folder.
When in doubt, pick the smaller size. If it grows, stop and let the human re-scope.
The main agent declares the task; subagents use it (a Codex subagent's shell has its own id:
run task.py from the main agent). An opened session is bound automatically.

**Gates**
- G1 Boundary, human: task.py approve <feature> in the human's terminal.
- G2 Plan, AI, once: plan reviewer plus scope auditor. Claude prompts use [plan-gate] and
  the page path; Codex task_name plan_gate*.
- G3 Review, AI: each task, then the whole branch; one round per scope.
- G4 Ship, human decides: one PR per change; ready PRs test each new head. Fetch main, rebase
  if needed, test, fast-forward. A PR grants nothing.
**Docs** (agentkeel.json sets "docs": "html"): flat docs/, one HTML page each;
task.py new starts one, task.py context reads it; plan and progress go in Working. The user is
a very visual person: present findings, reviews and progress as HTML pages, with mockups where
they help; the plain keel.css look is for the canon page only. Before main moves, rewrite the page's Outcome and run task.py finish. A gated
move names the full checked SHA, alone in its call: git merge --ff-only <full-sha>.
**Guards** refuse writes outside the task, protected-branch edits, bare commits, unpermitted
shipping, edits to hook config or task state, a third plan gate.
agentkeel.json "guards" sets each (task, secret, plan_gate, plan_size, fix) to block, warn
or off. One-command overrides (logged): AGENTKEEL_ALLOW_DESTRUCTIVE=1, AGENTKEEL_SHOW_SECRETS=1.
task.py verify runs a check: hooks record a pass, a failure records itself; Codex passes stay
unrecorded; CI ships. task.py status --html writes a status page.

**Limits**: hooks miss shell writes inside scripts or redirects (task.py open adds a
sandbox; Claude's temp folder is shared). Other MCP servers and browser writes are
unsupported. The record is scope, not consent.
