"""agentkeel status page: one HTML page with what the guards know about this session's task.

`task.py status --html` renders it from the same facts `task.py status --json` prints, plus the
guard modes of the repository and every other task record in AGENTKEEL_HOME (a record whose
session is over is the one thing the hooks cannot tell apart from a live one; the human deletes
it). It reads; it changes nothing. The look is plain on purpose: nothing checks it.
"""
import html
import json
import os
import time

from . import record


def other_records(environ=os.environ, mine=None):
    """Every task record in AGENTKEEL_HOME/tasks except this session's: task, session, size,
    kind, age in hours, worktrees that still exist, and the path the human deletes."""
    out = []
    tasks = os.path.join(record.home(environ), "tasks")
    for name in sorted(os.listdir(tasks)) if os.path.isdir(tasks) else []:
        path = os.path.join(tasks, name)
        try:
            with open(path) as fh:
                rec = json.load(fh)
        except Exception:
            continue
        if not isinstance(rec, dict) or (mine and path == record.record_path(mine.get("session_id"), environ)):
            continue
        out.append({"task": rec.get("task"), "session": rec.get("session_id"), "size": rec.get("size"),
                    "kind": rec.get("kind") or "feature",
                    "hours": round((time.time() - int(rec.get("declared_at") or 0)) / 3600, 1),
                    "worktrees": [w for w in rec.get("worktrees") or [] if os.path.isdir(w)], "path": path})
    return out


def _e(x):
    return html.escape(str(x if x is not None else ""))


def _rows(rows):
    return "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)


def render(out, rec, pol, others):
    t = out.get("task") or {}
    fix = t.get("fix") or {}
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime())
    parts = [f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
             f"<title>AgentKeel status</title><style>body{{font:15px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 16px;color:#1b1f1e;background:#fafbfa}}"
             "table{border-collapse:collapse;width:100%;margin:.6rem 0 1.4rem;font-size:.9rem}th,td{text-align:left;vertical-align:top;padding:.35rem .5rem;border-bottom:1px solid #d9e0dd}"
             "th{font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;color:#5a6763}h1{font-size:1.5rem;margin:0 0 .2rem}h2{font-size:1.1rem;margin:1.6rem 0 .3rem}"
             ".pill{display:inline-block;padding:.05em .5em;border-radius:999px;font-size:.8rem;font-weight:600;background:#e4f0ed;color:#0e7c6b}.no{background:#f8e3e3;color:#9b2c2c}.warn{background:#f5eed8;color:#8a6a12}"
             "code{font-family:ui-monospace,Menlo,monospace;font-size:.88em;background:#eef2f0;padding:.05em .3em;border-radius:4px}</style></head><body>",
             f"<h1>AgentKeel status</h1><p>{_e(out.get('repository'))} at {when}. Derived facts only; this page changes nothing.</p>"]
    if t:
        parts.append("<h2>This session's task</h2><table><tr><th>Task</th><th>Size</th><th>Kind</th><th>Permissions</th><th>Deliverable</th></tr>"
                     + _rows([(t.get("id"), t.get("size"), t.get("kind"), ", ".join(t.get("permissions") or []),
                               (t.get("deliverable") or "none") + ("" if not t.get("deliverable") else
                                (" (present)" if os.path.exists(t["deliverable"]) else " (not written yet)")))]) + "</table>")
        if t.get("kind") == "fix":
            failed = any(e.get("result") == "failed" for e in t.get("evidence") or [])
            parts.append("<h2>Fix guards</h2><table><tr><th>Check</th><th>State</th></tr>" + _rows([
                ("a failed check on record", "yes" if failed else "no: run task.py verify -- <cmd> first"),
                ("cause line", t.get("cause") or "none: task.py cause \"X causes Y because Z\""),
                ("edit-then-fail cycles", f"{int(fix.get('cycles') or 0)} of 3" + (", re-opened by the human" if fix.get("reopened_at") else "")),
            ]) + "</table>")
    else:
        parts.append("<h2>This session's task</h2><p>none declared</p>")
    parts.append("<h2>Guard modes</h2><table><tr><th>Guard</th><th>Mode</th></tr>" + "".join(
        f"<tr><td>{_e(g)}</td><td><span class=\"pill{' no' if m in ('off', 'pass') else ' warn' if m == 'warn' else ''}\">{_e(m)}</span></td></tr>"
        for g, m in sorted((pol.get("guards") or {}).items())) + "</table><p>Set in agentkeel.json, <code>\"guards\": {\"task\": \"warn\"}</code>; missing means block. MCP policy is managed by MCPClerk.</p>")
    parts.append("<h2>Host Stop enforcement</h2><table><tr><th>Host</th><th>Status</th></tr>" + _rows([
        (host, "Stop enforcement not verified here; handoff/finish enforce HTML")
        for host in ("Claude Code", "Codex")])
        + "</table><p>Installed, enabled or trusted hooks do not prove this Stop hook ran in the current session.</p>")
    ws = out.get("worktrees") or []
    parts.append("<h2>Worktrees of this task</h2>" + ("<table><tr><th>Path</th><th>Branch</th><th>State</th><th>Changed files</th></tr>" + _rows([
        (w.get("path"), w.get("branch"), w.get("error") or (f"{w.get('ahead')} commit(s) not in {w.get('protected')}, " + ("merged" if w.get("merged") else "not merged") if "ahead" in w else "no protected branch to compare with"), w.get("changed", ""))
        for w in ws]) + "</table>" if ws else "<p>none</p>"))
    ev = t.get("evidence") or []
    parts.append("<h2>Checks on record</h2>" + ("<table><tr><th>When</th><th>Command</th><th>Result</th><th>Why</th></tr>" + _rows([
        (time.strftime("%H:%M", time.localtime(int(e.get("at") or 0))), e.get("command"), e.get("result"), e.get("reason")) for e in ev[-12:]]) + "</table>" if ev else "<p>none yet (task.py verify -- &lt;command&gt;)</p>"))
    parts.append("<h2>Other task records</h2><p>These include historical claims. The workspace manifest determines the current owner after transfer. To continue existing work, use task.py resume with explicit --from-session IDs after those sessions stop using the tree. Record age is not proof that a session ended.</p>"
                 + ("<table><tr><th>Task</th><th>Size, kind</th><th>Age (h)</th><th>Worktrees that exist</th><th>Record</th></tr>" + _rows([
                     (o["task"], f"{o['size']}, {o['kind']}", o["hours"], ", ".join(o["worktrees"]) or "none", o["path"]) for o in others]) + "</table>" if others else "<p>none</p>"))
    parts.append("</body></html>")
    return "\n".join(parts)
