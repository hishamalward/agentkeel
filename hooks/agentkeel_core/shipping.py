"""Exact-commit PR shipping, canonical-main synchronization, and retryable cleanup."""
import json
import os
import subprocess
import time

from . import checks, delivery, evidence, gitops, record, workspace


class FinishError(ValueError):
    pass


def run(root, argv, environ):
    try:
        out = subprocess.run(argv, cwd=root, env=environ, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FinishError(str(exc)) from exc
    if out.returncode:
        raise FinishError((out.stderr or out.stdout).strip()[:1000] or "command failed")
    return out.stdout.strip()


def git(root, *args, environ=os.environ):
    return run(root, ["git", "-c", "core.fsmonitor=false", *args], environ)


def require(rec, *permissions):
    missing = set(permissions) - set(rec.get("permissions", []))
    if missing:
        raise FinishError("task lacks permission: " + ", ".join(sorted(missing)))


def html(rec):
    problems = delivery.problems(rec)
    if problems:
        raise FinishError("HTML pending: " + "; ".join(problems))


def candidate(rec):
    if not rec.get("workspace"):
        raise FinishError("this task has no Keel-owned linked worktree")
    owned = workspace.validate(rec["workspace"])
    root = owned["path"]
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise FinishError("commit or preserve worktree changes before shipping")
    sha, tree = evidence.code_state(root)
    if not sha or not any(e.get("result") == "passed" and (e.get("head"), e.get("tree")) == (sha, tree)
                          for e in rec.get("evidence", [])):
        raise FinishError("run task.py verify on this exact committed code before shipping")
    html(rec)
    return owned, sha


def pr(rec, title, body_file, environ=os.environ):
    require(rec, "push")
    owned, sha = candidate(rec)
    if not os.path.isfile(body_file):
        raise FinishError("PR body file is missing")
    root, branch = owned["path"], owned["branch"]
    git(root, "push", "origin", f"{sha}:refs/heads/{branch}", environ=environ)
    gh = environ.get("AGENTKEEL_GH", "gh")
    return run(root, [gh, "pr", "create", "--base", "main", "--head", branch,
                      "--title", title, "--body-file", os.path.abspath(body_file)], environ)


def reviewed(root, number, sha, branch, environ):
    gh = environ.get("AGENTKEEL_GH", "gh")
    data = json.loads(run(root, [gh, "pr", "view", str(number), "--json",
                               "state,isDraft,headRefOid,headRefName,baseRefName,reviewDecision,statusCheckRollup,url"], environ))
    if (data.get("state") != "OPEN" or data.get("isDraft") or data.get("headRefOid") != sha
            or data.get("headRefName") != branch or data.get("baseRefName") != "main"):
        raise FinishError("PR must be ready, open, based on main, and point to the exact tested task commit")
    if data.get("reviewDecision") not in ("", None, "APPROVED"):
        raise FinishError("PR review is pending or changes were requested")
    jobs = data.get("statusCheckRollup")
    if not isinstance(jobs, list) or not jobs:
        raise FinishError("PR has no verifiable checks; configure and run the repository's checks first")
    passed = False
    for job in jobs:
        if job.get("__typename") == "StatusContext":
            good = job.get("state") == "SUCCESS"
            passed = passed or good
        else:
            good = job.get("status") == "COMPLETED" and job.get("conclusion") in ("SUCCESS", "SKIPPED", "NEUTRAL")
            passed = passed or (good and job.get("conclusion") == "SUCCESS")
        if not good:
            raise FinishError("PR checks are pending or failed")
    if not passed:
        raise FinishError("PR has no successful check; skipped or neutral jobs alone do not verify a commit")
    required = record.policy(root)["require_check"]
    if required:
        state, detail = checks.conclusion(root, "origin", sha, required, environ)
        if state != "success":
            raise FinishError(detail)
    return data["url"]


def sync_main(primary, sha, environ=os.environ):
    """Caller holds the common Git finish lock. No reset, stash, rebase, or checkout."""
    if git(primary, "symbolic-ref", "--short", "HEAD", environ=environ) != "main":
        raise FinishError("canonical checkout is not on main; local-main sync pending")
    if git(primary, "status", "--porcelain", "--untracked-files=all", environ=environ):
        raise FinishError("canonical main is dirty; local-main sync pending")
    gitdir = git(primary, "rev-parse", "--absolute-git-dir", environ=environ)
    if any(os.path.exists(os.path.join(gitdir, p)) for p in
           ("index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")):
        raise FinishError("canonical main is busy; local-main sync pending")
    # A preflight fetch detects an ahead-only local main that pull would otherwise call up-to-date.
    git(primary, "fetch", "--no-tags", "origin", "main", environ=environ)
    fetched = git(primary, "rev-parse", "FETCH_HEAD", environ=environ)
    git(primary, "merge-base", "--is-ancestor", "HEAD", fetched, environ=environ)
    git(primary, "pull", "--ff-only", "--no-rebase", "--no-autostash", "origin", "main", environ=environ)
    merged = git(primary, "rev-parse", "FETCH_HEAD", environ=environ)
    if git(primary, "rev-parse", "HEAD", environ=environ) != merged:
        raise FinishError("local main does not match the commit fetched by pull; sync pending")
    git(primary, "merge-base", "--is-ancestor", sha, merged, environ=environ)
    return merged


def ship(rec, number, environ=os.environ):
    require(rec, "merge", "push")
    owned = workspace.validate(rec.get("workspace") or {})
    primary, root = owned["primary"], owned["path"]
    with record.locked(os.path.join(owned["common_dir"], "agentkeel-finish")):
        state = rec.setdefault("shipping", {})
        if state.get("synced"):
            return
        if not state.get("sha"):
            owned, sha = candidate(rec)
            url = reviewed(root, number, sha, owned["branch"], environ)
            state.update(sha=sha, pr=number, url=url)
            record.save(rec, environ)
        sha = state["sha"]
        if number != state["pr"]:
            raise FinishError("retry the recorded PR, not a different PR")
        if not state.get("pushed"):
            git(root, "fetch", "--no-tags", "origin", "main", environ=environ)
            remote = git(root, "rev-parse", "FETCH_HEAD", environ=environ)
            already = subprocess.run(["git", "merge-base", "--is-ancestor", sha, remote], cwd=root,
                                     capture_output=True, env=environ).returncode == 0
            if not already:
                _, current = candidate(rec)
                if current != sha:
                    raise FinishError("candidate changed; existing ship attempt must be resolved before shipping another commit")
                reviewed(root, number, sha, owned["branch"], environ)
                git(root, "merge-base", "--is-ancestor", remote, sha, environ=environ)
                git(root, "push", "origin", f"{sha}:refs/heads/main", environ=environ)
            state["pushed"] = True
            rec.update(lifecycle="sync_pending", outcome_at=time.time())
            record.save(rec, environ)
        try:
            state["main_sha"] = sync_main(primary, sha, environ)
        except FinishError:
            rec["lifecycle"] = "sync_pending"
            record.save(rec, environ)
            raise
        state["synced"] = True
        rec.update(lifecycle="cleanup_pending", outcome_at=time.time())
        record.save(rec, environ)


def finish(rec, environ=os.environ, keep=False):
    if rec.get("worktrees"):
        if not rec.get("shipping", {}).get("synced"):
            raise FinishError("ship and synchronize canonical main before cleanup")
        html(rec)
        if keep:
            rec["lifecycle"] = "retained"
            record.save(rec, environ)
            return
        owned = rec.get("workspace")
        if not owned:
            raise FinishError("legacy worktree has no ownership manifest; preserve it for explicit migration")
        workspace.prepare_release(owned)
        runtime = os.path.join(owned["gitdir"], "agent-runtime.json")
        if os.path.lexists(runtime):
            # One optional executable boundary; no access to Slots' private records.
            slots = environ.get("AGENTKEEL_SLOTS", "agent-slots")
            run(owned["primary"], [slots, "release", "--worktree", owned["path"]], environ)
        workspace.release(owned)
        rec["worktrees"] = []
        rec.update(lifecycle="report_pending", outcome_at=time.time())
        record.save(rec, environ)
    html(rec)
    rec["html_checkpoint"] = delivery.checkpoint(rec)
    rec["lifecycle"] = "complete"
    record.save(rec, environ)
