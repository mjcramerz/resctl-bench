# SPDX-License-Identifier: MIT
"""Source, export-contract and regression tests. Stub BCC/Cargo are NOT live BPF/Rust."""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build as bk
import runtime_support as support
import launch_iocost as launch


class SourceContractTests(unittest.TestCase):
    def test_reviewed_source_has_required_flags_and_unchanged_measurement(self):
        result = support.validate_source(ROOT / 'upstream', ROOT / 'compat/runtime-contract.json')
        self.assertEqual(result['bcc_cflags'], list(support.FLAGS))

    def test_original_measurement_program_is_identical(self):
        old = subprocess.check_output(['git', '-C', str(ROOT / 'upstream'), 'show',
                                      'HEAD:rd-agent/src/misc/biolatpcts.py']).decode()
        new = (ROOT / 'upstream/rd-agent/src/misc/biolatpcts.py').read_text()
        def bpf(text):
            return next(ast.literal_eval(n.value) for n in ast.parse(text).body
                        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bpf_source' for t in n.targets))
        self.assertEqual(bpf(old), bpf(new))

    def test_reset_repopulates_from_same_embedded_table_as_export(self):
        source = (ROOT / 'upstream/rd-agent/src/misc.rs').read_text()
        self.assertIn('write_misc_bins(Path::new(&cfg.misc_bin_path))?', source)
        self.assertIn('write_misc_bins(&directory)', source)
        for name in support.FILES:
            self.assertIn('include_bytes!("misc/' + name + '")', source)

    def test_export_precedes_host_initialization(self):
        main = (ROOT / 'upstream/rd-agent/src/main.rs').read_text().split('fn main() {', 1)[1]
        export = main.index('misc::maybe_export_support')
        self.assertLess(export, main.index('setup_prog_state()'))
        self.assertLess(export, main.index('let args_file = Args::init_args_and_logging'))
        self.assertLess(export, main.index('Config::new'))

    def test_dirty_base_version_remains_accepted_by_lab_1_5(self):
        self.assertRegex('resctl-bench 2.2.6-gbef3b59-dirty', r'\bresctl-bench 2\.2\.6-gbef3b59(?:\b|[0-9a-f])')

    def test_current_source_lock_accepts_only_reviewed_patch(self):
        lock = bk.Builder(ROOT, bk.Config.from_env({})).verify_source()
        self.assertEqual(lock['commit'], 'bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b')
        self.assertTrue(lock['patchset'])

    def test_update_source_cannot_silently_drop_patch(self):
        builder = bk.Builder(ROOT, bk.Config.from_env({}))
        with patch.object(builder, 'git', side_effect=AssertionError('No network/Git update may run')):
            with self.assertRaisesRegex(bk.BuildError, 'cannot silently remove'):
                builder.fetch(update=True)

    def test_native_filtered_tests_are_present(self):
        source = (ROOT / 'upstream/rd-agent/src/misc.rs').read_text()
        self.assertIn('mod support_tests', source)
        self.assertEqual(source.count('#[test]'), 10)
        self.assertIn('reset_recreation_preserves_compatibility', source)
        self.assertIn('rejects_helper_symlink_without_touching_target', source)

    def test_native_helper_write_is_atomic(self):
        source = (ROOT / 'upstream/rd-agent/src/misc.rs').read_text()
        self.assertIn('create_new(true)', source)
        self.assertIn('file.sync_all()', source)
        self.assertIn('fs::rename(&temporary, &path)', source)
        self.assertNotIn('.truncate(true)', source)


class ExportContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='support contract ')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.contract = support.read_contract(ROOT / 'compat/runtime-contract.json')
        self.directory = self.base / 'helpers'
        shutil.copytree(ROOT / 'upstream/rd-agent/src/misc', self.directory)

    def test_good_hashes(self):
        self.assertEqual(support.verify_files(self.directory, self.contract), self.contract['files'])

    def test_modified_helper_is_rejected(self):
        (self.directory / 'biolatpcts.py').write_text('old helper')
        with self.assertRaisesRegex(support.SupportError, 'differs'):
            support.verify_files(self.directory, self.contract)

    def test_nonexecutable_helper_rejected(self):
        (self.directory / 'biolatpcts.py').chmod(0o644)
        with self.assertRaisesRegex(support.SupportError, 'executable mode'):
            support.verify_files(self.directory, self.contract)

    def test_nonobject_contract_rejected(self):
        for data in (None, [], 5, 'text', {**self.contract, 'bcc_cflags': None}):
            path = self.base / 'malformed.json'
            path.write_text(json.dumps(data))
            with self.assertRaises(support.SupportError):
                support.read_contract(path)

    def test_extra_files_rejected(self):
        (self.directory / 'unreviewed.py').touch()
        with self.assertRaises(support.SupportError):
            support.verify_files(self.directory, self.contract)

    def test_missing_file_rejected(self):
        (self.directory / 'biolatpcts.py').unlink()
        with self.assertRaises(support.SupportError):
            support.verify_files(self.directory, self.contract)

    def test_symlink_helper_rejected(self):
        p = self.directory / 'biolatpcts.py'
        p.unlink()
        p.symlink_to(ROOT / 'upstream/rd-agent/src/misc/biolatpcts.py')
        with self.assertRaises(support.SupportError):
            support.verify_files(self.directory, self.contract)

    def test_symlink_directory_rejected(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(support.SupportError):
            support.verify_files(alias, self.contract)

    def test_malformed_contract_rejected(self):
        for bad in ({}, {**self.contract, 'files': {'../a': 'x'}}, {**self.contract, 'bcc_cflags': []}):
            path = self.base / 'bad.json'
            path.write_text(json.dumps(bad))
            with self.assertRaises(support.SupportError):
                support.read_contract(path)

    def fake_agent(self, body):
        binary = self.base / 'bin/rd-agent'
        binary.parent.mkdir(exist_ok=True)
        binary.write_text('#!/bin/sh\n' + body + '\n')
        binary.chmod(0o755)
        return binary.parent

    def test_old_binary_without_export_support_fails_closed(self):
        binary = self.fake_agent('echo "unknown option --export-support" >&2; exit 2')
        with self.assertRaisesRegex(support.SupportError, 'old/unpatched'):
            support.run_export(binary, self.contract)

    def test_zero_exit_without_export_is_not_success(self):
        binary = self.fake_agent('exit 0')
        with self.assertRaises(support.SupportError):
            support.run_export(binary, self.contract)

    def test_no_automatic_probe_while_exporting(self):
        binary = self.fake_agent('echo "$@" >&2; exit 2')
        with self.assertRaises(support.SupportError) as error:
            support.run_export(binary, self.contract)
        self.assertIn('--export-support', str(error.exception))
        self.assertNotIn('--prepare', str(error.exception))
        self.assertNotIn('--reset', str(error.exception))

    def test_probe_needs_root(self):
        with patch('os.geteuid', return_value=1000):
            with self.assertRaisesRegex(support.SupportError, 'requires root'):
                support.probe_latency(self.base, self.contract, 'nvme0n1')

    def test_device_path_traversal_rejected(self):
        for value in ('../../x', '/tmp/nvme0n1', 'x;echo', 'x\ny'):
            with self.subTest(value=value), self.assertRaises(support.SupportError):
                support.device_number(value)


class CollectorPythonTests(unittest.TestCase):
    def execute(self, has_rq_disk=True, which='on-device', fail=False):
        captures = []
        class BPF:
            @staticmethod
            def kernel_struct_has_field(*args):
                return int(has_rq_disk)
            def __init__(self, **kwargs):
                captures.append(kwargs)
                if fail:
                    raise RuntimeError('real compiler failure would not be hidden')
            def __getitem__(self, key):
                return object()
        module = types.ModuleType('bcc')
        module.BPF = BPF
        argv = ['biolatpcts.py', '259:0', '-i', '0', '-w', which]
        with patch.dict(sys.modules, {'bcc': module}), patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            try:
                runpy.run_path(str(ROOT / 'upstream/rd-agent/src/misc/biolatpcts.py'), run_name='__main__')
            except SystemExit as exc:
                self.assertEqual(exc.code, 0)
        return captures

    def test_passes_flags_to_actual_constructor_call(self):
        calls = self.execute()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['cflags'], list(support.FLAGS))

    def test_new_request_disk_path_and_target_are_preserved(self):
        c = self.execute(has_rq_disk=False)[0]['text']
        self.assertIn('rq->q->disk', c)
        self.assertIn('!= 259', c)
        self.assertIn('!= 0', c)
        self.assertIn('rq->io_start_time_ns', c)

    def test_old_request_disk_path_is_preserved(self):
        self.assertIn('rq->rq_disk', self.execute()[0]['text'])

    def test_measurement_selector_is_preserved(self):
        for selector, field in [('from-rq-alloc', 'alloc_time_ns'), ('after-rq-alloc', 'start_time_ns')]:
            self.assertIn('rq->' + field, self.execute(which=selector)[0]['text'])

    def test_compile_error_is_not_bypassed(self):
        with self.assertRaisesRegex(RuntimeError, 'compiler failure'):
            self.execute(fail=True)


