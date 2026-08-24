# <slug>: handover

**Goal**: one sentence. What is true when this stream is done.
**Status**: in progress | MERGED <date> | abandoned <date and why>
**Spec**: `docs/specs/<slug>-spec.md`, if any.

<!--
The rule that makes this work: NO DERIVABLE STATE. No branch names, no ports, no "the tree
currently sits on". git and your status scripts answer those accurately; a second written copy
is a lie waiting to happen. Write down only what cannot be derived: the goal, what was verified,
what will bite, what is next, and why a decision was made.

Update after finishing any item, and always before stopping. A session's numbered todo list is
ephemeral and invisible to every other session; flush it here before the session ends.
-->

## The shape of it in one paragraph

## Current state in code

<!-- The ledger: what is built, task by task, with verify status. Which planned task is complete
     is INTENT, not state: git log shows which commits landed, it cannot tell you that T4 passed
     its check. So it is written here. -->

## What will bite

<!-- The gotchas that cost the last agent a debugging round. The most useful section. -->

## Not built, in the order I would build it

## In flight

<!-- The one thing being worked on right now. -->

## Blocked

<!-- What, and on what or whom. -->

## What is decided (do not re-litigate)

<!-- Cite D-NNN. -->

## Open questions

<!-- For the human. -->

## Verification protocol

<!-- The exact commands that prove the above, with their expected output. -->
