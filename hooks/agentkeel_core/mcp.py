"""agentkeel MCP adapters: bind a guarded server's tool calls to the task's permissions and targets.

Both hosts send each MCP call to PreToolUse as `mcp__<server>__<tool>` with its arguments,
including the calls Codex makes inside its JavaScript `exec` tool (measured; see
docs/enforcement-design.md). An adapter reads only the tool name and the arguments, never a tool's
description. It sorts a call into a class:

  read          passes
  remote-write  creates, updates, archives, deletes, resolves or changes settings on the service:
                needs `remote-write`, and a target listed for the server in agentkeel.json
  paid          bills per call: needs `paid-job`
  unknown       anything the adapter does not know: refused, never assumed to be a read

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

READ, WRITE, PAID, UNKNOWN = "read", "remote-write", "paid", "unknown"

# server names each service is known by on Claude Code and Codex installs
SERVERS = {
    "revenuecat": {"revenuecat"},
    "posthog": {"posthog", "plugin_posthog_posthog"},
    "sentry": {"sentry", "plugin_sentry_sentry"},
    "dataforseo": {"dataforseo", "dfs-mcp", "dfs_mcp"},
}

READ_NAME = re.compile(r"^(list|get|search|find|query|describe|fetch|retrieve|read|count|docs)[_-]")
WRITE_NAME = re.compile(r"^(create|update|set|attach|detach|archive|unarchive|delete|remove|add|"
                        r"resolve|enable|disable|replace|patch|rename|move|import|bulk)[_-]")
READ_SUFFIX = re.compile(r"[_-](get|get-all|list|retrieve|search|query|count|summary)$")
WRITE_SUFFIX = re.compile(r"[_-](create|update|partial-update|delete|bulk-delete|add|remove|set|"
                          r"archive|enable|disable|resolve)$")


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


def _by_name(name):
    if READ_NAME.match(name) or READ_SUFFIX.search(name):
        return READ
    if WRITE_NAME.match(name) or WRITE_SUFFIX.search(name):
        return WRITE
    return UNKNOWN


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
    """(class, target or None, what) for one guarded call."""
    a, svc = call.args, call.service
    if svc == "revenuecat":
        return _by_name(call.tool), a.get("project_id"), call.tool
    if svc == "sentry":
        if call.tool == "analyze_issue_with_seer":
            return PAID, a.get("organizationSlug"), call.tool  # an AI analysis run on the account
        if call.tool == "execute_sentry_tool":
            inner = str(a.get("name") or "")
            inner_args = a.get("arguments") if isinstance(a.get("arguments"), dict) else {}
            return _by_name(inner), inner_args.get("organizationSlug") or a.get("organizationSlug"), inner
        return _by_name(call.tool), a.get("organizationSlug"), call.tool
    if svc == "posthog":
        if call.tool != "exec":
            return _by_name(call.tool), None, call.tool
        words = str(a.get("command") or "").split()
        verb = words[0] if words else ""
        if verb in ("tools", "search", "info", "learn", "switch"):
            return READ, None, verb  # switch only picks the project later calls use
        if verb == "call" and len(words) > 1:
            target_tool = words[1]
            body = _json_tail(str(a.get("command")))
            target = body.get("project_id") or (body.get("id") if target_tool.startswith("project") else None)
            if target_tool in ("execute-sql", "query", "docs-search", "read-data-schema"):
                return READ, None, target_tool
            return _by_name(target_tool), None if target is None else str(target), target_tool
        return UNKNOWN, None, verb or "exec"
    if svc == "dataforseo":
        if call.tool.startswith("docs_"):
            return READ, None, call.tool
        if call.tool == "api_request":
            path = str(a.get("path") or a.get("url") or "")
            method = str(a.get("method") or "GET").upper()
            if "/live" in path or "task_post" in path:
                return PAID, None, f"{method} {path}"
            if method == "GET" and re.search(r"(appendix|user_data|locations|languages|task_get|tasks_ready|"
                                             r"id_list|errors)", path):
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
        return None
    if "remote-write" not in perms:
        return (f"{label} changes the remote service and needs the 'remote-write' permission; task "
                f"'{rec.get('task')}' has {', '.join(sorted(perms)) or 'none'}.\n"
                "A git push permission does not cover changes to other services.")
    allowed = [str(t) for t in ((policy_mcp or {}).get(call.service) or {}).get("targets") or []]
    if "*" in allowed:
        return None
    if target is None:
        return (f"{label} changes the remote service, and agentkeel cannot tell which "
                f"{call.service} target it changes.\nIt is refused. agentkeel.json can allow every target for "
                f'this server with "mcp": {{"{call.service}": {{"targets": ["*"]}}}}.')
    if str(target) not in allowed:
        return (f"{label} targets '{target}', which agentkeel.json does not list for {call.service} "
                f"(allowed: {', '.join(allowed) or 'none'}).")
    return None
