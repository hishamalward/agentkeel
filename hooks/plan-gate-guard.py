#!/usr/bin/env python3
"""agentkeel plan-gate guard (PreToolUse; Claude Code matcher Agent, Codex matcher spawn_agent).

Invariant 3, every loop has a cap. A plan is gated ONCE: one plan reviewer and one scope auditor,
in parallel, before task 1. Re-gating the revised plan is what turned a control into a loop
feeding itself in practice: later rounds mostly found defects that earlier rounds' own revisions
had introduced, at roughly 1.2M subagent tokens before a line of code was written.

Prose could not stop that, because the session that wrote the prose is the one that drifted.
This runs in the harness before the dispatch and counts gate dispatches per plan file in
AGENTKEEL_HOME/plan-gates.json (default ~/.agentkeel), keyed by repository so every worktree of
one repository shares the count, under a file lock so two parallel dispatches cannot both read
the old count. The allowance is 2 per plan (one round of two agents).

A dispatch counts as a plan gate when its prompt names a docs/plans/*.md file AND either carries
the marker `[plan-gate]` (deterministic, preferred) or reads like a review of that document
(heuristic: "gate a", "scope audit", "review the plan", "plan ... verdict"). Task reviews and the
whole-branch review name a diff or a review package, never just a plan, and are excluded.

Codex encrypts a spawn_agent message before hooks see it, so there the gate is named in the
task name instead: a task_name starting with `plan_gate` (or `plan-gate`) counts, and the count is
kept per task (this session's task record) because the plan file is not visible.

The heuristic is a heuristic. A dispatch worded to avoid it will get through; the marker is the
honest path and the README says so. Exit 0 allows; exit 2 refuses; unparseable input allows.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import gitops, host, record  # noqa: E402

NAME_MARKER_RE = re.compile(r"^plan[_-]gate", re.IGNORECASE)

LIMIT = 2  # one round = one plan reviewer + one scope auditor
MARKER = "[plan-gate]"
PLAN_RE = re.compile(r"docs/plans/([A-Za-z0-9._-]+\.md)")
GATE_WORDS = re.compile(
    r"\bgate\s*[ab]\b|\bscope audit\b|\bplan review\b|\breview the plan\b"
    r"|\bre-review\b.{0,40}\bplan\b|\bplan\b.{0,40}\bverdict\b|\baudit\b.{0,30}\bplan\b",
    re.IGNORECASE | re.DOTALL,
)
EXCLUDE = re.compile(r"review-package|review-[0-9a-f]{7}\.\.|\.diff\b", re.IGNORECASE)


def state_path(environ=os.environ):
    return os.path.join(record.home(environ), "plan-gates.json")


def repo_key(payload, environ=os.environ):
    cwd = payload.get("cwd") or environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return gitops.common_dir(cwd) or os.path.realpath(cwd)


def decide(payload, environ=os.environ):
    cwd = payload.get("cwd") or os.getcwd()
    dispatches = [e for e in host.events(payload, cwd) if e.kind == "dispatch"]
    if not dispatches:
        return 0
    ev = dispatches[0]
    if ev.tool.endswith("spawn_agent"):
        if not NAME_MARKER_RE.match(ev.name):
            return 0
        rec = record.load(payload.get("session_id"), environ)
        plan = f"task:{rec['task']}" if rec else f"session:{payload.get('session_id')}"
        path = state_path(environ)
        with record.locked(path):
            return count(path, f"{repo_key(payload, environ)}::{plan}", plan)
    prompt = ev.prompt
    if not prompt:
        return 0
    marked = MARKER in prompt
    if not marked and EXCLUDE.search(prompt):
        return 0
    plans = PLAN_RE.findall(prompt)
    if not plans:
        return 0
    if not marked and not GATE_WORDS.search(prompt):
        return 0
    plan = sorted(set(plans))[0]
    path = state_path(environ)
    key = f"{repo_key(payload, environ)}::{plan}"
    with record.locked(path):
        return count(path, key, plan)


def count(path, key, plan):
    try:
        with open(path) as fh:
            state = json.load(fh)
    except Exception:
        state = {}
    used = int(state.get(key, 0))
    if used >= LIMIT:
        sys.stderr.write(
            f"PLAN GATE GUARD: refusing a further gate dispatch for {plan}.\n\n"
            f"That plan has already been gated ({used} gate agents recorded; the allowance is {LIMIT}:\n"
            "one round of a plan reviewer plus a scope auditor).\n\n"
            "Gate the plan ONCE, then execute. Re-gating a revised plan is what turned a control into\n"
            "a loop feeding itself. Dispatch the next task's implementer instead; the per-task review\n"
            "is the net for whatever the single gate missed.\n\n"
            "If this is genuinely a plan that was never gated, the counter is wrong: tell the human,\n"
            f"who can remove the \"{key}\" key from {path}.\n"
        )
        return 2
    state[key] = used + 1
    record.atomic_write_json(path, state)
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        return selftest()
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
    except Exception:
        return 0
    if record.plugin_inactive(sys.argv, payload):
        return 0
    try:
        return decide(payload)
    except Exception as exc:
        sys.stderr.write(f"plan-gate-guard: internal error, allowing: {exc}\n")
        return 0


def selftest():
    here = os.path.abspath(__file__)
    with tempfile.TemporaryDirectory() as tmp:
        def run(prompt, expect):
            payload = {"tool_name": "Agent", "cwd": tmp, "tool_input": {"prompt": prompt}}
            out = subprocess.run([sys.executable, here], input=json.dumps(payload), text=True,
                                 capture_output=True, env={**os.environ, "AGENTKEEL_HOME": tmp})
            ok = out.returncode == expect
            print(("PASS" if ok else "FAIL"), repr(prompt[:50]), "->", out.returncode)
            return ok
        gate = "[plan-gate] Review the plan docs/plans/json-flag-plan.md"
        results = [run(gate, 0), run(gate, 0), run(gate, 2),
                   run("Implement task 3 of docs/plans/json-flag-plan.md", 0),
                   run("Review the plan docs/plans/json-flag-plan.md against review-package-3.md", 0)]
    print("plan-gate-guard selftest:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
