"""What each host has of agentkeel, read from the host's own answer. Read only: it never changes a
host's configuration, and when it cannot read a fact reliably it says "unknown", never a guess.

- Installed, enabled and version come from the host's CLI: `claude plugin list --json`, and the
  STATUS and VERSION columns of `codex plugin list -m agentkeel`. Each fact is a separate field;
  a configuration entry alone never counts as installed.
- Codex trust (one [hooks.state."agentkeel@agentkeel:..."] table with a trusted_hash per hook the
  human trusted in /hooks) exists only in config.toml. It is read with a real TOML parser:
  tomllib (Python 3.11+) or its package form tomli (pip carries a copy), here or in a newer
  python3.x on PATH. Without one, trust is unknown.
- A project install (install.py) is found by its settings file calling task-guard.py.
"""
import json
import os
import shutil
import subprocess

PLUGIN_ID = "agentkeel@agentkeel"
UNKNOWN = None
TOML_TO_JSON = ("import json,sys,tomllib\n"
                "with open(sys.argv[1],'rb') as f: d=tomllib.load(f)\n"
                "print(json.dumps(d, default=str))")


def _run(argv, cwd, environ, timeout=60):
    exe = shutil.which(argv[0], path=environ.get("PATH"))
    if not exe:
        return None
    try:
        out = subprocess.run([exe, *argv[1:]], cwd=cwd, env=dict(environ), capture_output=True,
                             text=True, timeout=timeout)
    except Exception:
        return None
    return out if out.returncode == 0 else None


def _text(path):
    try:
        with open(path) as fh:
            return fh.read()
    except Exception:
        return None


def codex_dir(environ):
    return environ.get("CODEX_HOME") or os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".codex")


def project_install(repo, rel):
    return "task-guard.py" in (_text(os.path.join(repo, rel)) or "")


def claude(repo, environ=os.environ):
    """{'cli': bool, 'installed': bool|None, 'enabled': bool|None, 'version', 'scope', 'project_install'}"""
    out = {"cli": False, "installed": UNKNOWN, "enabled": UNKNOWN, "version": None, "scope": None,
           "project_install": project_install(repo, os.path.join(".claude", "settings.json"))}
    res = _run(["claude", "plugin", "list", "--json"], repo, environ)
    if res is None:
        return out
    out["cli"] = True
    try:
        entries = json.loads(res.stdout)
    except Exception:
        return out
    # The documented shape is a list of records with a string id; [] means nothing is installed.
    # Any other shape is evidence of nothing, so every fact stays unknown.
    if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get("id"), str)
                                                for e in entries):
        return out
    mine = [e for e in entries if e["id"] == PLUGIN_ID]
    if not mine:
        out["installed"] = False
        return out
    paths = [e.get("installPath") for e in mine]
    if all(isinstance(p, str) and p for p in paths):
        out["installed"] = all(os.path.isdir(p) for p in paths)
    flags = [e.get(k) for e in mine for k in ("enabled", "projectEnabled") if k in e]
    if flags and all(isinstance(f, bool) for f in flags):
        out["enabled"] = any(flags)
    e = mine[0]
    out["version"] = e.get("version") if isinstance(e.get("version"), str) else None
    out["scope"] = e.get("scope") if isinstance(e.get("scope"), str) else None
    return out


def _codex_row(text):
    """The STATUS and VERSION of agentkeel@agentkeel in `codex plugin list` output, or None."""
    lines = text.splitlines()
    header = next((ln for ln in lines if ln.split()[:1] == ["PLUGIN"] and "STATUS" in ln), None)
    if header is None:
        return None
    cols = [header.index(name) for name in ("PLUGIN", "STATUS", "VERSION", "SOURCE") if name in header]
    for ln in lines:
        if ln.startswith(PLUGIN_ID + " ") and len(cols) == 4:
            return ln[cols[1]:cols[2]].strip(), ln[cols[2]:cols[3]].strip()
    return None


def _tomllib():
    """tomllib (Python 3.11+), or tomli, the same parser as a package (pip carries a copy)."""
    for name in ("tomllib", "tomli", "pip._vendor.tomli"):
        try:
            return __import__(name, fromlist=["load"])
        except ImportError:
            continue
    return None


def _toml(path, environ):
    """(the parsed file as a dict, None) or (None, why it could not be read)."""
    tomllib = _tomllib()
    if tomllib is not None:
        try:
            with open(path, "rb") as fh:
                return tomllib.load(fh), None
        except Exception as e:
            return None, f"~/.codex/config.toml did not parse ({type(e).__name__})"
    for name in ("python3.14", "python3.13", "python3.12", "python3.11"):
        res = _run([name, "-c", TOML_TO_JSON, path], None, environ, timeout=20)
        if res is not None:
            try:
                return json.loads(res.stdout), None
            except Exception:
                break
    return None, "reading ~/.codex/config.toml needs Python 3.11 or newer (tomllib)"


def codex(repo, environ=os.environ):
    """{'cli': bool, 'installed', 'enabled', 'version', 'trusted': int|None, 'project_install'}"""
    out = {"cli": False, "installed": UNKNOWN, "enabled": UNKNOWN, "version": None, "trusted": UNKNOWN,
           "trust_unknown_because": None, "project_install": project_install(repo, os.path.join(".codex", "hooks.json"))}
    res = _run(["codex", "plugin", "list", "-m", "agentkeel"], repo, environ)
    if res is not None:
        out["cli"] = True
        row = _codex_row(res.stdout)
        if row is None:
            out["installed"] = False if "No plugins found" in res.stdout else UNKNOWN
        else:
            status = [w.strip() for w in row[0].split(",") if w.strip()]
            known = {"installed", "not installed", "enabled", "disabled"}
            if status and set(status) <= known:
                out["installed"] = "installed" in status
                out["enabled"] = True if "enabled" in status else False if "disabled" in status else UNKNOWN
            out["version"] = row[1] or None
    config = os.path.join(codex_dir(environ), "config.toml")
    if not os.path.exists(config):
        out["trusted"] = 0  # no configuration file holds no trust entries
        return out
    data, out["trust_unknown_because"] = _toml(config, environ)
    if data is not None:
        state = ((data.get("hooks") or {}).get("state") or {})
        out["trusted"] = sum(1 for k, v in state.items()
                             if k.startswith(PLUGIN_ID + ":") and isinstance(v, dict) and v.get("trusted_hash"))
    return out


def plugin_hook_count(hooks_dir):
    """How many hooks the plugin declares (each needs its own trust in Codex), or None."""
    try:
        with open(os.path.join(hooks_dir, "hooks.json")) as fh:
            data = json.load(fh)
    except Exception:
        return None
    return sum(len(group.get("hooks") or []) for groups in (data.get("hooks") or {}).values() for group in groups)
