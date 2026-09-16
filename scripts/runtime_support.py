#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify compiled rd-agent helpers, optionally initialize the real BPF collector.

Export-only mode writes private temporary files; it does not invoke the normal
agent lifecycle, detect disks, start services, change swap or attach BPF.
A separately requested --probe-latency needs root and attaches real BPF probes,
without starting a storage workload. No result is fabricated on a probe failure.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping

FILES = ('biolatpcts.py', 'biolatpcts_wrapper.sh', 'iocost_coef_gen.py', 'sideloader.py')
FLAGS = ('-fms-extensions', '-Wno-microsoft-anon-tag')


class SupportError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_contract(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if (not isinstance(data, dict) or data.get('schema') != 1
            or not isinstance(data.get('files'), dict) or set(data['files']) != set(FILES)
            or not isinstance(data.get('bcc_cflags'), list) or tuple(data['bcc_cflags']) != FLAGS
            or not isinstance(data.get('base_commit'), str)
            or not re.fullmatch(r'[0-9a-f]{40}', data['base_commit'])
            or not isinstance(data.get('id'), str) or not data['id']
            or not isinstance(data.get('bpf_measurement_program_sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', data['bpf_measurement_program_sha256'])):
        raise SupportError('Invalid runtime compatibility contract: ' + str(path))
    if not all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in data['files'].values()):
        raise SupportError('Invalid helper hash in runtime contract')
    return data


def verify_files(directory: Path, contract: Mapping[str, Any], *, exact: bool = True) -> dict[str, str]:
    if not directory.is_dir() or directory.is_symlink():
        raise SupportError('Agent did not export a real helper directory: ' + str(directory))
    if exact and {p.name for p in directory.iterdir()} != set(FILES):
        raise SupportError('Compiled support export has missing or unexpected files')
    hashes = {}
    for name in FILES:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise SupportError('Missing/nonregular support file: ' + name)
        if path.stat().st_mode & 0o7777 != 0o755:
            raise SupportError('Support file does not have the required executable mode: ' + name)
        actual = sha256(path)
        if actual != contract['files'][name]:
            raise SupportError('Embedded helper differs from reviewed source: ' + name)
        hashes[name] = actual
    return hashes


def validate_source(source: Path, contract_path: Path) -> dict[str, Any]:
    contract = read_contract(contract_path)
    directory = source / 'rd-agent/src/misc'
    verify_files(directory, contract)
    text = (directory / 'biolatpcts.py').read_text()
    tree = ast.parse(text)
    initializers = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'BPF']
    if len(initializers) != 1:
        raise SupportError('Expected exactly one real BPF constructor')
    options = {kw.arg: kw.value for kw in initializers[0].keywords}
    if 'cflags' not in options or tuple(ast.literal_eval(options['cflags'])) != FLAGS:
        raise SupportError('Required BCC C language flags missing')
    if not text.startswith('#!/usr/bin/python3\n'):
        raise SupportError('Latency helper must use Debian Python 3')
    bpf = next(ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bpf_source' for t in node.targets))
    if hashlib.sha256(bpf.encode()).hexdigest() != contract['bpf_measurement_program_sha256']:
        raise SupportError('Measurement program changed; explicit semantic review required')
    return contract


def run_export(binary_dir: Path, contract: Mapping[str, Any], *,
               environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    agent = binary_dir.resolve() / 'rd-agent'
    if not agent.is_file() or agent.is_symlink() or not os.access(agent, os.X_OK):
        raise SupportError('Missing executable rd-agent: ' + str(agent))
    env = dict(environment or os.environ)
    # Unlike normal agent startup, export cannot read an args file or host state.
    with tempfile.TemporaryDirectory(prefix='resctl-embedded-support-') as temp:
        base = Path(temp)
        target = base / 'helpers'
        env.update(HOME=temp, TMPDIR=temp, LC_ALL='C', PYTHONNOUSERSITE='1')
        before = sha256(agent)
        try:
            proc = subprocess.run([str(agent), '--export-support', str(target)],
                                  cwd=base, env=env, capture_output=True, text=True,
                                  timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SupportError('Embedded support export failed: ' + str(exc)) from exc
        if proc.returncode:
            raise SupportError(f'rd-agent --export-support exited {proc.returncode}; '
                               'this may be an old/unpatched or CPU-incompatible binary.\n' +
                               proc.stdout[-2000:] + proc.stderr[-6000:])
        hashes = verify_files(target, contract)
        if sha256(agent) != before:
            raise SupportError('Agent changed during compiled-helper verification')
    return {'schema': 1, 'verified': True, 'kind': 'compiled-embedded-helper-export',
            'bpf_attached': False, 'storage_workload_run': False,
            'compatibility_id': contract['id'], 'agent_sha256': before,
            'helper_sha256': hashes, 'stdout': proc.stdout, 'stderr': proc.stderr}


def device_number(device: str) -> str:
    if re.fullmatch(r'\d+:\d+', device):
        path = Path('/sys/dev/block') / device
    else:
        name = Path(device).name
        if device not in (name, '/dev/' + name) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise SupportError('Use a whole-device name, /dev/name, or major:minor')
        path = Path('/sys/class/block') / name
    path = path.resolve(strict=True)
    name = path.name
    if ((path / 'partition').exists() or name.startswith(('zram', 'ram', 'loop', 'dm-', 'md', 'sr'))
            or (path / 'slaves').exists() and any((path / 'slaves').iterdir())):
        raise SupportError('Probe target must be a directly attributable physical whole disk')
    devno = (path / 'dev').read_text().strip()
    if not re.fullmatch(r'\d+:\d+', devno):
        raise SupportError('Malformed sysfs device number')
    return devno


def probe_latency(binary_dir: Path, contract: Mapping[str, Any], device: str) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise SupportError('--probe-latency requires root to initialize the actual BPF collector')
    devno = device_number(device)
    agent = binary_dir.resolve() / 'rd-agent'
    # First refuse stale binaries using the same post-link acceptance check.
    verification = run_export(binary_dir, contract)
    with tempfile.TemporaryDirectory(prefix='resctl-latency-probe-') as temp:
        target = Path(temp) / 'helpers'
        env = {**os.environ, 'LC_ALL': 'C', 'HOME': temp, 'TMPDIR': temp,
               'PATH': '/usr/sbin:/usr/bin:/sbin:/bin'}
        exported = subprocess.run([str(agent), '--export-support', str(target)], env=env,
                                  capture_output=True, text=True, timeout=30, check=False)
        if exported.returncode:
            raise SupportError('Native support export failed: ' + exported.stderr[-6000:])
        verify_files(target, contract)
        if sha256(agent) != verification['agent_sha256']:
            raise SupportError('Agent changed before latency probe')
        argv = [str(target / 'biolatpcts_wrapper.sh'), devno, '--interval', '0']
        try:
            proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=90, check=False)
            result = {'returncode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr}
        except subprocess.TimeoutExpired as exc:
            def text(value: Any) -> str:
                return value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
            result = {'returncode': -1, 'stdout': text(exc.stdout), 'stderr': text(exc.stderr),
                      'error': 'Actual BPF initialization timed out after 90 seconds'}
    return {'schema': 1, 'kind': 'actual-bpf-initialization', 'device_number': devno,
            'probe_attempted': True, 'storage_workload_run': False,
            'passed': result['returncode'] == 0, 'collector': result,
            'compiled_support': verification}


def default_contract() -> Path:
    parent = Path(__file__).resolve().parent
    source = parent.parent / 'compat/runtime-contract.json'
    packaged = parent / 'share/resctl-bench/runtime-contract.json'
    return source if source.is_file() else packaged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--contract', type=Path, default=default_contract())
    parser.add_argument('--probe-latency', metavar='DEVICE', help='Explicit opt-in real BPF startup test; not a storage benchmark')
    args = parser.parse_args()
    try:
        contract = read_contract(args.contract)
        result = (probe_latency(args.runtime_dir / 'bin', contract, args.probe_latency) if args.probe_latency
                  else run_export(args.runtime_dir / 'bin', contract))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get('verified', result.get('passed', False)) else 2
    except (SupportError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'verified': False, 'error': str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
