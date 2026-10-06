"""MCP adapters: guarded servers' calls against the task's permissions and agentkeel.json's targets."""
import json
import os

from helpers import SESSION, RepoCase


class Adapters(RepoCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"mcp": {"revenuecat": {"targets": ["proj_ok"]}, "posthog": {"targets": ["111"]},
                               "sentry": {"targets": ["my-org"], "servers": ["sentry-eu"]}, "dataforseo": {}}}, fh)

    def call(self, tool, args=None, session=SESSION):
        return self.hook({"tool_name": tool, "cwd": self.repo, "session_id": session, "tool_input": args or {}})

    def ok(self, tool, args=None):
        code, err = self.call(tool, args)
        self.assertEqual(code, 0, f"{tool} {args}: {err}")

    def refused(self, tool, args=None, text=""):
        code, err = self.call(tool, args)
        self.assertEqual(code, 2, f"{tool} {args} was allowed")
        self.assertIn(text, err)
        return err

    def test_reads_pass_with_any_task_and_with_none(self):
        reads = [("mcp__revenuecat__list_apps", {"project_id": "proj_other"}),
                 ("mcp__revenuecat__get_product", {"project_id": "proj_ok", "product_id": "p"}),
                 ("mcp__plugin_posthog_posthog__exec", {"command": "search project-update"}),
                 ("mcp__plugin_posthog_posthog__exec", {"command": 'call execute-sql {"query": "select 1"}'}),
                 ("mcp__plugin_posthog_posthog__exec", {"command": 'call insight-get {"id": 4}'}),
                 ("mcp__plugin_posthog_posthog__exec", {"command": "switch 999"}),
                 ("mcp__plugin_sentry_sentry__search_issues", {"organizationSlug": "other-org"}),
                 ("mcp__plugin_sentry_sentry__execute_sentry_tool", {"name": "get_alert_rule", "arguments": {}}),
                 ("mcp__dfs-mcp__api_request", {"method": "GET", "path": "/v3/appendix/user_data"}),
                 ("mcp__dfs-mcp__docs_search", {"query": "serp"})]
        for tool, args in reads:
            self.ok(tool, args)
        self.declare(allow=("review",))
        for tool, args in reads:
            self.ok(tool, args)

    def test_a_permitted_write_to_an_allowed_target_passes(self):
        self.declare(allow=("implement", "remote-write"))
        self.ok("mcp__revenuecat__create_product", {"project_id": "proj_ok", "store_identifier": "plus"})
        self.ok("mcp__revenuecat__archive_offering", {"project_id": "proj_ok", "offering_id": "o"})
        self.ok("mcp__plugin_posthog_posthog__exec",
                {"command": 'call project-settings-update {"id": 111, "autocapture_opt_out": true}'})
        self.ok("mcp__plugin_sentry_sentry__update_issue",
                {"organizationSlug": "my-org", "issueId": "X-1", "status": "resolved"})
        self.ok("mcp__sentry-eu__update_issue", {"organizationSlug": "my-org", "issueId": "X-2", "status": "resolved"})

    def test_a_review_task_and_a_push_task_change_nothing(self):
        self.declare(allow=("review",))
        self.refused("mcp__revenuecat__create_product", {"project_id": "proj_ok"}, "'remote-write' permission")
        self.declare(allow=("implement", "merge", "push"))
        err = self.refused("mcp__plugin_sentry_sentry__update_issue",
                           {"organizationSlug": "my-org", "issueId": "X-1", "status": "resolved"}, "remote-write")
        self.assertIn("git push permission does not cover", err)

    def test_another_target_is_refused(self):
        self.declare(allow=("implement", "remote-write"))
        self.refused("mcp__revenuecat__create_product", {"project_id": "proj_b"}, "targets 'proj_b'")
        self.refused("mcp__plugin_posthog_posthog__exec",
                     {"command": 'call project-settings-update {"id": 222, "heatmaps_opt_in": true}'}, "targets '222'")
        self.refused("mcp__plugin_sentry_sentry__update_issue", {"organizationSlug": "their-org", "issueId": "1"},
                     "targets 'their-org'")

    def test_a_write_with_no_readable_target_is_refused_unless_every_target_is_allowed(self):
        self.declare(allow=("implement", "remote-write"))
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": 'call feature-flag-create {"key": "x"}'},
                     "cannot tell which")
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"mcp": {"posthog": {"targets": ["*"]}}}, fh)
        self.ok("mcp__plugin_posthog_posthog__exec", {"command": 'call feature-flag-create {"key": "x"}'})

    def test_paid_calls_need_paid_job(self):
        live = ("mcp__dfs-mcp__api_request", {"method": "POST", "path": "/v3/serp/google/organic/live/advanced"})
        post = ("mcp__dfs-mcp__api_request", {"method": "POST", "path": "/v3/serp/google/organic/task_post"})
        self.declare(allow=("implement", "remote-write"))
        for tool, args in (live, post):
            self.refused(tool, args, "'paid-job' permission")
        self.refused("mcp__plugin_sentry_sentry__analyze_issue_with_seer", {"organizationSlug": "my-org"}, "paid-job")
        self.declare(allow=("implement", "paid-job"))
        for tool, args in (live, post):
            self.ok(tool, args)

    def test_unknown_actions_are_refused_even_with_every_permission(self):
        self.declare(allow=("implement", "remote-write", "paid-job"))
        self.refused("mcp__revenuecat__frobnicate_offering", {"project_id": "proj_ok"}, "not an action")
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": "call weird-thing {}"}, "not an action")
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": "rm -rf"}, "not an action")
        self.refused("mcp__dfs-mcp__api_request", {"method": "POST", "path": "/v3/something/new"}, "not an action")
        self.refused("mcp__plugin_sentry_sentry__execute_sentry_tool", {"name": "mystery", "arguments": {}},
                     "not an action")

    def test_no_task_refuses_writes_and_paid_calls(self):
        self.refused("mcp__revenuecat__create_product", {"project_id": "proj_ok"}, "no task")
        self.refused("mcp__dfs-mcp__api_request", {"method": "POST", "path": "/v3/x/live"}, "no task")

    def test_servers_without_an_adapter_pass(self):
        self.declare(allow=("review",))
        self.ok("mcp__mobbin__search_screens", {"query": "paywall"})
        self.ok("mcp__someserver__delete_everything", {})

    def test_a_server_outside_an_opted_in_repository_passes(self):
        outside = os.path.join(self.tmp, "plain")
        os.makedirs(outside)
        code, err = self.hook({"tool_name": "mcp__revenuecat__create_product", "cwd": outside,
                               "session_id": SESSION, "tool_input": {"project_id": "x"}})
        # the guard (not as a plugin) still judges: no agentkeel.json means no targets listed
        self.assertEqual(code, 2)
