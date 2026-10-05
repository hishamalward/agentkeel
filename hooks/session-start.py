#!/usr/bin/env python3
"""agentkeel session start (SessionStart): tell the agent how to declare its task.

When agentkeel arrives as a plugin, its scripts live in the plugin folder, not in the repository,
so the instruction file cannot name them. This prints, as context for the session, the one
command the agent needs, with this install's real path. With --plugin it prints only in
repositories that opted in with agentkeel.json. It never blocks.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import record  # noqa: E402


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        print("session-start selftest: PASS")
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    if record.plugin_inactive(sys.argv, payload):
        return 0
    task = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task.py")
    print("agentkeel is active in this repository. Before your first write, declare the task from\n"
          "your reading of the request, state that reading in your first update, and proceed:\n"
          f'  python3 "{task}" start <task-id> --size small|medium|large --allow <permissions>\n'
          "Permissions: review, implement, merge, push, distribution-build, store-submission, paid-job.\n"
          "Code changes happen in the task's own worktree (git worktree add ../<repo>-<task> -b feat/<task>).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
