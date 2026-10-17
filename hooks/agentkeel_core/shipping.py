"""Exact-commit PR/local shipping to a configured protected branch and retryable cleanup."""
import json
import os
import subprocess
import time
from pathlib import Path

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


def target_branch(primary, environ=os.environ):
    branch = git(primary, "symbolic-ref", "--short", "HEAD", environ=environ)
    if branch not in record.policy(primary)["protected"]:
        raise FinishError(f"canonical checkout branch {branch!r} is not configured as protected")
    return branch


def pr(rec, title, body_file, environ=os.environ):
    require(rec, "push")
    owned, sha = candidate(rec)
    if not os.path.isfile(body_file):
        raise FinishError("PR body file is missing")
    root, branch = owned["path"], owned["branch"]
    base = target_branch(owned["primary"], environ)
    git(root, "push", "origin", f"{sha}:refs/heads/{branch}", environ=environ)
    gh = environ.get("AGENTKEEL_GH", "gh")
    return run(root, [gh, "pr", "create", "--base", base, "--head", branch,
                      "--title", title, "--body-file", os.path.abspath(body_file)], environ)


def reviewed(root, number, sha, branch, environ, base="main", *, admin=False, allow_merged=False):
    gh = environ.get("AGENTKEEL_GH", "gh")
    slug = checks.github_slug(root, "origin")
    if not slug:
        raise FinishError("origin is not a GitHub repository")
    data = json.loads(run(root, [gh, "pr", "view", str(number), "--repo", slug, "--json",
                               "state,isDraft,headRefOid,headRefName,baseRefName,reviewDecision,statusCheckRollup,url,mergeCommit"], environ))
    merged = allow_merged and data.get("state") == "MERGED"
    if ((data.get("state") != "OPEN" and not merged) or data.get("isDraft") or data.get("headRefOid") != sha
            or data.get("headRefName") != branch or data.get("baseRefName") != base):
        raise FinishError(f"PR must be ready, open, based on {base}, and point to the exact tested task commit")
    accepted_reviews = ("", None, "APPROVED", "REVIEW_REQUIRED") if admin else ("", None, "APPROVED")
    if data.get("reviewDecision") == "CHANGES_REQUESTED" or (not merged and data.get("reviewDecision") not in accepted_reviews):
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
    return data


def sync_branch(primary, sha, branch, environ=os.environ):
    """Caller holds the common Git finish lock. No reset, stash, rebase, or checkout."""
    if git(primary, "symbolic-ref", "--short", "HEAD", environ=environ) != branch:
        raise FinishError(f"canonical checkout is not on {branch}; sync pending")
    if git(primary, "status", "--porcelain", "--untracked-files=all", environ=environ):
        raise FinishError(f"canonical {branch} is dirty; sync pending")
    gitdir = git(primary, "rev-parse", "--absolute-git-dir", environ=environ)
    if any(os.path.exists(os.path.join(gitdir, p)) for p in
           ("index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")):
        raise FinishError(f"canonical {branch} is busy; sync pending")
    # A preflight fetch detects an ahead-only local main that pull would otherwise call up-to-date.
    git(primary, "fetch", "--no-tags", "origin", branch, environ=environ)
    fetched = git(primary, "rev-parse", "FETCH_HEAD", environ=environ)
    git(primary, "merge-base", "--is-ancestor", "HEAD", fetched, environ=environ)
    git(primary, "pull", "--ff-only", "--no-rebase", "--no-autostash", "origin", branch, environ=environ)
    merged = git(primary, "rev-parse", "FETCH_HEAD", environ=environ)
    if git(primary, "rev-parse", "HEAD", environ=environ) != merged:
        raise FinishError(f"local {branch} does not match the commit fetched by pull; sync pending")
    git(primary, "merge-base", "--is-ancestor", sha, merged, environ=environ)
    return merged


