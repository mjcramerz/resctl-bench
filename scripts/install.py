#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Standalone, checksum-verified installer. No Rust, services, or benchmarks."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

BINS = {"resctl-bench", "rd-agent", "rd-hashd", "resctl-demo"}
MANIFEST = Path("share/resctl-bench/buildkit-install.json")


class InstallError(RuntimeError):
    """Safe installation could not be completed."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def relative(name: str) -> Path:
    path = Path(name)
    if (not name or path.is_absolute() or ".." in path.parts or name != path.as_posix()
            or name == "." or any(c in name for c in "\n\r\0\\")):
        raise InstallError(f"Unsafe package path: {name!r}")
    return path


def no_symlinks(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink():
            raise InstallError(f"Refusing to follow installation symlink: {item}")


def payload_path(name: str) -> bool:
    path = relative(name)
    if len(path.parts) == 2 and path.parts[0] == "bin" and path.parts[1] in BINS:
        return True
    if (len(path.parts) == 3 and path.parts[:2] == ("bin", ".debug")
            and path.parts[2] in {b + ".debug" for b in BINS}):
        return True
    return any(path.is_relative_to(Path(base)) for base in
               ("share/doc/resctl-bench", "share/licenses/resctl-bench", "share/resctl-bench/build"))


def verify(package: Path) -> dict[str, str]:
    if package.is_symlink() or not package.is_dir():
        raise InstallError("Package root must be a real directory")
    sums = package / "SHA256SUMS"
    if sums.is_symlink() or not sums.is_file():
        raise InstallError("Missing regular SHA256SUMS file")
    records = {}
    for line in sums.read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise InstallError("Malformed SHA256SUMS")
        expected, name = match.groups()
        path = relative(name)
        if name in records or name == "SHA256SUMS":
            raise InstallError(f"Duplicate/self-referential checksum: {name}")
        actual = package / path
        no_symlinks(actual)
        if not actual.is_file() or sha256(actual) != expected:
            raise InstallError(f"Checksum mismatch/missing file: {name}")
        records[name] = expected
    found = set()
    for root, dirs, files in os.walk(package, followlinks=False):
        for item in dirs + files:
            path = Path(root) / item
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise InstallError(f"Non-regular package content: {path}")
            if path.is_file() and path != sums:
                found.add(path.relative_to(package).as_posix())
    if found != set(records):
        raise InstallError("Package contains missing or unlisted files")
    for name in ("resctl-bench", "rd-agent", "rd-hashd"):
        if "bin/" + name not in records:
            raise InstallError(f"Incomplete runtime package: {name}")
    return records


def ensure_directory(path: Path) -> None:
    """Set 0755 on newly created install directories, not existing ancestors.

    mkdir's mode is filtered by umask. Without an explicit chmod a root install
    under umask 077 can leave a new bin/ inaccessible to ordinary users. Do not
    change the caller's global umask or widen an existing private DESTDIR.
    """
    no_symlinks(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    if not current.is_dir():
        raise InstallError(f"Installation parent is not a directory: {current}")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o755)
        except FileExistsError:
            no_symlinks(directory)
            if not directory.is_dir():
                raise InstallError(f"Installation parent is not a directory: {directory}")
            continue  # Another creator owns its choice of directory permissions.
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fchmod(fd, 0o755)
        finally:
            os.close(fd)


def atomic_copy(source: Path, destination: Path, mode: int) -> None:
    no_symlinks(destination)
    ensure_directory(destination.parent)
    fd, name = tempfile.mkstemp(prefix=".resctl-install-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as src:
            shutil.copyfileobj(src, target)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(name, mode)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def load_manifest(prefix: Path) -> dict[str, Any]:
    manifest = prefix / MANIFEST
    no_symlinks(manifest)
    if not manifest.exists():
        return {"schema": 1, "files": {}}
    result = json.loads(manifest.read_text())
    if result.get("schema") != 1 or not isinstance(result.get("files"), dict):
        raise InstallError("Invalid installed manifest")
    for name, info in result["files"].items():
        if not payload_path(name) or not re.fullmatch(r"[0-9a-f]{64}", info["sha256"]):
            raise InstallError(f"Unsafe installed manifest entry: {name!r}")
    return result


def install(package: Path, prefix: Path, force: bool = False) -> int:
    records = verify(package)
    old = load_manifest(prefix)
    payload = {name: value for name, value in records.items() if payload_path(name)}
    # Preflight the complete destination set before writing any payload.
    for name, expected in payload.items():
        target = prefix / name
        no_symlinks(target)
        if target.exists() and (not target.is_file() or (sha256(target) != expected and not force)):
            raise InstallError(f"Will not overwrite {target}; review and use --force for deliberate replacement")
    tracked = dict(old["files"])
    for name, expected in sorted(payload.items()):
        source, target = package / name, prefix / name
        mode = 0o755 if Path(name).parent == Path("bin") else 0o644
        atomic_copy(source, target, mode)
        if sha256(target) != expected:
            raise InstallError(f"Installed file checksum mismatch: {target}")
        tracked[name] = {"sha256": expected, "mode": mode}
    manifest = {"schema": 1, "files": tracked}
    with tempfile.TemporaryDirectory(prefix="resctl-manifest-") as temp:
        src = Path(temp) / "manifest.json"
        src.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
        atomic_copy(src, prefix / MANIFEST, 0o644)
    print(f"Installed {len(payload)} files under {prefix}; no services started")
    return len(payload)


def uninstall(prefix: Path) -> int:
    manifest = load_manifest(prefix)
    if not (prefix / MANIFEST).exists():
        raise InstallError(f"No buildkit installation manifest at {prefix / MANIFEST}")
    targets = []
    # Refuse the entire uninstall if even one tracked file was modified.
    for name, info in manifest["files"].items():
        target = prefix / relative(name)
        no_symlinks(target)
        if target.exists():
            if not target.is_file() or sha256(target) != info["sha256"]:
                raise InstallError(f"Locally modified file retained: {target}. No files removed.")
            targets.append(target)
    parents = set()
    for target in targets + [prefix / MANIFEST]:
        target.unlink()
        p = target.parent
        while p != prefix and p.is_relative_to(prefix):
            parents.add(p)
            p = p.parent
    for p in sorted(parents, key=lambda item: len(item.parts), reverse=True):
        try:
            p.rmdir()  # Only empty directories; never recursive removal.
        except OSError:
            pass
    print(f"Removed {len(targets)} unchanged tracked files; benchmark data was not touched")
    return len(targets)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--prefix", type=Path, default=Path("/usr/local"))
    parser.add_argument("--destdir", type=Path)
    parser.add_argument("--force", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true")
    group.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    if args.verify:
        records = verify(args.package.absolute())
        print(f"Verified {len(records)} package files")
        return 0
    if not args.prefix.is_absolute() or ".." in args.prefix.parts or args.prefix == Path("/"):
        raise InstallError("PREFIX must be an absolute, non-root path without '..'")
    prefix = args.prefix
    if args.destdir is not None:
        if not args.destdir.is_absolute() or ".." in args.destdir.parts:
            raise InstallError("DESTDIR must be absolute and have no '..' components")
        prefix = args.destdir / str(prefix).lstrip("/")
    no_symlinks(prefix)
    lock = prefix / "share/resctl-bench/.buildkit-install.lock"
    no_symlinks(lock)
    ensure_directory(lock.parent)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        if args.uninstall:
            uninstall(prefix)
        else:
            install(args.package.absolute(), prefix, args.force)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (InstallError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
