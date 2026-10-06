"""task.py open: the task's own independent clone, its scratch folder and its session boundary."""
import json
import os
import subprocess
import sys

from helpers import HOOKS, SESSION, RepoCase, git, run_hook
import test_task_command


class Open(RepoCase):
    task = test_task_command.TaskCommand.task

    def setUp(self):
        super().setUp()
        self.env["AGENTKEEL_SCRATCH"] = os.path.join(self.tmp, "scratch")
        with open(os.path.join(self.primary, "agentkeel.json"), "w") as fh:
            json.dump({"writable": ["~/.npm", "relative/ignored", "/"]}, fh)
        git(self.primary, "add", "agentkeel.json")
        git(self.primary, "commit", "-q", "-m", "opt in")
        self.clone = os.path.join(self.tmp, "primary-json-flag")

    def open(self, *extra, host="claude", task="json-flag"):
        return self.task("open", task, "--host", host, "--size", "small", "--allow", "implement",
                         "--print", *extra, session=None, cwd=self.primary)

    def opened(self, task="json-flag"):
        with open(os.path.join(self.home, "opened", task + ".json")) as fh:
            return json.load(fh)

    def banner(self, cwd, session=SESSION):
        out = subprocess.run([sys.executable, os.path.join(HOOKS, "session-start.py")], text=True,
                             capture_output=True, input=json.dumps({"session_id": session, "cwd": cwd}),
                             env={**os.environ, **self.env})
        return out.stdout

    def test_the_clone_owns_its_objects(self):
        out = self.open()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.clone, ".git", "objects", "info", "alternates")))
        objects = [os.path.join(d, f) for d, _, fs in os.walk(os.path.join(self.clone, ".git", "objects"))
                   for f in fs if len(f) == 38 or f.endswith((".pack", ".idx"))]
        self.assertTrue(objects)
        self.assertTrue(all(os.stat(o).st_nlink == 1 for o in objects), "an object is hard-linked to the source")
        branch = subprocess.run(["git", "-C", self.clone, "branch", "--show-current"], capture_output=True, text=True)
        self.assertEqual(branch.stdout.strip(), "feat/json-flag")

    def test_the_clone_survives_cleanup_in_the_source(self):
        git(self.primary, "checkout", "-q", "-b", "tmp/gone")
        git(self.primary, "commit", "-q", "--allow-empty", "-m", "gone")
        self.assertEqual(self.open("--base", "tmp/gone").returncode, 0)
        git(self.primary, "checkout", "-q", "base")
        git(self.primary, "branch", "-q", "-D", "tmp/gone")
        git(self.primary, "reflog", "expire", "--expire=now", "--all")
        git(self.primary, "gc", "-q", "--prune=now")
        log = subprocess.run(["git", "-C", self.clone, "log", "--oneline", "-1"], capture_output=True, text=True)
        self.assertEqual(log.returncode, 0, log.stderr)
        self.assertIn("gone", log.stdout)

    def test_the_record_names_clone_base_and_scratch(self):
        self.assertEqual(self.open().returncode, 0)
        rec = self.opened()
        head = subprocess.run(["git", "-C", self.primary, "rev-parse", "base"], capture_output=True, text=True).stdout.strip()
        self.assertEqual((rec["clone"], rec["branch"], rec["base"], rec["base_sha"]), (self.clone, "feat/json-flag", "base", head))
        self.assertEqual(rec["repo"], self.primary)
        self.assertTrue(os.path.isdir(rec["scratch"]))
        self.assertFalse(rec["scratch"].startswith(self.home), "the scratch folder must be outside AGENTKEEL_HOME")
        self.assertEqual(rec["writable"], [os.path.realpath(os.path.expanduser("~/.npm"))])

    def test_claude_session_settings(self):
        out = self.open()
        settings_path = os.path.join(self.home, "sessions", "json-flag.claude.json")
        with open(settings_path) as fh:
            sandbox = json.load(fh)["sandbox"]
        self.assertTrue(sandbox["enabled"] and sandbox["failIfUnavailable"])
        self.assertFalse(sandbox["allowUnsandboxedCommands"])
        self.assertEqual(sandbox["filesystem"]["allowWrite"][0], self.opened()["scratch"])
        self.assertIn(f"claude --settings {settings_path}", out.stdout)

    def test_codex_session_arguments(self):
        out = self.open(host="codex")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, "sessions", "json-flag.claude.json")))
        from agentkeel_core import isolation
        args = isolation.codex_args(self.opened())
        self.assertEqual(args[:2], ["-C", self.clone])
        self.assertEqual(args[-2:], ["-P", "agentkeel-json-flag"])
        table = next(a for a in args if a.startswith("permissions.agentkeel-json-flag.filesystem="))
        self.assertIn('":workspace_roots"={"."="write",".git"="write",".claude"="read"}', table)
        self.assertIn('":tmpdir"="read"', table)
        self.assertIn('":slash_tmp"="read"', table)
        self.assertIn(json.dumps(self.opened()["scratch"]) + '="write"', table)
        self.assertIn(f"shell_environment_policy.set.TMPDIR={json.dumps(self.opened()['scratch'])}", args)

    def test_refusals(self):
        self.assertEqual(self.open().returncode, 0)
        again = self.open()
        self.assertEqual(again.returncode, 2); self.assertIn("already open", again.stderr)
        bad = self.open(task="Not Kebab")
        self.assertEqual(bad.returncode, 2)
        os.makedirs(os.path.join(self.tmp, "taken"))
        taken = self.open("--path", os.path.join(self.tmp, "taken"), task="other")
        self.assertEqual(taken.returncode, 2); self.assertIn("already exists", taken.stderr)
        inside = self.open("--path", os.path.join(self.primary, "nested"), task="third")
        self.assertEqual(inside.returncode, 2); self.assertIn("outside the repository", inside.stderr)
        perms = self.task("open", "fourth", "--host", "claude", "--size", "small", "--allow", "deploy", "--print",
                          session=None, cwd=self.primary)
        self.assertEqual(perms.returncode, 2); self.assertIn("unknown: deploy", perms.stderr)

    def test_session_start_in_the_clone_binds_the_task(self):
        self.assertEqual(self.open().returncode, 0)
        out = self.banner(self.clone)
        self.assertIn("This session was opened for task 'json-flag'", out)
        self.assertNotIn("declare the task", out)
        rec = self.record()
        self.assertEqual((rec["task"], rec["clone"], rec["worktrees"], rec["permissions"]),
                         ("json-flag", self.clone, [self.clone], ["implement"]))
        self.assertEqual(self.opened()["sessions"], [SESSION])

    def test_session_start_elsewhere_binds_nothing(self):
        self.assertEqual(self.open().returncode, 0)
        out = self.banner(self.primary)
        self.assertNotIn("This session was opened", out)
        self.assertFalse(os.path.exists(os.path.join(self.home, "tasks", SESSION + ".json")))

    def test_a_session_with_another_task_is_left_alone(self):
        self.assertEqual(self.open().returncode, 0)
        self.declare(task="other-task", worktrees=[self.repo])
        self.banner(self.clone)
        self.assertEqual(self.record()["task"], "other-task")

    def test_the_guard_allows_edits_in_the_own_clone_only(self):
        self.assertEqual(self.open().returncode, 0)
        self.banner(self.clone)
        code, err = self.hook(self.write(os.path.join(self.clone, "src.py"), cwd=self.clone))
        self.assertEqual(code, 0, err)
        code, err = self.hook(self.write(os.path.join(self.primary, "src.py"), cwd=self.clone))
        self.assertEqual(code, 2); self.assertIn("refusing to write", err)

    def test_open_is_the_humans_command(self):
        self.declare()
        code, err = self.hook(self.bash(f"python3 {os.path.join(HOOKS, 'task.py')} open x --host claude "
                                        "--size small --allow implement"))
        self.assertEqual(code, 2); self.assertIn("human's command", err)


