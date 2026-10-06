<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/261005-brand-banner-dark-asset.svg">
    <img src="docs/261005-brand-banner-light-asset.svg" width="100%" alt="AgentKeel: guardrails beneath your AI coding agents. The mark is a boat carrying blocks of work, with a keel below the waterline.">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml"><img src="https://github.com/hishamalward/agentkeel/actions/workflows/validate.yml/badge.svg" alt="validate"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2f5bd3" alt="License: MIT"></a>
  <a href="#requirements"><img src="https://img.shields.io/badge/python-3.10%2B-2f5bd3" alt="Python 3.10+"></a>
  <a href="#claude-code"><img src="https://img.shields.io/badge/Claude%20Code-plugin-2f5bd3" alt="Claude Code plugin"></a>
  <a href="#codex"><img src="https://img.shields.io/badge/Codex-plugin-2f5bd3" alt="Codex plugin"></a>
</p>

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
- **Bounded writes.** A file-tool write with no task, outside the task's worktree, or on
  `main` is refused. Every code task works in its own git worktree, so agents never share a
  checkout.
- **Shipping is a permission.** Moving `main` needs `merge`. Any remote push needs `push`.
  Distribution builds, store submissions and paid jobs each need their own permission. Local
  checks, local builds and local pushes between feature branches need only `implement`.
- **Large work waits for you.** A large task edits nothing outside `docs/` until you approve its
  boundary, and then only the paths that the boundary lists.
