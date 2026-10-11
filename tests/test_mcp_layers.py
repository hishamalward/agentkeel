"""MCP catalog layers: plugin default <- AGENTKEEL_HOME/mcp_catalog.json <- agentkeel.json "mcp", generic
services, guards.mcp_unknown, the unseen log and task.py mcp draft."""
import json
import os
import subprocess
import sys
import unittest

from helpers import HOOKS, SESSION, RepoCase

from agentkeel_core import mcp, mcp_catalog, record


class Merge(unittest.TestCase):
    def test_lists_are_a_union_and_targets_come_from_the_most_specific_layer(self):
        plugin = {"svc": {"read": ["a"], "write": ["w"], "targets": ["p"], "target_arg": "pid", "note": "plugin"}}
        user = {"svc": {"read": ["b"], "targets": ["u"]}, "_comment": "skipped", "bad": []}
        project = {"svc": {"read": ["a", "c"], "write": ["w2"], "target_arg": "project"}}
        got = mcp_catalog.merge(plugin, user, project)["svc"]
        self.assertEqual(got["read"], ["a", "b", "c"])
        self.assertEqual(got["write"], ["w", "w2"])
        self.assertEqual(got["targets"], ["u"])
        self.assertEqual(got["target_arg"], "project")
        self.assertEqual(got["note"], "plugin")
        self.assertEqual(set(mcp_catalog.merge(plugin, user, project)), {"svc"})
        # a project that lists targets again replaces them, even with none
        self.assertEqual(mcp_catalog.merge(plugin, user, {"svc": {"targets": []}})["svc"]["targets"], [])

    def test_merged_reads_the_home_file_and_the_project_block(self):
        import tempfile
        with tempfile.TemporaryDirectory() as home:
            env = {"AGENTKEEL_HOME": home}
            with open(os.path.join(home, "mcp_catalog.json"), "w") as fh:
                json.dump({"posthog": {"read": ["my-new-get"]}, "linear": {"read": ["list_issues"]}}, fh)
            cat = mcp_catalog.merged({"posthog": {"targets": ["1"]}, "linear": {"write": ["create_issue"]}}, env)
            self.assertIn("my-new-get", cat["posthog"]["read"])
            self.assertIn("insight-get", cat["posthog"]["read"])  # the plugin's list is kept
            self.assertEqual(cat["posthog"]["targets"], ["1"])
            self.assertEqual((cat["linear"]["read"], cat["linear"]["write"]), (["list_issues"], ["create_issue"]))
        self.assertEqual(set(mcp_catalog.merged(None, {"AGENTKEEL_HOME": "/nonexistent"})), set(mcp_catalog.SHIPPED))

    def test_a_layer_cannot_turn_a_listed_write_into_a_read(self):
        cat = mcp_catalog.merged({"revenuecat": {"read": ["create_product"]}}, {"AGENTKEEL_HOME": "/nonexistent"})
        call = mcp.match("mcp__revenuecat__create_product", cat)
        call.args = {"project_id": "p"}
        self.assertEqual(mcp.classify(call)[0], mcp.WRITE)

    def test_unclassified_is_a_write(self):
        self.assertEqual(mcp._listed("t", {"unclassified": ["t"]}), mcp.WRITE)
        self.assertEqual(mcp._listed("t", {"unclassified": ["t"], "publish": ["t"]}), mcp.PUBLISH)
        self.assertEqual(mcp._listed("t", {"read": ["x"]}), mcp.UNKNOWN)


