"""Real small allocations and notification sockets; no privileged host changes.

Counter/clock fault injection is explicit. These tests are not an IOCost run or
proof that a large balloon can be admitted on a particular maintenance host.
"""
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'upstream/rd-agent/src/misc/memory-balloon.py'
spec = importlib.util.spec_from_file_location('native_balloon', HELPER)
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
MIB = 1024**2
PAGE = os.sysconf('SC_PAGE_SIZE')


def ample():
    return {'MemTotal': 8 * 1024 * MIB, 'MemAvailable': 6 * 1024 * MIB}


class AllocationTests(unittest.TestCase):
    def allocate(self, size, **kw):
        return b.allocate_exact(size, PAGE, 100.0, 12, read_memory=kw.pop('read_memory', ample),
                                read_oom=kw.pop('read_oom', lambda: 12),
                                clock=kw.pop('clock', lambda: 1.0), **kw)

    def test_rounds_up_for_every_host_page_size(self):
        for page in (4096, 16384, 65536):
            self.assertEqual(b.rounded_size('10001', page), (10001 + page - 1) // page * page)
            self.assertEqual(b.rounded_size(str(2**60+1), page), 2**60+page)

    def test_zero_is_exact(self):
        self.assertEqual(b.rounded_size('0', PAGE), 0)
        self.assertIsNone(self.allocate(0))

    def test_bad_integer_and_overflow_rejected(self):
        for text in ('-1', '1.0', 'nan', 'inf', '1e9', ' 1', '+1', '', '9'*21, str(sys.maxsize)):
            with self.subTest(text=text), self.assertRaises(b.BalloonError):
                b.rounded_size(text, PAGE)

    def test_invalid_page_size_rejected(self):
        for page in (0, -1, 3, 6000):
            with self.assertRaises(b.BalloonError): b.rounded_size('1', page)

    def test_real_mapping_faults_every_page(self):
        size = (2 * MIB + PAGE)
        mapping = self.allocate(size)
        try:
            self.assertEqual(len(mapping), size)
            self.assertTrue(all(mapping[i] == 1 for i in range(0, size, PAGE)))
        finally:
            mapping.close()
        self.assertTrue(mapping.closed)

    def test_multiple_chunks_all_faulted(self):
        with patch.object(b, 'CHUNK', PAGE * 2):
            mapping = self.allocate(PAGE * 7)
        try:
            self.assertEqual([mapping[i] for i in range(0, len(mapping), PAGE)], [1]*7)
        finally:
            mapping.close()

    def test_physical_limit_rejected_before_mapping(self):
        with patch.object(b.mmap, 'mmap') as allocate:
            with self.assertRaisesRegex(b.BalloonError, 'physical RAM'):
                self.allocate(8 * 1024 * MIB)
            allocate.assert_not_called()

    def test_oom_delta_aborts_and_closes(self):
        mapping = b.mmap.mmap(-1, PAGE)
        with patch.object(b.mmap, 'mmap', return_value=mapping):
            with self.assertRaisesRegex(b.BalloonError, 'OOM counter'):
                self.allocate(PAGE, read_oom=lambda: 13)
        self.assertTrue(mapping.closed)

    def test_low_headroom_times_out_not_partial_success(self):
        mapping = b.mmap.mmap(-1, PAGE)
        now = [0.0]
        def sleep(_): now[0] += 51.0
        with patch.object(b.mmap, 'mmap', return_value=mapping):
            with self.assertRaisesRegex(b.BalloonError, 'timed out'):
                self.allocate(PAGE, read_memory=lambda: {'MemTotal': 8*1024*MIB, 'MemAvailable': 0},
                              clock=lambda: now[0], sleep=sleep)
        self.assertTrue(mapping.closed)

    def test_timeout_after_last_page_still_fails(self):
        clock = iter([1.0, 101.0])
        with self.assertRaisesRegex(b.BalloonError, 'deadline'):
            self.allocate(PAGE, clock=lambda: next(clock))

    def test_oom_after_last_page_still_fails(self):
        counter = iter([12, 13])
        with self.assertRaisesRegex(b.BalloonError, 'OOM counter'):
            self.allocate(PAGE, read_oom=lambda: next(counter))

    def test_signal_exception_releases_mapping(self):
        mapping = b.mmap.mmap(-1, PAGE)
        def fail(): raise b.Stopped()
        with patch.object(b.mmap, 'mmap', return_value=mapping):
            with self.assertRaises(b.Stopped): self.allocate(PAGE, read_oom=fail)
        self.assertTrue(mapping.closed)

    def test_allocation_failure_never_retries(self):
        with patch.object(b.mmap, 'mmap', side_effect=MemoryError('injected')) as allocate:
            with self.assertRaises(MemoryError): self.allocate(PAGE)
        allocate.assert_called_once()


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-balloon-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_meminfo_requires_consistent_real_units(self):
        p = self.root/'meminfo'
        p.write_text('MemTotal: 1024 kB\nMemAvailable: 512 kB\n')
        self.assertEqual(b.memory_info(p), {'MemTotal': 1024**2, 'MemAvailable': 512*1024})
        for text in ('MemTotal: 1 MB\nMemAvailable: 0 kB\n', 'MemTotal: 1 kB\nMemAvailable: 2 kB\n',
                     '', 'MemTotal: 1 kB\nMemTotal: 1 kB\nMemAvailable: 0 kB\n'):
            p.write_text(text)
            with self.assertRaises(b.BalloonError): b.memory_info(p)

    def test_oom_counter_is_required(self):
        p = self.root/'vmstat'
        p.write_text('oom_kill 12\n'); self.assertEqual(b.oom_count(p), 12)
        for text in ('', 'oom_kill -1\n', 'oom_kill bad\n'):
            p.write_text(text)
            with self.assertRaises(b.BalloonError): b.oom_count(p)

    def test_atomic_status_private_and_numeric(self):
        p = self.root/'status.json'
        b.write_status(p, state='ready', held_bytes=PAGE)
        data = json.loads(p.read_text())
        self.assertEqual(data['held_bytes'], PAGE)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob('.balloon-status-*')))

    def test_status_leaf_symlink_does_not_truncate_target(self):
        target = self.root/'other'; target.write_text('unchanged')
        p = self.root/'status.json'; p.symlink_to(target)
        b.write_status(p, state='ready', held_bytes=PAGE)
        self.assertEqual(target.read_text(), 'unchanged')
        self.assertFalse(p.is_symlink())

    def test_status_ancestor_symlink_is_rejected(self):
        real = self.root/'real'; (real/'subdir').mkdir(parents=True)
        alias = self.root/'alias'; alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(b.BalloonError): b.write_status(alias/'subdir/status', state='ready')

    def test_missing_or_relative_notify_rejected(self):
        for value in ('', 'relative'):
            with self.assertRaises(b.BalloonError): b.notify('READY=1', value)


