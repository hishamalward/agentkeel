"""One decision for every host: captured Claude Code and Codex payloads, same task, same answer."""
import copy
import json
import os
import unittest
from unittest import mock

from helpers import ROOT, SESSION, RepoCase, run_hook

FIX = os.path.join(ROOT, "tests", "fixtures")


def fixture(host, name):
    with open(os.path.join(FIX, host, name + ".json")) as fh:
        return json.load(fh)


def codex_patch(repo, body, session=SESSION):
    p = fixture("codex", "apply-patch-add")
    p.update(cwd=repo, session_id=session)
    p["tool_input"]["command"] = "*** Begin Patch\n" + body + "\n*** End Patch"
    return p


def claude_write(repo, rel, content="", session=SESSION):
    p = fixture("claude", "pretooluse-write")
    p.update(cwd=repo, session_id=session)
    p["tool_input"] = {"file_path": os.path.join(repo, rel), "content": content}
    return p


def codex_bash(repo, command, session=SESSION):
    p = fixture("codex", "bash")
    p.update(cwd=repo, session_id=session)
    p["tool_input"]["command"] = command
    return p


def claude_bash(repo, command, session=SESSION):
    p = fixture("claude", "pretooluse-bash")
    p.update(cwd=repo, session_id=session)
    p["tool_input"]["command"] = command
    return p


class CapturedShapes(unittest.TestCase):
    """The fixtures are real captures (Codex 0.160.0 on 2026-10-04; Claude Code 2.1.241)."""

    def test_codex_events(self):
        import helpers  # noqa: F401
        from agentkeel_core import host
        ev = lambda n: host.events(fixture("codex", n), "/r")
        self.assertEqual([(e.kind, e.path) for e in ev("apply-patch-add")], [("edit", "/r/d.py")])
        self.assertEqual(ev("apply-patch-add")[0].full_text, "d = 1\n")
        self.assertEqual([e.path for e in ev("apply-patch-move")], ["/r/b.py", "/r/b2.py"])
        self.assertEqual([e.path for e in ev("apply-patch-delete")], ["/r/c.py"])
        self.assertEqual(ev("bash")[0].kind, "command")
        d = ev("spawn-agent")[0]
        self.assertEqual((d.kind, d.name, d.prompt), ("dispatch", "echo_sub", ""))
        self.assertEqual(host.events(fixture("codex", "session-start"), "/r"), [])

    def test_claude_events(self):
        import helpers  # noqa: F401
        from agentkeel_core import host
        self.assertEqual(host.events(fixture("claude", "pretooluse-write"), "/r")[0].kind, "edit")
        self.assertEqual(host.events(fixture("claude", "pretooluse-agent"), "/r")[0].kind, "dispatch")

    def test_unknown_write_tool_is_a_visible_gap(self):
        import helpers  # noqa: F401
        from agentkeel_core import host
        self.assertEqual(host.events({"tool_name": "write_file_v2", "tool_input": {}}, "/r")[0].kind, "gap")
        self.assertEqual(host.events({"tool_name": "mcp__fs__write", "tool_input": {}}, "/r"), [])
        self.assertEqual(host.events({"tool_name": "Read", "tool_input": {}}, "/r"), [])


