"""agentkeel MCP catalog loader: the operations each adapter knows, by exact name.

The data lives in mcp_catalog.json next to this file, one object per service. An adapter never
infers a class from a name's shape: a name that is not listed there is unknown and refused. A read
lists, gets or queries and changes nothing on the service; every other listed operation is a remote
write. A server that adds a tool adds it to the json, after someone reads what it does.

Each list of a service becomes a module-level frozenset named SERVICE_KEY, upper-cased, for example
REVENUECAT_READ, SENTRY_PAID, POSTHOG_VERBS_READ and DATAFORSEO_PAID_SEGMENTS. The "note" strings and
the top-level "_comment" in the json are documentation and are not loaded.
"""
import json
import os


def _load():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_catalog.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {f"{service}_{key}".upper(): frozenset(names)
            for service, rules in data.items() if isinstance(rules, dict)
            for key, names in rules.items() if isinstance(names, list)}


globals().update(_load())
