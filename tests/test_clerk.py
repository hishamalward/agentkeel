from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import RepoCase, SESSION

from agentkeel_core import clerk


def executable(path: Path, source: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + source)
    path.chmod(0o700)
    return path


def decision(allowed=True):
    return {"allowed": allowed, "reason": "safe decision", "classification": "read"}


class ClerkBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.tool = executable(self.root / "mcpclerk", f"import json,sys\nsys.stdin.read()\nprint(json.dumps({decision()!r}))\n")
        self.env = {"AGENTKEEL_MCPCLERK": str(self.tool), "HOME": str(self.root / "home"),
                    "CODEX_HOME": str(self.root / "codex"), "CLAUDE_CONFIG_DIR": str(self.root / "claude"),
                    "CLAUDE_PROJECT_DIR": str(self.root / "project"),
                    "MCPCLERK_HOME": str(self.root / "mcpclerk-home"), "PATH": "/tmp/attacker"}

    def call(self):
        return clerk.judge("mcp__posthog__insight-get", {"token": "secret-value"}, "claude",
                           str(self.root), str(self.root), ["implement"], self.env)

    def test_sends_the_frozen_payload_on_stdin_and_only_safe_environment(self):
        capture = self.root / "captured.json"
        env_capture = self.root / "child-env.json"
        self.tool.write_text(f"#!{sys.executable}\nimport json,os,sys\n"
                             f"open({str(capture)!r},'w').write(sys.stdin.read())\n"
                             f"open({str(env_capture)!r},'w').write(json.dumps(dict(os.environ)))\n"
                             f"print(json.dumps({decision()!r}))\n")
        self.tool.chmod(0o700)
        self.assertEqual(self.call(), decision())
        payload = json.loads(capture.read_text())
        self.assertEqual(payload, {"version": 1, "tool": "mcp__posthog__insight-get",
                                   "args": {"token": "secret-value"}, "host": "claude",
                                   "cwd": str(self.root), "project_dir": str(self.root),
                                   "task": {"permissions": ["implement"]}})
        child_env = json.loads(env_capture.read_text())
        self.assertEqual({key: child_env[key] for key in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR", "MCPCLERK_HOME")},
                         {key: self.env[key] for key in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR", "MCPCLERK_HOME")})
        self.assertEqual(child_env["PATH"], clerk.SAFE_PATH)
        self.assertNotIn("API_KEY", child_env)
        self.assertNotIn("token", json.dumps(child_env))

    def test_allow_and_deny_decisions_are_returned(self):
        self.assertTrue(self.call()["allowed"])
        denied = executable(self.root / "deny", f"import json\nprint(json.dumps({decision(False)!r}))\n")
        self.env["AGENTKEEL_MCPCLERK"] = str(denied)
        self.assertFalse(self.call()["allowed"])

    def test_missing_malformed_noisy_failing_and_timed_out_clerk_fail_closed(self):
        self.env["AGENTKEEL_MCPCLERK"] = str(self.root / "missing")
        with self.assertRaisesRegex(clerk.ClerkError, "unavailable"):
            self.call()
        cases = [
            "print('not json')",
            f"print('log'); print(json.dumps({decision()!r}))",
            "print('{\\\"allowed\\\":true,\\\"reason\\\":3,\\\"classification\\\":\\\"read\\\"}')",
            "import sys; print('private-args-secret', file=sys.stderr); sys.exit(1)",
            "import time; time.sleep(1)",
        ]
        for source in cases:
            self.env["AGENTKEEL_MCPCLERK"] = str(executable(self.root / f"bad-{cases.index(source)}",
                                                            "import json,sys\n" + source + "\n"))
            if "time.sleep" in source:
                with mock.patch.object(clerk, "TIMEOUT_SECONDS", 0.01):
                    with self.assertRaises(clerk.ClerkError) as caught:
                        self.call()
            else:
                with self.assertRaises(clerk.ClerkError) as caught:
                    self.call()
            self.assertNotIn("private-args-secret", str(caught.exception))

    def test_fixed_user_executable_precedes_sanitized_path_lookup(self):
        home = Path(self.env["HOME"])
        (home / ".local/bin").mkdir(parents=True)
        local = executable(home / ".local/bin/mcpclerk", f"import json\nprint(json.dumps({decision()!r}))\n")
        del self.env["AGENTKEEL_MCPCLERK"]
        with mock.patch.object(clerk.shutil, "which", side_effect=AssertionError("which should not be called")):
            self.assertEqual(clerk._executable(self.env), str(local))

    def test_fallback_lookup_uses_fixed_path(self):
        del self.env["AGENTKEEL_MCPCLERK"]
        self.env["HOME"] = str(self.root / "empty-home")
        fallback = executable(self.root / "fallback-mcpclerk", "pass\n")
        with mock.patch.object(clerk.shutil, "which", return_value=str(fallback)) as which:
            self.assertEqual(clerk._executable(self.env), str(fallback))
        which.assert_called_once_with("mcpclerk", path=clerk.SAFE_PATH)


class GuardBridge(RepoCase):
    def test_missing_clerk_blocks_mcp_but_standalone_coding_still_runs(self):
        env = {"AGENTKEEL_MCPCLERK": os.path.join(self.tmp, "missing-clerk")}
        payload = {"tool_name": "mcp__anything__change", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {"id": "secret"}}
        code, err = self.hook(payload, env)
        self.assertEqual(code, 2)
        self.assertIn("MCP policy check unavailable", err)
        self.assertNotIn("secret", err)
        code, err = self.hook(self.bash("git status"), env)
        self.assertEqual((code, err), (0, ""))

    def test_installed_clerk_allow_and_deny_are_the_only_mcp_decisions(self):
        allow = executable(Path(self.tmp) / "allow", f"import json\nprint(json.dumps({decision()!r}))\n")
        deny = executable(Path(self.tmp) / "deny", f"import json\nprint(json.dumps({decision(False)!r}))\n")
        payload = {"tool_name": "mcp__unknown__read", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {"value": "secret"}}
        self.assertEqual(self.hook(payload, {"AGENTKEEL_MCPCLERK": str(allow)})[0], 0)
        code, err = self.hook(payload, {"AGENTKEEL_MCPCLERK": str(deny)})
        self.assertEqual(code, 2)
        self.assertIn("safe decision", err)

    def test_unknown_warn_is_visible_and_pass_is_silent(self):
        payload = {"tool_name": "mcp__unknown__read", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {}}
        hook = os.path.join(os.path.dirname(__file__), "..", "hooks", "task-guard.py")
        warn_result = {"allowed": True, "reason": "unknown MCP server; warning policy allows it",
                       "classification": "unknown"}
        pass_result = {"allowed": True, "reason": "unknown MCP server; pass policy allows it",
                       "classification": "unknown"}
        for result, expected in ((warn_result, warn_result["reason"]), (pass_result, "")):
            tool = executable(Path(self.tmp) / ("warn" if expected else "pass"),
                              f"import json\nprint(json.dumps({result!r}))\n")
            completed = subprocess.run([sys.executable, hook], input=json.dumps(payload), text=True,
                                        capture_output=True, env={**os.environ, **self.env,
                                                                 "AGENTKEEL_MCPCLERK": str(tool)})
            self.assertEqual(completed.returncode, 0, completed.stderr)
            if expected:
                self.assertEqual(json.loads(completed.stdout)["systemMessage"], expected)
            else:
                self.assertEqual(completed.stdout, "")

    def test_subdirectory_call_uses_git_project_root_and_preserves_claude_origin(self):
        nested = os.path.join(self.repo, "src")
        os.makedirs(nested, exist_ok=True)
        capture = Path(self.tmp) / "payload.json"
        executable_path = executable(Path(self.tmp) / "capture", f"import json,os,sys\n"
                                     f"open({str(capture)!r},'w').write(sys.stdin.read())\n"
                                     f"print(json.dumps({decision()!r}))\n")
        payload = {"tool_name": "mcp__anything__read", "cwd": nested, "session_id": SESSION,
                   "tool_input": {}}
        code, err = self.hook(payload, {"AGENTKEEL_MCPCLERK": str(executable_path),
                                        "CLAUDE_PROJECT_DIR": self.repo})
        self.assertEqual((code, err), (0, ""))
        request = json.loads(capture.read_text())
        self.assertEqual(request["cwd"], nested)
        self.assertEqual(request["project_dir"], self.repo)

    def test_mcp_denial_cannot_be_softened_by_task_or_mcpclerk_modes(self):
        Path(self.repo, "agentkeel.json").write_text(json.dumps({"guards": {"task": "off",
                                                                           "mcpclerk": "off"}}))
        deny = executable(Path(self.tmp) / "deny", f"import json\nprint(json.dumps({decision(False)!r}))\n")
        payload = {"tool_name": "mcp__unknown__read", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {}}
        code, err = self.hook(payload, {"AGENTKEEL_MCPCLERK": str(deny)})
        self.assertEqual(code, 2)
        self.assertIn("safe decision", err)

    def test_legacy_mcp_unknown_warn_mode_requires_migration_and_still_blocks(self):
        Path(self.repo, "agentkeel.json").write_text(json.dumps({"guards": {"mcp_unknown": "warn"}}))
        available = executable(Path(self.tmp) / "allow", f"import json\nprint(json.dumps({decision()!r}))\n")
        payload = {"tool_name": "mcp__anything__read", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {}}
        code, err = self.hook(payload, {"AGENTKEEL_MCPCLERK": str(available)})
        self.assertEqual(code, 2)
        self.assertIn("mcpclerk migrate-keel", err)

    def test_legacy_policy_inspection_error_fails_closed_without_leaking(self):
        spec = importlib.util.spec_from_file_location("task_guard_for_clerk_test",
                                                       os.path.join(os.path.dirname(__file__), "..", "hooks", "task-guard.py"))
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        event = type("Event", (), {"tool": "mcp__anything__read", "args": {}})()
        with mock.patch.object(guard.clerk, "has_legacy_policy", side_effect=OSError("private path")):
            with self.assertRaises(guard.Block) as caught:
                guard.judge_mcp(event, self.repo, {}, {}, {"CLAUDE_PROJECT_DIR": self.repo})
        self.assertEqual(caught.exception.guard, "mcpclerk")
        self.assertNotIn("private path", str(caught.exception))

    def test_legacy_mcp_policy_blocks_until_human_migration(self):
        Path(self.repo, "agentkeel.json").write_text(json.dumps({"mcp": {"old": {"targets": ["secret"]}}}))
        available = executable(Path(self.tmp) / "allow", f"import json\nprint(json.dumps({decision()!r}))\n")
        payload = {"tool_name": "mcp__posthog__insight-get", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {}}
        code, err = self.hook(payload, {"AGENTKEEL_MCPCLERK": str(available)})
        self.assertEqual(code, 2)
        self.assertIn("mcpclerk migrate-keel", err)
        self.assertNotIn("secret", err)

    def test_clerk_home_and_native_policy_file_are_protected(self):
        clerk_home = os.path.join(self.tmp, "clerk-home")
        os.makedirs(clerk_home)
        self.assertEqual(self.hook(self.write(os.path.join(clerk_home, "state.json")),
                                   {"MCPCLERK_HOME": clerk_home})[0], 2)
        self.assertEqual(self.hook(self.write(os.path.join(self.repo, "mcpclerk.json")))[0], 2)


if __name__ == "__main__":
    unittest.main()
