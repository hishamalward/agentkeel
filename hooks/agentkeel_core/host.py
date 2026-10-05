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
  gap       a tool that may write but that agentkeel cannot read: refused, so the gap is visible
"""
import os
import re
from dataclasses import dataclass, field

from . import patch as patchmod

READ_ONLY = {"Read", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "TodoWrite", "TaskList",
             "TaskGet", "ToolSearch", "view_image", "update_plan", "read_file", "list_dir"}
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
    change: object = None             # patch.FileChange for an apply_patch update


def _abs(cwd, p):
    return os.path.realpath(os.path.join(cwd, os.path.expanduser(str(p))))


def events(payload, cwd):
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        ti = {}
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
    if tool == "apply_patch" or (tool in ("Edit", "Write") and "*** Begin Patch" in str(ti.get("command", ""))):
        text = patchmod.envelope(str(ti.get("command") or ti.get("input") or ti.get("patch") or ""))
        if text is None:
            return [Event("gap", tool)]
        out = []
        for ch in patchmod.parse(text):
            out.append(Event("edit", tool, _abs(cwd, ch.path), full_text=ch.new_content(), change=ch))
        return out or [Event("gap", tool)]
    if tool in ("Bash", "shell", "exec_command", "local_shell"):
        cmd = ti.get("command")
        if isinstance(cmd, list):
            cmd = " ".join(str(c) for c in cmd)
        return [Event("command", tool, command=str(cmd or ""))]
    if tool in ("Agent", "Task") or tool.endswith("spawn_agent"):
        prompt = ti.get("prompt") if tool in ("Agent", "Task") else ""
        return [Event("dispatch", tool, prompt=str(prompt or ""),
                      name=str(ti.get("task_name") or ti.get("description") or ""))]
    if tool.startswith("mcp__") or tool in READ_ONLY or not MAY_WRITE_RE.search(tool):
        return []
    return [Event("gap", tool)]