class SameDecision(RepoCase):
    def both(self, claude, codex):
        a, b = self.hook(claude), self.hook(codex)
        self.assertEqual(a[0], b[0], (a, b))
        return a[0]

    def test_no_task_refuses_both(self):
        self.assertEqual(self.both(claude_write(self.repo, "d.py", "d = 1\n"),
                                   codex_patch(self.repo, "*** Add File: d.py\n+d = 1")), 2)

    def test_owned_worktree_allows_both(self):
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.both(claude_write(self.repo, "d.py", "d = 1\n"),
                                   codex_patch(self.repo, "*** Add File: d.py\n+d = 1")), 0)

    def test_protected_branch_refuses_both(self):
        self.declare()
        self.assertEqual(self.both(claude_write(self.repo, "d.py"), codex_patch(self.repo, "*** Add File: d.py\n+x")), 2)

    def test_shipping_command_same_on_both(self):
        self.declare(); self.branch("feat/x")
        for cmd, want in (("git push origin feat/x && git push origin main", 2), ("git status", 0)):
            self.assertEqual(self.both(claude_bash(self.repo, cmd), codex_bash(self.repo, cmd)), want, cmd)

    def test_refusal_text_is_the_same(self):
        a = self.hook(claude_write(self.repo, "d.py"))[1]
        b = self.hook(codex_patch(self.repo, "*** Add File: d.py\n+x"))[1]
        self.assertEqual(a, b); self.assertIn("no task is declared", a)

    def test_patch_judges_every_path(self):
        self.declare(); self.branch("feat/x")
        outside = os.path.join(self.tmp, "elsewhere", "x.py")
        code, err = self.hook(codex_patch(self.repo, f"*** Update File: a.py\n*** Move to: {outside}\n@@\n-a\n+b"))
        self.assertEqual(code, 2)
        code, _ = self.hook(codex_patch(self.repo, "*** Delete File: .claude/settings.json"))
        self.assertEqual(code, 2)

    def test_patch_cannot_approve_or_change_an_approved_spec(self):
        self.declare(size="large", task="j"); self.branch("feat/j")
        os.makedirs(os.path.join(self.repo, "docs", "specs"))
        spec = os.path.join(self.repo, "docs", "specs", "j-spec.md")
        with open(spec, "w") as fh:
            fh.write("---\nstatus: draft\n---\n")
        approve = "*** Update File: docs/specs/j-spec.md\n@@\n-status: draft\n+status: approved\n+approved_by: me\n+approved_on: 2026-10-04"
        self.assertEqual(self.hook(codex_patch(self.repo, approve))[0], 2)
        self.assertEqual(self.hook(codex_patch(self.repo, "*** Update File: docs/specs/j-spec.md\n@@\n+notes"))[0], 0)
        with open(spec, "w") as fh:
            fh.write("---\nstatus: approved\napproved_by: h\napproved_on: 2026-10-04\n---\n")
        self.assertEqual(self.hook(codex_patch(self.repo, "*** Update File: docs/specs/j-spec.md\n@@\n+more"))[0], 2)
        self.assertEqual(self.hook(codex_patch(self.repo, "*** Delete File: docs/specs/j-spec.md"))[0], 2)
        self.assertEqual(self.hook(codex_patch(self.repo, "*** Add File: src/x.py\n+x"))[0], 0)  # approved now

    def test_unknown_tool_refused_with_a_reason(self):
        code, err = self.hook({"tool_name": "write_file_v2", "cwd": self.repo, "session_id": SESSION, "tool_input": {}})
        self.assertEqual(code, 2); self.assertIn("cannot read the tool", err)


class CodexPlanGate(RepoCase):
    def spawn(self, name):
        p = fixture("codex", "spawn-agent")
        p.update(cwd=self.repo, session_id=SESSION)
        p["tool_input"]["task_name"] = name
        return p

    def test_third_named_gate_refused_before_launch(self):
        self.declare(task="json-flag")
        g = lambda n: run_hook("plan-gate-guard.py", self.spawn(n), env=self.env)[0]
        self.assertEqual([g("plan_gate_review"), g("plan_gate_scope"), g("plan_gate_again")], [0, 0, 2])
        self.assertEqual(g("implement_task_3"), 0)


class SessionFromEnv(unittest.TestCase):
    def setUp(self):
        import helpers  # noqa: F401
        from agentkeel_core import record
        self.record = record

    def test_single_host_variable(self):
        self.assertEqual(self.record.session_from_env({"CODEX_THREAD_ID": "c"}), "c")
        self.assertEqual(self.record.session_from_env({"CLAUDE_CODE_SESSION_ID": "a"}), "a")

    def test_nested_agents_pick_the_nearest(self):
        both = {"CODEX_THREAD_ID": "c", "CLAUDE_CODE_SESSION_ID": "a"}
        with mock.patch.object(self.record, "nearest_host", return_value="codex"):
            self.assertEqual(self.record.session_from_env(both), "c")
        with mock.patch.object(self.record, "nearest_host", return_value="claude"):
            self.assertEqual(self.record.session_from_env(both), "a")
        with mock.patch.object(self.record, "nearest_host", return_value=None):
            self.assertIsNone(self.record.session_from_env(both))
        self.assertEqual(self.record.session_from_env({**both, "AGENTKEEL_SESSION_ID": "x"}), "x")


