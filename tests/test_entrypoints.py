# SPDX-License-Identifier: MIT
"""Regressions for the actual distributed command entrypoints and missing imports."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build as bk


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "kit directory with spaces"
        bk.Builder(ROOT, bk.Config.from_env({})).copy_kit(self.root)

    def run_command(self, argv, **extra_env):
        env = dict(os.environ, **extra_env)
        return subprocess.run(argv, cwd=self.root, env=env, text=True,
                              capture_output=True, timeout=30)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_direct_isolated_python_loads_bundled_helpers(self):
        result = self.run_command([sys.executable, "-I", "-B", "scripts/build.py", "help"])
        self.assert_success(result)
        self.assertIn("make package", result.stdout)

    def test_direct_safe_path_with_conflicting_external_modules(self):
        poison = Path(self.temp.name) / "foreign python packages"
        poison.mkdir()
        for module in ("debian", "latest"):
            (poison / (module + ".py")).write_text('raise RuntimeError("foreign module imported")\n')
        result = self.run_command([sys.executable, "-B", "scripts/build.py", "help"],
                                  PYTHONSAFEPATH="1", PYTHONPATH=str(poison))
        self.assert_success(result)

    def test_make_ignores_broken_pythonhome_and_pythonpath(self):
        result = self.run_command(["make", "--no-print-directory", "help"],
                                  PYTHONSAFEPATH="1", PYTHONHOME="/nonexistent-python-home",
                                  PYTHONPATH="/nonexistent-python-packages")
        self.assert_success(result)

    def test_make_lint_works_from_an_extracted_style_tree(self):
        self.assert_success(self.run_command(["make", "--no-print-directory", "lint"],
                                            PYTHONSAFEPATH="1"))

    def test_missing_latest_reports_incomplete_archive_not_pip_dependency(self):
        (self.root / "scripts/latest.py").unlink()
        result = self.run_command(["make", "--no-print-directory", "help"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Incomplete build kit", result.stderr)
        self.assertIn("latest.py", result.stderr)
        self.assertIn("do not pip-install", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_debian_reports_incomplete_archive(self):
        (self.root / "scripts/debian.py").unlink()
        result = self.run_command([sys.executable, "-I", "scripts/build.py", "help"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Incomplete build kit", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_bare_make_selects_package_not_help(self):
        result = self.run_command(["make", "--no-print-directory", "--dry-run"])
        self.assert_success(result)
        self.assertIn("scripts/build.py package", result.stdout)

    def test_offline_make_package_starts_without_import_error(self):
        result = self.run_command(["make", "--no-print-directory", "package", "OFFLINE=1"],
                                  ALLOW_ROOT_BUILD="1", PYTHONSAFEPATH="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires an existing locked source tree", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_make_package_uses_one_driver_process(self):
        result = self.run_command(["make", "--no-print-directory", "--dry-run", "package"])
        self.assert_success(result)
        self.assertEqual(result.stdout.count("scripts/build.py package"), 1)


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_online_package_resolves_and_builds_in_one_call(self):
        with patch.object(bk, "ROOT", self.root), patch.dict(os.environ, {"OFFLINE": "0"}), \
             patch.object(sys, "argv", ["build.py", "package"]), \
             patch.object(bk.Builder, "newest") as newest:
            self.assertEqual(bk.main(), 0)
            newest.assert_called_once_with()

    def test_offline_package_skips_all_updates(self):
        with patch.object(bk, "ROOT", self.root), patch.dict(os.environ, {"OFFLINE": "1"}), \
             patch.object(sys, "argv", ["build.py", "package"]), \
             patch.object(bk.Builder, "newest") as newest, \
             patch.object(bk.Builder, "package") as package:
            self.assertEqual(bk.main(), 0)
            newest.assert_not_called()
            package.assert_called_once_with()

    def test_rebuild_uses_existing_locks(self):
        with patch.object(bk, "ROOT", self.root), patch.object(sys, "argv", ["build.py", "rebuild"]), \
             patch.object(bk.Builder, "newest") as newest, \
             patch.object(bk.Builder, "package") as package:
            self.assertEqual(bk.main(), 0)
            newest.assert_not_called()
            package.assert_called_once_with()

    def test_old_latest_commands_remain_supported(self):
        for action, complete in (("latest", False), ("latest-complete", True)):
            with self.subTest(action=action), patch.object(bk, "ROOT", self.root), \
                 patch.object(sys, "argv", ["build.py", action]), \
                 patch.object(bk.Builder, "newest") as newest:
                self.assertEqual(bk.main(), 0)
                newest.assert_called_once_with(complete=complete)


class RustupPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def tool(self, home):
        binary = home / "bin/rustup"
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        return binary

    def test_existing_home_install_needs_no_path_export(self):
        binary = self.tool(self.home / ".cargo")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home)}
        result = bk.rustup_environment(env)
        self.assertEqual(shutil.which("rustup", path=result["PATH"]), str(binary))
        self.assertEqual(env["PATH"], "/usr/bin:/bin")

    def test_custom_cargo_home_install_is_discovered(self):
        cargo = self.home / "custom rust install"
        binary = self.tool(cargo)
        result = bk.rustup_environment({"PATH": "/usr/bin:/bin", "HOME": str(self.home),
                                       "CARGO_HOME": str(cargo)})
        self.assertEqual(shutil.which("rustup", path=result["PATH"]), str(binary))

    def test_existing_path_install_takes_precedence(self):
        first = self.tool(self.home / "preferred")
        self.tool(self.home / ".cargo")
        env = {"PATH": str(first.parent) + ":/usr/bin", "HOME": str(self.home)}
        self.assertEqual(bk.rustup_environment(env), env)

    def test_non_executable_rustup_is_not_selected(self):
        binary = self.tool(self.home / ".cargo")
        binary.chmod(0o644)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home)}
        self.assertEqual(bk.rustup_environment(env), env)


class PrivilegePromptTests(unittest.TestCase):
    def test_sudo_authenticates_visibly_before_logged_apt_commands(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv == ["dpkg", "--print-architecture"]:
                return "amd64\n"
            return ""
        with tempfile.TemporaryDirectory() as temp:
            plan = {"indexes": [], "packages": [{"package": "gcc", "version": "1.1-1"}]}
            with patch.object(bk.debian, "require_forky"), \
                 patch.object(bk.debian, "dependency_plan", return_value=plan), \
                 patch.object(bk.debian, "installed_versions", return_value={"gcc": "1.1-1"}), \
                 patch.object(os, "geteuid", return_value=1000):
                bk.debian.install_dependencies(Path(temp), "build", runner, lambda *a: None)
        self.assertEqual(calls[0][0], ["sudo", "-v"])
        self.assertTrue(calls[0][1]["interactive"])
        elevated = [argv for argv, _ in calls[1:] if argv[0] == "sudo"]
        self.assertEqual(len(elevated), 2)
        self.assertTrue(all(argv[:3] == ["sudo", "-n", "apt-get"] for argv in elevated))


if __name__ == "__main__":
    unittest.main()
