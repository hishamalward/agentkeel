"""agentkeel MCP adapters: bind a guarded server's tool calls to the task's permissions and targets.

Both hosts send each MCP call to PreToolUse as `mcp__<server>__<tool>` with its arguments,
including the calls Codex makes inside its JavaScript `exec` tool (measured; see
docs/enforcement-design.md). An adapter reads only the tool name and the arguments, never a tool's
description. Each operation is listed by its exact name in mcp_catalog.py; the adapter never infers
a class from a name's shape. It sorts a call into a class:

  read          passes
  remote-write  creates, updates, archives, deletes, resolves or changes settings on the service:
                needs `remote-write`, and a target listed for the server in agentkeel.json
  paid          bills per call: needs `paid-job`, and a listed target too when the call names one
                (a Sentry organization); a paid call with no target at all (DataForSEO) needs only
                `paid-job`
  publish       makes something live for end users at once, or sends to them (a paywall, an
                experiment, a workflow, a flag rollout): needs `publish` and a listed target
  store         changes or submits products in the app stores: needs `store-submission` and a
                listed target
  unknown       a name the catalog does not list, however it is spelled: refused

agentkeel.json, for example:
  "mcp": {"revenuecat": {"targets": ["proj1a2b3c"]}, "posthog": {"targets": ["12345"]},
          "sentry": {"targets": ["my-org"]}, "dataforseo": {}}
`switch <id>`, `switch-project` and `switch-organization` change the connection's active project:
remote writes to the target they name (an organization is never a listed project).
`remote-write` alone never publishes and never submits to a store. The adapter sorts by the
operation's name, not by every argument: a generic update that can also turn something on through
a field (PostHog's update-feature-flag with "active") stays a remote write.

PostHog's tools act on the server's active project and do not name it (only the project-* tools
carry an id). The target is the project the host's own connection is pinned to (mcp_connection.py
reads the host's entry for the server that made the call): a write passes when that pin is a listed
project, and is refused with the reason when the connection is pinned elsewhere or not pinned.
Reads pass either way.
"targets": ["*"] allows any target for that server. A server name the host gives a guarded
service under another name is added with "servers": ["name"]. Servers with no adapter here pass and
are reported as unsupported; a refusal stops only the MCP call, not the same credentials used from
a shell or a browser.
"""
import json
import re

from . import mcp_catalog as cat

READ, WRITE, PAID, PUBLISH, STORE, UNKNOWN = "read", "remote-write", "paid", "publish", "store", "unknown"
NO_TARGET = object()
# the permission each class needs, and how a refusal describes the class
NEEDS = {WRITE: ("remote-write", "changes the remote service"),
         PAID: ("paid-job", "bills per call"),
         PUBLISH: ("publish", "makes something live for end users or sends to them"),
         STORE: ("store-submission", "changes or submits products in the app stores")}

# server names each service is known by on Claude Code and Codex installs
SERVERS = {
    "revenuecat": {"revenuecat"},
    "posthog": {"posthog", "plugin_posthog_posthog"},
    "sentry": {"sentry", "plugin_sentry_sentry"},
    "dataforseo": {"dataforseo", "dfs-mcp", "dfs_mcp"},
}

class Call:
    def __init__(self, service, server, tool, args):
        self.service, self.server, self.tool, self.args = service, server, tool, args or {}


def match(tool_name, extra_servers=None):
    """Call or None: which guarded service a host tool name belongs to."""
    if not str(tool_name).startswith("mcp__"):
        return None
    rest = tool_name[len("mcp__"):]
    for service, names in SERVERS.items():
        for name in sorted(names | set((extra_servers or {}).get(service) or []), key=len, reverse=True):
            if rest.startswith(name + "__"):
                return Call(service, name, rest[len(name) + 2:], None)
    return None


def _listed(name, read, write, paid=frozenset(), publish=frozenset(), store=frozenset()):
    for cls, names in ((READ, read), (PAID, paid), (PUBLISH, publish), (STORE, store), (WRITE, write)):
        if name in names:
            return cls
    return UNKNOWN


def _sentry_org(args):
    """The organization a Sentry call names: organizationSlug, or the subdomain of an issueUrl."""
    if args.get("organizationSlug"):
        return str(args["organizationSlug"])
    m = re.match(r"^https://([a-z0-9-]+)\.sentry\.io/", str(args.get("issueUrl") or ""))
    return m.group(1) if m else None


