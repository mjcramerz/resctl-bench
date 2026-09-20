#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Native Debian build/release driver. Python 3.11+, standard library only.

No action executes a benchmark or writes kernel/cgroup/device settings.
External commands are argument arrays, never interpolated shell commands.
"""
from __future__ import annotations

import ast
import contextlib
import dataclasses
import difflib
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.parse import urlsplit
from typing import Any, Iterator, Mapping, Sequence

# Do not rely on sys.path containing scripts/: -P, -I, PYTHONSAFEPATH,
# Python wrappers and third-party packages named "debian" can break that.
# Load only the bundled helpers from this driver's own directory.
def _load_helper(name: str) -> Any:
    path = Path(__file__).resolve().parent / (name + ".py")
    if not path.is_file():
        raise SystemExit(
            f"ERROR: Incomplete build kit: missing {path}. "
            "Re-extract the complete build-kit archive; do not pip-install this module."
        )
    module_name = "_resctl_buildkit_" + name
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"ERROR: Cannot load bundled helper {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


debian = _load_helper("debian")
host_rust = _load_helper("host_rust")
runtime_support = _load_helper("runtime_support")
source_archive = _load_helper("source_archive")

VERSION = "2.4.1"
ROOT = Path(__file__).resolve().parents[1]
GIB = 1024**3
BASE_BINS = ("resctl-bench", "rd-agent", "rd-hashd")
KIT_ITEMS = ("Makefile", "README.md", "LICENSE", "NOTICE.md", ".gitignore",
             ".editorconfig", "config.mk.example", "scripts", "tests", "docs",
             "packages", ".github", "CHANGELOG.md", "compat", "patches", "RUN-IOCOST-LAB.sh", "BUILD.sh")
HELP = """resctl-bench-buildkit 2.4.1 (Debian Forky, native amd64/arm64 GNU/Linux)

  make                  Same as make package (host Rust; locked source)
  make package          Build locked sources with host Rust; no APT or toolchain changes
  make latest           Blocked for this reviewed patch; rebase source explicitly
  make latest-complete  Blocked for this reviewed patch; use package + source-dist
  make deps             Install newest declared build packages from Forky (sudo for APT)
  make deps-plan        Simulate the Forky dependency transaction using current indexes
  make deps-runtime     Explicitly install runtime packages (may start distro services)
  make deps-llvm        Optional newest Forky LLVM/bindgen development packages
  make update-toolchain DISABLED: this kit never installs or updates Rust
  make update-rustup    DISABLED: this kit never installs or updates rustup
  make update-deps      Resolve newest compatible crates into a separate, audited lock
  make versions         Show source/toolchain/dependency locks and local package versions
  make native-validate  Verify source, check, compile tests, package and verify with REAL host Rust
  make doctor           Validate installed compiler, host, tools and flags
  make fetch            Verify/restore complete bundled source; no network for this release
  make verify-source    Read-only verification of patched source and recovery archive
  make restore-source   Restore absent/incomplete source offline; never overwrite edits
  make update-source    Blocked while a reviewed native source patch is selected
  make lock-toolchain   Record current host compiler identity (project-local metadata)
  make fetch-deps       Download dependencies without changing Cargo.lock
  make build            Build resctl-bench, rd-agent, rd-hashd, resctl-demo
  make check            Cargo check selected packages with --locked
  make test-compile     Compile upstream tests; DO NOT execute them
  make test-runtime     Compile/run ONLY file-support and device-JSON Rust regressions
  make smoke            Build; run only each binary's --version and --help
  make stage            Build, test embedded support, stage, split debug, verify
  make rebuild          Package the already selected source/toolchain/dependencies
  make all              Same as package
  make verify           Verify hashes of the most recently packaged release
  make vendor           Vendor the entire locked Cargo dependency graph
  make source-dist      Bundle this kit + locked upstream + vendored crates
  make snapshot-dist    Bundle complete selected source; no Rust/network required
  make kit-dist         For this patched release: same complete source as snapshot-dist
  make test             Run build-kit unit/integration tests (no Rust required)
  make lint             Check Python syntax and whitespace
  make runtime-check    Read-only host checks; optional SCRATCH=/mount/path
  make install          Install the last package; does NOT build (sudo as needed)
  make uninstall        Remove only unchanged, manifest-tracked installed files
  make clean            Remove .work/ only; retain sources, locks, vendor, dist
  make clean-vendor     Remove the kit-generated vendor tree only

Configuration: config.mk.example or make VAR=value.
  TOOLCHAIN=host TUNE=native|portable LTO=thin|fat|off JOBS=auto|N
  HOST_RUSTC= HOST_CARGO= HOST_RUSTDOC= (optional installed executable paths)
  WITH_DEMO=1 SPLIT_DEBUG=1 OFFLINE=0 HOST_CC=/usr/bin/gcc HOST_CXX=/usr/bin/g++
  OFFLINE=1 requires cached/vendored crates; never installs missing Rust
  CARGO_HOME is honored; existing Cargo configurations are read, never rewritten
  Ambient build overrides are scoped away in child processes, never rejected
  CARGO_TARGET_DIR/build-dir overrides do not redirect project output from .work/
  PREFIX=/usr/local DESTDIR= FORCE=0
  UPSTREAM_URL=https://github.com/facebookexperimental/resctl-demo.git
  UPSTREAM_REF=main (ignored for the already locked bundled source)

