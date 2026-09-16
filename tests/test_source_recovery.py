# SPDX-License-Identifier: MIT
"""Real offline Git/source recovery; no Rust compiler or benchmark is simulated here."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build as bk

archive_module = bk.source_archive


def execute(args, cwd, *, success=True):
    env = {**os.environ, 'OFFLINE': '1', 'GIT_TERMINAL_PROMPT': '0',
           'http_proxy': 'http://127.0.0.1:1', 'https_proxy': 'http://127.0.0.1:1',
           'GIT_AUTHOR_NAME': 'Source recovery test', 'GIT_COMMITTER_NAME': 'Source recovery test',
           'GIT_AUTHOR_EMAIL': 'test@example.invalid', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
           'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=120)
    if success and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result


class OfflineRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='source recovery ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'repository with spaces'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns(
            '.work', 'dist', '__pycache__', '.buildkit.lock', 'source-recovery-backups'))
        self.builder = bk.Builder(self.root, bk.Config.from_env({'OFFLINE': '1'}))
        self.source = self.root / 'upstream'

    def restore(self):
        with contextlib.redirect_stderr(io.StringIO()):
            return self.builder.fetch()

    def test_missing_tree_restores_actual_files_and_native_patch_offline(self):
        shutil.rmtree(self.source)
        original = bk.run
        commands = []
        def audited(argv, **kwargs):
            commands.append([str(x) for x in argv])
            return original(argv, **kwargs)
        with patch.object(bk, 'run', side_effect=audited):
            lock = self.restore()
        self.assertEqual(lock['commit'], 'bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b')
        self.assertEqual(len(bk.file_manifest(self.source, exclude_git=True)), 163)
        self.assertIn('cflags=["-fms-extensions", "-Wno-microsoft-anon-tag"]',
                      (self.source / 'rd-agent/src/misc/biolatpcts.py').read_text())
        self.assertFalse(any(c[0] in ('curl', 'wget', 'cargo', 'rustc') for c in commands))
        self.assertFalse(any('fetch' in c or 'clone' in c for c in commands))
        self.assertFalse(json.loads((self.root / '.work/source-recovery.json').read_text())['network_used'])

    def test_empty_tree_restores(self):
        shutil.rmtree(self.source)
        self.source.mkdir()
        self.restore()
        self.assertTrue((self.source / 'Cargo.lock').is_file())
        self.assertEqual(len(list((self.root / 'source-recovery-backups').glob('*/upstream'))), 1)

    def test_partial_copy_retained_and_restored(self):
        path = self.source / 'rd-agent/src/misc/biolatpcts.py'
        path.unlink()
        self.restore()
        self.assertTrue(path.is_file())
        backup = next((self.root / 'source-recovery-backups').glob('*/upstream'))
        self.assertFalse((backup / 'rd-agent/src/misc/biolatpcts.py').exists())
        self.assertEqual((backup / 'Cargo.lock').read_bytes(), (self.source / 'Cargo.lock').read_bytes())

    def test_missing_hidden_git_metadata_restored(self):
        shutil.rmtree(self.source / '.git')
        self.restore()
        self.assertEqual(execute(['git', '-C', self.source, 'rev-parse', 'HEAD'], self.base).stdout.strip(),
                         'bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b')

    def test_corrupt_git_metadata_restored_without_altering_working_content(self):
        (self.source / '.git/HEAD').write_text('not a valid reference\n')
        before = bk.file_manifest(self.source, exclude_git=True)
        self.restore()
        self.assertEqual(before, bk.file_manifest(self.source, exclude_git=True))
        backup = next((self.root / 'source-recovery-backups').glob('*/upstream'))
        self.assertEqual((backup / '.git/HEAD').read_text(), 'not a valid reference\n')

    def test_valid_tree_is_noop(self):
        before = (self.root / 'source.lock.json').read_bytes()
        self.restore()
        self.assertEqual(before, (self.root / 'source.lock.json').read_bytes())
        self.assertFalse((self.root / 'source-recovery-backups').exists())

    def test_modified_source_is_never_discarded(self):
        path = self.source / 'rd-agent/src/misc/biolatpcts.py'
        path.write_text('my local changes\n')
        with self.assertRaisesRegex(bk.BuildError, 'nothing was overwritten'):
            self.restore()
        self.assertEqual(path.read_text(), 'my local changes\n')
        self.assertFalse((self.root / 'source-recovery-backups').exists())

    def test_unknown_source_file_is_never_discarded(self):
        (self.source / 'my-notes.txt').write_text('retain me')
        with self.assertRaisesRegex(bk.BuildError, 'my-notes'):
            self.restore()
        self.assertEqual((self.source / 'my-notes.txt').read_text(), 'retain me')

    def test_source_symlink_is_rejected(self):
        moved = self.base / 'external-source'
        self.source.rename(moved)
        self.source.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(bk.BuildError, 'unsafe upstream'):
            self.restore()
        self.assertTrue((moved / 'Cargo.toml').is_file())

    def test_external_git_link_is_rejected(self):
        moved = self.base / 'external-git'
        (self.source / '.git').rename(moved)
        (self.source / '.git').symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(bk.BuildError, 'external .git'):
            self.restore()

    def test_corrupt_cache_fails_before_creating_source(self):
        shutil.rmtree(self.source)
        (self.root / 'source-cache/upstream.tar.gz').write_bytes(b'bad')
        with self.assertRaisesRegex(archive_module.SourceArchiveError, 'checksum mismatch'):
            self.restore()
        self.assertFalse(self.source.exists())

    def test_missing_cache_never_fetches_unpatched_remote(self):
        shutil.rmtree(self.source)
        (self.root / 'source-cache/upstream.tar.gz').unlink()
        with patch.object(self.builder, 'git', side_effect=AssertionError('No Git network call')):
            with self.assertRaisesRegex(archive_module.SourceArchiveError, 'absent'):
                self.restore()

    def test_complete_valid_source_build_does_not_need_the_redundant_cache(self):
        (self.root / 'source-cache/upstream.tar.gz').unlink()
        self.restore()
        self.assertTrue((self.source / 'Cargo.toml').is_file())

    def test_source_manifest_tamper_blocks_recovery(self):
        shutil.rmtree(self.source)
        (self.root / 'source-manifest.json').write_text('{}')
        with self.assertRaisesRegex(bk.BuildError, 'manifest was changed'):
            self.restore()
        self.assertFalse(self.source.exists())

    def test_cache_parent_symlink_rejected(self):
        shutil.rmtree(self.source)
        target = self.base / 'cache'
        (self.root / 'source-cache').rename(target)
        (self.root / 'source-cache').symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(archive_module.SourceArchiveError, 'symlink'):
            self.restore()

    def test_make_clean_retains_source_recovery_and_backup(self):
        (self.source / 'rd-agent/src/main.rs').unlink()
        self.restore()
        execute([self.root / 'BUILD.sh', 'clean'], self.base)
        self.assertFalse((self.root / '.work').exists())
        self.assertTrue((self.root / 'source-cache/upstream.tar.gz').is_file())
        self.assertTrue((self.root / 'source-recovery-backups').is_dir())
        shutil.rmtree(self.source)
        execute([self.root / 'BUILD.sh', 'fetch', 'OFFLINE=1'], self.base)
        self.assertTrue((self.source / 'rd-agent/src/main.rs').is_file())

    def test_absolute_build_launcher_outside_repo(self):
        shutil.rmtree(self.source)
        result = execute([self.root / 'BUILD.sh', 'fetch', 'verify-source'], self.base)
        self.assertIn('OFFLINE', result.stderr)
        self.assertFalse((self.base / 'upstream').exists())

    def test_symlinked_build_launcher(self):
        alias = self.base / 'my-builder'
        alias.symlink_to(self.root / 'BUILD.sh')
        result = execute([alias, 'verify-source'], self.base)
        self.assertIn('Verified complete patched source', result.stdout)

    def test_absolute_makefile_from_unrelated_directory_with_spaces(self):
        shutil.rmtree(self.source)
        result = execute(['make', '--no-print-directory', '-f', self.root / 'Makefile',
                          'fetch', 'verify-source', 'OFFLINE=1'], self.base)
        self.assertIn('Verified complete patched source', result.stdout)
        self.assertFalse((self.base / 'source.lock.json').exists())

    def test_reviewed_source_cannot_be_replaced_by_latest(self):
        with self.assertRaisesRegex(bk.BuildError, 'cannot silently remove'):
            self.builder.fetch(update=True)

    def test_git_checkout_without_ignored_upstream_recovers(self):
        execute(['git', 'init', '--quiet'], self.root)
        execute(['git', 'add', '.'], self.root)
        execute(['git', 'commit', '--quiet', '-m', 'Complete source distribution'], self.root)
        tracked = execute(['git', 'ls-files'], self.root).stdout.splitlines()
        self.assertIn('source-cache/upstream.tar.gz', tracked)
        self.assertFalse(any(p.startswith('upstream/') for p in tracked))
        clone = self.base / 'clone without upstream'
        execute(['git', 'clone', '--quiet', '--no-hardlinks', self.root, clone], self.base)
        self.assertFalse((clone / 'upstream').exists())
        execute([clone / 'BUILD.sh', 'fetch', 'verify-source', 'OFFLINE=1'], self.base)
        self.assertTrue((clone / 'upstream/resctl-bench/src/main.rs').is_file())

    def test_kit_dist_is_complete_for_this_patchset(self):
        result = execute([self.root / 'BUILD.sh', 'kit-dist'], self.base)
        path = self.root / 'dist/resctl-bench-2.2.6-complete-source-2.3.1.tar.gz'
        self.assertTrue(path.is_file(), result.stdout + result.stderr)
        with tarfile.open(path) as stream:
            names = set(stream.getnames())
        for suffix in ('upstream/Cargo.toml', 'upstream/Cargo.lock', 'upstream/.git/HEAD',
                       'upstream/rd-agent/src/misc/biolatpcts.py', 'BUILD.sh',
                       'source-cache/upstream.tar.gz', 'source.lock.json'):
            self.assertIn('resctl-bench/' + suffix, names)


    def test_archive_checksums_survive_recovery_after_git_index_refresh(self):
        # The stat cache in Git's index is mutable even with unchanged source.
        # A source release must use the SAME index as its pinned recovery asset.
        execute(['git', 'update-index', '--refresh'], self.source, success=False)
        execute([self.root / 'BUILD.sh', 'snapshot-dist'], self.base)
        archive = self.root / 'dist/resctl-bench-2.2.6-complete-source-2.3.1.tar.gz'
        unpacked = self.base / 'fresh release'
        unpacked.mkdir()
        execute(['tar', '-xzf', archive, '-C', unpacked], self.base)
        repo = unpacked / 'resctl-bench'
        execute(['sha256sum', '-c', 'SHA256SUMS'], repo)
        shutil.rmtree(repo / 'upstream')
        execute([repo / 'BUILD.sh', 'fetch', 'verify-source', 'OFFLINE=1'], self.base)
        result = execute(['sha256sum', '-c', 'SHA256SUMS'], repo)
        self.assertIn('upstream/.git/index: OK', result.stdout)


class RecoveryArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.archive = self.base / 'fixture.tar.gz'
        self.staging = self.base / 'staging'
        self.staging.mkdir()

    def make_tar(self, entries):
        with tarfile.open(self.archive, 'w:gz') as stream:
            for name, kind, mode in [('upstream', tarfile.DIRTYPE, 0o755), *entries]:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.mode = mode
                if kind == tarfile.SYMTYPE or kind == tarfile.LNKTYPE:
                    info.linkname = '/etc/passwd'
                stream.addfile(info)

    def test_traversal_absolute_and_wrong_root_rejected(self):
        for name in ('../escape', '/tmp/escape', 'upstream/../escape', 'other/file', 'upstream//file'):
            with self.subTest(name=name):
                self.make_tar([(name, tarfile.REGTYPE, 0o644)])
                with self.assertRaises(archive_module.SourceArchiveError):
                    archive_module.unpack(self.archive, self.staging)
                self.assertEqual(list(self.staging.iterdir()), [])

    def test_links_and_special_entries_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                self.make_tar([('upstream/evil', kind, 0o644)])
                with self.assertRaises(archive_module.SourceArchiveError):
                    archive_module.unpack(self.archive, self.staging)

    def test_duplicate_entries_rejected(self):
        self.make_tar([('upstream/file', tarfile.REGTYPE, 0o644)] * 2)
        with self.assertRaisesRegex(archive_module.SourceArchiveError, 'Duplicate'):
            archive_module.unpack(self.archive, self.staging)

    def test_non_directory_parent_rejected(self):
        self.make_tar([('upstream/a', tarfile.REGTYPE, 0o644),
                       ('upstream/a/child', tarfile.REGTYPE, 0o644)])
        with self.assertRaisesRegex(archive_module.SourceArchiveError, 'parent'):
            archive_module.unpack(self.archive, self.staging)

    def test_setuid_entry_rejected(self):
        self.make_tar([('upstream/evil', tarfile.REGTYPE, 0o4755)])
        with self.assertRaisesRegex(archive_module.SourceArchiveError, 'permissions'):
            archive_module.unpack(self.archive, self.staging)

    def test_existing_destination_rejected(self):
        (self.staging / 'existing').write_text('keep')
        self.make_tar([])
        with self.assertRaisesRegex(archive_module.SourceArchiveError, 'empty'):
            archive_module.unpack(self.archive, self.staging)
        self.assertEqual((self.staging / 'existing').read_text(), 'keep')

    def test_empty_archive_rejected(self):
        with tarfile.open(self.archive, 'w:gz'):
            pass
        with self.assertRaisesRegex(archive_module.SourceArchiveError, 'root'):
            archive_module.unpack(self.archive, self.staging)

    def test_too_many_entries_rejected(self):
        self.make_tar([('upstream/file', tarfile.REGTYPE, 0o644)])
        with patch.object(archive_module, 'MAX_MEMBERS', 1):
            with self.assertRaisesRegex(archive_module.SourceArchiveError, 'too many'):
                archive_module.unpack(self.archive, self.staging)

    def test_valid_small_archive_extracts(self):
        self.make_tar([('upstream/file', tarfile.REGTYPE, 0o644)])
        result = archive_module.unpack(self.archive, self.staging)
        self.assertEqual(result, self.staging / 'upstream')
        self.assertTrue((result / 'file').is_file())


if __name__ == '__main__':
    unittest.main()
