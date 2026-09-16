#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Discover already installed Rust tools without changing the host.

There is deliberately no installer, download, update, default/override mutation,
or configuration writer in this module. Rustup, when needed, is queried only
with `which` (never `--install`). Resolve proxies BEFORE entering upstream/ so
an upstream rust-toolchain file cannot select or provision another compiler.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
from typing import Callable, Mapping, Any


class HostRustError(RuntimeError):
    """The requested host tools are not already available."""


def validate_selection(selection: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", selection):
        raise HostRustError("TOOLCHAIN must be host or a plain already-installed rustup toolchain name")


def lookup(name: str, environment: Mapping[str, str], cwd: Path, *, fallback: bool = True) -> Path | None:
    """PATH wins over fallback Cargo bin directories; do not rewrite PATH."""
    name = os.path.expanduser(name)
    if "/" in name:
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return candidate.absolute() if candidate.is_file() and os.access(candidate, os.X_OK) else None
    path = os.pathsep.join(str((cwd / part).absolute()) if not Path(part).is_absolute() else part
                           for part in environment.get("PATH", os.defpath).split(os.pathsep))
    found = shutil.which(name, path=path)
    if found:
        # Do not resolve symlinks here: cargo/rustc can be rustup proxies.
        return Path(found).absolute()
    if fallback:
        homes = []
        if environment.get("CARGO_HOME"):
            home = Path(environment["CARGO_HOME"]).expanduser()
            homes.append(home if home.is_absolute() else cwd / home)
        homes.append(Path(environment.get("HOME", str(Path.home()))) / ".cargo")
        for home in homes:
            candidate = home / "bin" / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.absolute()
    return None


def proxy_manager(binary: Path, environment: Mapping[str, str], cwd: Path) -> Path | None:
    """Recognize both symlinked and hardlinked rustup proxies."""
    resolved = binary.resolve()
    if resolved.name == "rustup":
        return resolved
    candidates = [binary.parent / "rustup", lookup("rustup", environment, cwd)]
    for candidate in candidates:
        if candidate is not None and candidate.is_file() and os.access(candidate, os.X_OK):
            if os.path.samefile(binary, candidate):
                return candidate.absolute()
    return None


def discover(selection: str, overrides: Mapping[str, str], environment: Mapping[str, str],
             cwd: Path, run: Callable[..., Any]) -> dict[str, str]:
    validate_selection(selection)
    env = dict(environment)
    # Fail, rather than downloading anything, for a missing active toolchain.
    env["RUSTUP_AUTO_INSTALL"] = "0"
    if selection != "host" and any(overrides.values()):
        raise HostRustError("Use TOOLCHAIN=host with explicit HOST_RUSTC/HOST_CARGO/HOST_RUSTDOC "
                            "or RUSTC/CARGO/RUSTDOC; do not combine them with a named TOOLCHAIN")
    manager = None
    if selection != "host":
        manager = lookup("rustup", env, cwd)
        if manager is None:
            raise HostRustError("A named TOOLCHAIN needs an existing rustup installation. "
                                "Use TOOLCHAIN=host for distro/native Rust. Nothing was installed.")
        env["RUSTUP_TOOLCHAIN"] = selection
    result = {}
    for name in ("rustc", "cargo", "rustdoc"):
        binary = None
        chosen_manager = manager
        if selection == "host":
            requested = overrides.get(name) or name
            binary = lookup(requested, env, cwd, fallback=not bool(overrides.get(name)))
            if binary is None:
                raise HostRustError(f"Host {name} not found: {requested!r}. Put the installed tools on PATH "
                                    f"or set HOST_{name.upper()}=/absolute/path. "
                                    "Automatic Rust installation is disabled; no host configuration was changed.")
            chosen_manager = proxy_manager(binary, env, cwd)
        if chosen_manager is not None:
            args = [str(chosen_manager), "which"]
            if selection != "host":
                args += ["--toolchain", selection]
            args.append(name)
            try:
                output = run(args, cwd=cwd, env=env, timeout=30, quiet=True).strip()
            except RuntimeError as exc:
                raise HostRustError(f"Cannot resolve an already-installed host {name}; "
                                    f"automatic Rust installation is disabled. {exc}") from exc
            binary = Path(output)
            if not output or "\n" in output or not binary.is_absolute():
                raise HostRustError(f"rustup which returned an invalid {name} path: {output!r}")
            if proxy_manager(binary, env, cwd) is not None:
                raise HostRustError(f"rustup which returned another proxy instead of a concrete {name}: {binary}")
        assert binary is not None
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise HostRustError(f"Selected host {name} is not an installed executable: {binary}. "
                                "Automatic Rust installation is disabled.")
        result[name] = str(binary.resolve())
    return result
