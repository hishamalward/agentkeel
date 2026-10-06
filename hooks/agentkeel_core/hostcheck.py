"""What each host has of agentkeel: the plugin installed and enabled, a project install, and (Codex)
how many plugin hooks the human has trusted. Read only; it never changes a host's configuration.

Claude Code keeps installs in <config>/plugins/installed_plugins.json and the on/off switch in
enabledPlugins of a settings file (user, project or local scope). Codex keeps both in
<CODEX_HOME>/config.toml: [plugins."agentkeel@agentkeel"] and one [hooks.state."agentkeel@agentkeel:..."]
table, with a trusted_hash, for each hook the human trusted in /hooks.
"""
import json
import os
import re

PLUGIN_ID = "agentkeel@agentkeel"


def _json(path):
    try:
        with open(path) as fh:
            return json.load(fh) or {}
    except Exception:
        return None


def _text(path):
    try:
        with open(path) as fh:
            return fh.read()
    except Exception:
        return None


def claude_dir(environ):
    return environ.get("CLAUDE_CONFIG_DIR") or os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".claude")


def codex_dir(environ):
    return environ.get("CODEX_HOME") or os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".codex")


def _project_install(repo, rel):
    """install.py copies the hooks into the repository; its settings call task-guard.py there."""
    return "task-guard.py" in (_text(os.path.join(repo, rel)) or "")


def claude(repo, environ=os.environ):
    """{'installed': [scopes], 'enabled': bool, 'project_install': bool}"""
    base = claude_dir(environ)
    installed = (_json(os.path.join(base, "plugins", "installed_plugins.json")) or {}).get("plugins", {})
    scopes = [e.get("scope", "user") for e in installed.get(PLUGIN_ID, []) if isinstance(e, dict)]
    enabled = False
    for path in (os.path.join(base, "settings.json"), os.path.join(repo, ".claude", "settings.json"),
                 os.path.join(repo, ".claude", "settings.local.json")):
        value = ((_json(path) or {}).get("enabledPlugins") or {}).get(PLUGIN_ID)
        if value is not None:
            enabled = bool(value)
    return {"installed": scopes, "enabled": enabled,
            "project_install": _project_install(repo, os.path.join(".claude", "settings.json"))}


def codex(repo, environ=os.environ):
    """{'installed': bool, 'enabled': bool, 'trusted': int, 'readable': bool, 'project_install': bool}"""
    text = _text(os.path.join(codex_dir(environ), "config.toml"))
    out = {"installed": False, "enabled": False, "trusted": 0, "readable": text is not None,
           "project_install": _project_install(repo, os.path.join(".codex", "hooks.json"))}
    if text is None:
        return out
    m = re.search(r'^\[plugins\."' + re.escape(PLUGIN_ID) + r'"\]\s*$([^\[]*)', text, re.M)
    if m:
        out["installed"] = True
        out["enabled"] = not re.search(r"^\s*enabled\s*=\s*false\b", m.group(1), re.M)
    out["trusted"] = len(re.findall(r'^\[hooks\.state\."' + re.escape(PLUGIN_ID) + r':[^"]*"\]\s*\n\s*trusted_hash\s*=',
                                    text, re.M))
    return out


def plugin_hook_count(hooks_dir):
    """How many hooks the plugin declares (each needs its own trust in Codex), or None."""
    data = _json(os.path.join(hooks_dir, "hooks.json"))
    if not data:
        return None
    return sum(len(group.get("hooks") or []) for groups in (data.get("hooks") or {}).values() for group in groups)
