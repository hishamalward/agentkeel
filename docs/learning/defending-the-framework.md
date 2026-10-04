# Defending the framework

> **v0.2 note (2026-10-04).** This document describes v0.1, where a "tier" was one declaration that
> also granted actions (`tier.sh`, `tier-guard.py`, `write-path-guard.py`). v0.2 replaced it with
> the task record: size, permissions and resources answered separately (`task.py`,
> `task-guard.py`; `DECISIONS.md` D-004 to D-007). The reasoning below stands; the hook names,
> state paths and override names do not. The present behaviour is in the README and
> `docs/task-record.md`.

For the owner, in interviews and reviews. Two or three sentences each, evidence not assertion.
The evidence lines cite `docs/spec.md` §2.1, which cites the source lines in the practice repo.

## Why gates instead of better prompts?

Because the session that drifts is the session that read the prompt. In practice a rule that
said "gate the plan once" was in the CLAUDE.md the whole time the plan was gated three times,
at roughly 1.2M subagent tokens before a line of code; the prose was read and not held. A gate
with an owner and an exit condition is a place the work stops, and a hook is a gate the model
cannot forget, because it runs in the harness before the tool call.

## How do you stop an agent from widening blast radius mid-task?

Three ways that reinforce each other. The spec names `Changes` and `Must not change` before
the work starts; the tier declaration is state the hooks read, so a task cannot promote itself
from a one-file fix to a refactor without a recorded re-declaration; and the write-path guard
refuses the writes that widen it silently (a commit on `main`, an edit outside the worktree, a
push that moves `main`). What none of that catches is a `sed -i`, and the README says so; the
next hook reads the approved spec and refuses edits outside its `Changes` list.

## What does a hook catch that a CLAUDE.md rule does not?

The moment the rule is about to be broken. A CLAUDE.md rule is advice at the start of the
session; a hook is a decision at the tool call, with the reason handed back to the model as the
tool result. In the worked example the agent tried `git checkout main && git merge && git push`
after being told to, read the refusal, and reported "G4 is your call" instead of pushing; the
same agent had the rule in its context the whole time.

## How do you know the framework is working?

From what it caught and what it stopped costing. Eight task reviews plus a branch review on
one stream found zero implementation defects and seven plan defects, six of them a check scoped
wider than the work it checked; that is why the plan table has a scope column. A 4105-line plan
for 541 lines of shell is why plans no longer carry code. The worked example in the README is
six refusals from a real run, and one of them found a bug in a hook, which is the framework
working on itself.

## What is the difference between this and agent-slots?

agentkeel is the process side: what a task may do, who approves it, what proves it. agent-slots
is the resource side: a worktree isolates the filesystem and nothing else, so one integer derives
the database, the ports and the queue schema that two agents on one machine would otherwise
share. You can run either without the other; the README links, and does not duplicate.

## Self-check

<details><summary>1. Why is verification not a gate?</summary>
A gate is a point where work stops until a named owner produces named evidence. Verification has
no owner of its own and no single point; it is the evidence every gate consumes. Calling every
loop a gate produced six and made "gate" mean "step".
</details>

<details><summary>2. Why must every tier declare, including small?</summary>
If small were the silent default, an undeclared session could commit on main, which is the
unsafe default the hooks exist to remove. The cost is one command the agent runs itself; the
declaration also expires, so yesterday's small cannot grant today's commit.
</details>

<details><summary>3. What can the hooks not see?</summary>
Anything that is not a tool call: shell writes other than git (sed -i, redirects), a cd into a
different repo before a git command, a program that prints a secret, a plan-gate dispatch worded
to dodge the heuristic. The guarantee is "the agent's tool calls were bounded".
</details>

<details><summary>4. Why does every override echo to stderr?</summary>
So the transcript shows every time a guard was stepped around, and under which name. An
override that is silent is a hole; an override that is loud is a decision on record.
</details>

<details><summary>5. Why do plans never carry code?</summary>
A plan that transcribes the implementation makes implementers into transcribers whose
transcription is then reviewed: the work done twice. Three rules in the old practice were
workarounds for that one cause; removing the cause removed two of them.
</details>
