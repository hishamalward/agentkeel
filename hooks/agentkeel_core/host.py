"""agentkeel core: turn one host's tool call into the operations every guard judges.

Hosts name the same act differently. Claude Code edits with Write/Edit/NotebookEdit and Codex
with apply_patch (the patch text in tool_input.command); both run shell as Bash; Claude Code
dispatches a subagent with Agent and Codex with spawn_agent (reported as
`collaborationspawn_agent`, its message encrypted). Guards never read tool names: they read the
events below, so one decision serves every host. Payload shapes are pinned by the captured
fixtures in tests/fixtures/.

  edit      a file is written: `path` (absolute), and what is known of the new content
  command   a shell command line
  dispatch  a subagent is launched: its readable prompt (if any) and its task name (if any)
  mcp       an MCP tool call: its name and arguments, for the adapters in mcp.py
  gap       a tool that may write but that agentkeel cannot read: refused, so the gap is visible
"""
import os
import re
from dataclasses import dataclass, field

from . import patch as patchmod

# Tools that write no repository file: reads, planning, messaging, scheduling (a scheduled prompt
# runs later as ordinary tool calls, which are judged then). Everything else whose name suggests a
# write is a gap and refused. MCP tools become mcp events: guarded servers are judged by their
# adapter (mcp.py), and every other server passes, reported as unsupported.
NO_FILE_WRITE = {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "TodoWrite", "TaskList",
                 "TaskGet", "TaskCreate", "TaskUpdate", "TaskStop", "TaskOutput", "ToolSearch",
                 "Skill", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "SendMessage",
                 "ListAgents", "TeamCreate", "TeamDelete", "CronCreate", "CronDelete", "CronList",
                 "ScheduleWakeup", "Monitor", "PushNotification", "EnterWorktree", "ExitWorktree",
                 "Artifact", "ArtifactComments", "ArtifactData", "SendFeedback", "ReportFindings",
                 "ListMcpResourcesTool", "ReadMcpResourceTool", "BashOutput", "KillShell",
                 "view_image", "update_plan", "read_file", "list_dir", "web_search", "wait_agent", "collaborationwait_agent",
                 "list_agents", "collaborationlist_agents", "close_agent", "send_input", "SubagentHandback",
                 # Codex's hosted web tool, including its normalized hook name. Exact aliases
                 # only: browser script execution and unknown *run* tools remain judged below.
                 "webrun", "web.run", "web__run"}
READ_ONLY = NO_FILE_WRITE
MAY_WRITE_RE = re.compile(r"write|edit|patch|exec|shell|bash|command|run|spawn|agent|delete|move|create",
                          re.IGNORECASE)


@dataclass
class Event:
    kind: str
    tool: str = ""
    path: str = ""
    command: str = ""
    prompt: str = ""
    name: str = ""
    full_text: object = None          # the whole new content when known (Write, patch add)
    edit: dict = field(default_factory=dict)        # Edit: old_string/new_string/replace_all
    change: object = None             # patch.FileChange for an apply_patch update or move
    source_path: str = ""             # for a move: the file the content comes from
    args: dict = field(default_factory=dict)        # mcp: the tool call's arguments


def _abs(cwd, p):
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(str(p))))


def patch_events(tool, text, cwd):
    """Edit events for every file a patch text touches; None when the text holds no patch."""
    env = patchmod.envelope(text)
    if env is None:
        return None
    out, last_update = [], None
    for ch in patchmod.parse(env):
        path = _abs(cwd, ch.path)
        if ch.kind == "move-to" and last_update is not None:
            out.append(Event("edit", tool, path, change=last_update[1], source_path=last_update[0]))
            continue
        out.append(Event("edit", tool, path, full_text=ch.new_content(), change=ch))
        if ch.kind == "update":
            last_update = (path, ch)
    return out or [Event("gap", tool)]


def events(payload, cwd):
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        ti = {}
    # A patch may arrive under any file-tool name (Codex matches apply_patch as Edit and Write).
    carried = next((str(ti[k]) for k in ("command", "input", "patch") if isinstance(ti.get(k), str)
                    and patchmod.BEGIN in ti[k]), None)
    if tool in ("apply_patch", "Edit", "Write") and carried is not None:
        return patch_events(tool, carried, cwd)
    if tool == "apply_patch":
        return [Event("gap", tool)]
    if tool == "Write":
        return [Event("edit", tool, _abs(cwd, ti["file_path"]), full_text=str(ti.get("content", "")))] \
            if ti.get("file_path") else []
    if tool == "Edit":
        return [Event("edit", tool, _abs(cwd, ti["file_path"]),
                      edit={k: ti.get(k) for k in ("old_string", "new_string", "replace_all")})] \
            if ti.get("file_path") else []
    if tool in ("NotebookEdit", "MultiEdit"):
        raw = ti.get("notebook_path") or ti.get("file_path")
        return [Event("edit", tool, _abs(cwd, raw))] if raw else []
    if tool in ("Bash", "shell", "exec_command", "local_shell"):
        cmd = ti.get("command")
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        cmd = str(cmd or "")
        # Codex intercepts `apply_patch <<EOF ... EOF` inside a shell command: judge its files too
        shell_patch = patch_events(tool, cmd, cwd) if re.search(r"\bapply_patch\b", cmd) else None
        return [Event("command", tool, command=cmd)] + (shell_patch or [])
    if tool in ("Agent", "Task") or tool.endswith("spawn_agent"):
        prompt = ti.get("prompt") if tool in ("Agent", "Task") else ""
        return [Event("dispatch", tool, prompt=str(prompt or ""),
                      name=str(ti.get("task_name") or ti.get("description") or ""))]
    if tool.startswith("mcp__"):
        return [Event("mcp", tool, args=ti)]  # judged by an adapter when the server has one (mcp.py)
    if tool in READ_ONLY or not MAY_WRITE_RE.search(tool):
        return []
    return [Event("gap", tool)]
