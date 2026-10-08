# Required checks before main moves

Hooks guard the agent, not the branch. To keep `main` green, test the candidate commit **before** `main` moves, refuse a commit whose check has not passed, and make the deploy wait for it. A passing check proves the tests ran green on that commit; it proves nothing the tests do not cover.

## Two ways to hold main

| Setup | Who it stops | Needs |
|---|---|---|
| **Branch protection** requires `agentkeel-required` (below) | everyone, at GitHub | a public repository, or GitHub Pro/Team for a private one |
| **The AgentKeel push gate** plus the deploy waiting for CI | agents using active AgentKeel hooks, before their push; GitHub-triggered deploys for anyone | no paid GitHub branch-protection plan |

GitHub Free has no branch protection on private repositories. There, use the push gate: add `"require_check_before_push": "agentkeel-required"` to `agentkeel.json`. An agent's push into a protected branch is then refused unless the check passed on the exact commit it ships.

- **Allowed:** `git push origin <full-tested-sha>:main`, alone in its call.
- **Refused:** a branch name or `HEAD` as the source (it can move while the gate reads the check), an earlier command in the same call, a bare push, `--all`, a configured or wildcard refspec, and `gh pr merge` (GitHub writes a new, unchecked commit for every merge mode).
- **No answer, no push:** the gate asks GitHub through `gh` (check runs, or the commit's Actions jobs), and refuses when it gets no answer.
- **Humans:** a human can still push to `main` by hand. With the deploy waiting for CI, an untested commit is not deployed.

## The shipping path

This is the path for ordinary sessions with shipping permission. An isolated session opened
with `task.py open` returns its commit through the human's `task.py import`; the human then ships
from the shared repository. Its sandbox cannot be widened by adding `merge` or `push`.

1. **Back up the branch**: `git push origin feat/<task>` (needs `push`). Ordinary branch pushes run no CI.
2. **Open a ready PR** targeting `main`, or mark its draft ready. Opened, reopened, updated and ready-for-review PRs run the relevant tests on the exact PR head. Drafts skip checks; converting to draft cancels the previous run.
3. **Wait for the check**: `agentkeel-required` passes on that exact commit (`gh pr checks`). Before testing, CI requires fetched current `main` to be an ancestor of the PR head. Fetch, rebase and update the PR if it is behind.
4. **Recheck main and ship**: fetch again, confirm the tested commit still contains current `main`, then `git push origin <full-tested-sha>:main`, in its own call. If `main` moved beyond the candidate, rebase, update the PR and wait for the new commit's check.
5. **Deploy**: the main workflow reruns the docs check and reuses the successful PR app tests when its evidence matches. Without that evidence, it runs the needed app tests on `main` before deployment.

The push is a fast-forward, so `main` gets exactly the tested commit. GitHub then marks the
branch's pull request as merged. Under the push gate, `gh pr merge` is refused.

With branch protection configured, GitHub refuses a push whose required checks have not passed.
With the AgentKeel push gate alone, the hook refuses the agent's push; a human push is still
possible, and the deploy must wait for CI. These provide different levels of protection.

## Install

```
mkdir -p .github/workflows .github/agentkeel
cp agentkeel/templates/ci/required-checks.yml .github/workflows/agentkeel-checks.yml
cp agentkeel/templates/ci/candidate.py .github/agentkeel/candidate.py
cp agentkeel/templates/ci/select_checks.py .github/agentkeel/select_checks.py
cp agentkeel/hooks/agentkeel_core/pages.py .github/agentkeel/pages.py
```

Set the repository variables your app needs (Settings, Secrets and variables, Variables): `AGENTKEEL_SETUP_COMMAND` (default `npm ci`) and `AGENTKEEL_TEST_COMMAND` (default `npm test`). If the app is not a Node app, replace the `setup-node` step.

The template targets `main`; change both branch filters if your default branch has another name.
It needs `contents: read` for checkout and `actions: read` for the main run's evidence lookup.
Copy the CI helpers with the commands above; `task.py init` installs the managed instructions,
not the CI workflow or its helpers.
The standard PR workflow instruction comes from AgentKeel's managed `AGENTS.md` block.

The workflow has four jobs:

- `select` binds checkout to the exact PR head or pushed main SHA and checks that the base is its ancestor. For a PR, the base is fetched current main; for a main push, it is the previous main tip. It selects app tests from changed paths: Markdown, `docs/` and `design-exploration/` only skip app tests; other changes, or unreadable paths, require them.
- `app-tests` runs the selected tests. On main, `candidate.py` may reuse the latest same-SHA PR run from the expected workflow and repository. That run must be completed successfully, with a successful `Bind tested commit` step and `agentkeel-required` job. Missing, failed, cancelled, pending or unknown evidence runs the needed tests on main. These checks match recorded run metadata; they are not a stronger security provenance guarantee.
- `docs` checks the candidate against its base on every ready PR and main push, including when app tests are reused. It passes untouched where `agentkeel.json` does not set `"docs": "html"` ([the docs check](html-records.md#the-docs-check)).
- `agentkeel-required` reports for ready PRs and main pushes: green when selection and docs passed, and app tests passed, were reused or were not needed. It is the only check to require, so a docs-only change does not wait for app tests.

## Protect the branch

With the GitHub CLI, after the workflow has run once (a check must exist before it can be required):

```
gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["agentkeel-required"] },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```

`strict: true` is "require branches to be up to date before merging": a check that passed on an older base is stale and does not count. `enforce_admins: true` applies the rule to admins too. The same settings exist in the web UI (Settings, Branches) and as a repository ruleset.

## Make the deploy wait

The deploy must not start on a commit whose check has not passed.

- **Railway**: in the service's settings, enable waiting for GitHub check suites ("Wait for CI") for the GitHub-connected deploy (in the API: `deploymentTriggerUpdate` with `checkSuites: true`). Railway then holds the deploy of a pushed commit as `WAITING` until its checks finish, and does not deploy it if they fail (verified 2026-10-04).
- **Vercel, Netlify and others**: use their equivalent "wait for checks" or "ignored build step" setting, or deploy from CI after `agentkeel-required` passes instead of on push.

Check the setting in your provider's current documentation when you enable it; AgentKeel does not configure the host for you.

## What can still bypass it

| Bypass | Closed by |
|---|---|
| An admin pushing straight to `main` | `enforce_admins: true` (or a ruleset with no bypass actors) |
| A token or app on the bypass list of a ruleset | keep the bypass list empty |
| A deploy triggered by hand in the provider's dashboard or CLI (`railway up`) | the agent's `push` permission covers deploy commands; a human can still do it |
| Tests that do not cover the change | not a setting: write the test |
| A local pre-push hook | early feedback only; it can be skipped with `--no-verify` and is not part of this guarantee |

## Verification

The PR-driven workflow and main evidence reuse have local targeted test coverage; hosted acceptance and deployment verification are pending. The live check below covers the earlier push-driven workflow and deploy gate, not PR evidence reuse.

Checked live on 2026-10-04 in a private throwaway repository with the push gate and real Actions runs: a candidate whose tests failed was refused (`'agentkeel-required' ended failure`), as was one whose check had not run yet; a docs-only candidate skipped the app tests, passed the required check, was allowed, and `main` moved to it; a green candidate built on an older `main` was rejected by git as non-fast-forward, and after a rebase its new commit was refused until its own check ran. The same repository was connected to a Railway test service with wait for CI on (`checkSuites: true` on the service's GitHub deploy trigger; the API name of the dashboard setting): a failing commit pushed straight to `main` by hand was never deployed, and a passing commit was held `WAITING` while its run was in progress and deployed once it passed. Both test resources were deleted afterwards.