class SessionOwnership(RepoCase):
    """A task record belongs to one session: no shared hint, and only the caller's own id inline."""

    def task(self, env, *args):
        import subprocess, sys
        from helpers import HOOKS
        clean = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "AGENTKEEL_SESSION_ID")}
        return subprocess.run([sys.executable, os.path.join(HOOKS, "task.py"), *args], cwd=self.repo,
                              capture_output=True, text=True, env={**clean, **self.env, **env})

    def test_parent_guard_call_cannot_hand_its_session_to_a_child(self):
        from agentkeel_core import record
        self.declare(task="parent-review", allow=("review",), session="codex-thread")
        # the parent's guard sees a task.py command in this folder, then a nested child runs task.py
        self.assertEqual(self.hook(codex_bash(self.repo, "python3 task.py show", session="codex-thread"))[0], 0)
        both = {"CODEX_THREAD_ID": "codex-thread", "CLAUDE_CODE_SESSION_ID": "child-claude"}
        self.task(both, "start", "child", "--size", "small", "--allow", "implement")
        if record.nearest_host() != "codex":  # the child is not itself under a Codex process here
            self.assertEqual(self.record("codex-thread")["task"], "parent-review")

    def test_inline_id_must_be_the_callers_own(self):
        cmd = lambda v: f"AGENTKEEL_SESSION_ID={v} python3 task.py start y --size small --allow implement"
        code, err = self.hook(codex_bash(self.repo, cmd("someone-else"), session="me"))
        self.assertEqual(code, 2); self.assertIn("not this session's id", err)
        self.assertEqual(self.hook(codex_bash(self.repo, cmd("me"), session="me"))[0], 0)
        self.assertEqual(self.hook(codex_bash(self.repo, "env AGENTKEEL_SESSION_ID=x python3 task.py show", session="me"))[0], 2)
        code, err = self.hook(codex_bash(self.repo, "export AGENTKEEL_SESSION_ID=me", session="me"))
        self.assertEqual(code, 2); self.assertIn("refusing to export", err)

    def test_ambiguous_environment_fails_closed_and_says_how(self):
        out = self.task({"AGENTKEEL_SESSION_ID": "", "CODEX_THREAD_ID": "a", "CLAUDE_CODE_SESSION_ID": "b"}, "start", "z", "--size", "small", "--allow", "review")
        from agentkeel_core import record
        if record.nearest_host() is None:
            self.assertEqual(out.returncode, 2); self.assertIn("AGENTKEEL_SESSION_ID=<id>", out.stderr)

    def test_session_start_prints_the_id(self):
        import subprocess, sys
        from helpers import HOOKS
        out = subprocess.run([sys.executable, os.path.join(HOOKS, "session-start.py")], text=True, capture_output=True,
                             input=json.dumps(fixture("codex", "session-start") | {"cwd": self.repo}), env={**os.environ, **self.env})
        self.assertIn("AGENTKEEL_SESSION_ID=" + fixture("codex", "session-start")["session_id"], out.stdout)


class PlanSizeOnCodex(unittest.TestCase):
    def test_patch_to_a_long_plan_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            t = os.path.realpath(t)
            os.makedirs(os.path.join(t, "docs", "plans"))
            with open(os.path.join(t, "docs", "plans", "x-plan.md"), "w") as fh:
                fh.write("row\n" * 301)
            p = codex_patch(t, "*** Update File: docs/plans/x-plan.md\n@@\n+row")
            self.assertEqual(run_hook("plan-size-guard.sh", p)[0], 2)
            p = codex_patch(t, "*** Update File: notes.md\n@@\n+row")
            self.assertEqual(run_hook("plan-size-guard.sh", p)[0], 0)


if __name__ == "__main__":
    unittest.main()


