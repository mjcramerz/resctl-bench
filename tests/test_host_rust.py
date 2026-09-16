# SPDX-License-Identifier: MIT
"""Host-only selection regressions; all compiler/manager executables are fixtures."""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build as bk
hr = bk.host_rust


class HostRustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host rust tests ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "host-bin"
        self.bin.mkdir()
        self.env = {"PATH": str(self.bin), "HOME": str(self.root / "home"),
                    "CARGO_HOME": str(self.root / "custom cargo home"),
                    "RUSTUP_HOME": str(self.root / "custom rustup home"),
                    "RUSTUP_AUTO_INSTALL": "1"}
        self.calls = []

    def tool(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
        return path

    def native_tools(self, directory=None):
        directory = directory or self.bin
        return {name: str(self.tool(directory / name)) for name in ("rustc", "cargo", "rustdoc")}

    def proxy_tools(self, hardlink=False):
        manager = self.tool(self.bin / "rustup")
        actual = self.native_tools(self.root / "installed toolchain/bin")
        for name in actual:
            if hardlink:
                os.link(manager, self.bin / name)
            else:
                (self.bin / name).symlink_to(manager)
        def runner(args, **kwargs):
            self.calls.append((args, kwargs))
            self.assertEqual(args[1], "which")
            self.assertNotIn("--install", args)
            self.assertEqual(kwargs["env"]["RUSTUP_AUTO_INSTALL"], "0")
            self.assertEqual(kwargs["env"]["CARGO_HOME"], self.env["CARGO_HOME"])
            self.assertEqual(kwargs["env"]["RUSTUP_HOME"], self.env["RUSTUP_HOME"])
            self.assertEqual(kwargs["cwd"], self.root)
            return actual[args[-1]] + "\n"
        return actual, runner

    def discover(self, **kwargs):
        return hr.discover(kwargs.get("selection", "host"), kwargs.get("overrides", {}),
                           self.env, self.root, kwargs.get("run", Mock(side_effect=AssertionError("unexpected manager call"))))

    def test_default_is_host_not_nightly(self):
        self.assertEqual(bk.Config.from_env({}).toolchain, "host")

    def test_distro_tools_need_no_rustup(self):
        expected = self.native_tools()
        self.assertEqual(self.discover(), expected)

    def test_path_native_tools_win_even_when_rustup_exists(self):
        expected = self.native_tools()
        self.tool(self.bin / "rustup")
        self.assertEqual(self.discover(), expected)

    def test_symlink_proxies_resolve_without_install(self):
        expected, runner = self.proxy_tools()
        original = self.env.copy()
        self.assertEqual(self.discover(run=runner), expected)
        self.assertEqual(self.env, original)
        self.assertEqual(len(self.calls), 3)
        self.assertTrue(all("RUSTUP_TOOLCHAIN" not in call[1]["env"] for call in self.calls))

    def test_hardlink_proxies_resolve_without_install(self):
        expected, runner = self.proxy_tools(hardlink=True)
        self.assertEqual(self.discover(run=runner), expected)
        self.assertEqual(len(self.calls), 3)

    def test_inherited_active_toolchain_is_respected(self):
        self.env["RUSTUP_TOOLCHAIN"] = "already-installed-local"
        expected, runner = self.proxy_tools()
        self.assertEqual(self.discover(run=runner), expected)
        self.assertTrue(all(call[1]["env"]["RUSTUP_TOOLCHAIN"] == "already-installed-local" for call in self.calls))

    def test_explicit_installed_named_toolchain_only_uses_which(self):
        expected, runner = self.proxy_tools()
        self.assertEqual(self.discover(selection="nightly-local", run=runner), expected)
        for args, kwargs in self.calls:
            self.assertEqual(args[1:4], ["which", "--toolchain", "nightly-local"])
            self.assertEqual(kwargs["env"]["RUSTUP_TOOLCHAIN"], "nightly-local")

    def test_absent_named_toolchain_fails_instead_of_installing(self):
        _, runner = self.proxy_tools()
        run = Mock(side_effect=bk.BuildError("not installed"))
        with self.assertRaisesRegex(hr.HostRustError, "installation is disabled"):
            self.discover(selection="absent-nightly", run=run)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][1:4], ["which", "--toolchain", "absent-nightly"])

    def test_missing_manager_does_not_bootstrap_rustup(self):
        self.native_tools()
        with self.assertRaisesRegex(hr.HostRustError, "existing rustup"):
            self.discover(selection="nightly")

    def test_absent_host_tools_fail_without_subprocess(self):
        with self.assertRaisesRegex(hr.HostRustError, "Host rustc not found"):
            self.discover()

    def test_custom_cargo_home_bin_fallback(self):
        expected = self.native_tools(Path(self.env["CARGO_HOME"]) / "bin")
        self.assertEqual(self.discover(), expected)

    def test_default_home_bin_fallback(self):
        expected = self.native_tools(Path(self.env["HOME"]) / ".cargo/bin")
        self.assertEqual(self.discover(), expected)

    def test_non_executable_binary_is_not_accepted(self):
        tools = self.native_tools()
        Path(tools["cargo"]).chmod(0o644)
        with self.assertRaisesRegex(hr.HostRustError, "Host cargo not found"):
            self.discover()

    def test_explicit_native_paths_with_spaces(self):
        expected = self.native_tools(self.root / "some installed rust/bin")
        self.assertEqual(self.discover(overrides=expected), expected)

    def test_invalid_explicit_path_does_not_fall_back_to_other_rust(self):
        self.native_tools()
        with self.assertRaisesRegex(hr.HostRustError, "Host rustc not found"):
            self.discover(overrides={"rustc": "/does-not-exist/rustc"})

    def test_relative_explicit_paths_are_based_on_project_root(self):
        expected = self.native_tools()
        paths = {name: str(Path(value).relative_to(self.root)) for name, value in expected.items()}
        self.assertEqual(self.discover(overrides=paths), expected)

    def test_explicit_paths_and_named_toolchain_are_ambiguous(self):
        expected = self.native_tools()
        with self.assertRaisesRegex(hr.HostRustError, "do not combine"):
            self.discover(selection="nightly", overrides=expected)

    def test_standard_tool_environment_and_host_precedence(self):
        cfg = bk.Config.from_env({"RUSTC": "/host/rustc", "CARGO": "/host/cargo", "RUSTDOC": "/host/rustdoc"})
        self.assertEqual((cfg.host_rustc, cfg.host_cargo, cfg.host_rustdoc),
                         ("/host/rustc", "/host/cargo", "/host/rustdoc"))
        cfg = bk.Config.from_env({"RUSTC": "/ignored", "HOST_RUSTC": "/chosen"})
        self.assertEqual(cfg.host_rustc, "/chosen")

    def test_bad_toolchain_names_rejected_before_lookup(self):
        for name in ("", "--install", "nightly;touch /bad", "../rust", "nightly\nother"):
            with self.subTest(name=name), self.assertRaises(bk.BuildError):
                bk.Config.from_env({"TOOLCHAIN": name})

    def test_legacy_nightly_selection_is_ignored(self):
        (self.root / "toolchain-selection.json").write_text('{"resolved_toolchain":"nightly-2099-01-01"}')
        builder = bk.Builder(self.root, bk.Config.from_env({}))
        self.assertEqual(builder.effective_toolchain(), "host")
        self.assertNotIn("RUSTUP_TOOLCHAIN", {k: v for k, v in builder.environment().items()
                                           if k not in os.environ})

    def test_environment_does_not_invent_host_toolchain_override(self):
        with patch.dict(os.environ, self.env, clear=True):
            builder = bk.Builder(self.root, bk.Config.from_env({}))
            result = builder.environment()
            self.assertEqual(result["RUSTUP_AUTO_INSTALL"], "0")
            self.assertNotIn("RUSTUP_TOOLCHAIN", result)
            self.assertEqual(dict(os.environ), self.env)

    def test_default_cargo_home_is_host_home(self):
        env = {"HOME": self.env["HOME"], "PATH": self.env["PATH"]}
        with patch.dict(os.environ, env, clear=True):
            builder = bk.Builder(self.root, bk.Config.from_env({}))
        self.assertEqual(builder.cargo_home, Path(env["HOME"]) / ".cargo")

    def test_symlinked_work_directory_is_refused(self):
        (self.root / ".work").symlink_to(self.env["CARGO_HOME"])
        with self.assertRaisesRegex(bk.BuildError, "symlinked .work"):
            bk.Builder(self.root, bk.Config.from_env({}))

    def test_update_toolchain_target_cannot_call_any_external_command(self):
        builder = bk.Builder(self.root, bk.Config.from_env({}))
        with patch.object(bk, "run") as run, self.assertRaisesRegex(bk.BuildError, "disabled"):
            builder.update_toolchain()
        run.assert_not_called()

    def test_update_rustup_target_cannot_call_any_external_command(self):
        with patch.object(bk, "ROOT", self.root), patch.object(sys, "argv", ["build.py", "update-rustup"]), \
             patch.object(bk, "run") as run, self.assertRaisesRegex(bk.BuildError, "disabled"):
            bk.main()
        run.assert_not_called()

    def test_latest_has_no_apt_or_rust_installer_path(self):
        builder = bk.Builder(self.root, bk.Config.from_env({}))
        bk.write_json(self.root / "toolchain.lock.json", {"policy": "host-installed-only"})
        with patch.object(builder, "assert_build_user"), patch.object(bk.debian, "require_forky"), \
             patch.object(builder, "tools"), patch.object(builder, "fetch"), \
             patch.object(builder, "update_dependencies"), patch.object(builder, "doctor"), \
             patch.object(builder, "verify_source", return_value={}), \
             patch.object(builder, "verify_dependency_lock", return_value={}), \
             patch.object(bk.debian, "installed_versions", return_value={}), \
             patch.object(builder, "package") as package, \
             patch.object(builder, "update_toolchain") as update, \
             patch.object(bk.debian, "install_dependencies") as apt:
            builder.newest()
        apt.assert_not_called()
        update.assert_not_called()
        package.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
