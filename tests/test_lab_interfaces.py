# SPDX-License-Identifier: MIT
"""Help-only Lab interface detection; no native benchmark or installation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import launch_iocost as launch


class LabInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lab interfaces ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lab = self.root / 'lab'
        self.lab.mkdir()
        (self.lab / 'iocost_report.py').touch()
        self.stage = self.root / 'stage'
        (self.stage / 'bin').mkdir(parents=True)
        self.installed = self.root / 'installed'
        self.installed.mkdir()
        for name in ('resctl-bench', 'rd-agent', 'rd-hashd'):
            for directory in (self.stage / 'bin', self.installed):
                p = directory / name
                p.write_text('fixture bytes for ' + name)
                p.chmod(0o755)

    def help_script(self, option):
        (self.lab / 'RUN.sh').write_text('#!/bin/sh\n'
            '[ "$1" = run ] && [ "$2" = --help ] || exit 90\n'
            'printf "%s\\n" "usage: run ' + option + ' PATH"\n')

    def test_detects_installed_runtime_interface_from_help_only(self):
        self.help_script('--bin-dir')
        self.assertEqual(launch.detect_lab_interface(self.lab), '--bin-dir')

    def test_detects_legacy_runtime_interface(self):
        self.help_script('--runtime-dir')
        self.assertEqual(launch.detect_lab_interface(self.lab), '--runtime-dir')

    def test_unknown_or_partial_option_is_rejected(self):
        self.help_script('--bin-directory')
        with self.assertRaisesRegex(RuntimeError, 'supported'):
            launch.detect_lab_interface(self.lab)

    def test_nonzero_help_is_rejected(self):
        (self.lab / 'RUN.sh').write_text('#!/bin/sh\nexit 1\n')
        with self.assertRaisesRegex(RuntimeError, 'Cannot read'):
            launch.detect_lab_interface(self.lab)

    def test_modern_launch_uses_installed_bin_directory(self):
        self.help_script('--bin-dir')
        args = launch.prepare_arguments(self.lab, self.installed, 'full', runtime_option='--bin-dir')
        self.assertEqual(args[args.index('--bin-dir') + 1], str(self.installed))
        self.assertNotIn('--runtime-dir', args)
        self.assertNotIn('--yes', args)
        self.assertNotIn('--scratch', args)

    def test_modern_preflight_has_no_installation_flags(self):
        self.help_script('--bin-dir')
        args = launch.prepare_arguments(self.lab, self.installed, 'preflight', runtime_option='--bin-dir')
        self.assertNotIn('--install', args)
        self.assertNotIn('--install-deps', args)

    def test_unknown_argument_interface_rejected(self):
        self.help_script('--bin-dir')
        with self.assertRaises(RuntimeError):
            launch.prepare_arguments(self.lab, self.installed, 'full', runtime_option='--force')

    def test_installed_bytes_must_match_all_companions(self):
        with patch.object(launch.shutil, 'which', return_value=str(self.installed / 'resctl-bench')):
            self.assertEqual(launch.installed_bin_dir(self.stage), self.installed)

    def test_stale_agent_installation_not_used(self):
        (self.installed / 'rd-agent').write_text('old bytes')
        with patch.object(launch.shutil, 'which', return_value=str(self.installed / 'resctl-bench')):
            with self.assertRaisesRegex(RuntimeError, 'Installed rd-agent'):
                launch.installed_bin_dir(self.stage)

    def test_missing_installation_never_falls_back_to_user_stage(self):
        with patch.object(launch.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'uses installed commands'):
                launch.installed_bin_dir(self.stage)


if __name__ == '__main__':
    unittest.main()
