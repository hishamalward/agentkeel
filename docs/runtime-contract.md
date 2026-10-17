# Optional runtime boundary

AgentKeel creates and deletes new task worktrees and can resume existing ones. It does not allocate ports, databases,
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

For normal coding-task cleanup, Keel first confirms declared HTML pages are tracked and preserved unchanged in canonical `/doc`. No-code tasks have no worktree or runtime to release.

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

`resume` holds common then worktree lifecycle locks, verifies the Git identity, and requires
explicit handoff from the current session owner (all legacy owners if no manifest exists).
It refuses an attached runtime rather than changing Slots' records. The new manifest supersedes
legacy task claims. If saving the new task fails, the prior manifest is restored. Worktree files,
index and refs are unchanged. A resumed manifest has `retain_on_finish: true`; finish releases
the runtime and changes its state to `retained` without deleting the worktree or branch.
Slots cannot attach to that ended claim until a new session resumes it.