class Generic(unittest.TestCase):
    CAT = mcp_catalog.merge(mcp_catalog.DEFAULT, {
        "linear": {"servers": ["linear", "plugin_linear_linear"], "read": ["list_issues"],
                   "write": ["create_issue"], "publish": ["send_update"], "unclassified": ["odd_tool"],
                   "target_arg": "teamId"},
        "notes": {"read": ["get_note"], "write": ["put_note"]}})

    def classify(self, tool, args=None):
        call = mcp.match(tool, self.CAT)
        self.assertIsNotNone(call, tool)
        call.args = args or {}
        return mcp.classify(call)

    def test_a_generic_service_is_found_by_its_servers_or_its_key(self):
        self.assertEqual(mcp.match("mcp__plugin_linear_linear__list_issues", self.CAT).service, "linear")
        self.assertEqual(mcp.match("mcp__notes__get_note", self.CAT).service, "notes")
        self.assertIsNone(mcp.match("mcp__other__get_note", self.CAT))
        self.assertEqual(mcp.match("mcp__dfs-mcp__docs_search", self.CAT).service, "dataforseo")

    def test_classes_with_a_target_arg(self):
        self.assertEqual(self.classify("mcp__linear__list_issues")[0], mcp.READ)
        self.assertEqual(self.classify("mcp__linear__create_issue", {"teamId": "T1"})[:2], (mcp.WRITE, "T1"))
        self.assertEqual(self.classify("mcp__linear__create_issue")[:2], (mcp.WRITE, None))
        self.assertEqual(self.classify("mcp__linear__send_update", {"teamId": "T1"})[:2], (mcp.PUBLISH, "T1"))
        self.assertEqual(self.classify("mcp__linear__odd_tool", {"teamId": "T1"})[:2], (mcp.WRITE, "T1"))
        self.assertEqual(self.classify("mcp__linear__nope")[0], mcp.UNKNOWN)

    def test_classes_without_a_target_arg_have_no_target(self):
        self.assertEqual(self.classify("mcp__notes__put_note", {"id": "x"})[:2], (mcp.WRITE, mcp.NO_TARGET))
        # an unclassified name with no target_arg is a write to an unknown target
        cat = mcp_catalog.merge(self.CAT, {"notes": {"unclassified": ["odd"]}})
        call = mcp.match("mcp__notes__odd", cat)
        self.assertEqual(mcp.classify(call)[:2], (mcp.WRITE, None))
        rec = {"task": "x", "permissions": ["remote-write"]}
        self.assertIn("cannot tell which", mcp.judge(call, rec, cat))
        self.assertIsNone(mcp.judge(call, rec, mcp_catalog.merge(cat, {"notes": {"targets": ["*"]}})))
        rec = {"task": "x", "permissions": ["remote-write"]}
        self.assertIsNone(mcp.judge(mcp.match("mcp__notes__put_note", self.CAT), rec, self.CAT))
        self.assertIn("'remote-write' permission",
                      mcp.judge(mcp.match("mcp__notes__put_note", self.CAT), {"task": "x", "permissions": []}, self.CAT))

    def test_a_target_arg_needs_a_listed_target(self):
        rec = {"task": "x", "permissions": ["remote-write", "publish"]}
        cat = mcp_catalog.merge(self.CAT, {"linear": {"targets": ["T1"]}})
        call = mcp.match("mcp__linear__create_issue", cat)
        call.args = {"teamId": "T1"}
        self.assertIsNone(mcp.judge(call, rec, cat))
        call.args = {"teamId": "T2"}
        self.assertIn("targets 'T2'", mcp.judge(call, rec, cat))
        call.args = {}
        self.assertIn("cannot tell which", mcp.judge(call, rec, cat))


