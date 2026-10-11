"""agentkeel MCP adapters: bind a guarded server's tool calls to the task's permissions and targets.

Both hosts send each MCP call to PreToolUse as `mcp__<server>__<tool>` with its arguments,
including the calls Codex makes inside its JavaScript `exec` tool (measured; see
docs/enforcement-design.md). An adapter reads only the tool name and the arguments, never a tool's
description. Each operation is listed by its exact name in the catalog (mcp_catalog.py: the plugin
default, the human's AGENTKEEL_HOME/mcp_catalog.json, the project's agentkeel.json "mcp" block);
the adapter never infers a class from a name's shape. It sorts a call into a class:

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
  unclassified  listed by `task.py mcp draft` and not yet sorted: judged as a remote write
  unknown       a name the catalog does not list, however it is spelled: refused
A name a layer lists under more than one class takes the class that asks the most (store, publish,
paid, remote-write, then read): a layer adds names, it cannot turn a listed write into a read.

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
service under another name is added with "servers": ["name"]. Any other server is added the same
way, as a generic service: its class lists, and "target_arg", the argument that names the target
(absent: the operation has no target). A server with no catalog entry follows agentkeel.json
"guards": {"mcp_unknown": "pass" | "warn" | "block"} (default pass), and each of its tools is noted
once per task, argument names only, in the task's scratch folder (mcp-unseen.jsonl), which
`task.py mcp draft <server>` turns into an entry. A refusal stops only the MCP call, not the same
credentials used from a shell or a browser.
"""
import json
import os
import re
import tempfile
import time

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

UNSEEN_LOG = "mcp-unseen.jsonl"
CLASS_KEYS = ("read", "write", "paid", "publish", "store", "unclassified")


class Call:
    def __init__(self, service, server, tool, args, entry=None):
        self.service, self.server, self.tool, self.args = service, server, tool, args or {}
        self.entry = entry if entry is not None else cat.DEFAULT.get(service, {})


def match(tool_name, catalog=None):
    """Call or None: which catalog service a host tool name belongs to. `catalog` is the merged
    catalog (mcp_catalog.merged); None means the plugin default alone. The longest server name wins."""
    if not str(tool_name).startswith("mcp__"):
        return None
    catalog = cat.DEFAULT if catalog is None else catalog
    rest = tool_name[len("mcp__"):]
    names = []
    for service, entry in catalog.items():
        own = SERVERS.get(service) or ({service} if not entry.get("servers") else set())
        for name in own | set(entry.get("servers") or []):
            names.append((-len(name), service not in SERVERS, name, service))
    for _, _, name, service in sorted(names):
        if rest.startswith(name + "__"):
            return Call(service, name, rest[len(name) + 2:], None, catalog[service])
    return None


def split(tool_name):
    """(server, tool) of `mcp__<server>__<tool>`."""
    server, _, tool = str(tool_name)[len("mcp__"):].partition("__")
    return server, tool


def _listed(name, entry):
    """A name's class from an entry's lists. A name in more than one list takes the class that asks
    the most; unclassified is judged as a remote write."""
    for cls, key in ((STORE, "store"), (PUBLISH, "publish"), (PAID, "paid"), (WRITE, "write"),
                     (WRITE, "unclassified"), (READ, "read")):
        if name in (entry.get(key) or ()):
            return cls
    return UNKNOWN


