"""MCP adapters: guarded servers' calls against the task's permissions and agentkeel.json's targets."""
import json
import os
import subprocess
import sys

from helpers import HOOKS, SESSION, RepoCase


class Adapters(RepoCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"mcp": {"revenuecat": {"targets": ["proj_ok"]}, "posthog": {"targets": ["111"]},
                               "sentry": {"targets": ["my-org"], "servers": ["sentry-eu"]}, "dataforseo": {}}}, fh)
        # the hosts' own configuration lives in a private home, so no real connection is read
        self.hosthome = os.path.join(self.tmp, "hosthome")
        os.makedirs(os.path.join(self.hosthome, ".claude", "plugins"))
        os.makedirs(os.path.join(self.hosthome, ".codex"))
        self.env.update({"HOME": self.hosthome, "CODEX_HOME": os.path.join(self.hosthome, ".codex"),
                         "CLAUDE_PROJECT_DIR": self.repo, "CLAUDE_CONFIG_DIR": ""})

    def claude_servers(self, servers, scope="user", approved=()):
        """A Claude Code entry set: user scope in ~/.claude.json, the project's local scope there, or
        the project's own .mcp.json (used by the host only for the servers the human approved)."""
        path = os.path.join(self.hosthome, ".claude.json")
        data = json.load(open(path)) if os.path.exists(path) else {}
        if scope == "project":
            with open(os.path.join(self.repo, ".mcp.json"), "w") as fh:
                json.dump({"mcpServers": servers}, fh)
            data.setdefault("projects", {}).setdefault(self.repo, {})["enabledMcpjsonServers"] = list(approved)
        elif scope == "local":
            data.setdefault("projects", {}).setdefault(self.repo, {})["mcpServers"] = servers
        else:
            data["mcpServers"] = servers
        with open(path, "w") as fh:
            json.dump(data, fh)

    def claude_plugin(self, plugin, servers):
        install = os.path.join(self.hosthome, ".claude", "plugins", "cache", plugin, plugin, "1.0.0")
        os.makedirs(install, exist_ok=True)
        with open(os.path.join(install, ".mcp.json"), "w") as fh:
            json.dump({"mcpServers": servers}, fh)
        with open(os.path.join(self.hosthome, ".claude", "plugins", "installed_plugins.json"), "w") as fh:
            json.dump({"version": 2, "plugins": {f"{plugin}@{plugin}": [{"scope": "user", "installPath": install}]}}, fh)

    def codex_servers(self, toml):
        with open(os.path.join(self.hosthome, ".codex", "config.toml"), "w") as fh:
            fh.write(toml)

    def codex_call(self, tool, args):
        return self.hook({"tool_name": tool, "cwd": self.repo, "session_id": SESSION, "tool_input": args,
                          "turn_id": "t1"})

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

    def launched(self, env=None, codex=False):
        """Exercise the production environment filter, not just task-guard.py directly."""
        with open(os.path.join(self.home, "interpreter"), "w") as fh:
            fh.write(sys.executable + "\n")
        payload = {"tool_name": "mcp__posthog__exec", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {"command": 'call update-feature-flag {"id": 4, "name": "x"}'}}
        if codex:
            payload["turn_id"] = "t1"
        return subprocess.run(["/bin/sh", os.path.join(HOOKS, "run.sh"), "task-guard.py"],
                              input=json.dumps(payload), text=True, capture_output=True,
                              env={**os.environ, **self.env, **(env or {})}, cwd=self.repo, timeout=60)

    def test_launcher_uses_the_hosts_config_root(self):
        self.declare(allow=("implement", "remote-write"))
        self.claude_servers({"posthog": {"url": "https://mcp.posthog.com/mcp?project_id=111"}})
        self.codex_servers('[mcp_servers.posthog]\nurl = "https://mcp.posthog.com/mcp?project_id=111"\n')
        custom = os.path.join(self.tmp, "custom-host")
        os.makedirs(custom)
        for codex, key, filename in ((False, "CLAUDE_CONFIG_DIR", ".claude.json"),
                                     (True, "CODEX_HOME", "config.toml")):
            for pin, expected in (("222", 2), ("111", 0)):
                with self.subTest(codex=codex, pin=pin):
                    with open(os.path.join(custom, filename), "w") as fh:
                        url = "https://mcp.posthog.com/mcp?project_id=" + pin
                        if codex:
                            fh.write('[mcp_servers.posthog]\nurl = "' + url + '"\n')
                        else:
                            json.dump({"mcpServers": {"posthog": {"url": url}}}, fh)
                    result = self.launched({key: custom}, codex=codex)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    if expected:
                        self.assertIn("pinned to project '222'", result.stderr)

    def test_launcher_does_not_drop_an_unresolved_or_blank_pin(self):
        self.declare(allow=("implement", "remote-write"))
        base = "https://mcp.posthog.com/mcp?project_id=111"
        entries = [
            {"url": base, "headers": {"x-posthog-project-id": "${POSTHOG_PIN}"}},
            {"url": base, "headers": {"x-posthog-project-id": "${POSTHOG_PIN:-111}"}},
            {"url": base, "headers": {"x-posthog-project-id": ""}},
            {"url": base + "&project_id="},
        ]
        for entry in entries:
            with self.subTest(entry=entry):
                self.claude_servers({"posthog": entry})
                result = self.launched({"POSTHOG_PIN": "222"})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("is not pinned", result.stderr)
        self.claude_servers({"posthog": {"url": base,
                                         "headers": {"x-posthog-project-id": "111"}}})
        self.assertEqual(self.launched().returncode, 0)

    def test_reads_pass_with_any_task_and_with_none(self):
        reads = [("mcp__revenuecat__list_apps", {"project_id": "proj_other"}),
                 ("mcp__revenuecat__get_product", {"project_id": "proj_ok", "product_id": "p"}),
                 ("mcp__plugin_posthog_posthog__exec", {"command": "search project-update"}),
                 ("mcp__plugin_posthog_posthog__exec", {"command": 'call execute-sql {"query": "select 1"}'}),
                 ("mcp__plugin_posthog_posthog__exec", {"command": 'call insight-get {"id": 4}'}),
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
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": 'call create-feature-flag {"key": "x"}'},
                     "cannot tell which")
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"mcp": {"posthog": {"targets": ["*"]}}}, fh)
        self.ok("mcp__plugin_posthog_posthog__exec", {"command": 'call create-feature-flag {"key": "x"}'})

    def test_posthog_ignores_invented_project_fields_on_active_project_tools(self):
        self.declare(allow=("implement", "remote-write", "publish"))
        for command in (
            'call create-feature-flag {"key": "x", "project_id": 111}',
            'call update-feature-flag {"id": 111, "project_id": 111}',
            'call survey-launch {"id": "s", "project_id": 111}',
        ):
            self.refused("mcp__plugin_posthog_posthog__exec", {"command": command}, "active project")
        # project-settings-update really accepts id. An invented field cannot replace it.
        self.refused("mcp__plugin_posthog_posthog__exec", {
            "command": 'call project-settings-update {"id": 222, "project_id": 111}'
        }, "targets '222'")

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

    def test_paid_calls_need_a_listed_target_when_they_name_one(self):
        self.declare(allow=("implement", "paid-job"))
        seer = "mcp__plugin_sentry_sentry__analyze_issue_with_seer"
        self.refused(seer, {"organizationSlug": "outside-org", "issueId": "X-1"}, "targets 'outside-org'")
        self.refused(seer, {"issueUrl": "https://outside-org.sentry.io/issues/X-1/"}, "targets 'outside-org'")
        self.refused(seer, {"issueId": "X-1"}, "cannot tell which")
        self.refused("mcp__plugin_sentry_sentry__execute_sentry_tool",
                     {"name": "analyze_issue_with_seer", "arguments": {"organizationSlug": "outside-org"}},
                     "targets 'outside-org'")
        self.ok(seer, {"organizationSlug": "my-org", "issueId": "X-1"})
        self.ok("mcp__dfs-mcp__api_request", {"method": "POST", "path": "/v3/serp/google/organic/live/advanced"})
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"mcp": {}}, fh)
        self.refused(seer, {"organizationSlug": "my-org", "issueId": "X-1"}, "allowed: none")

    def test_unknown_names_are_refused_however_they_are_spelled(self):
        shaped = [("mcp__revenuecat__get_unrecognized_action", {"project_id": "proj_ok"}),
                  ("mcp__revenuecat__list_everything_and_delete", {"project_id": "proj_ok"}),
                  ("mcp__plugin_sentry_sentry__search_and_resolve", {"organizationSlug": "my-org"}),
                  ("mcp__plugin_sentry_sentry__execute_sentry_tool", {"name": "get_unrecognized", "arguments": {}}),
                  ("mcp__plugin_posthog_posthog__exec", {"command": 'call widgets-get-all {}'}),
                  ("mcp__plugin_posthog_posthog__exec", {"command": 'call --json query-unknown {}'}),
                  ("mcp__dfs-mcp__api_request", {"method": "GET", "path": "/v3/serp/google/locations_and_more"}),
                  ("mcp__dfs-mcp__docs_rewrite", {})]
        for tool, args in shaped:
            self.refused(tool, args, "no task")
        self.declare(allow=("implement", "remote-write", "paid-job"))
        for tool, args in shaped:
            self.refused(tool, args, "not an action")

    def test_call_flags_do_not_hide_the_tool(self):
        self.ok("mcp__plugin_posthog_posthog__exec", {"command": 'call --json insight-get {"id": 4}'})
        self.declare(allow=("implement",))
        self.refused("mcp__plugin_posthog_posthog__exec",
                     {"command": 'call --confirm project-settings-update {"id": 111}'}, "remote-write")

    def test_remote_write_alone_never_publishes_or_submits(self):
        self.declare(allow=("implement", "remote-write"))
        for tool in ("publish_paywall", "unpublish_paywall", "start_experiment", "resume_experiment"):
            err = self.refused("mcp__revenuecat__" + tool, {"project_id": "proj_ok"}, "'publish' permission")
            self.assertIn("'remote-write' does not cover it", err)
        for tool in ("submit_products_to_store", "apply_product_store_state_plan"):
            err = self.refused("mcp__revenuecat__" + tool, {"project_id": "proj_ok"}, "'store-submission' permission")
            self.assertIn("'remote-write' does not cover it", err)
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            json.dump({"mcp": {"posthog": {"targets": ["*"]}}}, fh)
        for command in ('call workflows-publish {"id": "w"}', 'call --confirm workflows-run-batch {"workflow_id": "w"}',
                        'call feature-flag-enable {"id": 3}', 'call experiment-launch {"id": 3}',
                        'call --json survey-launch {"id": "s"}', 'call cdp-functions-publish {"id": "f"}'):
            self.refused("mcp__plugin_posthog_posthog__exec", {"command": command}, "'publish' permission")
        self.ok("mcp__plugin_posthog_posthog__exec", {"command": 'call update-feature-flag {"id": 3, "name": "n"}'})

    def test_publish_and_store_calls_pass_with_their_own_permission_and_a_listed_target(self):
        self.declare(allow=("implement", "publish"))
        self.ok("mcp__revenuecat__publish_paywall", {"project_id": "proj_ok", "paywall_id": "p"})
        self.refused("mcp__revenuecat__publish_paywall", {"project_id": "proj_other"}, "targets 'proj_other'")
        self.refused("mcp__revenuecat__submit_products_to_store", {"project_id": "proj_ok"},
                     "'store-submission' permission")
        self.refused("mcp__revenuecat__create_product", {"project_id": "proj_ok"}, "'remote-write' permission")
        self.declare(allow=("implement", "store-submission"))
        self.ok("mcp__revenuecat__submit_products_to_store", {"project_id": "proj_ok"})
        self.refused("mcp__revenuecat__submit_products_to_store", {"project_id": "proj_other"}, "targets 'proj_other'")
        self.refused("mcp__revenuecat__publish_paywall", {"project_id": "proj_ok"}, "'publish' permission")

    def test_a_posthog_write_on_the_active_project_says_why_it_is_refused(self):
        self.declare(allow=("implement", "remote-write", "publish"))
        for command in ('call update-feature-flag {"id": 4, "name": "x"}', 'call survey-launch {"id": "s"}'):
            err = self.refused("mcp__plugin_posthog_posthog__exec", {"command": command}, "active project")
            self.assertIn("does not name", err)
        self.ok("mcp__plugin_posthog_posthog__exec",
                {"command": 'call project-settings-update {"id": 111, "autocapture_opt_out": true}'})

    def test_a_posthog_write_passes_when_the_hosts_connection_is_pinned_to_a_listed_project(self):
        self.declare(allow=("implement", "remote-write", "publish"))
        write = {"command": 'call update-feature-flag {"id": 4, "name": "x"}'}
        launch = {"command": 'call survey-launch {"id": "s"}'}
        # the plugin's own entry, unpinned: refused and told how to pin
        self.claude_plugin("posthog", {"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp"}})
        err = self.refused("mcp__plugin_posthog_posthog__exec", write, "is not pinned")
        self.assertIn("x-posthog-project-id", err)
        # pinned by header to the listed project: the write and the publish pass
        self.claude_plugin("posthog", {"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp",
                                                   "headers": {"x-posthog-project-id": "111"}}})
        self.ok("mcp__plugin_posthog_posthog__exec", write)
        self.ok("mcp__plugin_posthog_posthog__exec", launch)
        # pinned elsewhere: refused, and the refusal names the pin
        self.claude_plugin("posthog", {"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp",
                                                   "headers": {"X-PostHog-Project-Id": "222"}}})
        self.refused("mcp__plugin_posthog_posthog__exec", write, "pinned to project '222'")
        # a user-scope entry pinned by the URL query
        self.claude_servers({"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp?project_id=111"}})
        self.ok("mcp__posthog__exec", write)
        # the project's own .mcp.json counts only once the human approved that server for the project
        self.claude_servers({"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp"}}, scope="project")
        self.ok("mcp__posthog__exec", write)
        self.claude_servers({"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp"}}, scope="project",
                            approved=("posthog",))
        self.refused("mcp__posthog__exec", write, "is not pinned")
        # and the session cannot write it: it is a protected configuration file
        code, err = self.hook(self.write(".mcp.json", content="{}"))
        self.assertEqual(code, 2); self.assertIn(".mcp.json", err)
        # the host's project directory keys the local scope, not the hook's cwd
        self.claude_servers({"posthog": {"type": "http", "url": "https://proxy.example.com/mcp",
                                         "headers": {"x-posthog-project-id": "111"}}}, scope="local")
        self.refused("mcp__posthog__exec", write, "is not pinned")  # a pin on a URL that is not PostHog's
        code, err = self.hook({"tool_name": "mcp__posthog__exec", "cwd": os.path.join(self.repo, "src"),
                               "session_id": SESSION, "tool_input": write})
        self.assertEqual(code, 2); self.assertIn("is not pinned", err)
        # two pins that disagree are no pin; a torn ~/.claude.json is no pin
        self.claude_servers({"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp?project_id=222",
                                         "headers": {"X-PostHog-Project-Id": "111"}}}, scope="local")
        self.refused("mcp__posthog__exec", write, "is not pinned")
        with open(os.path.join(self.hosthome, ".claude.json"), "a") as fh:
            fh.write("{")
        self.refused("mcp__posthog__exec", write, "is not pinned")
        # reads pass unpinned; the explicit project tool is held to its own id, and to the pin
        self.ok("mcp__plugin_posthog_posthog__exec", {"command": 'call insight-get {"id": 4}'})
        self.refused("mcp__plugin_posthog_posthog__exec",
                     {"command": 'call project-settings-update {"id": 222, "autocapture_opt_out": true}'}, "targets '222'")
        self.claude_plugin("posthog", {"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp",
                                                   "headers": {"x-posthog-project-id": "222"}}})
        self.refused("mcp__plugin_posthog_posthog__exec",
                     {"command": 'call project-settings-update {"id": 111, "autocapture_opt_out": true}'}, "pinned to project '222'")
        # switching the active project is a write to the project it names
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": "switch 999"}, "pinned to project '222'")
        self.claude_plugin("posthog", {"posthog": {"type": "http", "url": "https://mcp.posthog.com/mcp"}})
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": "switch 999"}, "targets '999'")
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": 'call switch-project {"projectId": 999}'}, "targets '999'")
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": 'call switch-organization {"organizationId": "o1"}'}, "targets 'o1'")
        self.ok("mcp__plugin_posthog_posthog__exec", {"command": "switch 111"})
        self.declare(allow=("review",))
        self.refused("mcp__plugin_posthog_posthog__exec", {"command": "switch 111"}, "'remote-write' permission")

    def test_a_codex_posthog_connection_is_read_from_config_toml(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"))
        from agentkeel_core import hostcheck
        self.codex_servers('[mcp_servers.posthog]\nurl = "https://mcp.posthog.com/mcp"\n'
                           'http_headers = { "x-posthog-project-id" = "111" }\n')
        if hostcheck._toml(os.path.join(self.hosthome, ".codex", "config.toml"), {**os.environ, **self.env})[0] is None:
            self.skipTest("no TOML parser (Python 3.11+) on this machine")
        self.declare(allow=("implement", "remote-write"))
        write = {"command": 'call update-feature-flag {"id": 4, "name": "x"}'}
        code, err = self.codex_call("mcp__posthog__exec", write)
        self.assertEqual(code, 0, err)
        self.codex_servers('[mcp_servers.posthog]\nurl = "https://mcp.posthog.com/mcp"\n'
                           'env_http_headers = { "x-posthog-project-id" = "POSTHOG_PIN" }\n')
        code, err = self.codex_call("mcp__posthog__exec", write)
        self.assertEqual(code, 2, "an env header with no variable set is no pin")
        self.assertIn("is not pinned", err)
        code, err = self.hook({"tool_name": "mcp__posthog__exec", "cwd": self.repo, "session_id": SESSION,
                               "tool_input": write, "turn_id": "t1"}, env={"POSTHOG_PIN": "222"})
        self.assertEqual(code, 2)
        self.assertIn("pinned to project '222'", err)

    def test_every_listed_operation_has_one_class(self):
        import itertools
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"))
        from agentkeel_core import mcp_catalog as cat
        for prefix in ("REVENUECAT_", "SENTRY_", "POSTHOG_"):
            sets = {n: getattr(cat, n) for n in dir(cat) if n.startswith(prefix) and "VERBS" not in n}
            for a, b in itertools.combinations(sorted(sets), 2):
                self.assertFalse(sets[a] & sets[b], f"{a} and {b} share {sorted(sets[a] & sets[b])}")

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