class UnknownServers(RepoCase):
    def setUp(self):
        super().setUp()
        self.scratch = os.path.join(self.tmp, "scratch")

    def policy(self, **data):
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump(data, fh)

    def declare(self, **kw):
        super().declare(**kw)
        rec = self.record()
        rec["scratch"] = self.scratch
        record.atomic_write_json(os.path.join(self.home, "tasks", SESSION + ".json"), rec)

    def call(self, tool, args=None):
        payload = {"tool_name": tool, "cwd": self.repo, "session_id": SESSION, "tool_input": args or {}}
        clean = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID", "CODEX_THREAD_ID")}
        return subprocess.run([sys.executable, os.path.join(HOOKS, "task-guard.py")], input=json.dumps(payload),
                              text=True, capture_output=True, env={**clean, **self.env}, timeout=60)

    def unseen(self):
        with open(os.path.join(self.scratch, mcp.UNSEEN_LOG)) as fh:
            return [json.loads(line) for line in fh]

    def test_default_is_pass(self):
        self.declare(allow=("review",))
        for policy in ({}, {"guards": {"task": "warn"}}):
            self.policy(**policy)
            out = self.call("mcp__mobbin__delete_everything", {"id": "x"})
            self.assertEqual((out.returncode, out.stdout.strip(), out.stderr.strip()), (0, "", ""))

    def test_warn_runs_the_call_with_a_message(self):
        self.declare(allow=("review",)); self.policy(guards={"mcp_unknown": "warn"})
        out = self.call("mcp__mobbin__search_screens", {"query": "paywall"})
        self.assertEqual(out.returncode, 0, out.stderr)
        msg = json.loads(out.stdout)["systemMessage"]
        self.assertIn("warn mode", msg); self.assertIn("`mobbin`", msg); self.assertIn("task.py mcp draft mobbin", msg)

    def test_block_refuses_and_says_how_to_add_the_server(self):
        self.declare(allow=("implement", "remote-write")); self.policy(guards={"mcp_unknown": "block"})
        out = self.call("mcp__mobbin__search_screens", {"query": "paywall"})
        self.assertEqual(out.returncode, 2)
        for text in ("`mobbin`", "`search_screens`", 'agentkeel.json under "mcp"', '"servers": ["mobbin"]'):
            self.assertIn(text, out.stderr)
        # an entry for the server takes it out of the mode: then its catalog decides
        self.policy(guards={"mcp_unknown": "block"}, mcp={"mobbin": {"read": ["search_screens"]}})
        self.assertEqual(self.call("mcp__mobbin__search_screens", {"query": "paywall"}).returncode, 0)
        self.assertEqual(self.call("mcp__mobbin__delete_all", {}).returncode, 2)

    def test_an_unknown_mode_blocks_and_shipped_servers_are_not_affected(self):
        self.declare(allow=("review",)); self.policy(guards={"mcp_unknown": "maybe"})
        self.assertEqual(self.call("mcp__mobbin__search_screens", {}).returncode, 2)
        self.policy(guards={"mcp_unknown": "block"})
        self.assertEqual(self.call("mcp__dfs-mcp__docs_search", {"query": "serp"}).returncode, 0)

    def test_the_unseen_log_keeps_one_line_per_tool_and_no_values(self):
        self.declare(allow=("review",))
        self.call("mcp__mobbin__search_screens", {"query": "secret-token-123", "limit": 5})
        self.call("mcp__mobbin__search_screens", {"query": "other"})
        self.call("mcp__mobbin__get_screen", {"id": "s1"})
        self.call("mcp__dfs-mcp__docs_search", {"query": "serp"})  # a catalog server is not noted
        rows = self.unseen()
        self.assertEqual([(r["server"], r["tool"]) for r in rows],
                         [("mobbin", "search_screens"), ("mobbin", "get_screen")])
        self.assertEqual(rows[0]["args_keys"], ["limit", "query"])
        self.assertEqual(set(rows[0]), {"server", "tool", "args_keys", "ts"})
        with open(os.path.join(self.scratch, mcp.UNSEEN_LOG)) as fh:
            text = fh.read()
        for value in ("secret-token-123", "other", "s1"):
            self.assertNotIn(value, text)

    def test_draft_prints_an_entry_from_the_unseen_log(self):
        self.declare(allow=("review",))
        self.call("mcp__mobbin__search_screens", {"query": "q"})
        self.call("mcp__mobbin__get_screen", {"id": "s1"})
        self.call("mcp__figma__get_file", {"key": "k"})
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID", "CODEX_THREAD_ID")}
        env.update(self.env, CLAUDE_CODE_SESSION_ID=SESSION)
        run = lambda *a: subprocess.run([sys.executable, os.path.join(HOOKS, "task.py"), "mcp", "draft", *a],
                                        cwd=self.repo, capture_output=True, text=True, env=env)
        out = run("mobbin")
        self.assertEqual(out.returncode, 0, out.stderr)
        entry = json.loads(out.stdout)
        self.assertEqual(entry, {"mobbin": {"servers": ["mobbin"], "targets": [],
                                            "unclassified": ["get_screen", "search_screens"]}})
        self.assertIn("target_arg", out.stderr)
        # pasted as it is, every tool is judged a write and needs a listed target
        self.policy(mcp=entry)
        out = self.call("mcp__mobbin__get_screen", {"id": "s1"})
        self.assertEqual(out.returncode, 2); self.assertIn("'remote-write' permission", out.stderr)
        self.declare(allow=("implement", "remote-write"))
        out = self.call("mcp__mobbin__get_screen", {"id": "s1"})
        self.assertEqual(out.returncode, 2); self.assertIn("cannot tell which", out.stderr)
        out = run("nothing-here")
        self.assertEqual(out.returncode, 2); self.assertIn("no call on the MCP server 'nothing-here'", out.stderr)


if __name__ == "__main__":
    unittest.main()
