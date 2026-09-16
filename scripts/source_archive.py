#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Strict, offline extraction of a hash-pinned, complete source snapshot.

Never uses tar.extractall(), follows archive links, contacts a remote, or writes
outside the supplied empty staging directory. This is not a package signature:
the release checksum/lock files must come from a trusted distribution.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
from typing import Any

MAX_MEMBERS = 20000
MAX_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024


class SourceArchiveError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def checked_path(root: Path, name: str) -> Path:
    if (not isinstance(name, str) or not name or '\\' in name
            or any(ord(c) < 32 for c in name)):
        raise SourceArchiveError('Invalid recovery archive path')
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise SourceArchiveError('Unsafe recovery archive path: ' + repr(name))
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise SourceArchiveError('Recovery path contains a symlink: ' + str(current))
    return current


def validate_cache(root: Path, data: Any) -> Path:
    if (not isinstance(data, dict) or data.get('schema') != 1
            or data.get('format') != 'complete-source-tar-gzip'
            or not isinstance(data.get('sha256'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', data['sha256'])
            or not isinstance(data.get('path'), str)
            or not data['path'].startswith('source-cache/')):
        raise SourceArchiveError('Invalid source-recovery metadata in source.lock.json')
    path = checked_path(root, data['path'])
    if not path.is_file():
        raise SourceArchiveError('Bundled recovery archive is absent: ' + str(path)
                                 + '. No unpatched remote source will be substituted.')
    if sha256(path) != data['sha256']:
        raise SourceArchiveError('Bundled recovery archive checksum mismatch: ' + str(path))
    return path


def unpack(archive: Path, destination: Path) -> Path:
    """Extract one upstream/ tree from an already hash-verified release asset."""
    if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
        raise SourceArchiveError('Source staging directory must be empty and not symlinked')
    try:
        with tarfile.open(archive, mode='r:gz') as stream:
            entries = []
            seen = set()
            kinds = {}
            total = 0
            for member in stream:
                if len(entries) >= MAX_MEMBERS:
                    raise SourceArchiveError('Recovery archive has too many entries')
                # Tar permits a trailing slash on a directory header only.
                name = member.name[:-1] if member.isdir() and member.name.endswith('/') else member.name
                path = checked_path(destination, name)
                if name != 'upstream' and not name.startswith('upstream/'):
                    raise SourceArchiveError('Unexpected archive root: ' + repr(name))
                if name in seen:
                    raise SourceArchiveError('Duplicate archive entry: ' + name)
                if not member.isdir() and not member.isfile():
                    raise SourceArchiveError('Archive links/special files are forbidden: ' + name)
                if member.mode & ~0o777 or (member.isfile() and member.mode not in (0o644, 0o755)):
                    raise SourceArchiveError('Unsafe archive permissions: ' + name)
                if member.size < 0 or member.size > MAX_FILE_BYTES:
                    raise SourceArchiveError('Archive entry exceeds size limit: ' + name)
                total += member.size
                if total > MAX_BYTES:
                    raise SourceArchiveError('Recovery archive exceeds total size limit')
                if member.isdir() and member.size:
                    raise SourceArchiveError('Directory entry contains data: ' + name)
                seen.add(name)
                kinds[name] = member.isdir()
                entries.append((member, name, path))
            if kinds.get('upstream') is not True:
                raise SourceArchiveError('Recovery archive lacks its upstream/ root')
            for _, name, _ in entries:
                for parent in PurePosixPath(name).parents:
                    if str(parent) == '.':
                        continue
                    if kinds.get(str(parent)) is not True:
                        raise SourceArchiveError('Missing or non-directory archive parent: ' + str(parent))
            for member, name, path in sorted(entries, key=lambda row: (row[1].count('/'), row[1])):
                if member.isdir():
                    path.mkdir(mode=0o755)
                    continue
                source = stream.extractfile(member)
                if source is None:
                    raise SourceArchiveError('Unreadable source archive member: ' + name)
                with source, path.open('xb') as target:
                    remaining = member.size
                    while remaining:
                        block = source.read(min(1024 * 1024, remaining))
                        if not block:
                            raise SourceArchiveError('Truncated source archive member: ' + name)
                        target.write(block)
                        remaining -= len(block)
                    target.flush()
                    os.fsync(target.fileno())
                path.chmod(member.mode)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise SourceArchiveError('Cannot extract bundled source snapshot: ' + str(exc)) from exc
    return destination / 'upstream'
