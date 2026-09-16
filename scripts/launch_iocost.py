#!/usr/bin/python3
# SPDX-License-Identifier: MIT
"""Launch the existing IOCost Lab with the newly built, verified native runtime.

Never falls back to the old archive embedded in IOCost Lab. Preserves the
invocation directory, so output/workload placement follows the Lab's contract.
No benchmark, package installation, or swap change is authorized by this script;
the Lab still shows its maintenance plan and obtains the relevant approvals.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location('_resctl_launch_' + name,
                                                  Path(__file__).resolve().parent / (name + '.py'))
    if spec is None or spec.loader is None:
        raise RuntimeError('Missing bundled ' + name + '.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def runtime_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve(strict=True)
    record = ROOT / '.work/last-package.json'
    if not record.is_file():
        raise RuntimeError('No successfully built package. Run make package verify as your ordinary user first.')
    info = json.loads(record.read_text())
    path = Path(info['stage']).resolve(strict=True)
    if not path.is_relative_to((ROOT / '.work/stage').resolve()):
        raise RuntimeError('Saved stage is not inside this build tree; use --runtime-dir for a relocated package')
    return path


def prepare_arguments(lab: Path, runtime: Path, action: str) -> list[str]:
    if not (lab / 'iocost_report.py').is_file() or not (lab / 'RUN.sh').is_file():
        raise RuntimeError('--lab must identify the existing IOCost Lab directory containing RUN.sh')
    if action not in ('full', 'install', 'preflight'):
        raise RuntimeError('Unknown launch action')
    args = ['/bin/sh', str(lab / 'RUN.sh'), 'preflight' if action == 'preflight' else 'run',
            '--mode', 'full', '--runtime-dir', str(runtime)]
    if action != 'preflight':
        args += ['--install-deps']
    if action == 'install':
        args += ['--install']
    return args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab', type=Path, required=True, help='Existing IOCost Lab 1.5.0 directory (not a scratch path)')
    parser.add_argument('--runtime-dir', type=Path, help='Optional relocated runtime package; default is this build\'s last successful stage')
    parser.add_argument('--action', choices=('full', 'install', 'preflight'))
    parser.add_argument('--plan', action='store_true', help='Verify the package and print the command; do not launch the Lab')
    args = parser.parse_args()
    try:
        runtime = runtime_path(args.runtime_dir)
        installer = load('install')
        installer.verify(runtime)
        support = load('runtime_support')
        contract = support.read_contract(ROOT / 'compat/runtime-contract.json')
        # Require the reviewed contract, not an arbitrary contract supplied by an older package.
        if json.loads((runtime / 'share/resctl-bench/runtime-contract.json').read_text()) != contract:
            raise RuntimeError('Runtime is not this repaired source release')
        support.run_export(runtime / 'bin', contract)
        action = args.action
        if action is None:
            if not sys.stdin.isatty():
                raise RuntimeError('Noninteractive launch requires --action full, install, or preflight')
            print('Use the newly built native runtime:\n  1. Full benchmark and report\n  2. Full benchmark, report and install\n  3. Preflight only\n  0. Exit')
            selected = input('Choose action: ').strip()
            if selected == '0':
                return 0
            action = {'1': 'full', '2': 'install', '3': 'preflight'}.get(selected)
            if action is None:
                raise RuntimeError('Choose one of the displayed actions')
        command = prepare_arguments(args.lab.expanduser().resolve(strict=True), runtime, action)
        print('Rebuilt native runtime: ' + str(runtime), flush=True)
        print('Invocation/output directory: ' + os.getcwd(), flush=True)
        if args.plan:
            print(json.dumps(command, indent=2))
            return 0
        if os.geteuid() != 0:
            raise RuntimeError('Launching the Lab requires sudo; building the runtime does not')
        os.execv(command[0], command)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
