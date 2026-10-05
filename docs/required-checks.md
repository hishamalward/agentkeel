# Required checks before main moves

The hooks guard the agent, not the branch. A local pre-push hook can be skipped, and CI that runs
only after a push to `main` reports after the deploy has started. So the check that keeps `main`
green lives on the hosting side: the candidate commit is tested **before** `main` moves, the
protected branch refuses a commit whose check has not passed, and the deploy waits for it.

Passing checks are evidence, not a promise: they prove the tests the workflow runs passed on that
commit. A repository admin can still bypass the rule if the settings allow it (see the last
section).

## Two ways to hold main

| Setup | Who it stops | Needs |
|---|---|---|
| **Branch protection** requires `agentkeel-required` (below) | everyone, at GitHub | a public repository, or GitHub Pro/Team for a private one |
| **The agentkeel push gate** plus the deploy waiting for CI | every agent, before its push runs; the deploy for anyone | nothing paid |

GitHub Free has no branch protection or rulesets on private repositories (the API answers "Upgrade
to GitHub Pro or make this repository public to enable this feature"). There, use the push gate:
put `"require_check_before_push": "agentkeel-required"` in `agentkeel.json`, and an agent's push
or `gh pr merge` into a protected branch is refused unless that check passed on the exact commit
being shipped. A human can still push to `main` by hand, but with the deploy waiting for CI an
untested commit is not deployed. The gate asks GitHub through `gh`, using the check-runs API or,
for a token that cannot read checks, the Actions jobs of that commit; if it cannot get an answer,
it refuses.

Checked on 2026-10-04 in a private throwaway repository with the push gate and real Actions runs:
a candidate whose tests failed was refused (`'agentkeel-required' ended failure`), as was one
whose check had not run yet; a docs-only candidate skipped the app tests, passed the required
check, was allowed, and `main` moved to it; a green candidate built on an older `main` was
rejected by git as non-fast-forward, and after a rebase its new commit was refused until its
own check ran. The same repository was connected to a Railway test service with wait for CI on
(`checkSuites: true` on the service's GitHub deploy trigger; the API name of the dashboard
setting): a failing commit pushed straight to `main` by hand was never deployed, and a passing
commit was held `WAITING` while its run was in progress and deployed once it passed. Both test
resources were deleted afterwards.

## The shipping path

1. Push the task branch: `git push origin feat/<task>` (needs the `push` permission).
2. Wait for `agentkeel-required` to pass on that commit (`gh pr checks`, or
   `gh run watch` on the branch's run).
3. Move `main` to the same commit: fast-forward locally (needs `merge`) and push it (needs
   `push`), or merge the pull request (`gh pr merge`, needs both). Because the commit is the
   same, its passing check is already there and the protected branch accepts it.
4. The deploy starts only once the check on that commit is green.

A commit that never passed the check cannot reach `main` this way: GitHub refuses the push to a
protected branch whose required status checks have not passed on the pushed commit.

## Install

```bash
mkdir -p .github/workflows .github/agentkeel
cp agentkeel/templates/ci/required-checks.yml .github/workflows/agentkeel-checks.yml
cp agentkeel/templates/ci/select_checks.py .github/agentkeel/select_checks.py
```

Set the repository variables your app needs (Settings, Secrets and variables, Variables):
`AGENTKEEL_SETUP_COMMAND` (default `npm ci`) and `AGENTKEEL_TEST_COMMAND` (default `npm test`).
If the app is not a Node app, replace the `setup-node` step.

The workflow has three jobs. `select` decides from the changed paths whether the app tests run
(`templates/ci/select_checks.py`: Markdown, `docs/` and `design-exploration/` only means no app
tests; anything else, or anything it cannot read, means app tests). `app-tests` runs them.
`agentkeel-required` always reports: green when the tests passed or were not needed, red when they
failed or were cancelled. It is the only check to require, so a docs-only change is not blocked
waiting for a job that never ran.

## Protect the branch

With the GitHub CLI, after the workflow has run once (a check must exist before it can be
required):

```bash
gh api -X PUT repos/<owner>/<repo>/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["agentkeel-required"] },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```

`strict: true` is "require branches to be up to date before merging": a check that passed on an
older base is stale and does not count. `enforce_admins: true` applies the rule to admins too.
The same settings exist in the web UI (Settings, Branches) and as a repository ruleset.

## Make the deploy wait

The deploy must not start on a commit whose check has not passed.

- **Railway**: in the service's settings, enable waiting for GitHub check suites ("Wait for CI")
  for the GitHub-connected deploy (in the API: `deploymentTriggerUpdate` with
  `checkSuites: true`). Railway then holds the deploy of a pushed commit as `WAITING` until its
  checks finish, and does not deploy it if they fail (verified 2026-10-04).
- **Vercel, Netlify and others**: use their equivalent "wait for checks" or "ignored build step"
  setting, or deploy from CI after `agentkeel-required` passes instead of on push.

Check the setting in your provider's current documentation when you enable it; agentkeel does not
configure the host for you.

## What can still bypass it

| Bypass | Closed by |
|---|---|
| An admin pushing straight to `main` | `enforce_admins: true` (or a ruleset with no bypass actors) |
| A token or app on the bypass list of a ruleset | keep the bypass list empty |
| A deploy triggered by hand in the provider's dashboard or CLI (`railway up`) | the agent's `push` permission covers deploy commands; a human can still do it |
| Tests that do not cover the change | not a setting: write the test |
| A local pre-push hook | early feedback only; it can be skipped with `--no-verify` and is not part of this guarantee |