Build as your ordinary user. Never use make as a benchmark launcher.
"""


class BuildError(RuntimeError):
    """An actionable user-facing failure."""


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, canonical(value))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise BuildError(f"Cannot read {path}: {exc}") from exc


def safe_relative(name: str) -> Path:
    p = Path(name)
    if not name or p.is_absolute() or ".." in p.parts or name in (".", ".."):
        raise BuildError(f"Unsafe relative path: {name!r}")
    if any(ch in name for ch in "\n\r\0\\"):
        raise BuildError(f"Unsupported path: {name!r}")
    return p


def file_manifest(root: Path, exclude_git: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        if exclude_git:
            dirs[:] = [d for d in dirs if d != ".git"]
        for name in sorted(dirs + files):
            p = Path(current) / name
            rel = p.relative_to(root).as_posix()
            safe_relative(rel)
            if p.is_symlink():
                target = os.readlink(p)
                resolved = p.resolve()
                if not resolved.is_relative_to(root.resolve()):
                    raise BuildError(f"Symlink escapes its tree: {p}")
                result[rel] = {"symlink": target}
            elif p.is_file():
                mode = 0o755 if p.stat().st_mode & 0o111 else 0o644
                result[rel] = {"sha256": digest(p), "mode": mode}
            elif not p.is_dir():
                raise BuildError(f"Special file not permitted: {p}")
    return result


def make_archive(tree: Path, destination: Path, epoch: int) -> None:
    """Deterministic archive envelope; source tree must already be curated."""
    if epoch < 0 or epoch > 0xFFFFFFFF:
        raise BuildError("SOURCE_DATE_EPOCH must fit an unsigned 32-bit timestamp")
    file_manifest(tree)  # Reject devices and escaping symlinks before archiving.
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".archive-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as gz:
                with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
                    paths = [tree] + sorted(tree.rglob("*"), key=lambda p: p.as_posix())
                    for path in paths:
                        info = tar.gettarinfo(str(path), arcname=path.relative_to(tree.parent).as_posix())
                        info.uid = info.gid = 0
                        info.uname = info.gname = "root"
                        info.mtime = epoch
                        info.pax_headers = {}
                        info.mode = 0o755 if info.isdir() or (info.mode & 0o111) else 0o644
                        if info.isfile():
                            with path.open("rb") as stream:
                                tar.addfile(info, stream)
                        else:
                            tar.addfile(info)
        os.chmod(name, 0o644)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)
    atomic_write(destination.with_name(destination.name + ".sha256"),
                 f"{digest(destination)}  {destination.name}\n".encode())


def checksums(tree: Path) -> None:
    records = file_manifest(tree)
    lines = []
    for name, record in sorted(records.items()):
        if name == "SHA256SUMS":
            continue
        if "symlink" in record:
            raise BuildError("Release packages must contain regular files, not symlinks")
        lines.append(f"{record['sha256']}  {name}\n")
    atomic_write(tree / "SHA256SUMS", "".join(lines).encode())


def run(argv: Sequence[str | Path], *, cwd: Path | None = None,
        env: Mapping[str, str] | None = None, timeout: int | None = None,
        log: Path | None = None, quiet: bool = False, interactive: bool = False) -> str:
    args = [str(a) for a in argv]
    if not quiet:
        print("+ " + shlex.join(args), file=sys.stderr, flush=True)
    try:
        if interactive:
            if log is not None:
                raise BuildError("Interactive commands cannot capture a log")
            # Inherit the terminal so sudo's no-newline password prompt is visible.
            proc = subprocess.run(args, cwd=cwd, env=env, timeout=timeout, check=False)
            if proc.returncode:
                raise BuildError(f"Command failed ({proc.returncode}): {shlex.join(args)}")
            return ""
        if log is None:
            proc = subprocess.run(args, cwd=cwd, env=env, text=True,
                                  capture_output=True, timeout=timeout, check=False)
            if proc.returncode:
                raise BuildError(f"Command failed ({proc.returncode}): {shlex.join(args)}\n"
                                 f"{proc.stdout[-8000:]}{proc.stderr[-8000:]}")
            return proc.stdout
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as stream:
            stream.write("$ " + shlex.join(args) + "\n")
            with subprocess.Popen(args, cwd=cwd, env=env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
                assert proc.stdout is not None
                for line in proc.stdout:
                    stream.write(line)
                    stream.flush()
                    print(line, end="", file=sys.stderr, flush=True)
                code = proc.wait()
        if code:
            raise BuildError(f"Command failed ({code}); see {log}")
        return ""
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BuildError(f"Cannot execute {args[0]}: {exc}") from exc


def boolean(env: Mapping[str, str], key: str, default: str) -> bool:
    value = env.get(key, default)
    if value not in ("0", "1"):
        raise BuildError(f"{key} must be 0 or 1, not {value!r}")
    return value == "1"


def auto_jobs() -> int:
    cpus = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    memory = 2 * GIB
    try:
        data = Path("/proc/meminfo").read_text()
        match = re.search(r"^MemAvailable:\s+(\d+)", data, re.M)
        if match:
            memory = int(match[1]) * 1024
        # Check this cgroup and visible ancestors, including namespaced roots.
        candidates = {Path("/sys/fs/cgroup")}
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if line.startswith("0::") and ".." not in Path(line[3:]).parts:
                p = Path("/sys/fs/cgroup") / line[3:].lstrip("/")
                while p.is_relative_to(Path("/sys/fs/cgroup")):
                    candidates.add(p)
                    p = p.parent
        for p in candidates:
            try:
                limit = (p / "memory.max").read_text().strip()
                current = int((p / "memory.current").read_text())
                if limit != "max":
                    memory = min(memory, max(0, int(limit) - current))
                quota, period = (p / "cpu.max").read_text().split()
                if quota != "max":
                    cpus = min(cpus, max(1, int(quota) // int(period)))
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return max(1, min(cpus, max(1, memory // (2 * GIB))))


@dataclasses.dataclass(frozen=True)
class Config:
    url: str
    ref: str
    toolchain: str
    tune: str
    lto: str
    jobs: int
    demo: bool
    split_debug: bool
    offline: bool
    cc: str
    cxx: str
    extra_rust: tuple[str, ...]
    extra_c: tuple[str, ...]
    extra_cxx: tuple[str, ...]
    host_rustc: str
    host_cargo: str
    host_rustdoc: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        e = os.environ if env is None else env
        tune, lto = e.get("TUNE", "native"), e.get("LTO", "thin")
        if tune not in ("native", "portable") or lto not in ("thin", "fat", "off"):
            raise BuildError("Use TUNE=native|portable and LTO=thin|fat|off")
        ref = e.get("UPSTREAM_REF", "main")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref) or ".." in ref:
            raise BuildError("UPSTREAM_REF must be a plain branch, tag, or full Git SHA")
        url = e.get("UPSTREAM_URL", "https://github.com/facebookexperimental/resctl-demo.git")
        if not (url.startswith("https://") or Path(url).is_absolute()) or any(c in url for c in "\n\r\0"):
            raise BuildError("UPSTREAM_URL must be HTTPS or an explicit absolute local Git repository")
        if url.startswith("https://"):
            parsed = urlsplit(url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise BuildError("Keep credentials/query tokens out of UPSTREAM_URL; use Git credential helpers")
        jobs_s = e.get("JOBS", "auto")
        try:
            jobs = auto_jobs() if jobs_s == "auto" else int(jobs_s)
        except ValueError as exc:
            raise BuildError("JOBS must be auto or a positive integer") from exc
        if not 1 <= jobs <= 4096:
            raise BuildError("JOBS must be between 1 and 4096")
        selection = e.get("TOOLCHAIN", "host")
        try:
            host_rust.validate_selection(selection)
        except host_rust.HostRustError as exc:
            raise BuildError(str(exc)) from exc
        return cls(url, ref, selection, tune, lto, jobs,
                   boolean(e, "WITH_DEMO", "1"), boolean(e, "SPLIT_DEBUG", "1"),
                   boolean(e, "OFFLINE", "0"), e.get("HOST_CC", "/usr/bin/gcc"), e.get("HOST_CXX", "/usr/bin/g++"),
                   tuple(shlex.split(e.get("EXTRA_RUSTFLAGS", ""))),
                   tuple(shlex.split(e.get("EXTRA_CFLAGS", ""))),
                   tuple(shlex.split(e.get("EXTRA_CXXFLAGS", ""))),
                   e.get("HOST_RUSTC") or e.get("RUSTC", ""),
                   e.get("HOST_CARGO") or e.get("CARGO", ""),
                   e.get("HOST_RUSTDOC") or e.get("RUSTDOC", ""))

    @property
    def binaries(self) -> tuple[str, ...]:
        return BASE_BINS + (("resctl-demo",) if self.demo else ())


def compilation_flags(cfg: Config, host: str, root: Path, cargo_home: Path) -> tuple[list[str], list[str], list[str]]:
    if host not in ("x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"):
        raise BuildError(f"Supported native hosts are Debian amd64/arm64 GNU targets, not {host}")
    rust = ["-Cforce-frame-pointers=yes", "-Crelro-level=full",
            "-Clink-arg=-Wl,--build-id=sha1",
            f"--remap-path-prefix={root}=/usr/src/resctl-bench-buildkit",
            f"--remap-path-prefix={cargo_home}=/usr/src/cargo"]
    cflags = ["-O3", "-g1", "-fno-omit-frame-pointer",
              "-fstack-protector-strong", "-D_FORTIFY_SOURCE=3",
              f"-ffile-prefix-map={root}=/usr/src/resctl-bench-buildkit",
              f"-ffile-prefix-map={cargo_home}=/usr/src/cargo"]
    if cfg.tune == "native":
        rust.append("-Ctarget-cpu=native")
        cflags += (["-march=native", "-mtune=native"] if host.startswith("x86_64-") else ["-mcpu=native"])
    return rust + list(cfg.extra_rust), cflags + list(cfg.extra_c), cflags + list(cfg.extra_cxx)


# These inputs conflict with the kit's native-target/profile/flags/output contract.
# They are NOT invalid host settings: ignore them in a COPY of the environment,
# rather than asking users to unset them or edit their global configuration.
# Keep Cargo home, registries, credentials, mirrors, proxies and Rust selectors.
CONTROLLED_BUILD_VARIABLES = frozenset({
    "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS",
    "RUSTDOCFLAGS", "CARGO_ENCODED_RUSTDOCFLAGS", "CARGO_BUILD_RUSTDOCFLAGS",
    "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS",
    "RUSTC_BOOTSTRAP", "RUSTC_LINKER", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
    "CARGO_BUILD_RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER",
    "CARGO_BUILD_TARGET", "CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR",
    "CARGO_BUILD_BUILD_DIR", "CARGO_INCREMENTAL", "CARGO_BUILD_INCREMENTAL",
    "TARGET_CFLAGS", "HOST_CFLAGS", "TARGET_CXXFLAGS", "HOST_CXXFLAGS",
    "TARGET_AR", "HOST_AR", "AR", "ARFLAGS", "CRATE_CC_NO_DEFAULTS",
})


def controlled_build_variable(key: str) -> bool:
    """Return whether a host environment setting is replaced for this build."""
    return (key in CONTROLLED_BUILD_VARIABLES
            or key.startswith(("CARGO_PROFILE_", "CARGO_TARGET_"))
            or bool(re.match(r"^(CFLAGS|CXXFLAGS|CPPFLAGS|CC|CXX|AR|ARFLAGS)_", key)))


def cargo_output_environment(env: dict[str, str], target: Path) -> None:
    """Keep Cargo's final AND intermediate outputs inside the selected local tree.

    Cargo supports both target-dir names. Newer Cargo also has a separate
    build-dir setting; overriding it prevents global config from redirecting
    intermediates to a shared cache. Older Cargo ignores the unused setting.
    Only the supplied child-process dictionary is changed.
    """
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_TARGET_DIR=str(target),
               CARGO_BUILD_BUILD_DIR=str(target))


class Builder:
    def __init__(self, root: Path, cfg: Config):
        self.root, self.cfg = root.resolve(), cfg
        self.src = self.root / "upstream"
        self.work = self.root / ".work"
        self.dist = self.root / "dist"
        self.vendor_dir = self.root / "vendor"
        self.dependency_dir = self.root / "dependency-lock"
        if self.work.is_symlink():
            raise BuildError("Refuse a symlinked .work directory; generated state must stay inside the project")
        home = Path(os.environ.get("CARGO_HOME") or str(Path.home() / ".cargo")).expanduser()
        self.cargo_home = (home if home.is_absolute() else self.root / home).resolve()
        self._tools: dict[str, str] | None = None
        self._environment_notice_shown = False

    def effective_toolchain(self) -> str:
        # Legacy toolchain-selection.json is deliberately never consulted.
        return self.cfg.toolchain

    def environment(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items()
               if not controlled_build_variable(key)}
        for key in list(env):
            if key.startswith("VERGEN_") or key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
                env.pop(key, None)
        env.update(LC_ALL="C", LANG="C", TZ="UTC", CARGO_TERM_COLOR="never",
                   RUSTUP_AUTO_INSTALL="0",
                   GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", CARGO_HOME=str(self.cargo_home))
        # Empty wrappers explicitly override Cargo config wrappers without
        # editing those files. Select concrete host Rust executables below.
        env.update(RUSTC_WRAPPER="", RUSTC_WORKSPACE_WRAPPER="")
        cargo_output_environment(env, self.work / "cargo")
        if self.cfg.toolchain != "host":
            env["RUSTUP_TOOLCHAIN"] = self.cfg.toolchain
        if self._tools is not None:
            # Subprocesses and build scripts get the same concrete host tools.
            env.update(RUSTC=self._tools["rustc"], RUSTDOC=self._tools["rustdoc"], CARGO=self._tools["cargo"],
                       CARGO_BUILD_TARGET=self._tools["host"])
            bins = list(dict.fromkeys(str(Path(self._tools[name]).parent) for name in ("cargo", "rustc", "rustdoc")))
            env["PATH"] = os.pathsep.join([*bins, env.get("PATH", os.defpath)])
        return env

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false",
                    "-c", "diff.autoRefreshIndex=false", *args],
                   cwd=cwd or self.src, env=self.environment(), timeout=300, quiet=True).strip()

    def verify_source(self, source: Path | None = None) -> dict[str, Any]:
        src = self.src if source is None else source
        lock = read_json(self.root / "source.lock.json")
        if not re.fullmatch(r"[0-9a-f]{40}", lock["commit"]):
            raise BuildError("Invalid locked Git commit")
        manifest_path = self.root / "source-manifest.json"
        if digest(manifest_path) != lock["source_manifest_sha256"]:
            raise BuildError("Source manifest was changed; refuse to build")
        if not src.is_dir() or src.is_symlink():
            raise BuildError("Missing/unsafe upstream source directory")
        if file_manifest(src, exclude_git=True) != read_json(manifest_path):
            raise BuildError("Upstream files differ from the source lock; preserve your edits and review them first")
        if not (src / ".git").is_dir() or (src / ".git").is_symlink():
            raise BuildError("Missing/unsafe upstream Git identity; run make restore-source")
        if Path(self.git("rev-parse", "--show-toplevel", cwd=src)).resolve() != src.resolve():
            raise BuildError("Source Git identity points outside the source directory")
        if self.git("rev-parse", "HEAD", cwd=src) != lock["commit"]:
            raise BuildError("Upstream HEAD does not match the locked commit")
        changes = self.git("status", "--porcelain", "--untracked-files=all", cwd=src)
        patchset = lock.get("patchset")
        if patchset:
            patch_file = self.root / safe_relative(patchset["path"])
            if digest(patch_file) != patchset["sha256"]:
                raise BuildError("Reviewed source patch was changed")
            # HEAD stays at the real uploaded base commit. The native -dirty
            # version suffix truthfully identifies this reviewed local delta.
            delta = self.git("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--", ".", cwd=src)
            if delta != patch_file.read_text().strip():
                raise BuildError("Source changes differ from the reviewed native-runtime patch")
            base_manifest = self.root / safe_relative(patchset["base_manifest"])
            if digest(base_manifest) != patchset["base_manifest_sha256"]:
                raise BuildError("Original-source preservation manifest was changed")
            contract = self.root / safe_relative(patchset["runtime_contract"])
            if digest(contract) != patchset["runtime_contract_sha256"]:
                raise BuildError("Runtime compatibility contract was changed")
            runtime_support.validate_source(src, contract)
        elif changes:
            raise BuildError("Upstream Git worktree is dirty")
        if digest(src / "Cargo.lock") != lock["cargo_lock_sha256"]:
            raise BuildError("Cargo.lock has changed")
        return lock

    def restore_source(self) -> dict[str, Any]:
        """Reconstruct only absent/unmodified source from the pinned local snapshot.

        The old incomplete tree is retained outside .work/ (make clean must not
        destroy it). Candidate validation happens before any working-tree rename.
        A conflicting file is never silently discarded, even on explicit restore.
        """
        lock = read_json(self.root / "source.lock.json")
        manifest_path = self.root / "source-manifest.json"
        if digest(manifest_path) != lock["source_manifest_sha256"]:
            raise BuildError("Source manifest was changed; recovery is not authorized")
        expected = read_json(manifest_path)
        if self.src.is_symlink() or (self.src.exists() and not self.src.is_dir()):
            raise BuildError("Cannot restore an unsafe upstream path; no existing path was changed")
        if self.src.exists():
            gitdir = self.src / ".git"
            if gitdir.is_symlink() or (gitdir.exists() and not gitdir.is_dir()):
                raise BuildError("Cannot restore a symlinked/external .git; no files were changed")
            current = file_manifest(self.src, exclude_git=True)
            conflicts = sorted(name for name, value in current.items() if expected.get(name) != value)
            if conflicts:
                raise BuildError("Source recovery would overwrite local changes or untracked files: "
                                 + ", ".join(conflicts[:8]) + ". Preserve/review these files first; "
                                 "nothing was overwritten.")
        else:
            current = {}
        if current == expected:
            try:
                return self.verify_source()
            except (BuildError, OSError):
                # Exact working files with missing/corrupt local Git metadata
                # are recoverable, without resetting or deleting user edits.
                pass
        archive = source_archive.validate_cache(self.root, lock.get("recovery"))
        print("Restoring reviewed source OFFLINE from " + str(archive), file=sys.stderr)
        self.work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="source-restore-", dir=self.work) as temp:
            prepared = source_archive.unpack(archive, Path(temp))
            self.verify_source(source=prepared)
            backup = None
            if self.src.exists():
                backups = self.root / "source-recovery-backups"
                if backups.is_symlink():
                    raise BuildError("Refuse a symlinked source-recovery-backups directory")
                backups.mkdir(exist_ok=True)
                backup = Path(tempfile.mkdtemp(prefix="recovered-", dir=backups)) / "upstream"
                self.src.rename(backup)
            try:
                prepared.rename(self.src)
            except BaseException:
                if backup is not None and not self.src.exists():
                    backup.rename(self.src)
                raise
            result = self.verify_source()
            write_json(self.work / "source-recovery.json", {
                "schema": 1, "network_used": False, "source_commit": lock["commit"],
                "source_manifest_sha256": lock["source_manifest_sha256"],
                "recovery_sha256": lock["recovery"]["sha256"],
                "retained_previous_tree": str(backup) if backup else None,
                "restored_files": len(expected), "verified": True})
            print("Verified complete patched source: " + str(self.src), file=sys.stderr)
            if backup is not None:
                print("Previous incomplete tree retained: " + str(backup), file=sys.stderr)
            return result

    def create_recovery_archive(self) -> None:
        """Maintainer operation: seed a recovery asset from already verified source."""
        lock = self.verify_source()
        if lock.get("recovery"):
            source_archive.validate_cache(self.root, lock["recovery"])
            return
        target = self.root / "source-cache" / "upstream.tar.gz"
        if target.parent.is_symlink() or target.exists() or target.is_symlink():
            raise BuildError("Refuse to overwrite an unregistered source recovery archive")
        target.parent.mkdir(exist_ok=True)
        self.work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="seed-source-", dir=self.work) as temp:
            tree = Path(temp) / "upstream"
            self.copy_source(tree)
            make_archive(tree, target, lock["commit_epoch"])
        lock["recovery"] = {"schema": 1, "format": "complete-source-tar-gzip",
                            "path": "source-cache/upstream.tar.gz", "sha256": digest(target)}
        write_json(self.root / "source.lock.json", lock)

    def copy_recovery_archive(self, destination: Path) -> None:
        lock = read_json(self.root / "source.lock.json")
        if lock.get("recovery"):
            archive = source_archive.validate_cache(self.root, lock["recovery"])
            target = destination / safe_relative(lock["recovery"]["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(archive, target)

    def fetch(self, update: bool = False) -> dict[str, Any]:
        locked = (self.root / "source.lock.json").exists()
        if locked and read_json(self.root / "source.lock.json").get("patchset"):
            if update:
                raise BuildError("This source release carries a reviewed native compatibility patch. "
                                 "update-source/latest is blocked so it cannot silently remove the fix. "
                                 "Rebase and revalidate the patch explicitly; see docs/NATIVE-REPAIR.md.")
            if read_json(self.root / "source.lock.json").get("recovery"):
                self.restore_source()
            elif not self.src.is_dir():
                raise BuildError("This older source lock has no offline recovery asset. "
                                 "Use the complete 2.3.2+ source repository; "
                                 "an unpatched remote checkout is never a fallback.")
        if locked and self.src.exists():
            current = self.verify_source()
            if not update:
                if current["url"] != self.cfg.url:
                    raise BuildError("UPSTREAM_URL differs from the source lock; use update-source explicitly")
                return current
        elif self.src.exists():
            raise BuildError("Refusing to take over an upstream/ directory without a source lock")
        if self.cfg.offline:
            raise BuildError("OFFLINE=1 requires an existing locked source tree; run make fetch online first")
        self.work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="fetch-", dir=self.work) as temp:
            new = Path(temp) / "upstream"
            new.mkdir()
            self.git("init", "--quiet", cwd=new)
            self.git("remote", "add", "origin", self.cfg.url, cwd=new)
            # Restoring a missing worktree uses the locked SHA, not a moving ref.
            ref = read_json(self.root / "source.lock.json")["commit"] if locked and not update else self.cfg.ref
            print(f"Fetching {self.cfg.url} at {ref}", file=sys.stderr)
            self.git("fetch", "--no-tags", "--depth=1", "origin", ref, cwd=new)
            self.git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=new)
            if (new / ".gitmodules").exists():
                raise BuildError("This driver requires a repository without submodules; upstream layout changed")
            for name in ("Cargo.lock", "Cargo.toml", "LICENSE", *[f"{b}/Cargo.toml" for b in BASE_BINS]):
                if not (new / name).is_file():
                    raise BuildError(f"Required upstream file missing: {name}")
            commit = self.git("rev-parse", "HEAD", cwd=new)
            epoch = int(self.git("show", "-s", "--format=%ct", "HEAD", cwd=new))
            manifest = file_manifest(new, exclude_git=True)
            source_lock = {"schema": 1, "url": self.cfg.url, "requested_ref": ref,
                           "commit": commit, "commit_epoch": epoch,
                           "cargo_lock_sha256": digest(new / "Cargo.lock"),
                           "source_manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest()}
            if locked and not update:
                old = read_json(self.root / "source.lock.json")
                for key in ("commit", "source_manifest_sha256", "cargo_lock_sha256"):
                    if source_lock[key] != old[key]:
                        raise BuildError(f"Restored source disagrees with lock: {key}")
                source_lock = old
            if update and self.src.exists():
                if self.vendor_dir.exists():
                    self.verify_vendor()
                if self.dependency_dir.exists():
                    self.verify_dependency_lock()
                self.retire(self.vendor_dir)
                self.retire(self.dependency_dir)
            backup = Path(temp) / "old"
            if self.src.exists():
                self.src.rename(backup)
            new.rename(self.src)
            write_json(self.root / "source-manifest.json", manifest)
            write_json(self.root / "source.lock.json", source_lock)
        print(f"Locked upstream commit: {commit}", file=sys.stderr)
        return self.verify_source()

    def tools(self, refresh: bool = False) -> dict[str, str]:
        if self._tools is not None and not refresh:
            return self._tools
        debian.require_forky()
        required = ("git", "pkg-config", "readelf", "objcopy", "strip", self.cfg.cc, self.cfg.cxx)
        tool_env = self.environment()
        missing = [name for name in required if not shutil.which(name, path=tool_env.get("PATH"))]
        if missing:
            raise BuildError("Missing tools: " + ", ".join(missing) + ". Install prerequisites explicitly; make deps changes APT packages only when requested.")
        self.report_environment_overrides()
        env = self.environment()
        paths = host_rust.discover(self.cfg.toolchain,
                                   {"rustc": self.cfg.host_rustc, "cargo": self.cfg.host_cargo,
                                    "rustdoc": self.cfg.host_rustdoc},
                                   env, self.root, run)
        vv = run([paths["rustc"], "-vV"], env=env, timeout=30, quiet=True)
        cargo_v = run([paths["cargo"], "--version"], env=env, timeout=30, quiet=True).strip()
        match = re.search(r"^host: (.+)$", vv, re.M)
        if not match:
            raise BuildError("rustc -vV did not report a host triple")
        host = match[1]
        compilation_flags(self.cfg, host, self.root, self.cargo_home)
        locked = {"schema": 2, "policy": "host-installed-only",
                  "requested_toolchain": self.cfg.toolchain, "resolved_toolchain": self.effective_toolchain(),
                  "rustc_vv": vv, "cargo_version": cargo_v, "executables": paths.copy()}
        path = self.root / "toolchain.lock.json"
        # Provenance, not a request to restore/install a former compiler. A host
        # upgrade changes the build identity naturally; no global setting moves.
        if not path.exists() or read_json(path) != locked or refresh:
            write_json(path, locked)
        paths.update(host=host, rustc_vv=vv, cargo_version=cargo_v)
        self._tools = paths
        return paths

    def environment_overrides(self) -> list[str]:
        # Names only: avoid recording private paths/values/tokens in logs.
        return sorted(key for key, value in os.environ.items()
                      if value and controlled_build_variable(key))

    def report_environment_overrides(self) -> None:
        if self._environment_notice_shown:
            return
        names = self.environment_overrides()
        if names:
            print("NOTE: Using project-local build settings instead of inherited "
                  + ", ".join(names)
                  + ". Host environment/config files are unchanged; outputs stay in .work/. "
                  "Use EXTRA_*FLAGS/TUNE/LTO/JOBS for explicit kit overrides.", file=sys.stderr)
        self._environment_notice_shown = True

    def cargo_configuration_fingerprints(self, source: Path) -> dict[str, str]:
        """Record direct Cargo config inputs, without copying content or credentials.

        Cargo may read additional include files or environment settings; this is
        provenance, not a claim of a hermetic build. Existing user configuration
        is trusted input and is never deleted, replaced or rewritten by the kit.
        """
        candidates = {self.cargo_home / "config", self.cargo_home / "config.toml"}
        for parent in (source, *source.parents):
            candidates.update((parent / ".cargo/config", parent / ".cargo/config.toml"))
        return {str(p): digest(p) for p in sorted(candidates) if p.is_file()}

    def copy_source(self, destination: Path, *, stable_metadata: bool = False) -> None:
        """Copy actual source and a minimal Git identity; never fabricate a commit.

        A release snapshot uses the recovery asset's exact Git metadata too.
        Copying a refreshed mutable index from the build worktree would make
        SHA256SUMS differ after an otherwise correct offline recovery.
        """
        lock = self.verify_source()
        if stable_metadata and lock.get("recovery"):
            archive = source_archive.validate_cache(self.root, lock["recovery"])
            with tempfile.TemporaryDirectory(prefix="source-copy-", dir=destination.parent) as temp:
                prepared = source_archive.unpack(archive, Path(temp))
                self.verify_source(source=prepared)
                prepared.rename(destination)
            return
        shutil.copytree(self.src, destination, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        gitdir = destination / ".git"
        gitdir.mkdir()
        for filename in ("HEAD", "shallow", "packed-refs", "index", "objects", "refs"):
            p = self.src / ".git" / filename
            if p.is_dir():
                shutil.copytree(p, gitdir / filename)
            elif p.is_file():
                shutil.copyfile(p, gitdir / filename)
        for key, value in (("core.repositoryformatversion", "0"), ("core.filemode", "true"), ("core.bare", "false")):
            self.git("config", key, value, cwd=destination)

    def verify_dependency_lock(self) -> dict[str, Any]:
        info = read_json(self.dependency_dir / "manifest.json")
        lock = self.verify_source()
        if (info.get("schema") != 1 or info["source_commit"] != lock["commit"]
                or info["upstream_lock_sha256"] != lock["cargo_lock_sha256"]):
            raise BuildError("Updated dependency lock belongs to another upstream snapshot")
        if digest(self.dependency_dir / "Cargo.lock") != info["effective_lock_sha256"]:
            raise BuildError("Updated Cargo.lock was modified")
        for name, expected in info["evidence_sha256"].items():
            if digest(self.dependency_dir / safe_relative(name)) != expected:
                raise BuildError("Dependency-update evidence was modified")
        return info

    def effective_source(self) -> Path:
        """Keep pristine upstream intact; apply only the recorded dependency lock in a copy."""
        lock = self.verify_source()
        if not self.dependency_dir.exists():
            return self.src
        info = self.verify_dependency_lock()
        tree = self.work / "sources" / (lock["commit"][:12] + "-" + info["effective_lock_sha256"][:16])
        if not tree.exists():
            tree.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="source-", dir=tree.parent) as temp:
                candidate = Path(temp) / "upstream"
                self.copy_source(candidate)
                shutil.copyfile(self.dependency_dir / "Cargo.lock", candidate / "Cargo.lock")
                candidate.rename(tree)
        expected = read_json(self.root / "source-manifest.json")
        expected["Cargo.lock"] = {"sha256": info["effective_lock_sha256"], "mode": 0o644}
        if file_manifest(tree, exclude_git=True) != expected:
            raise BuildError("Effective build source was modified; inspect it before make clean")
        if self.git("rev-parse", "HEAD", cwd=tree) != lock["commit"]:
            raise BuildError("Effective build source has a different Git identity")
        return tree

    def retire(self, path: Path) -> None:
        if path.exists():
            if path.is_symlink() or path.parent != self.root:
                raise BuildError("Refusing to retire an unsafe generated tree")
            parent = self.work / "retired"
            parent.mkdir(parents=True, exist_ok=True)
            destination = Path(tempfile.mkdtemp(prefix=path.name + "-", dir=parent)) / path.name
            path.rename(destination)
            print(f"Previous generated state retained at {destination}", file=sys.stderr)

    def update_dependencies(self) -> None:
        self.assert_build_user()
        if self.cfg.offline:
            raise BuildError("update-deps must be online; an offline resolver cannot establish newest versions")
        tools = self.tools()
        source = self.fetch()
        if self.dependency_dir.exists():
            self.verify_dependency_lock()
        if self.vendor_dir.exists():
            self.verify_vendor()
        self.work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="resolve-", dir=self.work) as temp:
            candidate = Path(temp) / "upstream"
            self.copy_source(candidate)
            output = Path(temp) / "dependency-lock"
            output.mkdir()
            env = self.environment()
            env.update(RUSTC=tools["rustc"], RUSTDOC=tools["rustdoc"], CARGO_NET_OFFLINE="false")
            cargo_output_environment(env, Path(temp) / "target")
            run([tools["cargo"], "update", "--manifest-path", candidate / "Cargo.toml"],
                cwd=candidate, env=env, log=output / "update.log")
            expected = read_json(self.root / "source-manifest.json")
            actual = file_manifest(candidate, exclude_git=True)
            expected.pop("Cargo.lock", None)
            actual.pop("Cargo.lock", None)
            if actual != expected:
                raise BuildError("Dependency resolution changed something other than Cargo.lock")
            tomllib.loads((candidate / "Cargo.lock").read_text())
            shutil.copyfile(candidate / "Cargo.lock", output / "Cargo.lock")
            diff = "".join(difflib.unified_diff((self.src / "Cargo.lock").read_text().splitlines(True),
                            (output / "Cargo.lock").read_text().splitlines(True),
                            fromfile="upstream/Cargo.lock", tofile="dependency-lock/Cargo.lock"))
            atomic_write(output / "Cargo.lock.diff", diff.encode())
            info = {"schema": 1, "policy": "newest-compatible-with-upstream-manifests",
                    "source_commit": source["commit"], "upstream_lock_sha256": source["cargo_lock_sha256"],
                    "effective_lock_sha256": digest(output / "Cargo.lock"),
                    "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "cargo_version": tools["cargo_version"], "rustc_vv": tools["rustc_vv"],
                    "evidence_sha256": {name: digest(output / name) for name in ("update.log", "Cargo.lock.diff")}}
            write_json(output / "manifest.json", info)
            self.retire(self.vendor_dir)
            self.retire(self.dependency_dir)
            output.rename(self.dependency_dir)
        self.verify_dependency_lock()
        print("Newest compatible dependency resolution recorded; upstream Cargo.toml and Cargo.lock remain unchanged")

    def update_toolchain(self) -> None:
        raise BuildError("update-toolchain is disabled: this kit uses only already-installed host Rust. "
                         "Use make lock-toolchain to record host versions; it installs nothing.")

    def versions(self) -> None:
        report = {"kit_version": VERSION, "host": debian.host_release(),
                  "installed_packages": debian.installed_versions(run)}
        for filename in ("source.lock.json", "toolchain.lock.json",
                         "dependency-lock/manifest.json", "latest-resolution.json"):
            if (self.root / filename).exists():
                report[filename] = read_json(self.root / filename)
        print(json.dumps(report, indent=2, sort_keys=True))

    def newest(self, complete: bool = False) -> None:
        self.assert_build_user()
        debian.require_forky(allow_override=False)
        if self.cfg.offline or self.cfg.ref != "main":
            raise BuildError("latest requires online UPSTREAM_REF=main; Rust is always host-installed")
        self.tools()  # Fail before changing source/dependency selections if Rust is missing.
        self.invalidate_package()
        (self.root / "latest-resolution.json").unlink(missing_ok=True)
        if self.src.exists():
            self.verify_source()  # Reject edits before changing the selected source/dependencies.
        self.fetch(update=True)
        self.update_dependencies()
        self.doctor()
        write_json(self.root / "latest-resolution.json", {
            "schema": 2, "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": self.verify_source(), "toolchain": read_json(self.root / "toolchain.lock.json"),
            "dependencies": self.verify_dependency_lock(), "installed_packages": debian.installed_versions(run),
            "scope": "current main and compatible crates at resolution time, using unchanged host-installed Rust",
            "not_in_scope": ["Rust installation/update", "APT changes", "global configuration changes",
                             "kernel upgrade", "firmware", "breaking dependency migrations", "benchmark execution"]})
        self.package()
        if complete:
            self.source_dist()

    def assert_build_user(self) -> None:
        if os.geteuid() == 0 and os.environ.get("ALLOW_ROOT_BUILD") != "1":
            raise BuildError("Do not compile as root. Use your ordinary host user. ALLOW_ROOT_BUILD=1 is an explicit container/CI override.")

    def verify_vendor(self) -> dict[str, Any]:
        info = read_json(self.vendor_dir / "manifest.json")
        lock = self.verify_source()
        if info["commit"] != lock["commit"] or info["cargo_lock_sha256"] != digest(self.effective_source() / "Cargo.lock"):
            raise BuildError("Vendor tree belongs to another source lock. Use make clean-vendor, then make vendor.")
        if file_manifest(self.vendor_dir / "crates") != info["files"]:
            raise BuildError("Vendor tree hash mismatch")
        return info

    def vendor_config(self) -> list[str]:
        if not self.vendor_dir.exists():
            return []
        info = self.verify_vendor()
        lines = []
        for source, values in sorted(info["sources"].items()):
            lines.append(f"[source.{json.dumps(source)}]\n")
            for key, value in sorted(values.items()):
                if key == "directory":
                    value = str(self.vendor_dir / "crates")
                if not isinstance(value, str):
                    raise BuildError(f"Unsupported cargo vendor configuration: {key}")
                lines.append(f"{json.dumps(key)} = {json.dumps(value)}\n")
        path = self.work / "vendor-config.toml"
        atomic_write(path, "".join(lines).encode())
        return ["--config", str(path)]

    def cargo_context(self) -> tuple[dict[str, str], dict[str, Any]]:
        self.assert_build_user()
        lock = self.fetch()
        tools = self.tools()
        active_source = self.effective_source()
        rust, c, cxx = compilation_flags(self.cfg, tools["host"], self.root, self.cargo_home)
        env = self.environment()
        cc = str(Path(shutil.which(self.cfg.cc) or self.cfg.cc).resolve())
        cxx_bin = str(Path(shutil.which(self.cfg.cxx) or self.cfg.cxx).resolve())
        rust += [f"-Clinker={cc}"]
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", lock["commit_epoch"]))
        if not 0 <= epoch <= 0xFFFFFFFF:
            raise BuildError("Invalid SOURCE_DATE_EPOCH")
        env.update(RUSTC=tools["rustc"], RUSTDOC=tools["rustdoc"], CARGO=tools["cargo"],
                   CARGO_ENCODED_RUSTFLAGS="\x1f".join(rust),
                   CFLAGS=shlex.join(c), CXXFLAGS=shlex.join(cxx), CC=cc, CXX=cxx_bin,
                   HOST_CC=cc, HOST_CXX=cxx_bin, TARGET_CC=cc, TARGET_CXX=cxx_bin,
                   CC_SHELL_ESCAPED_FLAGS="1",
                   CARGO_PROFILE_RELEASE_OPT_LEVEL="3", CARGO_PROFILE_RELEASE_CODEGEN_UNITS="1",
                   CARGO_PROFILE_RELEASE_LTO=self.cfg.lto,
                   CARGO_PROFILE_RELEASE_DEBUG="1", CARGO_PROFILE_RELEASE_STRIP="none",
                   CARGO_PROFILE_RELEASE_PANIC="unwind", CARGO_PROFILE_RELEASE_INCREMENTAL="false",
                   CARGO_INCREMENTAL="0", SOURCE_DATE_EPOCH=str(epoch))
        if self.cfg.offline:
            env["CARGO_NET_OFFLINE"] = "true"
        else:
            env.pop("CARGO_NET_OFFLINE", None)
        rust_cfg = run([tools["rustc"], "--print", "cfg", "--target", tools["host"], *rust],
                       env=env, quiet=True, timeout=30)
        cpu = {}
        if self.cfg.tune == "native":
            try:
                for line in Path("/proc/cpuinfo").read_text().split("\n\n", 1)[0].splitlines():
                    key, sep, val = line.partition(":")
                    if sep and key.strip() in ("vendor_id", "cpu family", "model", "model name", "stepping",
                                               "flags", "Features", "CPU implementer", "CPU architecture", "CPU variant", "CPU part", "CPU revision"):
                        cpu[key.strip()] = val.strip()
            except OSError:
                pass
        cc_version = run([cc, "--version"], quiet=True).splitlines()[0]
        cxx_version = run([cxx_bin, "--version"], quiet=True).splitlines()[0]
        settings = {"kit_version": VERSION, "source": lock, "rustc_vv": tools["rustc_vv"],
                    "cargo_version": tools["cargo_version"], "host": tools["host"],
                    "resolved_toolchain": self.effective_toolchain(),
                    "effective_cargo_lock_sha256": digest(active_source / "Cargo.lock"),
                    "dependency_policy": "updated-compatible" if self.dependency_dir.exists() else "upstream-locked",
                    "tune": self.cfg.tune, "cpu_signature": cpu, "rustc_cfg": rust_cfg,
                    "rustflags": rust, "cflags": c, "cxxflags": cxx, "cc": cc_version, "cxx": cxx_version,
                    "profile": {k: v for k, v in env.items() if k.startswith("CARGO_PROFILE_RELEASE_")},
                    "binaries": list(self.cfg.binaries), "split_debug": self.cfg.split_debug,
                    "source_date_epoch": epoch,
                    "driver_sha256": digest(self.root / "scripts" / "build.py"),
                    "host_rust_helper_sha256": digest(self.root / "scripts" / "host_rust.py"),
                    "rust_executables": {name: tools[name] for name in ("rustc", "cargo", "rustdoc")},
                    "cargo_configuration_sha256": self.cargo_configuration_fingerprints(active_source),
                    "kit_scripts": {p.name: digest(p) for p in sorted((self.root / "scripts").glob("*.py"))},
                    "installed_debian_packages": debian.installed_versions(run),
                    "os_release": Path("/etc/os-release").read_text(),
                    "kernel": os.uname().release,
                    "glibc": run(["getconf", "GNU_LIBC_VERSION"], quiet=True).strip(),
                    "binutils": run(["ld", "--version"], quiet=True).splitlines()[0]}
        build_id = hashlib.sha256(canonical(settings)).hexdigest()[:16]
        target = self.work / "target" / build_id
        cargo_output_environment(env, target)
        settings.update(build_id=build_id, jobs=self.cfg.jobs,
                        environment_policy="project-local-build-overrides; host-config-files-read-only",
                        overridden_ambient_variables=self.environment_overrides(),
                        cargo_target_dir=str(target), cargo_build_dir=str(target))
        return env, settings

    def cargo(self, command: str, extra: Sequence[str], env: Mapping[str, str], *, log: Path | None = None) -> str:
        tools = self.tools()
        argv = [tools["cargo"], *self.vendor_config(), command,
                "--manifest-path", str(self.effective_source() / "Cargo.toml"),
                "--frozen" if self.cfg.offline else "--locked"]
        if command in ("build", "check", "test"):
            argv += ["--target-dir", env["CARGO_TARGET_DIR"]]
        argv += list(extra)
        output = run(argv, cwd=self.effective_source(), env=env, log=log)
        self.effective_source()  # Reject source/lock modifications by Cargo/build scripts.
        return output

    def doctor(self) -> None:
        self.assert_build_user()
        if (self.root / "source.lock.json").exists():
            self.fetch()
        tools = self.tools()
        rust, c, cxx = compilation_flags(self.cfg, tools["host"], self.root, self.cargo_home)
        env = self.environment()
        with tempfile.TemporaryDirectory(prefix="resctl-probe-") as temp:
            p = Path(temp)
            (p / "probe.rs").write_text('fn main() { println!("rust/linker probe OK"); }\n')
            (p / "probe.c").write_text('int main(void) { return 0; }\n')
            run([tools["rustc"], p / "probe.rs", "--target", tools["host"], *rust,
                 f"-Clinker={shutil.which(self.cfg.cc)}", "-o", p / "rust-probe"], env=env, timeout=60)
            run([self.cfg.cc, *c, p / "probe.c", "-o", p / "c-probe"], env=env, timeout=60)
            run([self.cfg.cxx, *cxx, "-x", "c++", p / "probe.c", "-o", p / "cxx-probe"], env=env, timeout=60)
            for name in ("rust-probe", "c-probe", "cxx-probe"):
                run([p / name], env=env, timeout=10)
        print(json.dumps({"host": tools["host"], "toolchain": tools["cargo_version"],
                          "tuning": self.cfg.tune, "jobs": self.cfg.jobs,
                          "rustflags": rust, "cflags": c,
                          "overridden_ambient_variables": self.environment_overrides(),
                          "output_root": str(self.work)}, indent=2))

    def verify_runtime_support(self, binary_dir: Path, destination: Path) -> None:
        contract = runtime_support.validate_source(self.effective_source(), self.root / "compat/runtime-contract.json")
        result = runtime_support.run_export(binary_dir, contract, environment=self.environment())
        write_json(destination, result)

    def runtime_tests(self) -> dict[str, Any]:
        env, settings = self.cargo_context()
        out = self.work / "builds" / settings["build_id"]
        out.mkdir(parents=True, exist_ok=True)
        result_file = out / "runtime-unit-tests.json"
        result_file.unlink(missing_ok=True)
        suites = []
        combined = []
        selections = [
            ("rd-agent", ["--bin", "rd-agent"], "misc::support_tests::", 10),
            ("rd-util", ["--lib"], "storage_info::source_resolution_tests::", 8),
            ("rd-agent", ["--bin", "rd-agent"], "slices::io_policy_tests::", 6),
            ("rd-util", ["--lib"], "runtime_contract_tests::", 3),
            ("rd-util", ["--lib"], "systemd::lifecycle_tests::", 3),
            ("rd-agent", ["--bin", "rd-agent"], "side::balloon_health_tests::", 4),
        ]
        for package, kind, selector, minimum in selections:
            log = out / ("runtime-unit-tests-" + package + "-" + selector.replace("::", "-").strip("-") + ".log")
            self.cargo("test", ["--release", "--target", settings["host"],
                       "--jobs", str(self.cfg.jobs), "-p", package, *kind,
                       selector, "--", "--test-threads=1"], env, log=log)
            output = log.read_text()
            matched = re.search(r"test result: ok\. (\d+) passed; 0 failed; 0 ignored;", output)
            if not matched or int(matched[1]) < minimum:
                raise BuildError("Required native regression tests did not all pass: " + selector)
            suites.append({"package": package, "filter": selector,
                           "passed": int(matched[1]), "failed": 0})
            combined.append("=== " + package + " " + selector + " ===\n" + output)
        atomic_write(out / "runtime-unit-tests.log", "\n".join(combined).encode())
        result = {"kind": "actual-rust-unit-tests", "suites": suites,
                  "passed": sum(item["passed"] for item in suites), "failed": 0,
                  "storage_workload_run": False}
        write_json(result_file, result)
        return result

    def build(self, command: str = "build") -> tuple[dict[str, Any], Path]:
        env, settings = self.cargo_context()
        out = self.work / "builds" / settings["build_id"]
        out.mkdir(parents=True, exist_ok=True)
        result_path = out / "result.json"
        if command == "build":
            result_path.unlink(missing_ok=True)  # Never reuse a failed build as success.
        packages = [arg for b in self.cfg.binaries for arg in ("-p", b)]
        action = "test" if command == "test-compile" else command
        extra = ["--release", "--target", settings["host"], "--jobs", str(self.cfg.jobs), *packages]
        extra += ["--no-run"] if command == "test-compile" else ["--bins"]
        self.cargo(action, extra, env, log=out / f"{command}.log")
        self.verify_source()
        if command != "build":
            return settings, out
        binaries_dir = Path(env["CARGO_TARGET_DIR"]) / settings["host"] / "release"
        hashes = {}
        for binary in self.cfg.binaries:
            path = binaries_dir / binary
            if not path.is_file() or path.is_symlink() or not os.access(path, os.X_OK):
                raise BuildError(f"Missing executable artifact: {path}")
            validate_elf(path, settings["host"])
            hashes[binary] = digest(path)
        self.verify_runtime_support(binaries_dir, out / "compiled-support.json")
        metadata = self.cargo("metadata", ["--format-version", "1", "--filter-platform", settings["host"]], env)
        write_json(out / "cargo-metadata.json", json.loads(metadata))
        tree = self.cargo("tree", ["--target", settings["host"], "--edges", "normal,build", *packages], env)
        atomic_write(out / "cargo-tree.txt", tree.encode())
        write_json(out / "build-info.json", settings)
        write_json(result_path, {"binaries_dir": str(binaries_dir), "hashes": hashes})
        return settings, out

    def smoke(self, binary_dir: Path, destination: Path) -> None:
        env = self.environment()
        env["PATH"] = str(binary_dir) + os.pathsep + env.get("PATH", "")
        outputs = {}
        with tempfile.TemporaryDirectory(prefix="resctl-smoke-") as temp:
            env["HOME"] = temp
            for name in self.cfg.binaries:
                for arg in ("--version", "--help"):
                    outputs[f"{name} {arg}"] = run([binary_dir / name, arg], cwd=Path(temp),
                                                   env=env, timeout=30, quiet=True)
        write_json(destination, outputs)

    def collect_licenses(self, metadata: dict[str, Any], destination: Path) -> None:
        inventory = []
        for pkg in metadata["packages"]:
            base = Path(pkg["manifest_path"]).parent
            identity = hashlib.sha256(pkg["id"].encode()).hexdigest()[:8]
            label = f"{pkg['name']}-{pkg['version']}-{identity}"
            safe_relative(label)
            item = {"name": pkg["name"], "version": pkg["version"], "id": pkg["id"],
                    "source": pkg.get("source"), "license": pkg.get("license"), "license_files": []}
            candidates = set()
            for glob in ("LICENSE*", "LICENCE*", "COPYING*", "NOTICE*", "UNLICENSE*"):
                candidates.update(base.glob(glob))
            for directory in ("licenses", "LICENSES"):
                if (base / directory).is_dir():
                    candidates.update((base / directory).rglob("*"))
            if pkg.get("license_file"):
                candidates.add(base / safe_relative(pkg["license_file"]))
            for path in sorted(candidates):
                if path.is_file() and path.resolve().is_relative_to(base.resolve()):
                    rel = path.relative_to(base)
                    dest = destination / label / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest)
                    dest.chmod(0o644)
                    item["license_files"].append(rel.as_posix())
            inventory.append(item)
        write_json(destination.parent / "THIRD-PARTY.json", inventory)

    def stage(self) -> tuple[Path, dict[str, Any]]:
        settings, out = self.build()
        result = read_json(out / "result.json")
        self.runtime_tests()
        version = tomllib.loads((self.src / "resctl-bench" / "Cargo.toml").read_text())["package"]["version"]
        if not re.fullmatch(r"[A-Za-z0-9.+-]+", version):
            raise BuildError("Unsupported upstream version string")
        name = f"resctl-bench-{version}-{settings['host']}-{self.cfg.tune}-{settings['build_id']}"
        stage_parent = self.work / "stage"
        stage_parent.mkdir(parents=True, exist_ok=True)
        final = stage_parent / name
        with tempfile.TemporaryDirectory(prefix="stage-", dir=self.work) as temp:
            stage = Path(temp) / name
            bin_dir = stage / "bin"
            doc = stage / "share/doc/resctl-bench"
            provenance = stage / "share/resctl-bench/build"
            licenses = stage / "share/licenses/resctl-bench"
            for p in (bin_dir, doc, provenance, licenses):
                p.mkdir(parents=True, exist_ok=True)
            elf_info = []
            for binary in self.cfg.binaries:
                built = Path(result["binaries_dir"]) / binary
                if digest(built) != result["hashes"][binary]:
                    raise BuildError(f"Artifact changed after compilation: {binary}")
                target = bin_dir / binary
                shutil.copyfile(built, target)
                target.chmod(0o755)
                if self.cfg.split_debug:
                    debug = bin_dir / ".debug" / f"{binary}.debug"
                    debug.parent.mkdir(exist_ok=True)
                    run(["objcopy", "--only-keep-debug", target, debug], quiet=True)
                    debug.chmod(0o644)
                    run(["strip", "--strip-unneeded", target], quiet=True)
                    run(["objcopy", f"--add-gnu-debuglink={debug}", target], quiet=True)
                elf_info.append(f"\n=== {binary} ===\n" + run(["readelf", "-h", "-l", "-d", "-V", target], quiet=True))
            atomic_write(provenance / "elf-info.txt", "".join(elf_info).encode())
            self.smoke(bin_dir, provenance / "smoke-test.json")
            self.verify_runtime_support(bin_dir, provenance / "compiled-support.json")
            shutil.copyfile(self.root / "compat/runtime-contract.json", stage / "share/resctl-bench/runtime-contract.json")
            for filename in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md"):
                if (self.src / filename).is_file():
                    shutil.copyfile(self.src / filename, doc / ("upstream-" + filename))
            for binary in self.cfg.binaries:
                if (self.src / binary / "README.md").exists():
                    shutil.copyfile(self.src / binary / "README.md", doc / (binary + "-README.md"))
            if (self.src / "resctl-bench/doc").is_dir():
                shutil.copytree(self.src / "resctl-bench/doc", doc / "upstream-bench-docs")
            shutil.copytree(self.root / "docs", doc / "buildkit-docs", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copyfile(self.root / "README.md", doc / "buildkit-README.md")
            shutil.copyfile(self.src / "LICENSE", licenses / "LICENSE.upstream")
            shutil.copyfile(self.root / "LICENSE", licenses / "LICENSE.buildkit")
            metadata = read_json(out / "cargo-metadata.json")
            self.collect_licenses(metadata, licenses / "third-party")
            for p in ("build-info.json", "cargo-metadata.json", "cargo-tree.txt", "build.log", "runtime-unit-tests.json", "runtime-unit-tests.log"):
                shutil.copyfile(out / p, provenance / p)
            for p in ("source.lock.json", "source-manifest.json", "toolchain.lock.json"):
                shutil.copyfile(self.root / p, provenance / p)
            shutil.copyfile(self.effective_source() / "Cargo.lock", provenance / "Cargo.lock")
            shutil.copyfile(self.src / "Cargo.lock", provenance / "Cargo.lock.upstream")
            if self.dependency_dir.exists():
                shutil.copytree(self.dependency_dir, provenance / "dependency-update")
            for filename in ("latest-resolution.json",):
                if (self.root / filename).exists():
                    shutil.copyfile(self.root / filename, provenance / filename)
            for filename in ("apt-build.json", "apt-runtime.json", "apt-llvm.json"):
                if (self.work / filename).exists():
                    shutil.copyfile(self.work / filename, provenance / filename)
            shutil.copytree(self.root / "packages", provenance / "debian-packages")
            shutil.copytree(self.root / "patches", provenance / "source-patches")
            for p in ("install.py", "runtime_check.py", "runtime_support.py"):
                shutil.copyfile(self.root / "scripts" / p, stage / p)
                (stage / p).chmod(0o755)
            shutil.copyfile(self.root / "docs/RELEASE-README.md", stage / "README.md")
            checksums(stage)
            run([sys.executable, "-I", "-B", stage / "install.py", "--package", stage, "--verify"], quiet=True)
            if final.exists():
                shutil.rmtree(final)
            stage.rename(final)
        write_json(self.work / "last-stage.json", {"path": str(final), "settings": settings})
        return final, settings

    def invalidate_package(self) -> None:
        """Never leave a convenience success pointer for an unsuccessful attempt."""
        (self.work / "last-package.json").unlink(missing_ok=True)
        alias = self.dist / "resctl-bench-latest.tar.gz"
        if alias.is_symlink():
            alias.unlink()
        elif alias.exists():
            raise BuildError(f"Refuse to overwrite non-generated archive alias: {alias}")
        (self.dist / "resctl-bench-latest.tar.gz.sha256").unlink(missing_ok=True)

    def package(self) -> Path:
        self.invalidate_package()
        stage, settings = self.stage()
        tar = self.dist / (stage.name + ".tar.gz")
        make_archive(stage, tar, settings["source_date_epoch"])
        alias = self.dist / "resctl-bench-latest.tar.gz"
        pending = self.dist / ".resctl-bench-latest.tar.gz.tmp"
        pending.unlink(missing_ok=True)
        pending.symlink_to(tar.name)
        os.replace(pending, alias)
        atomic_write(self.dist / "resctl-bench-latest.tar.gz.sha256",
                     f"{digest(tar)}  {alias.name}\n".encode())
        write_json(self.work / "last-package.json", {"path": str(tar), "sha256": digest(tar), "stage": str(stage)})
        print(f"\nCreated {tar}\nSHA256 {digest(tar)}\nBinary tarball: {alias}", flush=True)
        return tar

    def vendor(self) -> None:
        env, settings = self.cargo_context()
        if self.vendor_dir.exists():
            self.verify_vendor()
            print("Existing vendor tree verified")
            return
        with tempfile.TemporaryDirectory(prefix="vendor-", dir=self.work) as temp:
            tree = Path(temp) / "vendor"
            crates = tree / "crates"
            output = run([self.tools()["cargo"], "vendor", "--manifest-path", self.effective_source() / "Cargo.toml",
                          "--frozen" if self.cfg.offline else "--locked", "--respect-source-config", "--versioned-dirs", crates],
                         cwd=self.effective_source(), env=env)
            sources = tomllib.loads(output).get("source")
            if not sources:
                raise BuildError("cargo vendor did not emit source replacement configuration")
            for values in sources.values():
                if "directory" in values:
                    values["directory"] = "crates"
            write_json(tree / "manifest.json", {"schema": 1, "commit": settings["source"]["commit"],
                       "cargo_lock_sha256": settings["effective_cargo_lock_sha256"],
                       "sources": sources, "files": file_manifest(crates)})
            tree.rename(self.vendor_dir)
        self.verify_source()

    def copy_kit(self, destination: Path) -> None:
        destination.mkdir(parents=True)
        for name in KIT_ITEMS:
            src, dest = self.root / name, destination / name
            if src.is_dir():
                shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copyfile(src, dest)
        for p in (destination / "scripts").glob("*.py"):
            p.chmod(0o755)
        (destination / "RUN-IOCOST-LAB.sh").chmod(0o755)
        (destination / "BUILD.sh").chmod(0o755)
        # Archive completeness gate: isolated Python ignores PYTHONPATH and the
        # scripts directory, precisely the environment the old imports broke in.
        for action in ("help", "lint"):
            run([sys.executable, "-I", "-B", destination / "scripts/build.py", action],
                cwd=destination, timeout=30, quiet=True)
        (destination / ".buildkit.lock").unlink(missing_ok=True)

    def snapshot_dist(self) -> Path:
        """Archive all selected project sources without Rust, downloads or vendoring.

        Always includes the complete locked source and its recovery asset.
        Unlike source-dist it does not require Cargo or promise offline crates.
        """
        lock = self.fetch()
        if lock.get("patchset") and not lock.get("recovery"):
            self.create_recovery_archive()
            lock = self.verify_source()
        if self.dependency_dir.exists():
            self.verify_dependency_lock()
        if self.vendor_dir.exists():
            self.verify_vendor()
        name = "resctl-bench"
        self.work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="snapshot-dist-", dir=self.work) as temp:
            tree = Path(temp) / name
            self.copy_kit(tree)
            # Ship reviewed defaults, never a user's executable/private Make config.
            shutil.copyfile(tree / "config.mk.example", tree / "config.mk")
            self.copy_source(tree / "upstream", stable_metadata=True)
            self.copy_recovery_archive(tree)
            for filename in ("source.lock.json", "source-manifest.json"):
                shutil.copyfile(self.root / filename, tree / filename)
            for dirname in ("dependency-lock", "vendor"):
                if (self.root / dirname).exists():
                    shutil.copytree(self.root / dirname, tree / dirname)
            write_json(tree / "source-snapshot.json", {
                "schema": 1, "kind": "complete-project-source-snapshot",
                "kit_version": VERSION, "source_commit": lock["commit"],
                "upstream_files": len(read_json(self.root / "source-manifest.json")),
                "vendored_dependencies": self.vendor_dir.exists(),
                "rust_policy": "host-installed-only", "contains_compiled_binaries": False,
                "configuration": "config.mk contains shipped defaults, not the source host's overrides"})
            Builder(tree, self.cfg).verify_source()
            checksums(tree)
            epoch = int(os.environ.get("SOURCE_DATE_EPOCH", lock["commit_epoch"]))
            destination = self.dist / (f"resctl-bench-2.2.6-complete-source-{VERSION}.tar.gz")
            make_archive(tree, destination, epoch)
        print(destination)
        return destination

    def source_dist(self, kit_only: bool = False) -> Path:
        if (kit_only and (self.root / "source.lock.json").exists()
                and read_json(self.root / "source.lock.json").get("patchset")):
            print("kit-dist includes COMPLETE source for this patched release.", file=sys.stderr)
            return self.snapshot_dist()
        lock = None
        if not kit_only:
            self.fetch()
            self.vendor()
            lock = self.verify_source()
            self.verify_vendor()
        name = f"resctl-bench-buildkit-{VERSION}"
        if not kit_only:
            # Distinguish dependency/toolchain refreshes at an unchanged upstream SHA.
            identity = hashlib.sha256(canonical({
                "source": lock["commit"],
                "cargo_lock": digest(self.effective_source() / "Cargo.lock"),
                "toolchain": read_json(self.root / "toolchain.lock.json"),
            })).hexdigest()[:16]
            name += f"-source-{lock['commit'][:12]}-{identity}"
        self.work.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="source-dist-", dir=self.work) as temp:
            tree = Path(temp) / name
            self.copy_kit(tree)
            if not kit_only:
                for filename in ("source.lock.json", "source-manifest.json", "toolchain.lock.json"):
                    shutil.copyfile(self.root / filename, tree / filename)
                shutil.copytree(self.vendor_dir, tree / "vendor")
                self.copy_source(tree / "upstream", stable_metadata=True)
                self.copy_recovery_archive(tree)
                if self.dependency_dir.exists():
                    shutil.copytree(self.dependency_dir, tree / "dependency-lock")
                for filename in ("latest-resolution.json",):
                    if (self.root / filename).exists():
                        shutil.copyfile(self.root / filename, tree / filename)
                Builder(tree, self.cfg).verify_source()
            checksums(tree)
            epoch = int(os.environ.get("SOURCE_DATE_EPOCH", lock["commit_epoch"] if lock else 1789430400))
            destination = self.dist / (name + ".tar.gz")
            make_archive(tree, destination, epoch)
        print(destination)
        return destination

    def last_package(self) -> dict[str, Any]:
        """Read a completed publication, never infer success from leftover files.

        Failed package attempts deliberately remove this pointer. Installation
        must not compile as root, create a substitute manifest, or reuse an old
        stage after a newer build failed.
        """
        record = self.work / "last-package.json"
        recovery = ("Run make package verify as your ordinary user in this source directory. "
                    "Resolve its FIRST error; only after it succeeds run sudo ./BUILD.sh install. "
                    "Installation does not build, and no system files were changed.")
        if not record.exists():
            raise BuildError("No successfully completed package is available: " + str(record)
                             + ". A failed build (or make clean) leaves no install manifest. " + recovery)
        if self.work.is_symlink() or record.is_symlink() or not record.is_file():
            raise BuildError("Unsafe last-package manifest: " + str(record))
        try:
            last = read_json(record)
        except BuildError as exc:
            raise BuildError("Invalid last-package manifest. " + recovery) from exc
        if (not isinstance(last, dict)
                or not isinstance(last.get("stage"), str) or not last["stage"]
                or not isinstance(last.get("path"), str) or not last["path"]
                or not isinstance(last.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", last["sha256"])):
            raise BuildError("Invalid last-package manifest. " + recovery)
        stage, archive = Path(last["stage"]), Path(last["path"])
        for path, parent, label in ((stage, self.work / "stage", "stage"),
                                    (archive, self.dist, "archive")):
            if (not path.is_absolute() or ".." in path.parts
                    or path == parent or not path.is_relative_to(parent)
                    or not path.resolve().is_relative_to(parent.resolve())):
                raise BuildError("Unsafe last-package " + label + " path. " + recovery)
            current = path
            while current != self.root:
                if current.is_symlink():
                    raise BuildError("Symlink in last-package " + label + " path: " + str(current))
                current = current.parent
        if not stage.is_dir():
            raise BuildError("The completed package stage is missing: " + str(stage) + ". " + recovery)
        if not archive.is_file() or digest(archive) != last["sha256"]:
            raise BuildError("Release archive checksum/path mismatch. " + recovery)
        return last

    def install(self, uninstall: bool = False) -> None:
        cmd: list[str | Path] = [sys.executable, "-I", "-B", self.root / "scripts/install.py",
                                "--prefix", os.environ.get("PREFIX", "/usr/local")]
        if os.environ.get("DESTDIR"):
            cmd += ["--destdir", os.environ["DESTDIR"]]
        if uninstall:
            cmd.append("--uninstall")
        else:
            last = self.last_package()
            stage = Path(last["stage"])
            cmd += ["--package", stage]
            if boolean(os.environ, "FORCE", "0"):
                cmd.append("--force")
        print(run(cmd))


def validate_elf(path: Path, host: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1:
        raise BuildError(f"Not a 64-bit little-endian ELF artifact: {path}")
    machine = int.from_bytes(header[18:20], "little")
    expected = {"x86_64-unknown-linux-gnu": 62, "aarch64-unknown-linux-gnu": 183}[host]
    if machine != expected:
        raise BuildError(f"ELF machine mismatch for {path}: {machine} != {expected}")
    if int.from_bytes(header[16:18], "little") != 3:
        raise BuildError(f"Executable is not PIE: {path}")
    info = run(["readelf", "--wide", "-l", "-d", path], quiet=True)
    if "GNU_RELRO" not in info or not ("BIND_NOW" in info or re.search(r'Flags:.*\bNOW\b', info)):
        raise BuildError(f"Full RELRO not found in {path}")
    stacks = [line for line in info.splitlines() if "GNU_STACK" in line]
    if not stacks or any(re.search(r'\bRW?E\b', line) for line in stacks):
        raise BuildError(f"Non-executable-stack check failed for {path}")


def deps(root: Path, runtime: bool) -> None:
    debian.install_dependencies(root, "runtime" if runtime else "build", run, write_json)


@contextlib.contextmanager
def project_lock(root: Path) -> Iterator[None]:
    path = root / ".buildkit.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def main() -> int:
    action = sys.argv[1] if len(sys.argv) == 2 else "help"
    if action == "help":
        print(HELP)
        return 0
    cfg = Config.from_env()
    builder = Builder(ROOT, cfg)
    # Installation never needs rustup and may run as root after an ordinary-user build.
    if action in ("install", "uninstall"):
        builder.install(action == "uninstall")
        return 0
    with project_lock(ROOT):
        if action in ("deps", "deps-runtime"):
            deps(ROOT, action == "deps-runtime")
        elif action == "deps-plan":
            debian.install_dependencies(ROOT, "build", run, write_json, plan_only=True)
        elif action == "deps-llvm":
            debian.install_dependencies(ROOT, "llvm", run, write_json)
        elif action == "update-toolchain":
            builder.update_toolchain()
        elif action == "update-rustup":
            raise BuildError("update-rustup is disabled: this kit never installs or updates rustup or Rust")
        elif action == "update-deps":
            builder.update_dependencies()
        elif action == "versions":
            builder.versions()
        elif action in ("latest", "latest-complete"):
            builder.newest(complete=action == "latest-complete")
        elif action == "doctor":
            builder.doctor()
        elif action in ("fetch", "update-source"):
            lock = builder.fetch(update=action == "update-source")
            print("Verified source: " + str(builder.src) + " (" + lock["commit"] + ")")
        elif action == "restore-source":
            builder.restore_source()
        elif action == "verify-source":
            lock = builder.verify_source()
            if lock.get("recovery"):
                source_archive.validate_cache(ROOT, lock["recovery"])
            print("Verified complete patched source, Cargo.lock and offline recovery archive")
        elif action == "lock-toolchain":
            builder.tools(refresh=True)
            print("Installed compiler explicitly accepted in toolchain.lock.json")
        elif action == "fetch-deps":
            env, settings = builder.cargo_context()
            builder.cargo("fetch", ["--target", settings["host"]], env)
        elif action in ("build", "check", "test-compile"):
            builder.build(action)
        elif action == "test-runtime":
            builder.runtime_tests()
        elif action == "smoke":
            _, out = builder.build()
            builder.smoke(Path(read_json(out / "result.json")["binaries_dir"]), out / "smoke-test.json")
        elif action == "stage":
            stage, _ = builder.stage()
            print(stage)
        elif action == "package":
            builder.package()
        elif action == "rebuild":
            builder.package()
        elif action == "vendor":
            builder.vendor()
        elif action == "snapshot-dist":
            builder.snapshot_dist()
        elif action in ("source-dist", "kit-dist"):
            builder.source_dist(kit_only=action == "kit-dist")
        elif action == "verify":
            last = builder.last_package()
            run([sys.executable, "-I", "-B", ROOT / "scripts/install.py", "--package", last["stage"], "--verify"])
            print("Archive and staged files verified")
        elif action == "clean":
            if builder.work.is_symlink():
                raise BuildError("Refuse to remove a symlinked .work directory")
            if builder.work.exists():
                shutil.rmtree(builder.work)
        elif action == "clean-vendor":
            if builder.vendor_dir.exists():
                if builder.vendor_dir.is_symlink() or not (builder.vendor_dir / "manifest.json").is_file():
                    raise BuildError("Refuse to remove an unrecognized vendor directory")
                shutil.rmtree(builder.vendor_dir)
        elif action == "lint":
            count = 0
            for directory in (ROOT / "scripts", ROOT / "tests"):
                for path in directory.glob("*.py"):
                    text = path.read_text()
                    ast.parse(text, filename=str(path))
                    if not text.endswith("\n") or any(line.rstrip() != line for line in text.splitlines()):
                        raise BuildError(f"Whitespace error in {path}")
                    count += 1
            print(f"Syntax/whitespace checks passed: {count} Python files")
        else:
            raise BuildError(f"Unknown action {action!r}; run make help")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BuildError, debian.DebianError, host_rust.HostRustError, runtime_support.SupportError, source_archive.SourceArchiveError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if os.environ.get("BUILDKIT_TRACEBACK") == "1":
            raise
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted; incomplete builds are not published", file=sys.stderr)
        sys.exit(130)