- **Records with one current owner per fact.** In a repository that opts in, the agents' work
  records are HTML pages in one `docs/` folder, in the present tense. An agent's push to `main`,
  and a local move to a known commit, wait for the docs check; CI runs it for everyone. A commit
  made on `main`, a rebase or a non-fast-forward merge is checked later, at the push and in CI
  ([limits](docs/html-records.md#current-limitations-and-open-decisions)).
- **Loops have caps.** One plan gate per plan, one review round per scope.

## Install

Install AgentKeel as a plugin in your agent. The plugin acts only in a repository that opts in,
so it is safe to install once for all your work.

### Requirements

- **Python 3.10 or newer**, on your `PATH` as `python3`. The hooks are Python scripts, so the
  plugin needs it too. (macOS's `/usr/bin/python3` may be older.)
- git, and bash 3.2 or newer.

### Claude Code

```bash
claude plugin marketplace add hishamalward/agentkeel
claude plugin install agentkeel@agentkeel
```

In a session, the same commands are `/plugin marketplace add hishamalward/agentkeel` and
`/plugin install agentkeel@agentkeel`. Claude Code runs the plugin's hooks with no further trust
step. The first time an agent declares a task, Claude Code asks you to allow the `task.py` command;
allow it always, and later sessions do not ask again (an update to a new version asks once more,
because the path includes the version).

### Codex

```bash
codex plugin marketplace add hishamalward/agentkeel
codex plugin add agentkeel@agentkeel
```

Then open Codex in the repository, run `/hooks`, and trust AgentKeel's five hooks. Codex skips a
plugin hook until you trust it.

### Opt a repository in

Installing the plugin makes AgentKeel available; opting a repository in turns it on there. Run
`init` from the repository, with the path of the host you installed:

```bash
cd path/to/your-repo
python3 ~/.claude/plugins/cache/agentkeel/agentkeel/0.5.1/hooks/task.py init   # Claude Code
python3 ~/.codex/plugins/cache/agentkeel/agentkeel/0.5.1/hooks/task.py init    # Codex
```

`init` creates `agentkeel.json` only when it is missing, and never changes an existing one. It
registers the opt-in in `~/.agentkeel/opted-in.json`, so the guards act in this repository and all
its worktrees at once, before any commit, and a shell command that deletes the file does not
switch them off. It then reports three things apart: what the policy turns on, whether each host
has the plugin installed and enabled (from the host's own `plugin list`), and (Codex) how many of
its hooks you have trusted. Reading Codex trust needs a TOML parser (Python 3.11 or newer); when
`init` cannot read a fact reliably, it reports it as unknown.

An empty policy, `{}`, protects `main` and `master` and needs a task for every write. It does not
turn on HTML work records (`"docs": "html"`) or the push gate (`"require_check_before_push"`);
see [the policy file](docs/task-record.md#the-repository-policy-file). `init` does not commit.
Share the policy through your normal workflow when you choose:

```bash
git add agentkeel.json && git commit -m "Opt in to AgentKeel" -- agentkeel.json
```

### Prove it works

Open the repository's shared checkout in your agent, and give it this exact prompt before
anything else:

```text
This is a check of this repository's guard hooks. Without declaring any task and without
creating a worktree, use your file editing tool once to create the file agentkeel-probe.txt at
the root of this checkout, containing the word probe. Do not retry, do not use the shell, and do
not work around a refusal. Reply with the exact error text you received, or "created".
```

The test passes when the agent quotes a refusal that contains `AGENTKEEL:` and no
`agentkeel-probe.txt` exists. The host adds its own prefix (`PreToolUse:Write hook error` in
Claude Code, `Command blocked by PreToolUse hook` in Codex). Without a task, the refusal is
`no task is declared for this session`; with a task, it is `... is the repository's shared
checkout`. Both are correct. An ordinary edit request does not test this: a well-behaved agent
declares a task, makes a worktree, and edits there, which is allowed.

### Where `task.py` is

Agents run `task.py` to declare a task. With the plugin, it lives in the plugin's folder, and
each session starts with a message that gives its real path, for example
`~/.claude/plugins/cache/agentkeel/agentkeel/0.5.1/hooks/task.py` in Claude Code or
`~/.codex/plugins/cache/agentkeel/agentkeel/0.5.1/hooks/task.py` in Codex. A refusal repeats the
path, so an agent never has to guess it. The same message says where the session is (the
checkout, its branch, its task) and lists the repository's other worktrees with the task that
holds each.

### Update and remove

| | Claude Code | Codex |
|---|---|---|
| Update | `claude plugin marketplace update agentkeel`, then `claude plugin update agentkeel@agentkeel` | `codex plugin marketplace upgrade agentkeel`; trust changed hooks again in `/hooks` |
| Remove | `claude plugin uninstall agentkeel@agentkeel`, then `claude plugin marketplace remove agentkeel` | `codex plugin remove agentkeel@agentkeel`, then `codex plugin marketplace remove agentkeel`; then delete the empty `~/.codex/plugins/cache/agentkeel` folder and any `hooks.state."agentkeel@agentkeel:..."` sections in `~/.codex/config.toml`, which Codex leaves |
| Opt one repository out | delete its `agentkeel.json` and its entry in `~/.agentkeel/opted-in.json` | the same |
| Check the setup | run `task.py init` again in the repository: it changes nothing that exists and reports each host | the same |

### Per-repository install (fallback)

To put the hooks inside one repository instead, for everyone who clones it, use the installer.
Use one way per repository, never both.

```bash
git clone https://github.com/hishamalward/agentkeel
python3 agentkeel/install.py path/to/your-repo            # preview: lists every change
python3 agentkeel/install.py path/to/your-repo --apply    # hooks, settings for both hosts, AGENTS.md
python3 agentkeel/install.py path/to/your-repo --doctor   # what is installed and trusted
```

It copies the hooks into `.claude/hooks/`, merges its entries into `.claude/settings.json` and
`.codex/hooks.json`, and adds its instructions to `AGENTS.md` between markers. It keeps your other
hooks and settings, and it never creates a `CLAUDE.md` (Claude Code reads `AGENTS.md` only when no
`CLAUDE.md` exists). `task.py` is then `.claude/hooks/task.py`. `--host claude` or `--host codex`
installs one host; `--doctor --live` runs a probe on each host for you; `--uninstall` puts back
each file you have not edited since, and keeps your later edits.

## A small task, start to finish

You ask: "Add a `--json` flag to the CLI, then merge it." The agent reads that as a small task
with `implement` and `merge`, and says so in its first update. `$TASK` is the `task.py` path from
the session-start message.

```bash
# 1. In the shared checkout: declare the task. The hooks read this record on every tool call.
python3 "$TASK" start json-flag --size small --allow implement,merge

# 2. Make the task's own worktree. It is recorded as the task's automatically.
git worktree add ../myrepo-json-flag -b feat/json-flag
cd ../myrepo-json-flag

# 3. Edit there, then commit, naming the paths.
git add cli.py tests/test_cli.py
git commit -m "cli: add --json" -- cli.py tests/test_cli.py

# 4. Run the check and record its result against this HEAD.
python3 "$TASK" verify -- python3 -m pytest

# 5. Move main to the tested commit by its full SHA (git rev-parse HEAD), in its own call.
cd ../myrepo && git merge --ff-only <full-sha>

# 6. End the task. The output lists what the task owned.
python3 "$TASK" end
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
  see [required checks](docs/required-checks.md).
- Other hosts (Cursor, Copilot) read `AGENTS.md` only. For them, AgentKeel is guidance.

## Read next

| Page | Read it to |
|---|---|
| [Project canon](docs/canon.md) | learn the rules that apply now: the invariants, the four gates, and why each rule exists |
| [Guardrails](docs/guardrails.md) | see each hook, what it refuses, what it cannot see, the overrides, and the test for each protection |
| [The task record](docs/task-record.md) | declare a task: sizes, permissions, worktrees, scratch, `agentkeel.json` |
| [HTML records](docs/html-records.md) | write work records in your repository, get a boundary approved, and pass the docs check |
| [Required checks](docs/required-checks.md) | keep `main` green with a CI check and a deploy that waits for it |
| [Hosts](docs/hosts.md) | see the Claude Code and Codex facts and the live results |
| [Hook payloads](docs/hook-payloads.md) | read the captured JSON that the hooks parse |

Related work: [agent-slots](https://github.com/hishamalward/agent-slots) isolates the database,
ports and queues of several agents on one machine. AgentKeel is the process side; agent-slots is
the resource side.

## Test

```bash
python3 -m unittest discover -s tests
```

CI runs the suite on macOS and Linux, on Python 3.10 and 3.13, plus each hook's `--selftest`.

Every version field (both plugin manifests, the marketplace entry and the plugin paths in this
README) states one product version. `python3 release_check.py --tag vX.Y.Z` refuses a release
whose fields disagree with each other or with the tag, and CI runs it on every push and tag.

## License

MIT. See [`LICENSE`](LICENSE).
