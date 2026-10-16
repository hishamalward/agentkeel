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
branch tip, files and processes before removing the tree. An unknown process, unpreserved tip or ignored local data is a reason to retain it.
Amend/rebase history is not an extra preservation gate once the tip is merged. Ignored
`__pycache__`, `.pytest_cache`, `node_modules` and `.DS_Store` are treated as regenerated
artifacts. The canonical checkout’s `disposable_ignored` policy can allow additional exact
worktree-relative file/directory paths, such as `.venv` or `dist`; directory entries include
their descendants. Other ignored files need preservation or explicit `finish --discard-ignored`,
which discards all ignored data, including `.env`. The policy never waives checks for tracked
changes, untracked files, ownership, branch preservation or active processes.
Human-only `discard TASK --worktree PATH` can waive work preservation for a cancelled task,
but always retains identity, runtime-release and active-process checks. Other tasks' shared Git branches and stashes remain
untouched. Retaining a preview is explicit and keeps both ownership records.
