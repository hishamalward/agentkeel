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
  unknown       a name the catalog does not list, however it is spelled: refused

agentkeel.json, for example:
  "mcp": {"revenuecat": {"targets": ["proj1a2b3c"]}, "posthog": {"targets": ["12345"]},
          "sentry": {"targets": ["my-org"]}, "dataforseo": {}}
"targets": ["*"] allows any target for that server. A server name the host gives a guarded
service under another name is added with "servers": ["name"]. Servers with no adapter here pass and
are reported as unsupported; a refusal stops only the MCP call, not the same credentials used from
a shell or a browser.
"""
import json
import re

from . import mcp_catalog as cat

READ, WRITE, PAID, UNKNOWN = "read", "remote-write", "paid", "unknown"
NO_TARGET = object()

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


def _listed(name, read, write, paid=frozenset()):
    if name in read:
        return READ
    if name in paid:
        return PAID
    if name in write:
        return WRITE
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
        return _listed(call.tool, cat.REVENUECAT_READ, cat.REVENUECAT_WRITE), a.get("project_id"), call.tool
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
            return READ, None, verb  # switch only picks the project later calls use
        if verb == "call":
            rest = [w for w in words[1:] if w not in ("--json", "--confirm")]
            if not rest or rest[0].startswith("-"):
                return UNKNOWN, None, "call"
            target_tool = rest[0]
            body = _json_tail(str(a.get("command")))
            target = body.get("project_id") or (body.get("id") if target_tool.startswith("project") else None)
            return (_listed(target_tool, cat.POSTHOG_READ, cat.POSTHOG_WRITE),
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


def judge(call, rec, policy_mcp):
    """None when the call may run, else the refusal text."""
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
    if cls == PAID:
        if "paid-job" not in perms:
            return (f"{label} bills per call and needs the 'paid-job' permission; task '{rec.get('task')}' has "
                    f"{', '.join(sorted(perms)) or 'none'}.")
        if target is NO_TARGET:
            return None
    elif "remote-write" not in perms:
        return (f"{label} changes the remote service and needs the 'remote-write' permission; task "
                f"'{rec.get('task')}' has {', '.join(sorted(perms)) or 'none'}.\n"
                "A git push permission does not cover changes to other services.")
    allowed = [str(t) for t in ((policy_mcp or {}).get(call.service) or {}).get("targets") or []]
    if "*" in allowed:
        return None
    if target is None:
        return (f"{label} acts on the remote service, and agentkeel cannot tell which "
                f"{call.service} target it changes.\nIt is refused. agentkeel.json can allow every target for "
                f'this server with "mcp": {{"{call.service}": {{"targets": ["*"]}}}}.')
    if str(target) not in allowed:
        return (f"{label} targets '{target}', which agentkeel.json does not list for {call.service} "
                f"(allowed: {', '.join(allowed) or 'none'}).")
    return None
