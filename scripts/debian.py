#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Forky-specific APT planning. No repository editing or distribution upgrade."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Callable, Any


class DebianError(RuntimeError):
    """The host or package transaction does not meet the Forky policy."""


def c_locale(runner: Callable[..., str]) -> Callable[..., str]:
    """Keep machine-parsed APT/dpkg output stable under localized user shells."""
    def invoke(argv: list[str], **kwargs: Any) -> str:
        kwargs['env'] = {**(kwargs.get('env') or os.environ), 'LC_ALL': 'C', 'LANG': 'C'}
        return runner(argv, **kwargs)
    return invoke


def host_release(path: Path = Path('/etc/os-release')) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        words = shlex.split(value)
        if len(words) != 1:
            raise DebianError(f'Invalid os-release value: {key}')
        result[key] = words[0]
    return result


def require_forky(*, allow_override: bool = True) -> dict[str, str]:
    release = host_release()
    if release.get('ID') != 'debian' or release.get('VERSION_CODENAME') != 'forky':
        if not (allow_override and os.environ.get('ALLOW_UNSUPPORTED_DEBIAN') == '1'):
            raise DebianError('This edition targets Debian Forky. The host is '
                              f"{release.get('PRETTY_NAME', 'unknown')}. "
                              'No APT sources are changed. ALLOW_UNSUPPORTED_DEBIAN=1 '
                              'permits build experiments, not Forky package installation.')
    return release


def forky_indexes(policy: str) -> set[str]:
    """Associate each APT index with its signed Release origin/codename.

    Accept a sources.list alias of testing only when its Release says n=forky.
    A repository URL merely containing the word 'forky' is not sufficient.
    APT itself is responsible for signature/trust verification.
    """
    result: set[str] = set()
    current = None
    for line in policy.splitlines():
        match = re.match(r'^\s*-?\d+\s+(.+ Packages)\s*$', line)
        if match:
            current = match[1]
        elif line.strip().startswith('release ') and current:
            fields = dict(part.strip().split('=', 1) for part in line.strip()[8:].split(',') if '=' in part)
            if fields.get('o') == 'Debian' and fields.get('n') == 'forky':
                result.add(current)
            current = None
    return result


def madison_versions(text: str, allowed_indexes: set[str]) -> list[str]:
    versions = []
    for line in text.splitlines():
        columns = [item.strip() for item in line.split('|')]
        if len(columns) == 3 and columns[2] in allowed_indexes:
            if not re.fullmatch(r'[0-9A-Za-z.+:~\-]+', columns[1]):
                raise DebianError('Unexpected Debian version syntax')
            versions.append(columns[1])
    return list(dict.fromkeys(versions))


def newer(a: str, b: str) -> bool:
    proc = subprocess.run(['dpkg', '--compare-versions', a, 'gt', b], check=False)
    if proc.returncode not in (0, 1):
        raise DebianError('dpkg could not compare package versions')
    return proc.returncode == 0


def installed_versions(run: Callable[..., str]) -> dict[str, str]:
    run = c_locale(run)
    text = run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'], quiet=True)
    result = {}
    for line in text.splitlines():
        fields = line.split('\t')
        if len(fields) == 3 and fields[2] == 'installed':
            result[fields[0]] = fields[1]
    return result