class PluginOptIn(RepoCase):
    def run_plugin(self, name, payload):
        import subprocess, sys
        from helpers import HOOKS
        cmd = ([sys.executable] if name.endswith(".py") else ["bash"]) + [os.path.join(HOOKS, name), "--plugin"]
        out = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, cwd=self.repo,
                             env={**os.environ, **self.env})
        return out.returncode, out.stdout

    def test_plugin_guards_are_inert_without_agentkeel_json(self):
        p = claude_write(self.repo, "d.py")
        self.assertEqual(self.run_plugin("task-guard.py", p)[0], 0)
        self.assertEqual(self.run_plugin("secret-guard.py", claude_bash(self.repo, "cat .env"))[0], 0)
        self.assertEqual(self.run_plugin("session-start.py", fixture("codex", "session-start") | {"cwd": self.repo})[1], "")
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            fh.write("{}\n")
        self.assertEqual(self.run_plugin("task-guard.py", p)[0], 2)
        self.assertEqual(self.run_plugin("secret-guard.py", claude_bash(self.repo, "cat .env"))[0], 2)
        out = self.run_plugin("session-start.py", fixture("codex", "session-start") | {"cwd": self.repo})[1]
        self.assertIn("task.py\" start", out)

    def test_one_hooks_file_serves_both_plugin_manifests(self):
        with open(os.path.join(ROOT, ".codex-plugin", "plugin.json")) as fh:
            self.assertEqual(json.load(fh)["hooks"], "./hooks/hooks.json")
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as fh:
            cmds = [h["command"] for gs in json.load(fh)["hooks"].values() for g in gs for h in g["hooks"]]
        self.assertTrue(all("${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}" in c and c.endswith("--plugin") for c in cmds))


class StageTwoReviewFindings(RepoCase):
    """Regression tests for the Stage 2 review (2026-10-04), one per finding."""

    APPROVED = ("---\nstatus: approved\napproved_by: h\napproved_on: 2026-10-04\n---\n\n"
                "## 4. Blast radius\n\n- **Changes**: `src/a.py`\n")

    def setUp(self):
        super().setUp()
        self.declare(size="large", task="x"); self.branch("feat/x")
        os.makedirs(os.path.join(self.repo, "docs", "specs"))
        self.spec = os.path.join(self.repo, "docs", "specs", "x-spec.md")

    def put_spec(self, text):
        with open(self.spec, "w") as fh:
            fh.write(text)

    def patch(self, body):
        return self.hook(codex_patch(self.repo, body))[0]

    def edit(self, old, new):
        p = fixture("claude", "pretooluse-edit")
        p.update(cwd=self.repo, session_id=SESSION)
        p["tool_input"] = {"file_path": self.spec, "old_string": old, "new_string": new, "replace_all": False}
        return self.hook(p)[0]

    def test_superseded_line_in_the_body_does_not_unlock_an_approved_spec(self):
        self.put_spec(self.APPROVED)
        body = ("*** Update File: docs/specs/x-spec.md\n@@\n-- **Changes**: `src/a.py`\n"
                "+- **Changes**: `src/**`\n+status: superseded")
        self.assertEqual(self.patch(body), 2)
        self.assertEqual(self.edit("`src/a.py`", "`src/**`\nstatus: superseded"), 2)

    def test_quoted_or_piecewise_approval_refused_on_both_hosts(self):
        self.put_spec("---\nstatus: draft\napproved_by: h\napproved_on: 2026-10-04\n---\n")
        self.assertEqual(self.patch('*** Update File: docs/specs/x-spec.md\n@@\n-status: draft\n+status: "approved"'), 2)
        self.assertEqual(self.edit("status: draft", 'status: "approved"'), 2)
        self.put_spec("---\nstatus: approved\n---\n")
        self.assertEqual(self.patch("*** Update File: docs/specs/x-spec.md\n@@\n status: approved\n+approved_by: agent\n+approved_on: 2026-10-04"), 2)
        self.assertEqual(self.edit("status: approved", "status: approved\napproved_by: agent\napproved_on: 2026-10-04"), 2)

    def test_patch_that_does_not_fit_a_spec_is_refused(self):
        self.put_spec("---\nstatus: draft\n---\n")
        self.assertEqual(self.patch("*** Update File: docs/specs/x-spec.md\n@@\n-no such line\n+x"), 2)
        self.assertEqual(self.patch("*** Update File: docs/specs/x-spec.md\n@@\n status: draft\n+owner: me"), 0)

    def test_patch_under_edit_or_write_names_and_hidden_headers(self):
        shared = os.path.join(self.primary, "evil.py")
        for tool in ("Edit", "Write"):
            p = {"tool_name": tool, "cwd": self.repo, "session_id": SESSION,
                 "tool_input": {"command": f"*** Begin Patch\n*** Add File: {shared}\n+x\n*** End Patch"}}
            self.assertEqual(self.hook(p)[0], 2, tool)
        self.assertEqual(self.patch(f"*** Add File: docs/ok.md\n+x\n  *** Add File: {shared}\n+y"), 2)
        two = codex_patch(self.repo, "*** Add File: docs/ok.md\n+x")
        two["tool_input"]["command"] += f"\n*** Begin Patch\n*** Add File: {shared}\n+y\n*** End Patch"
        self.assertEqual(self.hook(two)[0], 2)
        sh = codex_bash(self.repo, f"apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: {shared}\n+y\n*** End Patch\nEOF")
        self.assertEqual(self.hook(sh)[0], 2)


