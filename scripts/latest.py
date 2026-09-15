#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve the current published nightly, never silently backtrack to an older one."""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tomllib
import urllib.error
import urllib.request
from typing import Any

MANIFEST_URL = 'https://static.rust-lang.org/dist/channel-rust-nightly.toml'


class LatestError(RuntimeError):
    """A moving release could not be resolved or verified."""


def download_manifest() -> bytes:
    request = urllib.request.Request(MANIFEST_URL, headers={'User-Agent': 'resctl-bench-buildkit/2.1.0'})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.geturl().split('://', 1)[0] != 'https':
                raise LatestError('Refusing a non-HTTPS Rust manifest redirect')
            content = response.read(8 * 1024 * 1024 + 1)
        if len(content) > 8 * 1024 * 1024:
            raise LatestError('Rust manifest exceeded the expected size bound')
        return content
    except (OSError, urllib.error.URLError) as exc:
        raise LatestError(f'Cannot resolve the latest nightly manifest: {exc}') from exc


def parse_manifest(content: bytes, host: str) -> dict[str, Any]:
    try:
        manifest = tomllib.loads(content.decode('utf-8'))
        stamp = manifest['date']
        if not isinstance(stamp, str) or date.fromisoformat(stamp).isoformat() != stamp:
            raise LatestError('Invalid nightly manifest date')
        if date.fromisoformat(stamp) > datetime.now(timezone.utc).date():
            raise LatestError('Nightly manifest is in the future; check the system clock')
        if manifest.get('manifest-version') != '2':
            raise LatestError('Unsupported Rust distribution manifest version')
        for component in ('rust', 'rustc', 'cargo', 'rust-std'):
            if manifest['pkg'][component]['target'][host].get('available') is not True:
                raise LatestError(f'Latest nightly {stamp} lacks {component} for {host}; no older fallback')
        compiler = manifest['pkg']['rustc']
        commit = compiler['git_commit_hash']
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise LatestError('Invalid nightly rustc commit hash')
        return {'schema': 1, 'requested_toolchain': 'nightly', 'resolved_toolchain': 'nightly-' + stamp,
                'manifest_date': stamp, 'rustc_commit': commit, 'rustc_version': compiler['version'],
                'host': host, 'manifest_url': MANIFEST_URL,
                'manifest_sha256': hashlib.sha256(content).hexdigest(),
                'resolved_at_utc': datetime.now(timezone.utc).isoformat()}
    except (KeyError, ValueError, TypeError) as exc:
        raise LatestError(f'Unexpected Rust nightly manifest: {exc}') from exc


def rustc_fields(vv: str) -> dict[str, str]:
    return {key.strip(): value.strip() for key, sep, value in
            (line.partition(':') for line in vv.splitlines()) if sep}


def verify_compiler(selection: dict[str, Any], vv: str) -> None:
    fields = rustc_fields(vv)
    if fields.get('host') != selection['host'] or fields.get('commit-hash') != selection['rustc_commit']:
        raise LatestError('Installed rustc does not match the latest nightly manifest; no stale toolchain accepted')
    if fields.get('release') != selection['rustc_version'].split()[0]:
        raise LatestError('Installed nightly release identifier does not match its manifest')


def selected_toolchain(root: Path, requested: str) -> str:
    path = root / 'toolchain-selection.json'
    if requested != 'nightly' or not path.exists():
        return requested
    if path.is_symlink():
        raise LatestError('Toolchain selection must be a regular file')
    selection = json.loads(path.read_text())
    name = selection.get('resolved_toolchain', '')
    if (selection.get('schema') != 1 or selection.get('requested_toolchain') != requested
            or not re.fullmatch(r'nightly-\d{4}-\d{2}-\d{2}', name)):
        raise LatestError('Invalid toolchain-selection.json')
    return name
