"""Compute code state around task.py verify without running repository config hooks."""
from . import repostate

KEEP = 20


def code_state(cwd):
    """(HEAD, working tree id including untracked files), or unknown when it cannot be read."""
    try:
        return repostate.state(cwd)
    except repostate.InspectError:
        return None, None


def host_of(payload):
    return "codex" if "turn_id" in payload else "claude"
