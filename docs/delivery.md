# HTML delivery checkpoints

Every task declares a persistent HTML report with `task.py start --deliverable`. It is a human checkpoint for the task's result, evidence, limits and next steps. Its structure and visual design are free form; AgentKeel does not prescribe sections or a template.

The report must be an absolute `.html` or `.htm` file inside a declared write root, outside the task's disposable worktrees. It must be a readable, nonempty file with real `html`, `title` and `body` tags and nonempty title/body content. Handoff and Stop checks validate these requirements without interpreting page content.

`task.py handoff` records the report's path, modification time, digest and current worktree code snapshot. A report older than task declaration, outcome or recorded evidence is stale. If code changes after a saved checkpoint while the report itself is unchanged, the report is stale; rewriting the report allows a fresh checkpoint. The Stop hook blocks once for a missing or stale report and does not repeat a block if the host reports that it is already retrying the hook. A cancelled task is retained without requiring a report update.

`finish` can clean up a shipped task's worktree before the final checkpoint. It may then return `report_pending`; update the report to describe the final state and rerun `finish`.

A report is not proof of authorization or a code security boundary. Keep sensitive information out of it and verify claims against the referenced source, commands and checks.
