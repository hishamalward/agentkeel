# Optional runtime boundary

AgentKeel creates and deletes Git worktrees. It does not allocate ports, databases,
dependencies, simulators or server processes. AgentSlots may attach to an existing worktree.

Keel writes `agent-workspace.json` in that worktree's Git administrative directory. Its
version-1 identity includes the canonical worktree path, Git directory, common Git directory,
primary checkout, task, session, branch, base commit, directory device/inode and random token.
The task record holds the same identity. A replaced path or mismatched token is not owned.

Slots writes its resource ownership and allocation intent to `agent-runtime.json` in the
same Git directory, before allocating external resources. This is a resource claim, not a
second task registry. No integration reads the other tool's private task directories.

Both tools use an exclusive flock on `agent-lifecycle.lock` in the worktree's Git directory.
Keel uses the same name in the common Git directory to serialize creation and disposal.
When both locks are needed, acquire common first, worktree second. Do not unlink lock files.
After acquiring a lock, revalidate identity and state; an earlier path check is insufficient.

Keel marks the workspace `disposal_pending` before releasing its lifecycle lock to invoke:

```sh
agent-slots release --worktree /absolute/task/worktree
```

`AGENTKEEL_SLOTS` may name an absolute executable instead. No runtime marker means no Slots
invocation. A malformed marker or unavailable executable leaves cleanup pending. Slots refuses
new attachment to a disposing workspace; release remains retryable there. Successful release
removes only resources and configuration it owns, then removes the marker. It never removes
the Git worktree or branch. Pausing retains the marker, data and worktree.

Keel then takes the lock again and rechecks identity, absent runtime claim, preserved task
commits, files and processes before removing the tree. An unknown process, ignored file or
unpreserved work is a reason to retain it. Other tasks' shared Git branches and stashes remain
untouched. Retaining a preview is explicit and keeps both ownership records.
