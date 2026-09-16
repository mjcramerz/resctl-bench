# SPDX-License-Identifier: MIT
"""Pure environment-policy regressions: no compiler, network or global writes."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build as bk


class BuildEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="build environment tests ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.cfg = bk.Config.from_env({})

    def test_all_controlled_exact_variables_no_longer_cause_rejection(self):
        source = {key: "host-setting-must-not-leak" for key in bk.CONTROLLED_BUILD_VARIABLES}
        with patch.dict(os.environ, source, clear=True):
            builder = bk.Builder(self.root, self.cfg)
            env = builder.environment()
            for name in source:
                with self.subTest(variable=name):
                    self.assertNotEqual(env.get(name), source[name])
            self.assertEqual(dict(os.environ), source)
            self.assertEqual(builder.environment_overrides(), sorted(source))

    def test_profile_and_target_specific_patterns_are_scoped_away(self):
        source = {key: "ambient" for key in (
            "CARGO_PROFILE_RELEASE_CODEGEN_UNITS", "CARGO_PROFILE_DEV_DEBUG",
            "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER", "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER",
            "CFLAGS_x86_64_unknown_linux_gnu", "CXXFLAGS_aarch64-unknown-linux-gnu",
            "CC_x86_64_unknown_linux_gnu", "CXX_aarch64_unknown_linux_gnu",
            "AR_x86_64_unknown_linux_gnu", "ARFLAGS_x86_64_unknown_linux_gnu",
            "CPPFLAGS_x86_64_unknown_linux_gnu")}
        with patch.dict(os.environ, source, clear=True):
            env = bk.Builder(self.root, self.cfg).environment()
            for name in source:
                self.assertNotIn(name, env)

    def test_registry_mirror_credentials_and_proxy_environment_are_preserved(self):
        source = {"CARGO_HOME": str(self.root.parent / "custom Cargo home"),
                  "RUSTUP_HOME": "/existing/rustup", "RUSTUP_TOOLCHAIN": "host-existing-choice",
                  "CARGO_REGISTRIES_CRATES_IO_PROTOCOL": "sparse", "CARGO_REGISTRY_TOKEN": "fixture-secret",
                  "CARGO_REGISTRIES_COMPANY_TOKEN": "fixture-company-secret", "CARGO_HTTP_PROXY": "proxy.invalid:8080",
                  "CARGO_HTTP_CAINFO": "/existing/company-ca.pem", "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
                  "HTTPS_PROXY": "https://proxy.invalid", "NO_PROXY": "localhost",
                  "CARGO_NET_OFFLINE": "true", "PKG_CONFIG_PATH": "/existing/pkgconfig"}
        with patch.dict(os.environ, source, clear=True):
            builder = bk.Builder(self.root, self.cfg)
            env = builder.environment()
            for key, value in source.items():
                self.assertEqual(env[key], value)
            self.assertEqual(builder.environment_overrides(), [])

    def test_explicit_rust_selectors_are_not_cleared(self):
        source = {"RUSTC": "/host/rustc", "CARGO": "/host/cargo", "RUSTDOC": "/host/rustdoc",
                  "HOST_RUSTC": "/explicit/rustc", "HOST_CARGO": "/explicit/cargo", "HOST_RUSTDOC": "/explicit/rustdoc"}
        with patch.dict(os.environ, source, clear=True):
            env = bk.Builder(self.root, self.cfg).environment()
            for key in source:
                self.assertEqual(env[key], source[key])

    def test_both_target_aliases_and_intermediates_share_local_path(self):
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": "/outside/final", "CARGO_BUILD_TARGET_DIR": "/outside/alias",
                                    "CARGO_BUILD_BUILD_DIR": "/outside/intermediate"}):
            builder = bk.Builder(self.root, self.cfg)
            env = builder.environment()
            for name in ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
                self.assertEqual(env[name], str(self.root / ".work/cargo"))
            bk.cargo_output_environment(env, self.root / ".work/target/new-id")
            for name in ("CARGO_TARGET_DIR", "CARGO_BUILD_TARGET_DIR", "CARGO_BUILD_BUILD_DIR"):
                self.assertEqual(env[name], str(self.root / ".work/target/new-id"))

    def test_unusual_inherited_target_values_are_not_parsed_or_used(self):
        for value in ("", "../relative target", "~/shared/cache", "/missing/readonly", "{workspace-root}/shared"):
            with self.subTest(value=value), patch.dict(os.environ, {"CARGO_TARGET_DIR": value}):
                self.assertEqual(bk.Builder(self.root, self.cfg).environment()["CARGO_TARGET_DIR"],
                                 str(self.root / ".work/cargo"))
                self.assertEqual(os.environ["CARGO_TARGET_DIR"], value)

    def test_wrapper_and_bootstrap_environment_cannot_override_host_selection(self):
        with patch.dict(os.environ, {"RUSTC_WRAPPER": "/missing/sccache", "RUSTC_WORKSPACE_WRAPPER": "/missing/wrapper",
                                    "RUSTC_BOOTSTRAP": "1", "RUSTUP_AUTO_INSTALL": "1"}):
            env = bk.Builder(self.root, self.cfg).environment()
            self.assertEqual(env["RUSTC_WRAPPER"], "")
            self.assertEqual(env["RUSTC_WORKSPACE_WRAPPER"], "")
            self.assertEqual(env["RUSTUP_AUTO_INSTALL"], "0")
            self.assertNotIn("RUSTC_BOOTSTRAP", env)

    def test_notice_contains_names_only_once_and_does_not_leak_values(self):
        source = {"CARGO_TARGET_DIR": "/private/user/location", "RUSTFLAGS": "--private-flag-value"}
        with patch.dict(os.environ, source, clear=True):
            builder = bk.Builder(self.root, self.cfg)
            text = io.StringIO()
            with contextlib.redirect_stderr(text):
                builder.report_environment_overrides()
                builder.report_environment_overrides()
            self.assertEqual(text.getvalue().count("NOTE:"), 1)
            for key, value in source.items():
                self.assertIn(key, text.getvalue())
                self.assertNotIn(value, text.getvalue())

    def test_empty_overrides_do_not_generate_noise(self):
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": "", "RUSTFLAGS": ""}, clear=True):
            builder = bk.Builder(self.root, self.cfg)
            text = io.StringIO()
            with contextlib.redirect_stderr(text):
                builder.report_environment_overrides()
            self.assertEqual(text.getvalue(), "")
            self.assertEqual(builder.environment_overrides(), [])

    def test_environment_construction_does_not_write_files(self):
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": str(self.root.parent / "must-not-exist")}):
            before = set(self.root.parent.rglob("*"))
            bk.Builder(self.root, self.cfg).environment()
            self.assertEqual(before, set(self.root.parent.rglob("*")))


if __name__ == "__main__":
    unittest.main()
