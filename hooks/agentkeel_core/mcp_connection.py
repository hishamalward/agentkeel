"""agentkeel MCP connections: which project a host's connection is pinned to, read from the host's own configuration.

PostHog's MCP server acts on one active project per connection and its tools do not name it. The
server documents one way to fix that project: the entry's URL carries `?project_id=<id>`, or its
headers carry `x-posthog-project-id: <id>`, and the pinned connection no longer offers the switch
tools. The adapter (mcp.py) treats a pinned connection as the call's target, so a write passes
only when the host's entry for the server that made the call is pinned to a listed project.

This reads the entry the host itself uses, never a claim in the call, and never a file the session
could have written:
- Claude Code: `mcp__<server>__<tool>` resolves in the host's order for the host's project
  directory (CLAUDE_PROJECT_DIR, the folder the session was started in; the hook's cwd follows
  `cd` and is not it): the project's own entry (~/.claude.json, projects.<dir>.mcpServers), then
  <dir>/.mcp.json, and that one only for a server the human approved for the project
  (enabledMcpjsonServers or enableAllProjectMcpServers, and not disabledMcpjsonServers), then the
  user's entry (~/.claude.json, mcpServers). `mcp__plugin_<plugin>_<server>__<tool>` is the
  plugin's own .mcp.json under its install paths (installed_plugins.json); installs that disagree
  are no pin. A `${VAR}` in a header needs the variable in the hook environment. Use literal
  project ids with the hardened launcher, which clears other environment variables.
- Codex: [mcp_servers.<server>] in ~/.codex/config.toml: url, http_headers and env_http_headers
  (a header whose value is the name of an environment variable).
A pin counts only for an entry whose URL is on posthog.com, and only when every pin the entry
carries (header spellings, query values) names the same project. A configuration file that exists
and does not parse, a missing project directory, or two sources that disagree all mean "not
pinned": the adapter then refuses the write and says how to pin, never guesses.
"""
import json
import os
import re
from urllib.parse import parse_qs, urlsplit

from . import hostcheck

HEADER = "x-posthog-project-id"
QUERY = "project_id"
PLUGIN_RE = re.compile(r"^plugin_([^_]+)_(.+)$")
UNREADABLE = object()


def _json(path):
    """The parsed file, None when it does not exist, UNREADABLE when it exists and does not parse."""
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            data = json.load(fh)
    except Exception:
        return UNREADABLE
    return data if isinstance(data, dict) else UNREADABLE


def _expand(value, environ):
    """Expand only known variables; a cleared host variable cannot justify its default."""
    pattern = r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}"
    value = str(value)
    if any(environ.get(m.group(1)) is None for m in re.finditer(pattern, value)):
        return ""
    return re.sub(pattern, lambda m: environ[m.group(1)], value)


def _one(values):
    values = set(values)
    return values.pop() if len(values) == 1 and all(values) else None


def _pin_of(url, headers, environ):
    """The one project id an entry pins, or None (no pin, or pins that disagree)."""
    url = _expand(url or "", environ)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not (host == "posthog.com" or host.endswith(".posthog.com")):
        return None
    items = headers.items() if isinstance(headers, dict) else (headers or [])
    pins = [_expand(value, environ).strip() for key, value in items if str(key).lower() == HEADER]
    pins += [v.strip() for v in parse_qs(parts.query, keep_blank_values=True).get(QUERY) or []]
    return _one(pins)


def _claude_dir(environ):
    return environ.get("CLAUDE_CONFIG_DIR") or os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".claude")


def _claude_settings(environ):
    config_dir = _claude_dir(environ)
    path = (os.path.join(config_dir, ".claude.json") if environ.get("CLAUDE_CONFIG_DIR")
            else os.path.join(os.path.dirname(config_dir), ".claude.json"))
    return _json(path)


def _plugin_pins(server, plugin, environ):
    registry = _json(os.path.join(_claude_dir(environ), "plugins", "installed_plugins.json"))
    if registry in (None, UNREADABLE):
        return None
    pins, seen = [], False
    for plugin_id, installs in (registry.get("plugins") or {}).items():
        if str(plugin_id).split("@")[0] != plugin:
            continue
        for inst in installs if isinstance(installs, list) else [installs]:
            manifest = _json(os.path.join(str((inst or {}).get("installPath") or ""), ".mcp.json"))
            if manifest is UNREADABLE:
                return None
            entry = ((manifest or {}).get("mcpServers") or {}).get(server)
            if isinstance(entry, dict):
                seen = True
                pins.append(_pin_of(entry.get("url"), entry.get("headers") or {}, environ) or "")
    return _one(pins) if seen and all(pins) else None


def _claude_pin(server, environ):
    plugin = PLUGIN_RE.match(server)
    if plugin:
        return _plugin_pins(plugin.group(2), plugin.group(1), environ)
    settings = _claude_settings(environ)
    if settings is UNREADABLE:
        return None
    settings = settings or {}
    project_dir = environ.get("CLAUDE_PROJECT_DIR")
    scopes = []
    if project_dir:
        project = (settings.get("projects") or {}).get(project_dir) \
            or (settings.get("projects") or {}).get(os.path.realpath(project_dir)) or {}
        scopes.append(project.get("mcpServers") or {})
        approved = (project.get("enableAllProjectMcpServers") is True
                    or server in (project.get("enabledMcpjsonServers") or [])) \
            and server not in (project.get("disabledMcpjsonServers") or [])
        shared = _json(os.path.join(project_dir, ".mcp.json"))
        if shared is UNREADABLE:
            return None
        if approved and shared:
            scopes.append(shared.get("mcpServers") or {})
    scopes.append(settings.get("mcpServers") or {})
    for scope in scopes:
        entry = scope.get(server)
        if isinstance(entry, dict):
            return _pin_of(entry.get("url"), entry.get("headers") or {}, environ)
    return None


def _codex_pin(server, environ):
    path = os.path.join(hostcheck.codex_dir(environ), "config.toml")
    if not os.path.exists(path):
        return None
    data, _why = hostcheck._toml(path, environ)
    entry = ((data or {}).get("mcp_servers") or {}).get(server)
    if not isinstance(entry, dict):
        return None
    # an env header names a variable; an unset variable sends no header
    headers = [(k, v) for k, v in (entry.get("http_headers") or {}).items()]
    headers += [(k, environ.get(str(var)) or "") for k, var in (entry.get("env_http_headers") or {}).items()]
    return _pin_of(entry.get("url"), headers, environ)


def pinned_project(server, host, cwd=None, environ=os.environ):
    """The PostHog project id the host's connection `server` is pinned to, or None."""
    if host == "codex":
        return _codex_pin(server, environ)
    return _claude_pin(server, environ)
