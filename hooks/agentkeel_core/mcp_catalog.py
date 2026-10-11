"""agentkeel MCP catalog loader: the operations each service is known by, by exact name, in layers.

The plugin's data lives in mcp_catalog.json next to this file, one object per service. An adapter
never infers a class from a name's shape: a name that is not listed is unknown and refused. A read
lists, gets or queries and changes nothing on the service; every other listed operation is a remote
write.

The catalog the guard uses is three layers, merged in order, the most specific last:

  1. the plugin default, mcp_catalog.json (RevenueCat, PostHog, Sentry, DataForSEO)
  2. the human's own file, AGENTKEEL_HOME/mcp_catalog.json (default ~/.agentkeel), optional
  3. the project's agentkeel.json "mcp" block

A service entry, in any layer, may carry "servers" (the host's server names; default the service
key), "targets", the class lists "read", "write", "paid", "publish", "store" and "unclassified"
(exact tool names; unclassified is judged as a write), "target_arg" (the argument that names the
target; absent means the operation has no target) and "note". Lists merge by union across layers;
"targets", "target_arg" and "note" come from the most specific layer that sets them. A layer adds
names; it cannot take a name out of a lower layer's list.

The plugin default's lists stay importable as module-level frozensets named SERVICE_KEY, upper-cased,
for example REVENUECAT_READ, SENTRY_PAID, POSTHOG_VERBS_READ and DATAFORSEO_PAID_SEGMENTS. The
"note" strings and the top-level "_comment" in the json are documentation.
"""
import json
import os

from . import record

OVERRIDE = ("targets", "target_arg", "note")  # the most specific layer wins; every other list is a union
USER_FILE = "mcp_catalog.json"


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _plugin():
    return _read_json(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_catalog.json"))


DEFAULT = {k: v for k, v in _plugin().items() if isinstance(v, dict)}
SHIPPED = frozenset(DEFAULT)


def user_path(environ=os.environ):
    return os.path.join(record.home(environ), USER_FILE)


def merge(*layers):
    """One catalog from layers given least specific first. Entries that are not objects, and keys
    starting with "_", are skipped."""
    out = {}
    for layer in layers:
        for service, entry in (layer or {}).items() if isinstance(layer, dict) else []:
            if str(service).startswith("_") or not isinstance(entry, dict):
                continue
            into = out.setdefault(str(service), {})
            for key, value in entry.items():
                if key in OVERRIDE:
                    into[key] = [str(x) for x in value] if isinstance(value, list) else value
                elif isinstance(value, list):
                    have = into.setdefault(key, [])
                    have += [str(x) for x in value if str(x) not in have]
                elif key not in into:
                    into[key] = value
    return out


def merged(project_mcp=None, environ=os.environ):
    """The catalog for one call: the plugin default <- the human's file <- the project's "mcp"
    block (record.policy(root)["mcp"]). Nothing is read at import time but the plugin default."""
    return merge(DEFAULT, _read_json(user_path(environ)), project_mcp if isinstance(project_mcp, dict) else {})


globals().update({f"{service}_{key}".upper(): frozenset(names)
                  for service, rules in DEFAULT.items()
                  for key, names in rules.items() if isinstance(names, list)})