class PluginScope(RepoCase):
    def run_plugin(self, name, payload):
        import subprocess, sys
        from helpers import HOOKS
        out = subprocess.run([sys.executable, os.path.join(HOOKS, name), "--plugin"], input=json.dumps(payload),
                             capture_output=True, text=True, env={**os.environ, **self.env})
        return out.returncode

    def setUp(self):
        super().setUp()
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            fh.write("{}\n")
        self.outside = os.path.join(self.tmp, "outside"); os.makedirs(self.outside)

    def test_opt_in_follows_the_target_not_the_session_folder(self):
        self.declare(); self.branch("feat/x")
        for cmd in (f"cd {self.repo} && git push origin main", f"git -C {self.repo} push origin main"):
            self.assertEqual(self.run_plugin("task-guard.py", codex_bash(self.outside, cmd)), 2, cmd)
        no_task = claude_write(self.outside, os.path.join(self.repo, "src", "a.py"), session="no-task-session")
        self.assertEqual(self.run_plugin("task-guard.py", no_task), 2)

    def test_deleting_agentkeel_json_does_not_switch_the_guards_off(self):
        self.declare(); self.branch("feat/x")
        self.assertEqual(self.run_plugin("task-guard.py", codex_bash(self.repo, "git push origin main")), 2)
        os.remove(os.path.join(self.repo, "agentkeel.json"))
        self.assertEqual(self.run_plugin("task-guard.py", codex_bash(self.repo, "git push origin main")), 2)


class ConfiguredRoute(unittest.TestCase):
    """The shipped hook configurations and the adapter together: what reaches the task guard."""

    CONFIGS = [os.path.join(ROOT, "templates", "claude-hooks.json"), os.path.join(ROOT, "templates", "codex-hooks.json"),
               os.path.join(ROOT, "hooks", "hooks.json")]

    @staticmethod
    def matches(matcher, tool):
        import re
        return matcher in ("*", "") or re.fullmatch(matcher, tool) is not None or re.search(matcher, tool) is not None

    def task_guard_matchers(self, path):
        with open(path) as fh:
            groups = json.load(fh)["hooks"]["PreToolUse"]
        return [g["matcher"] for g in groups if any("task-guard.py" in h["command"] for h in g["hooks"])]

    def test_unknown_writer_reaches_the_guard_and_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            for cfg in self.CONFIGS:
                for tool, want in (("write_file_v2", 2), ("write_stdin", 2), ("Read", 0), ("CronCreate", 0),
                                   ("TaskCreate", 0), ("mcp__fs__write_file", 0)):
                    routed = any(self.matches(m, tool) for m in self.task_guard_matchers(cfg))
                    self.assertTrue(routed, (cfg, tool))
                    code, err = run_hook("task-guard.py", {"tool_name": tool, "cwd": home, "session_id": "s",
                                                           "tool_input": {}}, env={"AGENTKEEL_HOME": home})
                    self.assertEqual(code, want, (cfg, tool, err))
