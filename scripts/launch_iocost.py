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
import hashlib
import re
import shutil
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


def prepare_arguments(lab: Path, runtime: Path, action: str, *,
                      runtime_option: str = '--runtime-dir', quiesce_zram_writeback: bool = False) -> list[str]:
    if not (lab / 'iocost_report.py').is_file() or not (lab / 'RUN.sh').is_file():
        raise RuntimeError('--lab must identify the existing IOCost Lab directory containing RUN.sh')
    if action not in ('full', 'install', 'preflight'):
        raise RuntimeError('Unknown launch action')
    if runtime_option not in ('--runtime-dir', '--bin-dir'):
        raise RuntimeError('Unknown Lab runtime-selection interface')
    args = ['/bin/sh', str(lab / 'RUN.sh'), 'preflight' if action == 'preflight' else 'run',
            '--mode', 'full', runtime_option, str(runtime)]
    if action != 'preflight':
        args += ['--install-deps']
    if action == 'install':
        args += ['--install']
    if quiesce_zram_writeback:
        if runtime_option != '--bin-dir':
            raise RuntimeError('Writeback preparation requires IOCost Lab 2.1 or later')
        args += ['--quiesce-zram-writeback']
    return args


def detect_lab_interface(lab: Path) -> str:
    """Query only argparse help; never guess a runtime option or launch a job."""
    if not (lab / 'RUN.sh').is_file() or not (lab / 'iocost_report.py').is_file():
        raise RuntimeError('--lab must identify the IOCost Lab code directory')
    result = subprocess.run(['/bin/sh', str(lab / 'RUN.sh'), 'run', '--help'],
                            capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError('Cannot read IOCost Lab help: ' + result.stderr[-2000:])
    text = result.stdout
    for option in ('--bin-dir', '--runtime-dir'):
        if re.search(r'(?<![\w-])' + re.escape(option) + r'(?![\w-])', text):
            return option
    raise RuntimeError('IOCost Lab does not advertise a supported runtime-selection interface')


def installed_bin_dir(runtime: Path) -> Path:
    """Lab 2.x requires root-owned installed commands, not a user-writable stage.

    Compare installed executable bytes with this verified package so an old
    installation cannot be mistaken for the new build. The Lab performs its
    own additional ownership, permissions and companion-resolution checks.
    """
    entries = [p for p in os.environ.get('PATH', os.defpath).split(os.pathsep) if p and Path(p).is_absolute()]
    entries += [p for p in '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'.split(':') if p not in entries]
    command = shutil.which('resctl-bench', path=os.pathsep.join(entries))
    if not command:
        raise RuntimeError('IOCost Lab 2.x uses installed commands. After building, run '
                           'sudo ./BUILD.sh install; then run the Lab again.')
    directory = Path(command).resolve(strict=True).parent
    def digest(path: Path) -> str:
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
        return h.hexdigest()
    for name in ('resctl-bench', 'rd-agent', 'rd-hashd'):
        candidate = directory / name
        expected = runtime / 'bin' / name
        if (not candidate.is_file() or not os.access(candidate, os.X_OK)
                or digest(candidate) != digest(expected)):
            raise RuntimeError('Installed ' + name + ' does not match the verified new build. '
                               'Install it using sudo ./BUILD.sh install first. '
                               'No old executable or user-writable stage is substituted.')
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab', type=Path, required=True, help='Existing IOCost Lab 1.5.x or 2.x code directory (not a scratch path)')
    parser.add_argument('--runtime-dir', type=Path, help='Optional relocated runtime package; default is this build\'s last successful stage')
    parser.add_argument('--action', choices=('full', 'install', 'preflight'))
    parser.add_argument('--quiesce-zram-writeback', action='store_true', help='Pass an explicit temporary writeback-service plan to IOCost Lab 2.1+')
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
        lab = args.lab.expanduser().resolve(strict=True)
        runtime_option = detect_lab_interface(lab)
        selected = installed_bin_dir(runtime) if runtime_option == '--bin-dir' else runtime
        command = prepare_arguments(lab, selected, action, runtime_option=runtime_option,
                                    quiesce_zram_writeback=args.quiesce_zram_writeback)
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
