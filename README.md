<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/261005-brand-banner-dark-asset.svg">
  <img src="docs/261005-brand-banner-light-asset.svg" width="100%" alt="AgentKeel: guardrails beneath your AI coding agents. The mark is a boat carrying blocks of work, with a keel below the waterline.">
</picture>

[![validate](https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml/badge.svg)](https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml)

AgentKeel keeps AI coding agents inside the task you gave them. Each agent declares its task
before its first write. Hooks then check every tool call against that declaration and refuse what
falls outside it, with a reason the agent reads. It runs in **Claude Code** and **Codex**, from one
core, with no dependencies.

## The problem

Agents write code faster than anyone can review it. The failures are rarely in the code. They
are missing gates: a one-file fix that became a refactor, a commit on `main` that nothing
stopped, a check that could not fail, a build nobody asked for. Rules in an instruction file do
not hold, because the session that drifts is the session that read them. AgentKeel moves the
rules that matter into hooks, outside the model's memory.

## What it does

- **One task record per session.** The agent states the task's size (how much process),
  permissions (which actions) and worktrees (where). Size never grants a permission.
- **Bounded writes.** A write with no task, outside the task's worktree, or on `main` is
  refused. Every code task works in its own git worktree, so agents never share a checkout.
- **Shipping is a permission.** Moving `main` needs `merge`. Any push needs `push`. Builds,
  store submissions and paid jobs each need their own permission.
- **Large work waits for you.** A large task edits nothing outside `docs/` until you approve its
  boundary, and then only the paths that the boundary lists.
- **One current owner per fact.** Documentation is authored HTML pages in one `docs/` folder,
  in the present tense. `main` moves only when the docs check passes.
- **Loops have caps.** One plan gate per plan, one review round per scope.

## Quickstart

Python 3.10 or newer. Preview first; the installer changes nothing without `--apply`.

```bash
git clone https://github.com/hishamalward/agentkeel
python3 agentkeel/install.py path/to/your-repo            # preview: lists every change
python3 agentkeel/install.py path/to/your-repo --apply    # hooks, settings for both hosts, AGENTS.md
python3 agentkeel/install.py path/to/your-repo --doctor   # what is installed and trusted
```

Then prove it works. Open the repository in your agent and ask for a one-line edit before
anything else. The agent must get this refusal:

```text
AGENTKEEL: no task is declared for this session.
```

On Codex, trust the new hooks first (`/hooks` in Codex): Codex skips a project hook until you
trust it. `--doctor --live` runs this proof for you, one short session per host.

The installer writes `.claude/hooks/`, merges its entries into `.claude/settings.json` and
`.codex/hooks.json`, and adds its instructions to `AGENTS.md` between markers. It keeps your
other hooks and settings, and it never creates a `CLAUDE.md` (Claude Code reads `AGENTS.md` only
when no `CLAUDE.md` exists). `--host claude` or `--host codex` installs one host. `--uninstall`
puts back each file you have not edited since, and keeps your later edits.

To use AgentKeel in every repository, install it as a plugin instead: `.claude-plugin/` and
`.codex-plugin/` share one `hooks/hooks.json`. A plugin acts only in a repository with an
`agentkeel.json` at its root. Use one way per repository, not both.

## A small task, start to finish

You ask: "Add a `--json` flag to the CLI, then merge it." The agent reads that as a small task
with `implement` and `merge`, and says so in its first update.

```bash
# 1. In the shared checkout: declare the task. The hooks read this record on every tool call.
python3 .claude/hooks/task.py start json-flag --size small --allow implement,merge

# 2. Make the task's own worktree. It is recorded as the task's automatically.
git worktree add ../myrepo-json-flag -b feat/json-flag
cd ../myrepo-json-flag

# 3. Edit there, then commit, naming the paths.
git add cli.py tests/test_cli.py
git commit -m "cli: add --json" -- cli.py tests/test_cli.py

# 4. Run the check and record its result against this HEAD.
python3 ../myrepo/.claude/hooks/task.py verify -- python3 -m pytest

# 5. Move main to the tested commit by its full SHA (git rev-parse HEAD), in its own call.
cd ../myrepo && git merge --ff-only <full-sha>

# 6. End the task. The output lists what the task owned.
python3 .claude/hooks/task.py end
```

What the hooks refuse on the way, and why:

| The agent tries | The hook answers |
|---|---|
| an edit in the shared checkout | `... is the repository's shared checkout. Every code task, small ones included, works in its own worktree` |
| an edit on `main` | `this worktree is on the protected branch 'main'` |
| `git commit -m x` with no paths | `refusing a commit that does not name its paths` |
| `git push origin feat/json-flag` | `a push to 'feat/json-flag' needs the 'push' permission; task 'json-flag' has implement, merge` |

"Merge" did not include "push", so the agent stops at step 5 and reports that the work is
ready to push.

## Limits

- The hooks see the agent's tool calls, not the filesystem. A shell write that is not git
  (`sed -i`, `>`), a command inside a script, and MCP tools are not checked.
- The task record is the agent's declaration, not your consent. It makes every action match
  one stated scope. For consent itself, use your host's permission prompts.
- An approval digest detects a change to an approved boundary. It does not prove who approved.
- Hooks guard the agent, not the branch. Tests before `main` moves need a required CI check:
  see [required checks](docs/261004-required-checks-state.html).
- Other hosts (Cursor, Copilot) read `AGENTS.md` only. For them, AgentKeel is guidance.

## Read next

The documentation is HTML. Open the `docs/` pages from a clone, in a browser. On github.com, a
link to a page shows its source.

| Page | Read it to |
|---|---|
| [Project canon](docs/260823-project-reference.html) | learn the rules that apply now: the invariants, the four gates, and why each rule exists |
| [Guardrails](docs/260823-guardrails-reference.html) | see each hook, what it refuses, what it cannot see, the overrides, and the test for each protection |
| [The task record](docs/261004-task-record-state.html) | declare a task: sizes, permissions, worktrees, scratch, `agentkeel.json` |
| [HTML documentation](docs/261005-html-docs-state.html) | write docs pages, get a boundary approved, and pass the docs check |
| [Required checks](docs/261004-required-checks-state.html) | keep `main` green with a CI check and a deploy that waits for it |
| [Hosts](docs/261004-hosts-state.html) | see the Claude Code and Codex facts and the live results |
| [Hook payloads](docs/260823-hook-payloads-reference.html) | read the captured JSON that the hooks parse |

Related work: [agent-slots](https://github.com/hishamalward/agent-slots) isolates the database,
ports and queues of several agents on one machine. AgentKeel is the process side; agent-slots is
the resource side.

## Test

```bash
python3 -m unittest discover -s tests
```

CI runs the suite on macOS and Linux, on Python 3.10 and 3.13, plus each hook's `--selftest`.

## License

MIT. See [`LICENSE`](LICENSE).