class Evidence(RepoCase):
    """A verify run is recorded by the hooks: start in the guard, result in verify-record.py."""

    def setUp(self):
        super().setUp()
        self.declare()
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "work")
        self.cmd = f"python3 {os.path.join(HOOKS, 'task.py')} verify -- true"

    def start(self, call_id="t1", **tool_input):
        payload = {**self.bash(self.cmd), "tool_use_id": call_id}
        payload["tool_input"].update(tool_input)
        return self.hook(payload)

    def done(self, response, call_id="t1", codex=False):
        payload = {"tool_name": "Bash", "cwd": self.repo, "session_id": SESSION, "tool_use_id": call_id,
                   "hook_event_name": "PostToolUse", "tool_input": {"command": self.cmd}, "tool_response": response}
        if codex:
            payload["turn_id"] = "turn-1"
        return run_hook("verify-record.py", payload, env=self.env)

    def last(self):
        return (self.record().get("evidence") or [None])[-1]

    def test_a_foreground_success_on_unchanged_code_passes(self):
        self.assertEqual(self.start()[0], 0)
        self.assertEqual(len(self.record()["pending"]), 1)
        self.done({"stdout": "", "stderr": "", "interrupted": False})
        self.assertEqual(self.last()["result"], "passed")
        self.assertEqual(self.record()["pending"], [])

    def test_a_failure_leaves_the_run_unrecorded(self):
        self.start()  # Claude Code sends no PostToolUse for a non-zero exit
        self.assertIsNone(self.last())
        self.assertEqual(len(self.record()["pending"]), 1)

    def test_background_interrupted_and_codex_never_pass(self):
        self.start(call_id="bg", run_in_background=True)
        self.done({"interrupted": False, "backgroundTaskId": "b1"}, call_id="bg")
        self.assertEqual(self.last()["result"], "unrecorded")
        self.start(call_id="int")
        self.done({"interrupted": True}, call_id="int")
        self.assertEqual(self.last()["result"], "unrecorded")
        self.start(call_id="cx")
        self.done("", call_id="cx", codex=True)
        self.assertEqual(self.last()["result"], "unrecorded")
        self.assertIn("no exit status", self.last()["reason"])

    def test_printed_success_text_changes_nothing(self):
        self.start()
        self.done("all tests passed, exit code 0")
        self.assertEqual(self.last()["result"], "unrecorded")

    def test_code_that_moves_during_the_run_is_stale(self):
        self.start()
        with open(os.path.join(self.repo, "new.txt"), "w") as fh:
            fh.write("x")
        self.done({"interrupted": False})
        self.assertEqual(self.last()["result"], "stale")

    def test_a_refused_call_records_no_start(self):
        self.declare(allow=("review",))
        code, _ = self.hook({**self.bash(self.cmd + " && git push origin main"), "tool_use_id": "t9"})
        self.assertEqual(code, 2)
        self.assertNotIn("pending", self.record())

    def test_verify_itself_writes_no_evidence(self):
        out = test_task_command.TaskCommand.task(self, "verify", "--", "true")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("pending", self.record())
        self.assertEqual(self.record()["evidence"], [])