def _json_tail(text):
    m = re.search(r"\{.*\}\s*$", text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def classify(call):
    """(class, target, what) for one guarded call. target is None when the call names none that
    agentkeel can read, or NO_TARGET for an operation that has no target at all."""
    a, svc = call.args, call.service
    if svc == "revenuecat":
        return (_listed(call.tool, cat.REVENUECAT_READ, cat.REVENUECAT_WRITE, publish=cat.REVENUECAT_PUBLISH,
                        store=cat.REVENUECAT_STORE), a.get("project_id"), call.tool)
    if svc == "sentry":
        name, args = call.tool, a
        if call.tool == "execute_sentry_tool":
            name = str(a.get("name") or "")
            args = {**a, **(a.get("arguments") if isinstance(a.get("arguments"), dict) else {})}
        return _listed(name, cat.SENTRY_READ, cat.SENTRY_WRITE, cat.SENTRY_PAID), _sentry_org(args), name
    if svc == "posthog":
        if call.tool != "exec":
            return UNKNOWN, None, call.tool
        words = str(a.get("command") or "").split()
        verb = words[0] if words else ""
        if verb in cat.POSTHOG_VERBS_READ:
            return READ, None, verb
        if verb == "switch":
            # changes the connection's active project: a write to the project it names
            return WRITE, (words[1] if len(words) > 1 else None), "switch"
        if verb == "call":
            rest = [w for w in words[1:] if w not in ("--json", "--confirm")]
            if not rest or rest[0].startswith("-"):
                return UNKNOWN, None, "call"
            target_tool = rest[0]
            body = _json_tail(str(a.get("command")))
            # Only these schemas name the affected project. Other tools use the server's
            # active project; an extra project_id is not a selector.
            target = None
            if target_tool == "project-settings-update":
                target = body.get("id")
            elif target_tool in ("switch-project", "switch-organization"):
                target = body.get("projectId") or body.get("project_id") or body.get("id") \
                    or body.get("organizationId") or body.get("organization_id")
            return (_listed(target_tool, cat.POSTHOG_READ, cat.POSTHOG_WRITE, publish=cat.POSTHOG_PUBLISH),
                    None if target is None else str(target), target_tool)
        return UNKNOWN, None, verb or "exec"
    if svc == "dataforseo":
        if call.tool in cat.DATAFORSEO_READ:
            return READ, None, call.tool
        if call.tool == "api_request":
            path = str(a.get("path") or a.get("url") or "")
            method = str(a.get("method") or "GET").upper()
            segments = set(re.split(r"[/?#]", path))
            if segments & cat.DATAFORSEO_PAID_SEGMENTS:
                return PAID, NO_TARGET, f"{method} {path}"  # billed to the account; no project to name
            if method == "GET" and segments & cat.DATAFORSEO_READ_SEGMENTS:
                return READ, None, f"{method} {path}"
            return UNKNOWN, None, f"{method} {path}"
        return UNKNOWN, None, call.tool
    return UNKNOWN, None, call.tool


def judge(call, rec, policy_mcp, pinned=None):
    """None when the call may run, else the refusal text. `pinned` is the project the host's
    connection for this call is pinned to (mcp_connection.pinned_project), or a function that
    reads it, called only when the decision needs it."""
    cls, target, what = classify(call)
    perms = set((rec or {}).get("permissions") or [])
    label = f"{call.service} `{what}`"
    if cls == READ:
        return None
    if not rec:
        return (f"{label} changes or spends on a remote service, and this session has no task.\n"
                "Declare the task first; a remote change needs the 'remote-write' permission.")
    if cls == UNKNOWN:
        return (f"{label} is not an action agentkeel's {call.service} adapter knows, so it is refused rather\n"
                "than assumed to be a read. If the human wants it, they run it themselves, or the adapter\n"
                "learns it.")
    need, does = NEEDS[cls]
    if need not in perms:
        more = {WRITE: "\nA git push permission does not cover changes to other services.",
                PUBLISH: "\n'remote-write' does not cover it.", STORE: "\n'remote-write' does not cover it."}
        return (f"{label} {does} and needs the '{need}' permission; task '{rec.get('task')}' has "
                f"{', '.join(sorted(perms)) or 'none'}." + more.get(cls, ""))
    if target is NO_TARGET:
        return None
    allowed = [str(t) for t in ((policy_mcp or {}).get(call.service) or {}).get("targets") or []]
    if "*" in allowed:
        return None
    if call.service == "posthog" and callable(pinned):
        pinned = pinned()
    if call.service == "posthog" and pinned is not None and target is not None and str(target) != str(pinned):
        return (f"{label} names project '{target}' while the host's `{call.server}` connection is pinned to "
                f"project '{pinned}'; agentkeel cannot tell which one the server changes, so it is refused.")
    if target is None and call.service == "posthog":
        if pinned is not None and str(pinned) in allowed:
            return None
        if pinned is not None:
            return (f"{label} acts on PostHog's active project, and the host's `{call.server}` connection is\n"
                    f"pinned to project '{pinned}', which agentkeel.json does not list for posthog "
                    f"(allowed: {', '.join(allowed) or 'none'}).")
        return (f"{label} acts on PostHog's active project, which the call does not name, and the host's\n"
                f"`{call.server}` connection is not pinned to one, so agentkeel cannot tell which project it\n"
                "changes. It is refused while agentkeel.json lists specific projects. Pin the connection:\n"
                f"the header `x-posthog-project-id: <id>` (or `?project_id=<id>` on the URL) on the host's\n"
                'entry for this server. Or the human runs it, or allows every project with\n'
                '"mcp": {"posthog": {"targets": ["*"]}}.')
    if target is None:
        return (f"{label} acts on the remote service, and agentkeel cannot tell which "
                f"{call.service} target it changes.\nIt is refused. agentkeel.json can allow every target for "
                f'this server with "mcp": {{"{call.service}": {{"targets": ["*"]}}}}.')
    if str(target) not in allowed:
        return (f"{label} targets '{target}', which agentkeel.json does not list for {call.service} "
                f"(allowed: {', '.join(allowed) or 'none'}).")
    return None
