<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/261005-brand-banner-dark-asset.svg">
    <img src="docs/261005-brand-banner-light-asset.svg" width="100%" alt="AgentKeel: one script, one convention, no hooks.">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml"><img src="https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml/badge.svg" alt="validate"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2f5bd3" alt="License: MIT"></a>
</p>

AgentKeel 1.0 is one bash script and one convention for working with coding agents in git
worktrees. Each stream of work gets a worktree that is a sibling of the repository; any number of
agents may share it; runtime resources are attached only when the work needs them. There are no
hooks, no task records, no permissions to declare and nothing running in the background.

Until 0.12 AgentKeel was a Claude Code plugin with four hooks, task declarations, worktree
ownership and a fail-closed MCP bridge. It was retired on 2026-10-21 because it created worktrees
nobody asked for and made two agents in one tree impossible. The review that led here, with the
evidence and the before/after architecture, is [docs/keel-simplification-review.html](docs/keel-simplification-review.html).
The skills-only release is [v1.0.0](https://github.com/hishamalward/agentkeel/releases/tag/v1.0.0).
The `v0.12.0` tag preserves the last hook-based release; it does not contain the 1.0 rewrite.

## What you get

| File | What it is |
|---|---|
| `bin/workstream` | The script: `new`, `ls`, `done`, `selftest`. Bash and git only. |
| `skills/workstream/SKILL.md` | The agent's doorway: when to open a tree and which resources to attach. |
| `skills/review-page/SKILL.md` | Ask the agent for visual HTML pages instead of prose. |
| `skills/debugging/SKILL.md` | Root cause first, failing check first, one change at a time. |
| `templates/AGENTS-section.md` | The convention, ready to paste into `AGENTS.md` or `CLAUDE.md`. |
| `templates/claude-settings-snippet.json` | Native Claude Code deny/ask rules that replace the old guards. |

## Install

Copy one file into your repository and make it executable:

```bash
curl -fsSL https://raw.githubusercontent.com/hishamalward/agentkeel/v1.0.0/bin/workstream -o scripts/workstream
chmod +x scripts/workstream
scripts/workstream selftest
```

Then paste `templates/AGENTS-section.md` into your `AGENTS.md`, and the deny/ask rules from
`templates/claude-settings-snippet.json` into `~/.claude/settings.json`. For the skills, symlink
the three folders into `~/.claude/skills/`, or install the repository as a Claude Code plugin
(skills only, no hooks):

```bash
claude plugin marketplace add hishamalward/agentkeel
claude plugin install agentkeel@agentkeel
```

## Use

```
scripts/workstream new weekly-recap --type feat           # sibling ../<prefix>weekly-recap on feat/weekly-recap
scripts/workstream new metro-port --type fix --service web --service db
scripts/workstream ls
scripts/workstream done weekly-recap                      # after the PR merges
```

- The path is computed from the repository root, never from the shell's cwd, so a tree can never
  end up nested inside another. The sibling prefix comes from `AGENT_WORKTREE_PREFIX` in
  `.agent-slots.conf` when present, otherwise `<repo-name>-`.
- `--service` and `--prepare` are passed through to [AgentSlots](https://github.com/hishamalward/agent-slots)
  (`scripts/agent-slots attach`) when the repository has it. Without them the tree is bare.
- `done` releases the slot, then removes the tree and branch. It requires a clean tree and either
  commits already on the local base branch or exactly matching committed content (a squash merge).
  Update your local base after merging. If the base has since changed and the content differs,
  cleanup still refuses; inspect the differences before using `--force`, which also permits
  deleting uncommitted work.

## The convention

Work where you were launched. Open a new tree only when the user asks for a new stream or when
you are on `main` with code to change. Reviews and questions get no tree. Ship with a pull
request and `gh pr merge --auto`; protect `main` with a GitHub ruleset, not with a hook. The full
text is in `templates/AGENTS-section.md`.

## License

MIT.