class HookLauncher(RepoCase):
    """hooks/run.sh: a verified interpreter, isolated mode, an emptied environment."""
    RUN = os.path.join(HOOKS, "run.sh")

    def launch(self, hook, payload, env=None, cwd=None):
        clean = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
        return subprocess.run(["/bin/sh", self.RUN, hook], input=json.dumps(payload), text=True,
                              capture_output=True, cwd=cwd or self.repo, env={**clean, **self.env, **(env or {})})

    def plant(self, folder):
        os.makedirs(folder, exist_ok=True)
        marker = os.path.join(self.tmp, "PLANTED")
        with open(os.path.join(folder, "json.py"), "w") as fh:
            fh.write(f"open({marker!r}, 'a').write('loaded')\nraise ImportError('planted')\n")
        return marker

    def test_a_poisoned_environment_does_not_reach_the_hook(self):
        marker = self.plant(os.path.join(self.tmp, "evil"))
        self.plant(self.repo)  # also a json.py in the session's working folder
        out = self.launch("task-guard.py", self.write("src/a.py"),
                          env={"PYTHONPATH": os.path.join(self.tmp, "evil"), "PYTHONSTARTUP": marker,
                               "PYTHONHOME": "/nonexistent"})
        self.assertEqual(out.returncode, 2, out.stderr)  # the guard ran: no task is declared
        self.assertIn("declare", out.stderr.lower())
        self.assertFalse(os.path.exists(marker), "a planted module ran inside the hook")

    def test_the_plain_form_is_redirected_by_the_same_environment(self):
        marker = self.plant(os.path.join(self.tmp, "evil"))
        subprocess.run([sys.executable, os.path.join(HOOKS, "task-guard.py")], input="{}", text=True,
                       capture_output=True, env={**os.environ, "PYTHONPATH": os.path.join(self.tmp, "evil")})
        self.assertTrue(os.path.exists(marker), "baseline: without the launcher the planted module loads")

    def test_agentkeel_home_passes_and_the_record_is_read(self):
        self.declare()
        out = self.launch("task-guard.py", self.bash("git status"))
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_the_recorded_interpreter_is_used(self):
        fake = os.path.join(self.tmp, "fakepy")
        with open(fake, "w") as fh:
            fh.write(f"#!/bin/sh\necho \"$@\" > {os.path.join(self.tmp, 'used')}\n")
        os.chmod(fake, 0o755)
        os.makedirs(self.home, exist_ok=True)
        with open(os.path.join(self.home, "interpreter"), "w") as fh:
            fh.write(fake + "\n")
        self.launch("task-guard.py", {})
        with open(os.path.join(self.tmp, "used")) as fh:
            self.assertTrue(fh.read().startswith("-I " + os.path.join(os.path.realpath(HOOKS), "task-guard.py")))

    def test_only_a_hook_file_in_the_folder_runs(self):
        for bad in ("../install.py", "/bin/sh", ".hidden", "missing.py"):
            out = self.launch(bad, {})
            self.assertEqual(out.returncode, 0)
            self.assertIn("agentkeel:", out.stderr)

    def test_every_plugin_hook_goes_through_the_launcher(self):
        with open(os.path.join(HOOKS, "hooks.json")) as fh:
            groups = [g for gs in json.load(fh)["hooks"].values() for g in gs]
        commands = [h["command"] for g in groups for h in g["hooks"]]
        self.assertTrue(commands)
        for c in commands:
            self.assertTrue(c.startswith('/bin/sh "${CLAUDE_PLUGIN_ROOT:-$PLUGIN_ROOT}/hooks/run.sh" '), c)
            self.assertTrue(os.path.exists(os.path.join(HOOKS, c.split()[2])), c)