def package_list(root: Path, group: str) -> list[str]:
    path = root / 'packages' / (group + '.txt')
    packages = [line.split('#', 1)[0].strip() for line in path.read_text().splitlines()]
    packages = list(dict.fromkeys(p for p in packages if p))
    if not packages or any(not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', p) for p in packages):
        raise DebianError('Invalid Debian package list')
    return packages


def dependency_plan(root: Path, group: str, run: Callable[..., str]) -> dict[str, Any]:
    run = c_locale(run)
    require_forky(allow_override=False)
    allowed = forky_indexes(run(['apt-cache', 'policy'], quiet=True))
    if not allowed:
        raise DebianError('No Debian-origin n=forky package indexes. Configure and update '
                          'your Forky repositories yourself; the kit never adds Sid or rewrites APT sources.')
    native_arch = run(['dpkg', '--print-architecture'], quiet=True).strip()
    installed = installed_versions(run)
    plan = []
    queue = package_list(root, group)
    declared = list(queue)
    seen = set()
    # Follow compiler metapackages, without pinning GCC/LLVM major numbers in code.
    # Explicitly requesting compiler implementation packages also upgrades them
    # when an old installed implementation still satisfies its metapackage.
    compiler_name = re.compile(r'^(?:gcc|g\+\+|cpp|clang|llvm|lld|libclang)(?:-[a-z0-9][a-z0-9-]*)?$')
    while queue:
        package = queue.pop(0)
        if package in seen:
            continue
        seen.add(package)
        if len(seen) > 256:
            raise DebianError('Unexpectedly large compiler dependency expansion')
        versions = madison_versions(run(['apt-cache', 'madison', package], quiet=True), allowed)
        if not versions:
            raise DebianError(f'{package} is unavailable in the configured Forky indexes; '
                              'there is no fallback to another Debian release.')
        newest = versions[0]
        for version in versions[1:]:
            if newer(version, newest):
                newest = version
        current = installed.get(package, installed.get(package + ':' + native_arch))
        if current and newer(current, newest):
            raise DebianError(f'{package}: installed {current} is newer than Forky {newest}; '
                              'refusing an implicit downgrade or mixed-release build.')
        plan.append({'package': package, 'version': newest, 'installed_before': current})
        if group in ('build', 'llvm') and compiler_name.fullmatch(package):
            control = run(['apt-cache', 'show', package + '=' + newest], quiet=True)
            unfolded = re.sub(r'\n[ \t]+', ' ', control)
            for field in re.findall(r'^(?:Pre-Depends|Depends): (.+)$', unfolded, re.M):
                for alternative in re.split(r'[,|]', field):
                    name = alternative.strip().split(' ', 1)[0].split(':', 1)[0]
                    if compiler_name.fullmatch(name) and name not in seen:
                        queue.append(name)
    return {'schema': 1, 'codename': 'forky', 'group': group,
            'resolved_at_utc': datetime.now(timezone.utc).isoformat(),
            'freshness': 'as of configured APT indexes, not all Debian or upstream releases',
            'indexes': sorted(allowed), 'declared_packages': declared, 'packages': plan}


def install_dependencies(root: Path, group: str, run: Callable[..., str],
                         write_json: Callable[..., None], *, plan_only: bool = False) -> dict[str, Any]:
    run = c_locale(run)
    require_forky(allow_override=False)
    prefix = [] if os.geteuid() == 0 else ['sudo', '-n']
    if not plan_only and prefix:
        # Authenticate on the terminal before piping APT output to its build log.
        run(['sudo', '-v'], interactive=True)
    if not plan_only:
        run([*prefix, 'apt-get', 'update', '--error-on=any'], log=root / '.work/logs/apt-update.log')
    plan = dependency_plan(root, group, run)
    specs = [row['package'] + '=' + row['version'] for row in plan['packages']]
    flags = ['--no-remove', '--no-install-recommends', '-t', 'forky']
    simulation = run(['apt-get', '--simulate', *flags, 'install', *specs], quiet=True)
    if re.search(r'^Remv\s', simulation, re.M):
        raise DebianError('APT simulation proposes removing packages; review the system manually')
    # Check every proposed upgrade/install, including transitive dependencies.
    # Do not allow an exact pin for a top-level package to conceal a Sid dependency.
    for line in simulation.splitlines():
        match = re.match(r'^Inst\s+(\S+)\s+(?:\[[^]]+\]\s+)?\((\S+)\s', line)
        if match:
            package, version = match.groups()
            allowed_versions = madison_versions(run(['apt-cache', 'madison', package], quiet=True), set(plan['indexes']))
            if version not in allowed_versions:
                raise DebianError(f'APT proposes non-Forky dependency {package}={version}; refusing transaction')
    plan['simulation'] = simulation
    print(json.dumps(plan, indent=2))
    if plan_only:
        return plan
    run([*prefix, 'apt-get', *flags, 'install', '--yes', *specs], log=root / f'.work/logs/apt-{group}-install.log')
    installed = installed_versions(run)
    arch = run(['dpkg', '--print-architecture'], quiet=True).strip()
    for row in plan['packages']:
        actual = installed.get(row['package'], installed.get(row['package'] + ':' + arch))
        if actual != row['version']:
            raise DebianError(f"Package verification failed: {row['package']}: {actual} != {row['version']}")
    plan['installed_after'] = {row['package']: row['version'] for row in plan['packages']}
    write_json(root / f'.work/apt-{group}.json', plan)
    return plan
