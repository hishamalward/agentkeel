<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/261005-brand-banner-dark-asset.svg">
    <img src="docs/261005-brand-banner-light-asset.svg" width="100%" alt="AgentKeel: guardrails beneath your AI coding agents.">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml"><img src="https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml/badge.svg" alt="validate"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2f5bd3" alt="License: MIT"></a>
  <a href="#install-and-opt-in"><img src="https://img.shields.io/badge/python-3.10%2B-2f5bd3" alt="Python 3.10+"></a>
</p>

AgentKeel is a guardrail plugin for Claude Code and Codex. Before writing, an agent declares a task, its permissions, a persistent HTML report, and (for code work) gets a linked worktree. Hooks check supported edits, commands and MCP calls against that scope. The core uses Python's standard library.

## What it does

- Each session owns one task record outside the repository. `no-code`, `small` and `large` describe task process; permissions independently authorize actions.
- Coding tasks get a linked worktree created by AgentKeel. The session-start message prints its path; the agent must change into it before editing. A `no-code` task has no worktree.
- Every task names a free-form HTML deliverable in a persistent folder outside the repository and disposable worktrees. Handoff and Stop checks require a current, readable report with real `html`, `title` and `body` tags and content. There is no page template or content schema.
- `fix` tasks require a recorded failed check and cause before code edits. The guard limits repeated edit/fail cycles; see [Debugging](skills/debugging/SKILL.md).
- Each guard can be set to `block`, `warn` or `off` in `agentkeel.json`; MCP unknown-server handling also accepts `pass`.
- Shipping is permissioned. `pr` creates a pull request, `ship` verifies and fast-forwards the exact candidate, and `finish` releases owned worktree resources after synchronization. If cleanup changes the code snapshot, finish reports `report_pending`; refresh the HTML and run finish again.
- MCP adapters currently check supported calls for RevenueCat, PostHog, Sentry and DataForSEO. This is an interim implementation pending the Clerk phase; other servers and access through shell/browser paths have the limits described in [guardrails](docs/guardrails.md).
- `review-page` helps write a useful human review report. Ponytail provides coding preferences; the debugging skill remains the workflow for fixes.

## Install and opt in

Install AgentKeel through the host's plugin marketplace, then opt each repository in. Python 3.10+, git, and bash 3.2+ are required.

Claude Code:

```bash
claude plugin marketplace add hishamalward/agentkeel
claude plugin install agentkeel@agentkeel
```

Codex:

```bash
codex plugin marketplace add hishamalward/agentkeel
codex plugin add agentkeel@agentkeel
```

In Codex, open `/hooks` in the repository and trust AgentKeel's hooks. In the repository, run the installed `task.py init` path printed by the host/plugin instructions. Plugin files are cached under a versioned path such as `~/.claude/plugins/cache/agentkeel/agentkeel/0.9.1/hooks/task.py`; session start prints the actual path. `init` creates `agentkeel.json` only when absent, updates its managed block in `AGENTS.md`, registers the repository, and reports host install/trust state. It does not commit.

The default `{}` policy protects `main` and `master`. Every write needs a declared task. Configure optional protected branches, command rules, MCP catalog entries and `require_check_before_push` in `agentkeel.json`; see [the policy guide](docs/task-record.md#repository-policy).

## A task from start to finish

The plugin session-start message prints the correct `task.py` path. Start from the shared checkout; AgentKeel creates and records the coding worktree and prints its location. The report path must be absolute and outside the repository, and is within the default write root when no `--write-root` is supplied.

```bash
python3 "$TASK" start add-json --size small --allow implement,review,merge,push --deliverable /path/to/reports/add-json.html
cd /path/printed/by/task.py
# edit, commit with explicit paths, and check
python3 "$TASK" verify -- python3 -m unittest discover -s tests -q
python3 "$TASK" handoff
python3 "$TASK" pr --title "Add JSON output" --body-file /path/to/pr-body.txt
python3 "$TASK" ship --pr 123
# Update the report to describe the shipped result, then:
python3 "$TASK" finish
```

Use `--size no-code` for tasks without code changes. `--kind fix` enables the debugging guards; `--kind` may also be `feature`, `review`, `docs` or `chore`. `--write-root DIR` may be repeated when the report lives in a different persistent directory. `verify` records a foreground check against the current code. `cancel` retains incomplete work and marks the task cancelled. `status --json` prints derived state; `status --html` writes a temporary status view.

The legacy human-operated `open`, `import` and `release` commands still provide an isolated clone/session path on supported macOS setups. Their OS sandbox behavior is separate from the normal linked-worktree task flow and is not proven on every host/platform; see [enforcement design](docs/enforcement-design.md).

## Limits

Hooks inspect supported host tool events and parsed shell operations. They cannot contain arbitrary shell scripts, unparsed side effects, browser writes or credentials used outside an intercepted MCP call. Linked worktrees share Git internals with the primary checkout. The optional isolated-clone mode uses host OS sandboxing for a stronger shell boundary, with platform-specific limits. Hooks do not replace host permission prompts or CI checks.

## Documentation

- [Task record, CLI and policy](docs/task-record.md)
- [Free-form HTML delivery](docs/delivery.md)
- [Guardrails and limits](docs/guardrails.md)
- [Host behavior](docs/hosts.md)
- [Captured hook payloads](docs/hook-payloads.md)
- [Enforcement design](docs/enforcement-design.md)
- [Review-page skill](skills/review-page/SKILL.md)
- [Debugging skill](skills/debugging/SKILL.md)

AgentKeel works alongside [AgentSlots](https://github.com/hishamalward/agentslots), which manages local runtime resources such as databases and ports.

## Test

```bash
python3 -m unittest discover -s tests -q
```
