# SPDX-License-Identifier: MIT
"""Regression for the reported make package / missing last-package failure.

Real source archives and Make entrypoints; no Rust compiler or storage workload.
The separate PipelineTests exercise publication/installation with a labelled
synthetic C ELF and Cargo double, not a native resctl build.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build as bk
import runtime_support as support
import install as installer


class SourcePermissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='source permissions ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'upstream'
        self.helpers = self.source / 'rd-agent/src/misc'
        shutil.copytree(ROOT / 'upstream/rd-agent/src/misc', self.helpers)
        self.contract_path = ROOT / 'compat/runtime-contract.json'
        self.contract = support.read_contract(self.contract_path)

    def set_modes(self, mode):
        for name in support.FILES:
            (self.helpers / name).chmod(mode)

    def test_source_validation_accepts_restricted_readable_assets_without_chmod(self):
        for mode in (0o700, 0o750, 0o755, 0o600, 0o640, 0o644):
            with self.subTest(mode=oct(mode)):
                self.set_modes(mode)
                self.assertEqual(support.validate_source(self.source, self.contract_path), self.contract)
                self.assertTrue(all((self.helpers / n).stat().st_mode & 0o7777 == mode
                                    for n in support.FILES))
        # The builder independently enforces the Git/source-lock executable bit;
        # no-exec source identity changes are NOT accepted by verify_source().

    def test_export_validation_still_requires_exact_runtime_mode(self):
        for mode in (0o700, 0o750, 0o600, 0o644, 0o775, 0o4755):
            with self.subTest(mode=oct(mode)):
                self.set_modes(mode)
                with self.assertRaisesRegex(support.SupportError, 'executable mode.*expected 0755'):
                    support.verify_files(self.helpers, self.contract)
        self.set_modes(0o755)
        self.assertEqual(support.verify_files(self.helpers, self.contract), self.contract['files'])

    def test_restricted_source_hash_mismatch_is_still_rejected(self):
        self.set_modes(0o700)
        with (self.helpers / 'biolatpcts.py').open('a') as stream:
            stream.write('\n# unreviewed modification\n')
        with self.assertRaisesRegex(support.SupportError, 'differs'):
            support.validate_source(self.source, self.contract_path)

    def test_restricted_source_symlink_is_still_rejected(self):
        self.set_modes(0o700)
        helper = self.helpers / 'biolatpcts.py'
        helper.unlink()
        helper.symlink_to(ROOT / 'upstream/rd-agent/src/misc/biolatpcts.py')
        with self.assertRaisesRegex(support.SupportError, 'nonregular'):
            support.validate_source(self.source, self.contract_path)

    @unittest.skipUnless(shutil.which('tar') and shutil.which('git'), 'Requires GNU tar and Git')
    def test_actual_locked_source_extracted_with_restrictive_umasks(self):
        archive = self.root / 'upstream.tar.gz'
        bk.make_archive(ROOT / 'upstream', archive, 0)
        for mask, mode in ((0o022, 0o755), (0o027, 0o750), (0o077, 0o700)):
            with self.subTest(umask=oct(mask)):
                dest = self.root / str(mask)
                dest.mkdir()
                subprocess.run(['tar', '--no-same-permissions', '-xzf', str(archive), '-C', str(dest)],
                               check=True, umask=mask, capture_output=True)
                source = dest / 'upstream'
                paths = [source / 'rd-agent/src/misc' / n for n in support.FILES]
                self.assertTrue(all(p.stat().st_mode & 0o777 == mode for p in paths))
                # This verifies the REAL 163-file source manifest, reviewed
                # Git patch, Cargo.lock and source helper contract together.
                bk.Builder(ROOT, bk.Config.from_env({})).verify_source(source=source)
                self.assertTrue(all(p.stat().st_mode & 0o777 == mode for p in paths))
                paths[0].chmod(0o600)
                with self.assertRaisesRegex(bk.BuildError, 'differ from the source lock'):
                    bk.Builder(ROOT, bk.Config.from_env({})).verify_source(source=source)


class CompletedPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='completed package ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.builder = bk.Builder(self.root, bk.Config.from_env({}))
        self.record = self.builder.work / 'last-package.json'
        self.stage = self.builder.work / 'stage/fixture'
        self.stage.mkdir(parents=True)
        self.archive = self.builder.dist / 'fixture.tar.gz'
        self.archive.parent.mkdir()
        self.archive.write_bytes(b'NOT A NATIVE PACKAGE - metadata-validation fixture\n')
        self.info = {'stage': str(self.stage), 'path': str(self.archive), 'sha256': bk.digest(self.archive)}

    def save(self, info=None):
        bk.write_json(self.record, self.info if info is None else info)

    def test_missing_package_install_explains_order_without_build_or_writes(self):
        with patch.object(bk, 'run') as run, patch.object(self.builder, 'build') as build:
            with self.assertRaisesRegex(bk.BuildError, 'No successfully completed package') as ctx:
                self.builder.install()
        self.assertIn('make package verify as your ordinary user', str(ctx.exception))
        self.assertIn('only after it succeeds', str(ctx.exception))
        run.assert_not_called()
        build.assert_not_called()
        self.assertFalse(self.record.exists())

    def test_last_package_returns_validated_record(self):
        self.save()
        self.assertEqual(self.builder.last_package(), self.info)

    def test_missing_stage_is_actionable(self):
        self.save()
        self.stage.rmdir()
        with self.assertRaisesRegex(bk.BuildError, 'stage is missing'):
            self.builder.last_package()

    def test_damaged_archive_is_not_installed(self):
        self.save()
        self.archive.write_bytes(b'tampered')
        with patch.object(bk, 'run') as run:
            with self.assertRaisesRegex(bk.BuildError, 'checksum/path mismatch'):
                self.builder.install()
            run.assert_not_called()

    def test_missing_archive_is_not_installed(self):
        self.save()
        self.archive.unlink()
        with self.assertRaisesRegex(bk.BuildError, 'checksum/path mismatch'):
            self.builder.last_package()

    def test_invalid_json_is_actionable(self):
        self.record.write_text('{broken')
        with self.assertRaisesRegex(bk.BuildError, 'Invalid last-package manifest.*make package verify'):
            self.builder.last_package()

    def test_invalid_manifest_shapes_are_rejected(self):
        for info in ([], 'invalid', 1, {}, {**self.info, 'stage': None},
                     {**self.info, 'path': ''}, {**self.info, 'sha256': 'bad'}):
            with self.subTest(info=info):
                self.save(info)
                with self.assertRaisesRegex(bk.BuildError, 'Invalid last-package manifest'):
                    self.builder.last_package()

    def test_paths_cannot_escape_the_publication_directories(self):
        for field in ('stage', 'path'):
            for value in ('relative/path', '/tmp/other', str(self.builder.work / 'stage'),
                          str(self.builder.dist), str(self.stage / '../fixture')):
                with self.subTest(field=field, path=value):
                    self.save({**self.info, field: value})
                    with self.assertRaisesRegex(bk.BuildError, 'Unsafe last-package'):
                        self.builder.last_package()

    def test_stage_symlink_is_rejected_even_when_it_stays_inside_work(self):
        other = self.stage.with_name('other')
        other.mkdir()
        self.stage.rmdir()
        self.stage.symlink_to(other, target_is_directory=True)
        self.save()
        with self.assertRaisesRegex(bk.BuildError, 'Symlink in last-package stage'):
            self.builder.last_package()

    def test_manifest_symlink_is_rejected(self):
        other = self.root / 'other.json'
        bk.write_json(other, self.info)
        self.record.symlink_to(other)
        with self.assertRaisesRegex(bk.BuildError, 'Unsafe last-package manifest'):
            self.builder.last_package()

    def test_failed_new_attempt_cannot_reuse_old_published_package(self):
        self.save()
        with patch.object(self.builder, 'stage', side_effect=bk.BuildError('fixture compile failure')):
            with self.assertRaisesRegex(bk.BuildError, 'fixture compile failure'):
                self.builder.package()
        self.assertFalse(self.record.exists())
        with self.assertRaisesRegex(bk.BuildError, 'No successfully completed package'):
            self.builder.install()


class InstallDirectoryPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='install directories ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_new_directories_have_public_traversal_under_restrictive_umasks(self):
        for mask in (0o022, 0o027, 0o077):
            with self.subTest(umask=oct(mask)):
                target = self.root / str(mask) / 'usr/local/bin'
                old = os.umask(mask)
                try:
                    installer.ensure_directory(target)
                finally:
                    os.umask(old)
                while target != self.root:
                    self.assertEqual(target.stat().st_mode & 0o777, 0o755)
                    target = target.parent

    def test_existing_private_parent_is_not_widened(self):
        parent = self.root / 'private-destdir'
        parent.mkdir(mode=0o700)
        installer.ensure_directory(parent / 'usr/local/bin')
        self.assertEqual(parent.stat().st_mode & 0o777, 0o700)

    def test_symlink_parent_is_rejected_without_chmod(self):
        outside = self.root / 'outside'
        outside.mkdir(mode=0o700)
        alias = self.root / 'alias'
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(installer.InstallError, 'symlink'):
            installer.ensure_directory(alias / 'bin')
        self.assertEqual(outside.stat().st_mode & 0o777, 0o700)
        self.assertFalse((outside / 'bin').exists())

    def test_nondirectory_parent_is_rejected(self):
        file = self.root / 'file'
        file.write_text('not a directory')
        with self.assertRaisesRegex(installer.InstallError, 'not a directory'):
            installer.ensure_directory(file / 'bin')


if __name__ == '__main__':
    unittest.main()
