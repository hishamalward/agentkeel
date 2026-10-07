"""agentkeel MCP connections: which project a host's connection is pinned to, read from the host's own configuration.

PostHog's MCP server acts on one active project per connection and its tools do not name it. The
server documents one way to fix that project: the entry's URL carries `?project_id=<id>`, or its
headers carry `x-posthog-project-id: <id>`, and the pinned connection no longer offers the switch
tools. The adapter (mcp.py) treats a pinned connection as the call's target, so a write passes
only when the host's entry for the server that made the call is pinned to a listed project.

This reads the entry the host itself uses, never a claim in the call:
- Claude Code: `mcp__<server>__<tool>` resolves in the host's order, the project's own entry
  (~/.claude.json, projects.<cwd>.mcpServers), then <cwd>/.mcp.json, then the user's
  (~/.claude.json, mcpServers). `mcp__plugin_<plugin>_<server>__<tool>` is the plugin's own
  .mcp.json under its install path (installed_plugins.json). A `${VAR}` in a header expands from
  the hook's environment, as the host expands it.
- Codex: [mcp_servers.<server>] in ~/.codex/config.toml: url, http_headers and env_http_headers
  (a header whose value is the name of an environment variable).
A pin counts only for an entry whose URL is on posthog.com. Anything unreadable is "not pinned":
the adapter then refuses the write and says how to pin, never guesses.
"""
import json
import os
import re
from urllib.parse import parse_qs, urlsplit

from . import hostcheck

HEADER = "x-posthog-project-id"
QUERY = "project_id"
PLUGIN_RE = re.compile(r"^plugin_([^_]+)_(.+)$")


def _json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _expand(value, environ):
    """${VAR} and ${VAR:-default} as the hosts expand them in a server entry."""
    def one(m):
        name, default = m.group(1), m.group(2)
        return environ.get(name) if environ.get(name) is not None else (default or "")
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}", one, str(value))


def _pin_of(url, headers, environ):
    """The project id an entry pins, or None."""
    url = _expand(url or "", environ)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not (host == "posthog.com" or host.endswith(".posthog.com")):
        return None
    for key, value in (headers or {}).items():
        if str(key).lower() == HEADER and str(value).strip():
            return _expand(value, environ).strip() or None
    pinned = parse_qs(parts.query).get(QUERY) or []
    return pinned[0].strip() if pinned and pinned[0].strip() else None


def _claude_dir(environ):
    return environ.get("CLAUDE_CONFIG_DIR") or os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".claude")


def _claude_entry(server, cwd, environ):
    config_dir = _claude_dir(environ)
    settings = _json(os.path.join(config_dir, ".claude.json") if environ.get("CLAUDE_CONFIG_DIR")
                     else os.path.join(os.path.dirname(config_dir), ".claude.json")) or {}
    plugin = PLUGIN_RE.match(server)
    if plugin:
        registry = _json(os.path.join(config_dir, "plugins", "installed_plugins.json")) or {}
        for plugin_id, installs in (registry.get("plugins") or {}).items():
            if str(plugin_id).split("@")[0] != plugin.group(1):
                continue
            for inst in installs if isinstance(installs, list) else [installs]:
                manifest = _json(os.path.join(str((inst or {}).get("installPath") or ""), ".mcp.json")) or {}
                entry = (manifest.get("mcpServers") or {}).get(plugin.group(2))
                if isinstance(entry, dict):
                    return entry
        return None
    scopes = []
    if cwd:
        project = (settings.get("projects") or {}).get(os.path.realpath(cwd)) or (settings.get("projects") or {}).get(cwd) or {}
        scopes.append(project.get("mcpServers") or {})
        scopes.append((_json(os.path.join(cwd, ".mcp.json")) or {}).get("mcpServers") or {})
    scopes.append(settings.get("mcpServers") or {})
    for scope in scopes:
        entry = scope.get(server)
        if isinstance(entry, dict):
            return entry
    return None


def _codex_entry(server, environ):
    path = os.path.join(hostcheck.codex_dir(environ), "config.toml")
    if not os.path.exists(path):
        return None
    data, _why = hostcheck._toml(path, environ)
    entry = ((data or {}).get("mcp_servers") or {}).get(server)
    return entry if isinstance(entry, dict) else None


def pinned_project(server, host, cwd=None, environ=os.environ):
    """The PostHog project id the host's connection `server` is pinned to, or None."""
    if host == "codex":
        entry = _codex_entry(server, environ)
        if not entry:
            return None
        headers = dict(entry.get("http_headers") or {})
        for key, var in (entry.get("env_http_headers") or {}).items():
            if environ.get(str(var)):
                headers[key] = environ[str(var)]
        return _pin_of(entry.get("url"), headers, environ)
    entry = _claude_entry(server, cwd, environ)
    if not entry:
        return None
    return _pin_of(entry.get("url"), entry.get("headers") or {}, environ)