class ProcessTests(unittest.TestCase):
    setUp = MetadataTests.setUp
    def run_helper(self, address, env_changes=None, amount='10001'):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind('\0'+address[1:] if address.startswith('@') else address)
            receiver.settimeout(5)
            env = {'PATH': '/usr/bin:/bin', 'NOTIFY_SOCKET': address, 'PYTHONDONTWRITEBYTECODE': '1',
                   **(env_changes or {})}
            p = subprocess.Popen([sys.executable, '-I', '-B', str(HELPER), amount, '--status', str(self.root/'state.json')],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                messages = []
                while not any(x.startswith('READY=1') for x in messages):
                    messages.append(receiver.recv(4096).decode())
                row = json.loads((self.root/'state.json').read_text())
                self.assertEqual(row['state'], 'ready')
                self.assertEqual(row['held_bytes'], b.rounded_size(amount, PAGE))
                self.assertEqual(row['requested_bytes'], int(amount))
                p.send_signal(signal.SIGTERM)
                _, stderr = p.communicate(timeout=5)
                self.assertEqual(p.returncode, 0, stderr)
                stopped = json.loads((self.root/'state.json').read_text())
                self.assertEqual(stopped['held_bytes'], 0)
                self.assertTrue(stopped['was_ready'])
                self.assertIsInstance(stopped['requested_bytes'], int)
            finally:
                if p.poll() is None: p.kill()
                p.communicate(timeout=5)

    def test_real_path_notification_and_graceful_release(self):
        self.run_helper(str(self.root/'notify'))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux abstract sockets')
    def test_real_abstract_notification_and_release(self):
        self.run_helper('@resctl-test-'+str(os.getpid())+'-'+str(time.monotonic_ns()))

    def test_legacy_override_is_rejected_before_allocation(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(HELPER), '10001'],
                                env={'IOCOST_BALLOON_STATE_DIR': str(self.root)}, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'legacy IOCost balloon override', result.stderr)

    def test_missing_notification_cannot_claim_success(self):
        result = subprocess.run([sys.executable, '-I', '-B', str(HELPER), '10001'],
                                env={}, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'NOTIFY_SOCKET', result.stderr)


if __name__ == '__main__':
    unittest.main()
