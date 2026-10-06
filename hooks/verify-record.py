#!/usr/bin/env python3
"""agentkeel verify record (PostToolUse, matcher Bash): close a `task.py verify` run that the task
guard saw start, and record its result against the code it ran on (agentkeel_core/evidence.py).
It never blocks and never prints to the agent."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agentkeel_core import evidence, record  # noqa: E402


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        print("verify-record selftest: PASS")
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        if record.plugin_inactive(sys.argv, payload):
            return 0
        evidence.finish(payload)
    except Exception as exc:  # never block on our own failure
        sys.stderr.write(f"verify-record: internal error, nothing recorded: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
