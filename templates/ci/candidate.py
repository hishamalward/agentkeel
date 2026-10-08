#!/usr/bin/env python3
"""Bind CI to a PR head, or reuse that head's successful PR run after a fast-forward.

Run from the checked-out candidate. GitHub API uncertainty means run tests, never skip them.
Only a run of this workflow with the explicit head-binding step can supply reusable evidence.
"""
import json
import os
import re
import subprocess
import sys

from select_checks import changed, needs_app, DEFAULT_DOCS


def git(*args):
    return subprocess.check_output(["git", *args], text=True, stderr=subprocess.PIPE).strip()


def api(path):
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError("GitHub evidence lookup failed")
    return json.loads(result.stdout)


def reusable_run(repo, sha, workflow, query=api):
    """Return a successful run id, or None. Do not fall back to an older green attempt."""
    data = query(f"repos/{repo}/actions/workflows/{workflow}/runs?event=pull_request&head_sha={sha}&per_page=100")
    runs = [r for r in data["workflow_runs"]
            if r.get("event") == "pull_request" and r.get("head_sha") == sha
            and r.get("path") == f".github/workflows/{workflow}"
            and r.get("head_repository", {}).get("full_name") == repo]
    if not runs:
        return None
    latest = max(runs, key=lambda r: (r["run_number"], r.get("run_attempt", 1)))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        return None
    run_id, attempt = int(latest["id"]), int(latest["run_attempt"])
    jobs = query(f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")["jobs"]
    required = [j for j in jobs if j.get("name") == "agentkeel-required"]
    binding = [j for j in jobs if j.get("name") == "select"]
    if len(required) != 1 or len(binding) != 1:
        return None
    if any(j.get("status") != "completed" or j.get("conclusion") != "success"
           for j in required + binding):
        return None
    if not any(s.get("name") == "Bind tested commit" and s.get("conclusion") == "success"
               for s in binding[0].get("steps", [])):
        return None
    return run_id


def candidate(event, payload, environ):
    default = payload["repository"]["default_branch"]
    if event == "pull_request":
        pr = payload["pull_request"]
        if pr["draft"] or pr["base"]["ref"] != default:
            raise ValueError("only ready PRs targeting the default branch are merge candidates")
        sha = pr["head"]["sha"]
        # Use fetched main, not the base recorded when the event was queued.
        base = git("rev-parse", f"refs/remotes/origin/{default}")
    elif event == "push" and environ["GITHUB_REF"] == f"refs/heads/{default}":
        sha, base = environ["GITHUB_SHA"], payload["before"]
    else:
        raise ValueError("backup branch pushes are not CI candidates")
    if not all(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", x) and set(x) != {"0"} for x in (sha, base)):
        raise ValueError("candidate and base must be full commit ids")
    if git("rev-parse", "HEAD") != sha:
        raise ValueError("checkout is not the exact candidate commit")
    git("merge-base", "--is-ancestor", base, sha)
    return sha, base


def main(environ=os.environ):
    try:
        with open(environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
            payload = json.load(fh)
        event = environ["GITHUB_EVENT_NAME"]
        sha, base = candidate(event, payload, environ)
        reused = None
        if event == "push":
            try:
                workflow = environ["GITHUB_WORKFLOW_REF"].split("@", 1)[0].rsplit("/", 1)[1]
                reused = reusable_run(environ["GITHUB_REPOSITORY"], sha, workflow)
            except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
                print("CI evidence unavailable; running checks on main.", file=sys.stderr)
        globs = [g for g in environ.get("AGENTKEEL_DOCS_GLOBS", "").split(":") if g] or DEFAULT_DOCS
        app = needs_app(changed(base, sha, since=base), globs)
        print(f"sha={sha}\nbase={base}\napp={str(app).lower()}\nreuse={str(reused is not None).lower()}")
        if reused is not None:
            print(f"Reusing successful PR run {reused} for {sha}; app tests will not repeat.", file=sys.stderr)
        return 0
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Cannot bind CI candidate ({type(exc).__name__}). Fetch main, rebase if needed, and update the PR.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