def ship_local(rec, environ=os.environ):
    """Fast-forward the canonical checkout to this verified task commit without a remote."""
    require(rec, "merge")
    owned = workspace.validate(rec.get("workspace") or {})
    primary = owned["primary"]
    required_check = record.policy(primary)["require_check"]
    if required_check:
        raise FinishError(f"repository requires check {required_check!r}; use PR shipping")
    with record.locked(os.path.join(owned["common_dir"], "agentkeel-finish")):
        state = rec.setdefault("shipping", {})
        if state.get("mode") not in (None, "local"):
            raise FinishError("a different ship mode is already recorded for this task")
        if state.get("synced") and state.get("mode") != "local":
            raise FinishError("this task was already synchronized through a different ship mode")
        branch = target_branch(primary, environ)
        if state.get("target_branch") not in (None, branch):
            raise FinishError("canonical protected branch changed during local ship; resolve the recorded attempt first")
        if state.get("synced"):
            if state.get("target_branch") != branch:
                raise FinishError("canonical protected branch changed after local ship")
            return
        state["mode"] = "local"
        state["target_branch"] = branch
        if not state.get("sha"):
            _, sha = candidate(rec)
            state["sha"] = sha
            record.save(rec, environ)
        else:
            _, current = candidate(rec)
            if current != state["sha"]:
                raise FinishError("candidate changed; existing local ship attempt must be resolved before shipping another commit")
        sha = state["sha"]
        rec["lifecycle"] = "sync_pending"
        record.save(rec, environ)
        if git(primary, "status", "--porcelain", "--untracked-files=all", environ=environ):
            raise FinishError("canonical protected checkout is dirty; local ship sync pending")
        gitdir = git(primary, "rev-parse", "--absolute-git-dir", environ=environ)
        if any(os.path.exists(os.path.join(gitdir, p)) for p in
               ("index.lock", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")):
            raise FinishError("canonical protected checkout is busy; local ship sync pending")
        head = git(primary, "rev-parse", "HEAD", environ=environ)
        included = subprocess.run(["git", "-c", "core.fsmonitor=false", "merge-base", "--is-ancestor", sha, head],
                                  cwd=primary, capture_output=True, env=environ).returncode == 0
        if not included:
            ancestor = subprocess.run(["git", "-c", "core.fsmonitor=false", "merge-base", "--is-ancestor", head, sha],
                                      cwd=primary, capture_output=True, env=environ).returncode == 0
            if not ancestor:
                raise FinishError("candidate is not a fast-forward of the canonical protected checkout; local ship pending")
            if git(primary, "symbolic-ref", "--short", "HEAD", environ=environ) != branch:
                raise FinishError("canonical protected branch changed during local ship; sync pending")
            git(primary, "merge", "--no-autostash", "--ff-only", sha, environ=environ)
        if git(primary, "symbolic-ref", "--short", "HEAD", environ=environ) != branch:
            raise FinishError("canonical protected branch changed during local ship; sync pending")
        final = git(primary, "rev-parse", "HEAD", environ=environ)
        git(primary, "merge-base", "--is-ancestor", sha, final, environ=environ)
        state.update(target_sha=final, synced=True)
        rec.update(lifecycle="cleanup_pending", outcome_at=time.time())
        record.save(rec, environ)


def ship(rec, number, environ=os.environ, *, admin=False):
    require(rec, "merge", "push")
    owned = workspace.validate(rec.get("workspace") or {})
    primary, root = owned["primary"], owned["path"]
    with record.locked(os.path.join(owned["common_dir"], "agentkeel-finish")):
        state = rec.setdefault("shipping", {})
        if state.get("mode") not in (None, "pr"):
            raise FinishError("a different ship mode is already recorded for this task")
        if state.get("synced"):
            return
        base = target_branch(primary, environ)
        if state.get("target_branch") not in (None, base):
            raise FinishError("canonical protected branch changed during ship; resolve the recorded attempt first")
        state["target_branch"] = base
        slug = checks.github_slug(root, "origin")
        if not slug or state.get("repo") not in (None, slug):
            raise FinishError("GitHub origin is unavailable or changed during ship")
        if not state.get("sha"):
            owned, sha = candidate(rec)
            data = reviewed(root, number, sha, owned["branch"], environ, base,
                            admin=admin, allow_merged=True)
            state.update(mode="pr", sha=sha, pr=number, url=data["url"], repo=slug)
            record.save(rec, environ)
        sha = state["sha"]
        if number != state["pr"]:
            raise FinishError("retry the recorded PR, not a different PR")
        if not state.get("pushed"):
            data = reviewed(root, number, sha, owned["branch"], environ, base,
                            admin=admin, allow_merged=True)
            if data["state"] == "OPEN":
                _, current = candidate(rec)
                if current != sha:
                    raise FinishError("candidate changed; existing ship attempt must be resolved before shipping another commit")
                git(root, "fetch", "--no-tags", "origin", base, environ=environ)
                remote = git(root, "rev-parse", "FETCH_HEAD", environ=environ)
                git(root, "merge-base", "--is-ancestor", remote, sha, environ=environ)
                gh = environ.get("AGENTKEEL_GH", "gh")
                argv = [gh, "pr", "merge", str(number), "--repo", slug,
                        "--merge", "--match-head-commit", sha]
                if admin:
                    argv.append("--admin")
                run(root, argv, environ)
                data = reviewed(root, number, sha, owned["branch"], environ, base,
                                admin=admin, allow_merged=True)
            if data["state"] != "MERGED":
                raise FinishError("PR merge is pending; retry ship after GitHub confirms it merged")
            merged = (data.get("mergeCommit") or {}).get("oid")
            if not isinstance(merged, str) or len(merged) != 40 or any(c not in "0123456789abcdef" for c in merged):
                raise FinishError("merged PR has no verifiable merge commit")
            git(root, "fetch", "--no-tags", "origin", base, environ=environ)
            remote = git(root, "rev-parse", "FETCH_HEAD", environ=environ)
            git(root, "merge-base", "--is-ancestor", sha, merged, environ=environ)
            git(root, "merge-base", "--is-ancestor", merged, remote, environ=environ)
            state.update(pushed=True, merge_sha=merged)
            rec.update(lifecycle="sync_pending", outcome_at=time.time())
            record.save(rec, environ)
        try:
            state["main_sha"] = sync_branch(primary, sha, base, environ)
        except FinishError:
            rec["lifecycle"] = "sync_pending"
            record.save(rec, environ)
            raise
        state["synced"] = True
        rec.update(lifecycle="cleanup_pending", outcome_at=time.time())
        record.save(rec, environ)


def finish(rec, environ=os.environ, keep=False, discard_ignored=False):
    if rec.get("worktrees"):
        if not rec.get("shipping", {}).get("synced"):
            raise FinishError("ship and synchronize the canonical protected branch before cleanup")
        html(rec)
        if keep:
            rec["lifecycle"] = "retained"
            record.save(rec, environ)
            return
        owned = rec.get("workspace")
        if not owned:
            raise FinishError("legacy worktree has no ownership manifest; preserve it for explicit migration")
        preserved = {}
        if rec.get("report_root") and not owned.get("retain_on_finish"):
            for key in ("deliverable", "spec"):
                if not rec.get(key):
                    continue
                relative = os.path.relpath(rec[key], owned["path"])
                target = delivery.report_path(owned["primary"], relative)
                git(owned["primary"], "ls-files", "--error-unmatch", "--", relative)
                if not os.path.isfile(target) or Path(target).read_bytes() != Path(rec[key]).read_bytes():
                    raise FinishError("task page is not preserved unchanged in canonical main: " + relative)
                preserved[key] = target
        workspace.prepare_release(owned)
        runtime = os.path.join(owned["gitdir"], "agent-runtime.json")
        if os.path.lexists(runtime):
            # One optional executable boundary; no access to Slots' private records.
            slots = environ.get("AGENTKEEL_SLOTS", "agent-slots")
            run(owned["primary"], [slots, "release", "--worktree", owned["path"]], environ)
        if owned.get("retain_on_finish"):
            rec["workspace"] = workspace.retain(owned)
        else:
            workspace.release(owned, discard_ignored=discard_ignored)
        rec["worktrees"] = []
        if rec.get("report_root"):
            rec.update(preserved)
            if preserved:
                rec["report_root"] = os.path.join(owned["primary"], "doc")
                rec["write_roots"] = [rec["report_root"]]
            rec["html_checkpoint"] = delivery.checkpoint(rec)
            rec["lifecycle"] = "complete"
            record.save(rec, environ)
            return
        rec.update(lifecycle="report_pending", outcome_at=time.time())
        record.save(rec, environ)
    html(rec)
    rec["html_checkpoint"] = delivery.checkpoint(rec)
    rec["lifecycle"] = "complete"
    record.save(rec, environ)