@unittest.skipUnless(shutil.which('clang'), 'Clang fixture requires a C compiler')
class ClangRegressionTests(unittest.TestCase):
    FIXTURE = '''#include <stddef.h>
struct __filename_head { char prefix[24]; };
struct filename { struct __filename_head; char iname[40]; };
_Static_assert(sizeof(struct filename) % 64 == 0, "sizeof(struct filename) % 64 == 0");
#ifdef CHECK_MEMBERS
_Static_assert(offsetof(struct filename, prefix) == 0, "head member offset");
_Static_assert(offsetof(struct filename, iname) == 24, "tail offset");
#endif
'''
    def clang(self, flags):
        return subprocess.run([shutil.which('clang'), '-x', 'c', '-std=gnu11', '-fsyntax-only', *flags, '-'],
                              input=self.FIXTURE, capture_output=True, text=True, check=False)

    def test_original_language_options_reproduce_40_equals_zero(self):
        result = self.clang([])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('40 == 0', result.stderr)

    def test_warning_suppression_alone_does_not_fix_layout(self):
        self.assertNotEqual(self.clang(['-Wno-missing-declarations']).returncode, 0)

    def test_required_options_preserve_layout_and_member_access(self):
        result = self.clang([*support.FLAGS, '-DCHECK_MEMBERS'])
        self.assertEqual(result.returncode, 0, result.stderr)


