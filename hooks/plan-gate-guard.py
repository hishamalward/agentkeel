#!/usr/bin/env python3
"""agentkeel plan-gate guard (PreToolUse, matcher Agent).

Invariant 3, every loop has a cap. A plan is gated ONCE: one plan reviewer and one scope auditor,
in parallel, before task 1. Re-gating the revised plan is what turned a control into a loop
feeding itself in practice: later rounds mostly found defects that earlier rounds' own revisions
had introduced, at roughly 1.2M subagent tokens before a line of code was written.

Prose could not stop that, because the session that wrote the prose is the one that drifted.
This runs in the harness before the dispatch and counts gate dispatches per plan file in
.claude/state/plan-gates.json. The allowance is 2 per plan (one round of two agents).

A dispatch counts as a plan gate when its prompt names a docs/plans/*.md file AND either carries
the marker `[plan-gate]` (deterministic, preferred) or reads like a review of that document
(heuristic: "gate a", "scope audit", "review the plan", "plan ... verdict"). Task reviews and the
whole-branch review name a diff or a review package, never just a plan, and are excluded.

The heuristic is a heuristic. A dispatch worded to avoid it will get through; the marker is the
honest path and the README says so. Exit 0 allows; exit 2 refuses; unparseable input allows.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

LIMIT = 2  # one round = one plan reviewer + one scope auditor
MARKER = "[plan-gate]"
PLAN_RE = re.compile(r"docs/plans/([A-Za-z0-9._-]+\.md)")
GATE_WORDS = re.compile(
    r"\bgate\s*[ab]\b|\bscope audit\b|\bplan review\b|\breview the plan\b"
    r"|\bre-review\b.{0,40}\bplan\b|\bplan\b.{0,40}\bverdict\b|\baudit\b.{0,30}\bplan\b",
    re.IGNORECASE | re.DOTALL,
)
EXCLUDE = re.compile(r"review-package|review-[0-9a-f]{7}\.\.|\.diff\b", re.IGNORECASE)


def state_path(payload, environ=os.environ):
    root = environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return os.path.join(root, ".claude", "state", "plan-gates.json")


def decide(payload, environ=os.environ):
    if payload.get("tool_name") != "Agent":
        return 0
    prompt = str((payload.get("tool_input") or {}).get("prompt", ""))
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

    path = state_path(payload, environ)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path) as fh:
            state = json.load(fh)
    except Exception:
        state = {}
    used = int(state.get(plan, 0))
    if used >= LIMIT:
        sys.stderr.write(
            f"PLAN GATE GUARD: refusing a further gate dispatch for {plan}.\n\n"
            f"That plan has already been gated ({used} gate agents recorded; the allowance is {LIMIT}:\n"
            "one round of a plan reviewer plus a scope auditor).\n\n"
            "Gate the plan ONCE, then execute. Re-gating a revised plan is what turned a control into\n"
            "a loop feeding itself. Dispatch the next task's implementer instead; the per-task review\n"
            "is the net for whatever the single gate missed.\n\n"
            f"If this is genuinely a plan that was never gated, the counter is wrong: remove the\n"
            f"\"{plan}\" key from {path} deliberately, then retry.\n"
        )
        return 2
    state[plan] = used + 1
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
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
                                 capture_output=True, env={**os.environ, "CLAUDE_PROJECT_DIR": tmp})
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
