"""stop-report.py: what a session's task still holds when a turn ends, reported and never touched.

The Stop payloads below follow each host's documented input: Claude Code's Stop hook input, and
the `stop.command.input` schema embedded in Codex CLI 0.160.1. They are not live captures."""
import json
import os
import subprocess

from helpers import HOOKS, SESSION, RepoCase, git

RUN = os.path.join(HOOKS, "run.sh")


def claude_stop(cwd, session=SESSION):
    return {"session_id": session, "transcript_path": "/t/s.jsonl", "cwd": cwd, "permission_mode": "default",
            "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "done"}


def codex_stop(cwd, session=SESSION):
    return {"cwd": cwd, "hook_event_name": "Stop", "last_assistant_message": "done", "model": "gpt-6-astra",
            "permission_mode": "bypassPermissions", "session_id": session, "stop_hook_active": False,
            "transcript_path": None, "turn_id": "turn-1"}


class StopReport(RepoCase):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.primary, "agentkeel.json"), "w") as fh:
            fh.write("{}\n")
        git(self.primary, "add", "agentkeel.json")
        git(self.primary, "commit", "-q", "-m", "opt in")
        self.wt = os.path.join(self.tmp, "primary-x")
        git(self.primary, "worktree", "add", "-q", self.wt, "-b", "feat/x", "main")

    def stop(self, payload=None, plugin=True, raw=None):
        """Run the hook as the plugin does: run.sh, --plugin. Returns (exit, the systemMessage or '', stderr)."""
        clean = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
        out = subprocess.run(["/bin/sh", RUN, "stop-report.py"] + (["--plugin"] if plugin else []),
                             input=raw if raw is not None else json.dumps(payload or claude_stop(self.primary)),
                             text=True, capture_output=True, env={**clean, **self.env}, timeout=120)
        msg = json.loads(out.stdout)["systemMessage"] if out.stdout.strip() else ""
        if out.stdout.strip():
            self.assertEqual(set(json.loads(out.stdout)), {"systemMessage"})  # never a block or continue
        return out.returncode, msg, out.stderr

    def put(self, folder, name, text="x\n"):
        with open(os.path.join(folder, name), "w") as fh:
            fh.write(text)

    def test_dirty_worktree_is_reported_and_left_as_it_is(self):
        self.declare(task="x", worktrees=[self.wt])
        self.put(self.wt, "a.py"); git(self.wt, "add", "a.py"); git(self.wt, "commit", "-q", "-m", "a", "--", "a.py")
        self.put(self.wt, "notes.txt")
        code, msg, err = self.stop()
        self.assertEqual(code, 0, err)
        self.assertIn("task 'x' still holds", msg)
        self.assertIn(f"worktree {self.wt} (branch feat/x): 1 commit not in main; 1 changed or untracked file", msg)
        self.assertNotIn("can be removed", msg)
        # a report only: the folder, its files and its branch are all still there
        for name in ("a.py", "notes.txt", ".git"):
            self.assertTrue(os.path.exists(os.path.join(self.wt, name)), name)
        self.assertIn("feat/x", subprocess.run(["git", "-C", self.primary, "branch"], capture_output=True, text=True).stdout)

    def test_merged_clean_worktree_can_be_removed(self):
        self.declare(task="x", worktrees=[self.wt])
        code, msg, _ = self.stop()
        self.assertEqual(code, 0)
        self.assertIn("(branch feat/x): merged: it can be removed; 0 changed or untracked files", msg)
        self.assertTrue(os.path.isdir(self.wt))

    def test_unreadable_worktree_is_never_called_clean(self):
        broken = os.path.join(self.tmp, "broken")
        os.makedirs(broken)
        self.put(broken, ".git", "not a gitdir line\n")
        self.declare(task="x", worktrees=[broken])
        code, msg, _ = self.stop()
        self.assertEqual(code, 0)
        self.assertIn(f"worktree {broken}: unreadable", msg)
        self.assertIn("not known to be clean", msg)
        self.assertNotIn("merged", msg)

    def test_a_worktree_that_is_gone_is_not_reported(self):
        self.declare(task="x", worktrees=[os.path.join(self.tmp, "gone")])
        self.assertEqual(self.stop()[:2], (0, ""))

    def test_no_task_is_silent(self):
        self.assertEqual(self.stop()[:2], (0, ""))

    def test_a_repository_that_did_not_opt_in_is_silent(self):
        other = os.path.join(self.tmp, "other")
        subprocess.run(["git", "init", "-q", "-b", "main", other], check=True)
        self.declare(task="x", worktrees=[self.wt])
        self.assertEqual(self.stop(claude_stop(other))[:2], (0, ""))

    def test_same_state_is_said_once_and_a_change_speaks_again(self):
        self.declare(task="x", worktrees=[self.wt])
        self.put(self.wt, "one.txt")
        first = self.stop()[1]
        self.assertIn("1 changed or untracked file", first)
        self.assertEqual(self.stop()[:2], (0, ""))
        self.put(self.wt, "two.txt")
        self.assertIn("2 changed or untracked files", self.stop()[1])
        self.assertEqual(self.stop()[:2], (0, ""))

    def test_both_hosts_get_the_same_report(self):
        self.declare(task="x", worktrees=[self.wt])
        a = self.stop(claude_stop(self.primary))[1]
        self.declare(task="x", worktrees=[self.wt], session="codex-thread")
        b = self.stop(codex_stop(self.primary, session="codex-thread"))[1]
        self.assertTrue(a); self.assertEqual(a, b)

    def test_an_internal_error_exits_0_with_nothing_that_blocks(self):
        from agentkeel_core import record
        record.atomic_write_json(os.path.join(self.home, "tasks", SESSION + ".json"),
                                 {"task": "x", "session_id": SESSION, "worktrees": 5})
        code, msg, err = self.stop()
        self.assertEqual((code, msg), (0, "")); self.assertIn("internal error", err)
        for raw in ("not json", "[1]", ""):
            code, msg, _ = self.stop(raw=raw)
            self.assertEqual((code, msg), (0, ""), raw)

    def test_opened_clone_ready_then_not(self):
        from agentkeel_core import isolation
        env = {"AGENTKEEL_HOME": self.home, "AGENTKEEL_SCRATCH": os.path.join(self.tmp, "scratch")}
        rec = isolation.open_task(self.primary, "t", "codex", "small", ["implement"], environ=env)
        isolation.bind(SESSION, rec["clone"], environ=env)
        code, msg, _ = self.stop(codex_stop(rec["clone"]))
        self.assertEqual(code, 0)
        self.assertIn(f"clone {rec['clone']} (branch feat/t): ready to release", msg)
        self.assertNotIn("worktree", msg)
        self.put(rec["clone"], "work.txt")
        msg = self.stop(codex_stop(rec["clone"]))[1]
        self.assertIn("not ready to release: the clone has 1 changed or untracked file(s)", msg)
        self.assertIn("The human runs task.py import, then task.py release", msg)
        self.assertTrue(os.path.exists(os.path.join(rec["clone"], "work.txt")))

    def test_registered_for_both_hosts_and_both_installs(self):
        from helpers import ROOT
        for rel in ("hooks/hooks.json", "templates/claude-hooks.json", "templates/codex-hooks.json"):
            with open(os.path.join(ROOT, rel)) as fh:
                stop = [h["command"] for g in json.load(fh)["hooks"]["Stop"] for h in g["hooks"]]
            self.assertEqual(len(stop), 1, rel); self.assertIn("stop-report.py", stop[0], rel)
