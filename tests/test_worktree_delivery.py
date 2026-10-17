"""Task pages live in Git and survive normal shipping and cleanup."""
import json
import os
import sys
import unittest
from pathlib import Path

import test_task_lifecycle
from helpers import git, run_hook


class WorktreeDelivery(unittest.TestCase):
    setUp = test_task_lifecycle.Lifecycle.setUp
    tearDown = test_task_lifecycle.Lifecycle.tearDown
    task = test_task_lifecycle.Lifecycle.task
    rec = test_task_lifecycle.Lifecycle.rec

    def start(self, *extra):
        return self.task('start', 'pages', '--size', 'small', '--allow', 'review,implement,merge',
                         '--deliverable', 'doc/pages-progress.html', '--spec', 'doc/pages-spec.html', *extra)

    def pages(self):
        rec = self.rec()
        for key, text in [('spec', 'The agreed plan'), ('deliverable', 'Implementation checked')]:
            p = Path(rec[key]); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('<html><title>Task</title><body>' + text + '</body></html>')
        return Path(rec['worktrees'][0])

    def test_pair_has_worktree_relative_paths_and_no_generated_template(self):
        out = self.start()
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = self.rec(); tree = Path(rec['worktrees'][0])
        self.assertEqual(rec['deliverable'], str(tree / 'doc/pages-progress.html'))
        self.assertEqual(rec['spec'], str(tree / 'doc/pages-spec.html'))
        self.assertFalse(Path(rec['deliverable']).exists())
        self.assertNotEqual(self.task('handoff').returncode, 0)
        self.pages()
        self.assertEqual(self.task('handoff').returncode, 0)
        Path(rec['spec']).unlink()
        self.assertNotEqual(self.task('handoff').returncode, 0)

    def test_outside_paths_are_rejected_before_creating_a_worktree(self):
        out = self.start('--deliverable', str(self.root / 'outside.html'))
        self.assertNotEqual(out.returncode, 0)
        self.assertFalse((self.root / 'repo-pages').exists())
        out = self.start('--spec', 'doc/../../outside.html')
        self.assertNotEqual(out.returncode, 0)
        self.assertFalse((self.root / 'repo-pages').exists())

    def test_committed_pages_survive_shipping_without_an_edit_verify_loop(self):
        self.assertEqual(self.start().returncode, 0)
        tree = self.pages()
        git(str(tree), 'add', 'doc')
        git(str(tree), 'commit', '-qm', 'task pages')
        self.assertEqual(self.task('verify', '--', sys.executable, '-c', 'pass', cwd=tree).returncode, 0)
        self.assertEqual(self.task('handoff').returncode, 0)
        out = self.task('ship', '--local')
        self.assertEqual(out.returncode, 0, out.stderr)
        before = {name: (tree / 'doc' / name).read_bytes() for name in ('pages-spec.html', 'pages-progress.html')}
        out = self.task('finish')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(tree.exists())
        for name, content in before.items():
            self.assertEqual((self.repo / 'doc' / name).read_bytes(), content)
        self.assertEqual(self.rec()['deliverable'], str(self.repo / 'doc/pages-progress.html'))
        self.assertEqual(self.rec()['lifecycle'], 'complete')

    def test_changes_after_handoff_require_a_new_checkpoint_not_a_new_layout(self):
        self.assertEqual(self.start().returncode, 0)
        tree = self.pages()
        self.assertEqual(self.task('handoff').returncode, 0)
        from agentkeel_core import delivery
        self.assertEqual(delivery.problems(self.rec()), [])
        (tree / 'change.py').write_text('value = 1\n')
        self.assertTrue(delivery.problems(self.rec()))
        self.assertEqual(self.task('handoff').returncode, 0)
        self.assertEqual(delivery.problems(self.rec()), [])

    def test_no_code_defaults_to_temp_without_creating_any_worktree(self):
        import tempfile
        from agentkeel_core import record
        self.env['AGENTKEEL_SESSION_ID'] = 'temp-' + self.root.name
        out = self.task('start', 'review', '--size', 'no-code', '--allow', 'review')
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = record.load(self.env['AGENTKEEL_SESSION_ID'], self.env)
        self.assertEqual(rec['worktrees'], [])
        self.assertIsNone(rec['report_root'])
        self.assertTrue(rec['deliverable'].startswith(os.path.realpath(tempfile.gettempdir()) + os.sep))
        self.assertFalse((self.root / 'repo-review').exists())
        self.assertFalse(Path(rec['deliverable']).exists())

    def test_no_code_provider_files_allow_html_but_not_repository_edits(self):
        page = self.root / 'provider' / 'progress.html'
        spec = self.root / 'provider' / 'spec.html'
        out = self.task('start', 'review', '--size', 'no-code', '--allow', 'review',
                        '--deliverable', str(page), '--spec', str(spec))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.rec()['worktrees'], [])
        for path, allowed in ((page, True), (self.repo / 'doc/plan.html', False), (self.repo / 'source.py', False)):
            code, error = run_hook('task-guard.py', {'session_id': 'test', 'cwd': str(self.repo),
                'tool_name': 'Write', 'tool_input': {'file_path': str(path), 'content': 'x'}}, self.env)
            self.assertEqual(code == 0, allowed, error)
        page.parent.mkdir()
        for path in (page, spec):
            path.write_text('<html><title>Review</title><body>Current findings</body></html>')
        self.assertEqual(self.task('handoff').returncode, 0)
        out = self.task('finish')
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(page.exists())
        self.assertEqual(self.rec()['lifecycle'], 'complete')

    def test_doc_write_permission_does_not_open_source_or_primary_or_symlink(self):
        self.assertEqual(self.start('--allow', 'review').returncode, 0)
        rec = self.rec(); tree = Path(rec['worktrees'][0])
        (tree / 'doc').mkdir()
        (tree / 'doc/escape').symlink_to(self.repo, target_is_directory=True)
        for path, allowed in ((tree / 'doc/plan.html', True), (tree / 'source.py', False),
                              (self.repo / 'doc/plan.html', False), (tree / 'doc/escape/plan.html', False)):
            code, error = run_hook('task-guard.py', {'session_id': 'test', 'cwd': str(tree),
                'tool_name': 'Write', 'tool_input': {'file_path': str(path), 'content': 'x'}}, self.env)
            self.assertEqual(code == 0, allowed, error)
        out = self.start('--spec', 'doc/escape/plan.html')
        self.assertNotEqual(out.returncode, 0)
        (tree / 'doc/escape').unlink()
        (tree / 'doc').rmdir()
        (tree / 'doc').symlink_to(self.root / 'provider', target_is_directory=True)
        self.assertNotEqual(self.start().returncode, 0)

    def test_single_page_is_allowed_and_no_code_cannot_steal_coding_ownership(self):
        out = self.task('start', 'pages', '--size', 'small', '--allow', 'review')
        self.assertEqual(out.returncode, 0, out.stderr)
        rec = self.rec()
        self.assertIsNone(rec['spec'])
        self.assertNotEqual(self.task('start', 'pages', '--size', 'no-code', '--allow', 'review').returncode, 0)
        self.assertEqual(self.rec(), rec)
        self.assertNotEqual(self.start('--spec', 'doc/pages-progress.html').returncode, 0)

    def test_spec_edits_invalidate_handoff_and_unchanged_verification_does_not(self):
        from agentkeel_core import delivery
        self.assertEqual(self.start().returncode, 0)
        tree = self.pages()
        self.assertEqual(self.task('handoff').returncode, 0)
        self.assertEqual(self.task('verify', '--', sys.executable, '-c', 'pass', cwd=tree).returncode, 0)
        self.assertEqual(delivery.problems(self.rec()), [])
        spec = Path(self.rec()['spec'])
        spec.write_text(spec.read_text().replace('agreed plan', 'revised plan'))
        self.assertTrue(delivery.problems(self.rec()))
        self.assertEqual(self.task('handoff').returncode, 0)
        self.assertEqual(delivery.problems(self.rec()), [])

    def test_cleanup_refuses_if_canonical_page_is_not_preserved(self):
        self.assertEqual(self.start().returncode, 0)
        tree = self.pages()
        git(str(tree), 'add', 'doc')
        git(str(tree), 'commit', '-qm', 'task pages')
        self.assertEqual(self.task('verify', '--', sys.executable, '-c', 'pass', cwd=tree).returncode, 0)
        self.assertEqual(self.task('handoff').returncode, 0)
        self.assertEqual(self.task('ship', '--local').returncode, 0)
        page = self.repo / 'doc/pages-progress.html'
        original = page.read_bytes()
        page.write_text('changed by someone else')
        out = self.task('finish')
        self.assertNotEqual(out.returncode, 0)
        self.assertIn('preserved', out.stderr)
        self.assertTrue(tree.is_dir())
        page.write_bytes(original)
        self.assertEqual(self.task('finish').returncode, 0)