class BuildAcceptanceTests(unittest.TestCase):
    def test_cargo_target_flag_precedes_test_harness_separator(self):
        builder = bk.Builder(ROOT, bk.Config.from_env({}))
        with patch.object(builder, 'tools', return_value={'cargo': '/fake/cargo'}), \
             patch.object(builder, 'vendor_config', return_value=[]), \
             patch.object(builder, 'effective_source', return_value=ROOT / 'upstream'), \
             patch.object(bk, 'run', return_value='') as run:
            builder.cargo('test', ['filter', '--', '--test-threads=1'], {'CARGO_TARGET_DIR': '/tmp/target'})
        args = run.call_args.args[0]
        self.assertLess(args.index('--target-dir'), args.index('--'))

    def test_make_exposes_safe_native_test_target(self):
        self.assertIn('test-runtime', (ROOT / 'Makefile').read_text())
        source = (ROOT / 'scripts/build.py').read_text()
        self.assertIn('"misc::support_tests::", 10', source)
        self.assertIn('"storage_info::source_resolution_tests::", 8', source)
        self.assertIn('selector, "--", "--test-threads=1"', source)

    def test_native_support_is_checked_before_success_record(self):
        source = (ROOT / 'scripts/build.py').read_text().split('    def build(self,', 1)[1].split('    def smoke(', 1)[0]
        self.assertLess(source.index('self.verify_runtime_support('), source.index('write_json(result_path,'))

    def test_post_strip_gate_is_required(self):
        source = (ROOT / 'scripts/build.py').read_text().split('    def stage(', 1)[1].split('    def invalidate_package', 1)[0]
        self.assertLess(source.index('self.runtime_tests()'), source.index('checksums(stage)'))
        self.assertLess(source.index('"strip"'), source.index('self.verify_runtime_support('))


class LabBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lab = Path(self.tmp.name) / 'lab with spaces'
        self.lab.mkdir()
        (self.lab / 'RUN.sh').touch()
        (self.lab / 'iocost_report.py').touch()
        self.runtime = Path(self.tmp.name) / 'new runtime'

    def test_full_mode_pins_the_rebuilt_runtime(self):
        args = launch.prepare_arguments(self.lab, self.runtime, 'full')
        self.assertEqual(args[args.index('--runtime-dir') + 1], str(self.runtime))
        self.assertIn('--install-deps', args)
        self.assertNotIn('--yes', args)
        self.assertNotIn('--force', args)
        self.assertNotIn('--install', args)
        self.assertNotIn('--scratch', args)

    def test_install_is_explicit(self):
        self.assertIn('--install', launch.prepare_arguments(self.lab, self.runtime, 'install'))

    def test_preflight_never_requests_installation(self):
        args = launch.prepare_arguments(self.lab, self.runtime, 'preflight')
        self.assertIn('preflight', args)
        self.assertNotIn('--install-deps', args)
        self.assertNotIn('--install', args)

    def test_missing_successful_build_does_not_fallback_to_old_vendor(self):
        with patch.object(launch, 'ROOT', self.lab):
            with self.assertRaisesRegex(RuntimeError, 'No successfully built package'):
                launch.runtime_path(None)

    def test_shell_does_not_change_invocation_directory(self):
        text = (ROOT / 'RUN-IOCOST-LAB.sh').read_text()
        self.assertIn('BASE=$(CDPATH= cd', text)
        self.assertNotIn('\ncd ', text)
        self.assertIn(' -I -B ', text)


class StorageResolutionTests(unittest.TestCase):
    def test_source_uses_json_target_and_no_subvolume_suffix(self):
        source = (ROOT / 'upstream/rd-util/src/storage_info.rs').read_text()
        lookup = source.split('const FINDMNT_SOURCE_ARGS:', 1)[1].split('];', 1)[0]
        for flag in ('--json', '--first-only', '--evaluate', '--nofsroot', '--target'):
            self.assertIn('"' + flag + '"', lookup)
        function = source.split('pub fn path_to_devname', 1)[1].split('fn read_model', 1)[0]
        self.assertIn('findmnt_source(&output.stdout)', function)
        self.assertIn('is_block_device()', function)
        self.assertNotIn('fs::metadata(source.trim())', function)

    def test_invalid_swap_entries_are_not_silently_dropped(self):
        function = (ROOT / 'upstream/rd-util/src/storage_info.rs').read_text().split('pub fn swap_devnames', 1)[1].split('pub fn is_devname_rotational', 1)[0]
        self.assertNotIn('filter_map', function)
        self.assertIn('swap.context(', function)

    def test_eight_pure_native_storage_regressions_present(self):
        source = (ROOT / 'upstream/rd-util/src/storage_info.rs').read_text().split('mod source_resolution_tests', 1)[1]
        self.assertEqual(source.count('#[test]'), 8)
        self.assertNotIn('Command::new', source)

    @unittest.skipUnless(shutil.which('findmnt'), 'Requires util-linux findmnt')
    def test_actual_findmnt_options_use_structured_output(self):
        # Real read-only command; this is NOT execution of the Rust parser or a Btrfs mount test.
        result = subprocess.run(['findmnt', '--json', '--first-only', '--evaluate', '--nofsroot',
                                 '--output', 'SOURCE', '--target', str(ROOT)],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(len(data['filesystems']), 1)
        self.assertIsInstance(data['filesystems'][0]['source'], str)

    @unittest.skipUnless(shutil.which('findmnt'), 'Requires util-linux findmnt')
    def test_real_findmnt_btrfs_subvolume_suffix_regression(self):
        # Feed a mountinfo fixture to the actual util-linux parser; no mount or block IO.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'mountinfo'
            path.write_text('123 1 259:6 /@ / rw,relatime - btrfs /dev/nvme0n1p6 rw,subvolid=256,subvol=/@\n')
            base = ['findmnt', '--kernel', '--tab-file', str(path), '--json', '--first-only',
                    '--output', 'SOURCE', '--target', '/']
            observed = []
            for options in ([], ['--nofsroot']):
                result = subprocess.run(base + options, text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                observed.append(json.loads(result.stdout)['filesystems'][0]['source'])
            self.assertEqual(observed, ['/dev/nvme0n1p6[/@]', '/dev/nvme0n1p6'])
