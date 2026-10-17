"""Existing work survives a new host session and explicit ownership handoff."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import test_task_lifecycle
from helpers import HOOKS, git


class Resume(unittest.TestCase):
    setUp = test_task_lifecycle.Lifecycle.setUp
    tearDown = test_task_lifecycle.Lifecycle.tearDown
    task = test_task_lifecycle.Lifecycle.task
    start = test_task_lifecycle.Lifecycle.start
    rec = test_task_lifecycle.Lifecycle.rec
    def existing(self):
        tree = self.root / 'existing'
        git(str(self.repo), 'worktree', 'add', '-qb', 'feat/existing', str(tree))
        (tree / 'staged').write_text('keep staged\n')
        git(str(tree), 'add', 'staged')
        (tree / 'staged').write_text('keep unstaged too\n')
        (tree / 'untracked').write_bytes(b'keep\x00bytes')
        return tree

    def resume(self, tree, *extra):
        return self.task('resume', 'continue-work', '--worktree', str(tree), '--size', 'small',
                         '--allow', 'review,implement', '--deliverable', str(self.report), *extra)

    def guard(self, tree, session, command='git commit -m continued -- staged'):
        payload = {'session_id': session, 'cwd': str(tree), 'tool_name': 'Bash',
                   'tool_input': {'command': command}}
        return subprocess.run([sys.executable, os.path.join(HOOKS, 'task-guard.py')],
                              input=json.dumps(payload), text=True, capture_output=True, env=self.env)

    def test_legacy_dirty_worktree_transfers_both_old_claims_without_touching_files_or_index(self):
        tree = self.existing()
        admin = Path(subprocess.check_output(['git', '-C', str(tree), 'rev-parse', '--absolute-git-dir'], text=True).strip())
        index = (admin / 'index').read_bytes()
        state = self.root / 'state/tasks'
        state.mkdir(parents=True)
        for session in ('old-a', 'old-b'):
            (state / (session + '.json')).write_text(json.dumps({
                'version': 1, 'task': 'old', 'session_id': session, 'size': 'large',
                'permissions': ['implement', 'push'], 'worktrees': [str(tree)]}))
        out = self.resume(tree)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('--from-session', out.stderr)
        out = self.resume(tree, '--from-session', 'old-a', '--from-session', 'old-b')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((admin / 'index').read_bytes(), index)
        self.assertEqual((tree / 'staged').read_text(), 'keep unstaged too\n')
        self.assertEqual((tree / 'untracked').read_bytes(), b'keep\x00bytes')
        rec = self.rec()
        self.assertEqual(rec['worktrees'], [str(tree)])
        self.assertEqual(rec['evidence'], [])
        self.assertTrue(rec['workspace']['retain_on_finish'])
        self.assertEqual(self.guard(tree, 'test').returncode, 0)
        self.assertNotEqual(self.guard(tree, 'old-a').returncode, 0)
        self.assertNotEqual(self.guard(tree, 'old-b').returncode, 0)
        self.assertNotEqual(self.guard(tree, 'old-a', 'git push origin feat/existing').returncode, 0)
        self.assertEqual(len(subprocess.check_output(['git', '-C', str(self.repo), 'worktree', 'list', '--porcelain'], text=True).split('worktree ')), 3)

    def test_unclaimed_tree_can_be_resumed_and_primary_cannot(self):
        out = self.resume(self.repo)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('linked', out.stderr)
        tree = self.existing()
        out = self.resume(tree)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_managed_tree_requires_exact_owner_and_invalidates_prior_manifest(self):
        self.assertEqual(self.start().returncode, 0)
        old = self.rec()
        self.env['AGENTKEEL_SESSION_ID'] = 'new'
        out = self.resume(old['worktrees'][0], '--from-session', 'wrong')
        self.assertNotEqual(out.returncode, 0)
        out = self.resume(old['worktrees'][0], '--from-session', 'test')
        self.assertEqual(out.returncode, 0, out.stderr)
        from agentkeel_core import workspace
        with self.assertRaises(workspace.WorkspaceError):
            workspace.validate(old['workspace'])
        self.assertNotEqual(self.guard(old['worktrees'][0], 'test').returncode, 0)

    def test_runtime_attachment_is_preserved_and_transfer_refused(self):
        tree = self.existing()
        from agentkeel_core import workspace
        marker = Path(workspace.runtime_path(str(tree)))
        marker.write_text('{"keep":"runtime owner"}\n')
        out = self.resume(tree)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('runtime', out.stderr)
        self.assertEqual(marker.read_text(), '{"keep":"runtime owner"}\n')

    def test_detached_and_protected_worktrees_are_refused(self):
        tree = self.existing()
        git(str(tree), 'checkout', '--detach')
        self.assertNotEqual(self.resume(tree).returncode, 0)
        git(str(tree), 'checkout', '-b', 'release')
        (self.repo / 'agentkeel.json').write_text('{"protected_branches":["main","release"]}')
        self.assertNotEqual(self.resume(tree).returncode, 0)

    def test_finish_retains_adopted_tree_and_a_later_session_can_resume_it(self):
        tree = self.existing()
        self.assertEqual(self.resume(tree).returncode, 0)
        git(str(tree), 'add', 'staged', 'untracked')
        git(str(tree), 'commit', '-qm', 'continued work')
        self.assertEqual(self.task('start', 'continue-work', '--size', 'small',
                                   '--allow', 'review,implement,merge', '--deliverable', str(self.report)).returncode, 0)
        self.assertEqual(self.task('verify', '--', sys.executable, '-c', 'pass', cwd=tree).returncode, 0)
        self.report.parent.mkdir()
        def report(text):
            self.report.write_text('<html><title>Resume</title><body>' + text + '</body></html>')
        report('Candidate checked')
        self.assertEqual(self.task('handoff').returncode, 0)
        out = self.task('ship', '--local')
        self.assertEqual(out.returncode, 0, out.stderr)
        report('Local main synchronized')
        self.assertNotEqual(self.task('finish').returncode, 0)
        self.assertTrue(tree.is_dir())
        self.assertEqual((tree / 'staged').read_text(), 'keep unstaged too\n')
        report('Existing worktree retained')
        self.assertEqual(self.task('finish').returncode, 0)
        self.assertEqual(self.rec()['lifecycle'], 'complete')
        self.env['AGENTKEEL_SESSION_ID'] = 'later'
        out = self.resume(tree)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_failed_record_save_rolls_back_the_claim(self):
        tree = self.existing()
        from agentkeel_core import workspace
        marker = Path(workspace._gitpath(str(tree), 'agent-workspace.json'))
        with self.assertRaises(OSError):
            with workspace.resume(str(tree), 'work', 'test', [], self.env):
                raise OSError('record save failed')
        self.assertFalse(marker.exists())
        with workspace.resume(str(tree), 'original', 'first', [], self.env):
            pass
        prior = marker.read_bytes()
        with self.assertRaises(OSError):
            with workspace.resume(str(tree), 'replacement', 'second', ['first'], self.env):
                raise OSError('record save failed')
        self.assertEqual(marker.read_bytes(), prior)

    def test_stale_owner_cannot_redeclare_or_ship_after_transfer(self):
        self.assertEqual(self.start().returncode, 0)
        self.assertEqual(self.task('start', 'work', '--size', 'small', '--allow', 'review,implement,merge',
                                   '--deliverable', str(self.report)).returncode, 0)
        tree = self.rec()['worktrees'][0]
        self.env['AGENTKEEL_SESSION_ID'] = 'new'
        self.assertEqual(self.resume(tree, '--from-session', 'test').returncode, 0)
        self.env['AGENTKEEL_SESSION_ID'] = 'test'
        self.assertNotEqual(self.start().returncode, 0)
        out = self.task('ship', '--local')
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('identity', out.stderr)
