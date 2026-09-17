"""Delivery-failure regressions. Source inspection and synthetic orchestration only."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import build as bk
import launch_iocost as launch

class NativeSourceRegressions(unittest.TestCase):
    def test_contract_precedes_initialization_in_every_binary(self):
        for name in ('resctl-bench','rd-agent','rd-hashd','resctl-demo'):
            text=(ROOT/'upstream'/name/'src/main.rs').read_text().split('fn main() {',1)[1]
            self.assertTrue(text.lstrip().startswith('if maybe_show_runtime_contract()'))
    def test_job_failure_returns_error_instead_of_explicit_panic(self):
        source=(ROOT/'upstream/resctl-bench/src/main.rs').read_text()
        body=source.split('if let Err(e) = rctx.run_jctx(jctx) {',1)[1].split('\n            }',1)[0]
        self.assertIn('return Err',body);self.assertNotIn('panic!',body)
    def test_memory_and_process_snapshots_are_refreshed(self):
        source=(ROOT/'upstream/rd-agent/src/main.rs').read_text().split('fn startup_checks',1)[1]
        self.assertLess(source.index('sys.refresh_memory()'),source.index('sys.used_swap()'))
        self.assertLess(source.index('sys.refresh_processes()'),source.index('sys.processes()'))
    def test_shutdown_stops_retry_before_reset_or_panic(self):
        source=(ROOT/'upstream/rd-agent/src/report.rs').read_text()
        body=source.split('fn maybe_retry_iolat',1)[1].split('fn run',1)[0]
        self.assertLess(body.index('if prog_exiting()'),body.index('iolat.reset()'))
        self.assertIn('return false;',body)
        self.assertGreaterEqual(source.count("break 'outer;"),2)
    def test_native_validation_target_runs_compiler_gates(self):
        text=(ROOT/'Makefile').read_text().split('native-validate:',1)[1]
        self.assertIn('verify-source doctor check test-compile package verify',text)

class RustTestSelectionOrchestration(unittest.TestCase):
    """Cargo is a deliberate double, never evidence of a Rust pass."""
    def test_filters_have_unique_logs_and_required_counts(self):
        counts={'misc::support_tests::':10,'storage_info::source_resolution_tests::':8,
                'slices::io_policy_tests::':6,'runtime_contract_tests::':3}
        with tempfile.TemporaryDirectory() as tmp:
            b=bk.Builder(Path(tmp),bk.Config.from_env({}));calls=[]
            def cargo(action,args,env,*,log):
                selected=next(x for x in args if x in counts);calls.append((selected,log))
                log.write_text('SYNTHETIC TEST OUTPUT; no Rust execution\n'
                    f'test result: ok. {counts[selected]} passed; 0 failed; 0 ignored;\n')
                return ''
            with patch.object(b,'cargo_context',return_value=({}, {'build_id':'fixture','host':'fixture'})),patch.object(b,'cargo',side_effect=cargo):
                result=b.runtime_tests()
            self.assertEqual(result['passed'],27)
            self.assertEqual({x[0] for x in calls},set(counts));self.assertEqual(len({x[1] for x in calls}),4)
    def test_empty_test_filter_never_counts_as_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=bk.Builder(Path(tmp),bk.Config.from_env({}))
            def cargo(action,args,env,*,log):
                log.write_text('test result: ok. 0 passed; 0 failed; 0 ignored;\n')
            with patch.object(b,'cargo_context',return_value=({}, {'build_id':'fixture','host':'fixture'})),patch.object(b,'cargo',side_effect=cargo):
                with self.assertRaisesRegex(bk.BuildError,'did not all pass'):b.runtime_tests()
            self.assertFalse((b.work/'builds/fixture/runtime-unit-tests.json').exists())

class LauncherExplicitServicePlan(unittest.TestCase):
    def test_service_plan_forwarded_without_unattended_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            lab=Path(tmp);(lab/'RUN.sh').touch();(lab/'iocost_report.py').touch()
            args=launch.prepare_arguments(lab,Path('/usr/local/bin'),'full',runtime_option='--bin-dir',quiesce_zram_writeback=True)
            self.assertIn('--quiesce-zram-writeback',args);self.assertNotIn('--yes',args);self.assertNotIn('--force',args)
    def test_legacy_runtime_cannot_receive_new_service_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            lab=Path(tmp);(lab/'RUN.sh').touch();(lab/'iocost_report.py').touch()
            with self.assertRaisesRegex(RuntimeError,'2.1'):
                launch.prepare_arguments(lab,Path('/runtime'),'full',quiesce_zram_writeback=True)
