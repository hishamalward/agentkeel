"""agentkeel core: ask the hosting side whether a commit's required check passed.

Used by the push gate: when a repository's agentkeel.json names a required check
(`"require_check_before_push": "agentkeel-required"`), an agent's push or PR merge into a
protected branch needs that check to have passed on the exact commit being shipped (a PR merge is
refused: GitHub writes a new, unchecked commit for it). Git refuses a
non-fast-forward push and the guard refuses a force push, so a pushed commit already contains the
branch it lands on: a green check on that commit is a check on what main becomes.

It asks GitHub through the `gh` CLI (AGENTKEEL_GH names another binary): the check-runs API, or,
for a token that may read Actions but not Checks, the jobs of the commit's workflow runs. When the answer cannot be
had (no gh, no network, not a GitHub remote), the result says so and the guard refuses: an
unverifiable ship is not a verified one.
"""
import json
import os
import re
import subprocess

GH_URL_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$")


def _run(cmd, cwd, timeout=20):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if out.returncode != 0:
        return None, (out.stderr or out.stdout).strip()[:200]
    return out.stdout.strip(), ""


def github_slug(root, remote):
    url, _ = _run(["git", "remote", "get-url", remote or "origin"], root)
    m = GH_URL_RE.search(url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _check_runs(gh, slug, sha, name, root):
    out, err = _run([gh, "api", f"repos/{slug}/commits/{sha}/check-runs?per_page=100"], root)
    if out is None:
        return None, err
    try:
        return [{"status": r.get("status"), "conclusion": r.get("conclusion"), "started_at": r.get("started_at")}
                for r in json.loads(out).get("check_runs", []) if r.get("name") == name], ""
    except ValueError:
        return None, "GitHub's answer was not JSON"


def _action_jobs(gh, slug, sha, name, root):
    """The same answer through the Actions API, for tokens that may read Actions but not Checks."""
    out, err = _run([gh, "api", f"repos/{slug}/actions/runs?head_sha={sha}&per_page=50"], root)
    if out is None:
        return None, err
    try:
        runs = json.loads(out).get("workflow_runs", [])
    except ValueError:
        return None, "GitHub's answer was not JSON"
    jobs = []
    for run in runs:
        jout, jerr = _run([gh, "api", f"repos/{slug}/actions/runs/{run['id']}/jobs?per_page=100"], root)
        if jout is None:
            return None, jerr
        try:
            jobs += [{"status": j.get("status"), "conclusion": j.get("conclusion"), "started_at": j.get("started_at")}
                     for j in json.loads(jout).get("jobs", []) if j.get("name") == name]
        except ValueError:
            return None, "GitHub's answer was not JSON"
    return jobs, ""


def conclusion(root, remote, sha, name, environ=os.environ):
    """(state, detail). state is 'success', 'failure', 'pending', 'missing' or 'unknown'."""
    slug = github_slug(root, remote)
    if not slug:
        return "unknown", f"remote '{remote or 'origin'}' is not a GitHub repository"
    gh = environ.get("AGENTKEEL_GH") or "gh"
    runs, err = _check_runs(gh, slug, sha, name, root)
    if runs is None:
        runs, err2 = _action_jobs(gh, slug, sha, name, root)
        if runs is None:
            return "unknown", f"could not ask GitHub ({err or err2 or 'no output'})"
    if not runs:
        return "missing", f"no '{name}' check has run on {sha[:12]}"
    latest = max(runs, key=lambda r: r.get("started_at") or "")
    if latest.get("status") != "completed":
        return "pending", f"'{name}' is still {latest.get('status')} on {sha[:12]}"
    if latest.get("conclusion") == "success":
        return "success", f"'{name}' passed on {sha[:12]}"
    return "failure", f"'{name}' ended {latest.get('conclusion')} on {sha[:12]}"

