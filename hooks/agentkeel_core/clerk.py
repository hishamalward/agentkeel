"""Fail-closed subprocess bridge to MCPClerk's frozen judge protocol."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping


SAFE_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
TIMEOUT_SECONDS = 8


class ClerkError(ValueError):
    """MCPClerk could not return one valid decision."""


def _executable(environ: Mapping[str, str]) -> str:
    override = environ.get("AGENTKEEL_MCPCLERK")
    if override:
        if os.path.isabs(override) and os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        raise ClerkError("MCP policy check unavailable; refusing this MCP call.")
    home = environ.get("HOME")
    if home:
        local = str(Path(home) / ".local" / "bin" / "mcpclerk")
        if os.path.isabs(local) and os.path.isfile(local) and os.access(local, os.X_OK):
            return local
    executable = shutil.which("mcpclerk", path=SAFE_PATH)
    if executable and os.path.isabs(executable) and os.access(executable, os.X_OK):
        return executable
    raise ClerkError("MCP policy check unavailable; refusing this MCP call.")


def _child_env(environ: Mapping[str, str]) -> dict[str, str]:
    result = {"PATH": SAFE_PATH}
    for key in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR", "MCPCLERK_HOME"):
        value = environ.get(key)
        if value is not None:
            result[key] = value
    return result


def has_legacy_policy(cwd: str, environ: Mapping[str, str]) -> bool:
    """Detect old AgentKeel MCP policy locations without interpreting their rules."""
    project = Path(cwd).resolve()
    if not project.is_dir():
        project = project.parent
    for folder in (project, *project.parents):
        legacy = folder / "agentkeel.json"
        if not legacy.is_file():
            continue
        try:
            value = json.loads(legacy.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return True
        if isinstance(value, dict) and ("mcp" in value or
                isinstance(value.get("guards"), dict) and "mcp_unknown" in value["guards"]):
            return True
    home = Path(environ.get("AGENTKEEL_HOME") or
                (Path(environ.get("HOME") or Path.home()) / ".agentkeel")).expanduser()
    return (home / "mcp_catalog.json").exists()


def judge(tool: str, args: dict[str, Any], host: str, cwd: str, project_dir: str | None,
          permissions: list[str], environ: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Run exactly one MCPClerk judge request; never expose child output on failure."""
    payload = {"version": 1, "tool": tool, "args": args, "host": host, "cwd": cwd,
               "project_dir": project_dir, "task": {"permissions": permissions}}
    try:
        result = subprocess.run([_executable(environ), "judge"], input=json.dumps(payload),
                                text=True, capture_output=True, timeout=TIMEOUT_SECONDS,
                                env=_child_env(environ), check=False)
        if result.returncode != 0:
            raise ClerkError("MCP policy check failed; refusing this MCP call.")
        decision = json.loads(result.stdout)
        if (not isinstance(decision, dict) or set(decision) != {"allowed", "reason", "classification"}
                or not isinstance(decision["allowed"], bool)
                or not isinstance(decision["reason"], str)
                or not isinstance(decision["classification"], str)):
            raise ClerkError("MCP policy check failed; refusing this MCP call.")
        return decision
    except ClerkError:
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        raise ClerkError("MCP policy check failed; refusing this MCP call.") from None
