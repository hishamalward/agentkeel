"""task.py: the record is bound to one session, size and permissions are separate."""
import json
import os
import subprocess
import sys
import unittest

from helpers import HOOKS, SESSION, RepoCase, run_hook

T = os.path.join(HOOKS, "task.py")


class TaskCommand(RepoCase):
    def task(self, *args, session=SESSION, cwd=None):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "AGENTKEEL_SESSION_ID", "CODEX_THREAD_ID")}
        env.update(self.env)
        if session:
            env["CLAUDE_CODE_SESSION_ID"] = session
        return subprocess.run([sys.executable, T, *args], cwd=cwd or self.repo, capture_output=True,
                              text=True, env=env)

    def test_start_writes_a_session_bound_record(self):
        out = self.task("start", "json-flag", "--size", "medium", "--allow", "implement,merge")
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = self.record()
        self.assertEqual((rec["task"], rec["size"], rec["session_id"]), ("json-flag", "medium", SESSION))
        self.assertEqual(rec["permissions"], ["implement", "merge"])
        self.assertEqual(rec["worktrees"], [self.repo])

    def test_shared_checkout_is_not_recorded_as_the_tasks_worktree(self):
        out = self.task("start", "x", "--size", "small", "--allow", "implement", cwd=self.primary)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.record()["worktrees"], [])
        self.assertIn("shared checkout", out.stdout)
        self.assertTrue(os.path.isdir(self.record()["scratch"]))

    def test_write_root_inside_a_repository_refused(self):
        out = self.task("start", "review-report", "--size", "large", "--allow", "review",
                        "--write-root", os.path.join(self.primary, "src"), cwd=self.primary)
        self.assertEqual(out.returncode, 2); self.assertIn("inside the repository", out.stderr)
        report = os.path.join(self.tmp, "report"); os.makedirs(report)
        self.assertEqual(self.task("start", "r", "--size", "small", "--allow", "review",
                                   "--write-root", report).returncode, 0)

    def test_no_session_id_refused(self):
        out = self.task("start", "x", "--size", "small", "--allow", "implement", session=None)
        self.assertEqual(out.returncode, 2); self.assertIn("no session id", out.stderr)

    def test_bad_inputs_refused(self):
        self.assertNotEqual(self.task("start", "x", "--size", "huge", "--allow", "implement").returncode, 0)
        self.assertNotEqual(self.task("start", "Not Kebab", "--size", "small", "--allow", "implement").returncode, 0)
        out = self.task("start", "x", "--size", "small", "--allow", "deploy")
        self.assertEqual(out.returncode, 2); self.assertIn("unknown: deploy", out.stderr)
        self.assertNotEqual(self.task("start", "x", "--size", "small").returncode, 0)
        self.assertEqual(self.task("start", "x", "--size", "small", "--allow", "review",
                                   "--write-root", "/").returncode, 2)

    def test_changing_size_keeps_permissions_and_is_recorded(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        out = self.task("start", "x", "--size", "large", "--allow", "implement")
        self.assertIn("re-declared size small -> large", out.stderr)
        rec = self.record()
        self.assertEqual(rec["permissions"], ["implement"])
        self.assertEqual(rec["history"][0]["size"], "small")

    def test_widening_permissions_is_said_out_loud(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        out = self.task("start", "x", "--size", "small", "--allow", "implement,push")
        self.assertIn("permissions widened", out.stderr); self.assertIn("+push", out.stderr)

    def test_a_new_task_does_not_inherit_the_old_ones_resources(self):
        report = os.path.join(self.tmp, "r"); os.makedirs(report)
        self.task("start", "a", "--size", "small", "--allow", "review", "--write-root", report)
        self.task("start", "b", "--size", "small", "--allow", "implement")
        self.assertEqual(self.record()["write_roots"], [])

    def test_show_verify_end(self):
        self.task("start", "x", "--size", "small", "--allow", "implement")
        self.assertEqual(self.task("show").returncode, 0)
        out = self.task("verify", "--", sys.executable, "-c", "raise SystemExit(3)")
        self.assertEqual(out.returncode, 3)
        ev = self.record()["evidence"][-1]
        self.assertEqual(ev["exit"], 3); self.assertTrue(ev["head"])
        self.assertEqual(self.task("end").returncode, 0)
        self.assertEqual(self.task("show").returncode, 1)

    def test_human_approve_writes_the_boundary_approval(self):
        from helpers import state_page
        from agentkeel_core import pages, record
        os.makedirs(os.path.join(self.repo, "docs"))
        p = os.path.join(self.repo, "docs", "261005-x-state.html")
        with open(p, "w") as fh:
            fh.write(state_page())
        out = self.task("approve", "x", session=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("D-NNN", out.stdout)
        with open(p) as fh:
            text = fh.read()
        self.assertEqual(pages.boundary_state(os.path.basename(p), text)[0], "approved")
        kept = record.approved_boundary_path(pages.approval(text)[0], {"AGENTKEEL_HOME": self.home})
        self.assertTrue(os.path.exists(kept))
        with open(p, "w") as fh:
            fh.write(state_page(boundary=False))
        self.assertEqual(self.task("approve", "x", session=None).returncode, 2)  # nothing to approve

    def test_new_page_needs_a_task_its_worktree_and_implement(self):
        self.assertEqual(self.task("new", "state", "import").returncode, 2)            # no task
        self.task("start", "import", "--size", "small", "--allow", "review", "--write-root", self.tmp + "/out")
        self.assertEqual(self.task("new", "state", "import").returncode, 2)            # no implement
        self.task("start", "import", "--size", "large", "--allow", "implement")
        self.assertEqual(self.task("new", "state", "import", cwd=self.primary).returncode, 2)  # shared checkout
        out = self.task("new", "state", "import")
        self.assertEqual(out.returncode, 0, out.stderr)
        from agentkeel_core import pages
        docs = os.path.join(self.repo, "docs")
        names = sorted(os.listdir(docs))
        self.assertEqual(len(names), 2); self.assertIn("keel.css", names)
        page = os.path.join(docs, next(n for n in names if n.endswith("-import-state.html")))
        with open(page) as fh:
            text = fh.read()
        self.assertEqual(pages.boundary_state(os.path.basename(page), text)[0], "unapproved")  # large: boundary
        self.assertTrue(pages.sections(text, "working"))
        self.assertEqual(self.task("new", "state", "import").returncode, 2)            # one per feature
        self.assertEqual(self.task("new", "project").returncode, 0)
        self.assertEqual(self.task("new", "project").returncode, 2)                    # one canon
        self.assertEqual(self.task("new", "audit", "import", "--qualifier", "memory").returncode, 0)

    def test_finish_context_check_and_index(self):
        self.task("start", "import", "--size", "medium", "--allow", "implement")
        self.task("new", "state", "import")
        with open(os.path.join(self.repo, "agentkeel.json"), "w") as fh:
            fh.write('{"docs": "html"}')
        docs = os.path.join(self.repo, "docs")
        page = os.path.join(docs, next(n for n in os.listdir(docs) if n.endswith("-state.html")))
        out = self.task("check")
        self.assertEqual(out.returncode, 1); self.assertIn("Working section", out.stdout)
        ctx = self.task("context", page)
        self.assertEqual(ctx.returncode, 0); self.assertIn("[working section begins]", ctx.stdout)
        self.assertIn("## State now", ctx.stdout)
        self.assertEqual(self.task("finish", page).returncode, 0)
        out = self.task("check")
        self.assertEqual(out.returncode, 0, out.stdout)
        out = self.task("index")
        self.assertEqual(out.returncode, 0); self.assertIn("add docs/index.html to .gitignore", out.stdout)
        with open(os.path.join(docs, "index.html")) as fh:
            self.assertIn(os.path.basename(page), fh.read())
        self.assertEqual(self.task("check").returncode, 0)  # an untracked index is not a problem locally

    def test_record_drives_the_guard(self):
        self.branch("feat/x")
        payload = {"tool_name": "Write", "cwd": self.repo, "session_id": SESSION,
                   "tool_input": {"file_path": os.path.join(self.repo, "a.py"), "content": ""}}
        self.assertEqual(run_hook("task-guard.py", payload, env=self.env)[0], 2)
        self.task("start", "x", "--size", "small", "--allow", "implement")
        self.assertEqual(run_hook("task-guard.py", payload, env=self.env)[0], 0)


if __name__ == "__main__":
    unittest.main()