def _target(entry, args, name=None):
    """A generic service's target: the argument target_arg names, or NO_TARGET without one. An
    unclassified name is a write whose target is unknown without target_arg: None, so only
    "targets": ["*"] lets it through."""
    if not entry.get("target_arg"):
        sorted_ = any(name in (entry.get(k) or ()) for k in CLASS_KEYS if k != "unclassified")
        return None if name in (entry.get("unclassified") or ()) and not sorted_ else NO_TARGET
    value = args.get(str(entry["target_arg"]))
    return None if value is None or value == "" else str(value)


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
    a, svc, e = call.args, call.service, call.entry
    if svc == "revenuecat":
        return _listed(call.tool, e), a.get("project_id"), call.tool
    if svc == "sentry":
        name, args = call.tool, a
        if call.tool == "execute_sentry_tool":
            name = str(a.get("name") or "")
            args = {**a, **(a.get("arguments") if isinstance(a.get("arguments"), dict) else {})}
        return _listed(name, e), _sentry_org(args), name
    if svc == "posthog":
        if call.tool != "exec":
            return UNKNOWN, None, call.tool
        words = str(a.get("command") or "").split()
        verb = words[0] if words else ""
        if verb in (e.get("verbs_read") or ()):
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
            return _listed(target_tool, e), None if target is None else str(target), target_tool
        return UNKNOWN, None, verb or "exec"
    if svc == "dataforseo":
        if call.tool != "api_request" and _listed(call.tool, e) == READ:
            return READ, None, call.tool
        if call.tool == "api_request":
            path = str(a.get("path") or a.get("url") or "")
            method = str(a.get("method") or "GET").upper()
            segments = set(re.split(r"[/?#]", path))
            if segments & set(e.get("paid_segments") or ()):
                return PAID, NO_TARGET, f"{method} {path}"  # billed to the account; no project to name
            if method == "GET" and segments & set(e.get("read_segments") or ()):
                return READ, None, f"{method} {path}"
            return UNKNOWN, None, f"{method} {path}"
        return _listed(call.tool, e), _target(e, a, call.tool), call.tool
    # a generic service, from a user or project layer: its lists, and its target_arg
    return _listed(call.tool, e), _target(e, a, call.tool), call.tool


def judge(call, rec, policy_mcp, pinned=None):
    """None when the call may run, else the refusal text. `policy_mcp` is the merged catalog, whose
    entries carry the listed "targets". `pinned` is the project the host's
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


def unknown_text(server, tool, mode):
    """What the guard says about a call on a server with no catalog entry (guards.mcp_unknown)."""
    head = (f"the MCP server `{server}` (tool `{tool}`) has no entry in agentkeel's MCP catalog, so agentkeel\n"
            "cannot tell what the call does" + (", and agentkeel.json sets guards.mcp_unknown to block, so it is\n"
                                                "refused." if mode == "block" else "."))
    return (head + "\nThe human adds the server in agentkeel.json under \"mcp\", for example\n"
            f'  "mcp": {{"{server}": {{"servers": ["{server}"], "read": ["..."], "write": ["..."], "targets": [], "target_arg": "..."}}}}\n'
            f"`task.py mcp draft {server}` prints an entry from the calls this task has seen.")


def scratch_of(rec, session_id):
    """The task's scratch folder: the record's, else the one task.py start makes for the session."""
    if rec and rec.get("scratch"):
        return rec["scratch"]
    if not session_id:
        return None
    from . import record
    return os.path.join(os.path.realpath(tempfile.gettempdir()), "agentkeel-scratch", record._safe(session_id))


def _unseen(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        pass
    return out


def log_unseen(folder, server, tool, args):
    """Note one call on a server with no catalog entry, once per (server, tool) in this folder. Only
    the argument names are kept, never their values, which can hold secrets."""
    if not folder:
        return False
    path = os.path.join(folder, UNSEEN_LOG)
    if any(r.get("server") == server and r.get("tool") == tool for r in _unseen(path)):
        return False
    os.makedirs(folder, exist_ok=True)
    keys = sorted(str(k) for k in args) if isinstance(args, dict) else []
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"server": server, "tool": tool, "args_keys": keys, "ts": int(time.time())}) + "\n")
    return True


def draft(folder, server):
    """A catalog entry for `server` from the unseen log: every tool unclassified, no target listed.
    None when the log holds no call on that server."""
    tools = sorted({str(r.get("tool")) for r in _unseen(os.path.join(folder or "", UNSEEN_LOG))
                    if r.get("server") == server and r.get("tool")})
    if not tools:
        return None
    return {server: {"servers": [server], "targets": [], "unclassified": tools}}
