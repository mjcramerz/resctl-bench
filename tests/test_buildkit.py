# SPDX-License-Identifier: MIT
"""Tests use fake host Rust/Cargo plus real Git, GCC ELF, strip and objcopy.

These validate orchestration and packaging, NOT upstream Rust compilation.
No test needs network access, root, systemd, cgroup writes or an NVMe device.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build as bk
import install as installer


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    return subprocess.check_output(["git", "-C", str(repo), *args], env=env, text=True,
                                   stderr=subprocess.DEVNULL).strip()


class ConfigTests(unittest.TestCase):
    def test_native_x86_flags(self):
        cfg = bk.Config.from_env({"JOBS": "2"})
        rust, c, _ = bk.compilation_flags(cfg, "x86_64-unknown-linux-gnu", Path("/tmp/project"), Path("/tmp/cargo"))
        self.assertIn("-Ctarget-cpu=native", rust)
        self.assertIn("-march=native", c)
        self.assertIn("-mtune=native", c)
        self.assertEqual(cfg.binaries, bk.BASE_BINS + ("resctl-demo",))

    def test_native_arm_flags(self):
        cfg = bk.Config.from_env({})
        _, c, _ = bk.compilation_flags(cfg, "aarch64-unknown-linux-gnu", Path("/tmp/project"), Path("/tmp/cargo"))
        self.assertIn("-mcpu=native", c)
        self.assertNotIn("-march=native", c)

    def test_portable_has_no_native_options(self):
        cfg = bk.Config.from_env({"TUNE": "portable", "WITH_DEMO": "0"})
        rust, c, _ = bk.compilation_flags(cfg, "x86_64-unknown-linux-gnu", Path("/a"), Path("/b"))
        self.assertFalse(any("native" in flag for flag in rust + c))
        self.assertEqual(cfg.binaries, bk.BASE_BINS)

    def test_invalid_config_rejected(self):
        for env in ({"JOBS": "0"}, {"JOBS": "-4"}, {"JOBS": "NaN"}, {"WITH_DEMO": "yes"},
                    {"TUNE": "fast"}, {"LTO": "junk"}, {"UPSTREAM_REF": "--upload-pack=x"},
                    {"UPSTREAM_REF": "../../x"}, {"UPSTREAM_URL": "https://user:secret@example.org/repo.git"}):
            with self.subTest(env=env), self.assertRaises(bk.BuildError):
                bk.Config.from_env(env)

    def test_cross_target_rejected(self):
        with self.assertRaises(bk.BuildError):
            bk.compilation_flags(bk.Config.from_env({}), "x86_64-unknown-linux-musl", Path("/a"), Path("/b"))

    def test_extra_flags_are_tokenized_not_executed(self):
        cfg = bk.Config.from_env({"EXTRA_RUSTFLAGS": "--cfg 'some_value=\"with space\"'"})
        self.assertEqual(cfg.extra_rust, ("--cfg", 'some_value="with space"'))

    def test_auto_jobs_positive(self):
        self.assertGreaterEqual(bk.auto_jobs(), 1)

    def test_root_guard(self):
        with tempfile.TemporaryDirectory() as temp, patch("os.geteuid", return_value=0):
            builder = bk.Builder(Path(temp), bk.Config.from_env({}))
            with patch.dict(os.environ, {"ALLOW_ROOT_BUILD": "0"}):
                with self.assertRaises(bk.BuildError):
                    builder.assert_build_user()


class ArchiveTests(unittest.TestCase):
    def test_deterministic_envelope_and_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tree = root / "bundle"
            tree.mkdir()
            (tree / "text").write_text("hello\n")
            first, second = root / "a.tar.gz", root / "b.tar.gz"
            bk.make_archive(tree, first, 1700000000)
            os.utime(tree / "text", (1800000000, 1800000000))
            bk.make_archive(tree, second, 1700000000)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with tarfile.open(first) as tar:
                for info in tar.getmembers():
                    self.assertEqual((info.uid, info.gid, info.mtime), (0, 0, 1700000000))
                    self.assertFalse(info.name.startswith("/"))

    def test_escape_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "bad").symlink_to("/etc/passwd")
            with self.assertRaises(bk.BuildError):
                bk.file_manifest(root)

    def test_unsafe_relative_paths(self):
        for name in ("/etc/passwd", "../bad", "foo/../../bad", "x\ny", "x\\y"):
            with self.subTest(name=name), self.assertRaises(bk.BuildError):
                bk.safe_relative(name)


FAKE_TOOL = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
p = pathlib.Path
name = p(sys.argv[0]).name
args = sys.argv[1:]
if name in ('rustup', 'sudo', 'apt-get'):
    with open(os.environ['FIXTURE_LOG'],'a') as f:
        f.write(json.dumps({'forbidden':name,'args':args})+'\n')
    sys.exit('forbidden installer/manager invocation: '+name+' '+repr(args))
if name in ('rustc', 'cargo', 'rustdoc') and os.environ.get('RUSTUP_AUTO_INSTALL') != '0':
    sys.exit('automatic Rust installation was not disabled')
if name == 'rustdoc':
    print('rustdoc fixture'); sys.exit(0)
if name == 'rustc':
    if '-vV' in args:
        print('rustc 1.95.0 (fixture)\nbinary: rustc\ncommit-hash: ffffffffffffffffffffffffffffffffffffffff\ncommit-date: 2026-01-01\nhost: x86_64-unknown-linux-gnu\nrelease: 1.95.0\nLLVM version: 21.0.0')
    elif '--print' in args:
        print('target_arch="x86_64"\ntarget_feature="sse2"')
    elif '-o' in args:
        shutil.copyfile(os.environ['FIXTURE_ELF'], args[args.index('-o')+1])
        p(args[args.index('-o')+1]).chmod(0o755)
    else:
        sys.exit('unexpected rustc invocation: '+repr(args))
    sys.exit(0)
if args == ['--version']:
    print(os.environ.get('FIXTURE_CARGO_VERSION','cargo 1.95.0 (fixture)')); sys.exit(0)
while args[:1] == ['--config']:
    args = args[2:]
command = args[0]
with open(os.environ['FIXTURE_LOG'],'a') as f:
    f.write(json.dumps({'args':sys.argv[1:], 'command':command,
       'rustflags':os.environ.get('CARGO_ENCODED_RUSTFLAGS'),
       'cflags':os.environ.get('CFLAGS'), 'panic':os.environ.get('CARGO_PROFILE_RELEASE_PANIC'),
       'lto':os.environ.get('CARGO_PROFILE_RELEASE_LTO'), 'target':os.environ.get('CARGO_TARGET_DIR'),
       'rustc':os.environ.get('RUSTC'), 'cargo':os.environ.get('CARGO'),
       'rustup_auto_install':os.environ.get('RUSTUP_AUTO_INSTALL'),
       'cargo_home':os.environ.get('CARGO_HOME'),
       'build_target_dir':os.environ.get('CARGO_BUILD_TARGET_DIR'),
       'build_build_dir':os.environ.get('CARGO_BUILD_BUILD_DIR'),
       'wrapper':os.environ.get('RUSTC_WRAPPER'),
       'workspace_wrapper':os.environ.get('RUSTC_WORKSPACE_WRAPPER'),
       'ambient_rustflags':os.environ.get('RUSTFLAGS'),
       'bootstrap':os.environ.get('RUSTC_BOOTSTRAP'),
       'build_target':os.environ.get('CARGO_BUILD_TARGET')})+'\n')
manifest = p(args[args.index('--manifest-path')+1])
source = manifest.parent
if command == 'build':
    if os.environ.get('FIXTURE_FAIL') == '1':
        print('simulated Cargo compilation failure',file=sys.stderr); sys.exit(9)
    host = args[args.index('--target')+1]
    target = p(os.environ['CARGO_TARGET_DIR']) / host / 'release'
    target.mkdir(parents=True,exist_ok=True)
    for idx,arg in enumerate(args):
        if arg == '-p':
            out = target / args[idx+1]
            shutil.copyfile(os.environ['FIXTURE_ELF'],out); out.chmod(0o755)
    print('Synthetic build completed; not upstream Rust',file=sys.stderr)
elif command == 'metadata':
    packages=[]
    for binary in ('resctl-bench','rd-agent','rd-hashd','resctl-demo'):
        packages.append({'name':binary,'version':'0.1.0','id':binary+' 0.1.0 (fixture)',
                         'manifest_path':str(source/binary/'Cargo.toml'),'license':'MIT','source':None})
    dep = p(os.environ['CARGO_HOME'])/'fixture-dependency'
    dep.mkdir(parents=True,exist_ok=True)
    (dep/'LICENSE').write_text('Fixture dependency license\n')
    (dep/'Cargo.toml').write_text('[package]\nname="fixture-dep"\nversion="1.0.0"\n')
    packages.append({'name':'fixture-dep','version':'1.0.0','id':'fixture-dep 1.0.0',
                     'manifest_path':str(dep/'Cargo.toml'),'license':'MIT','source':'registry+fixture'})
    print(json.dumps({'packages':packages,'workspace_members':[q['id'] for q in packages[:4]]}))
elif command == 'tree':
    print('fixture-dep v1.0.0 (synthetic fixture, not real Cargo resolution)')
elif command == 'vendor':
    target=p(args[-1]); crate=target/'fixture-dep-1.0.0'; crate.mkdir(parents=True)
    (crate/'Cargo.toml').write_text('[package]\nname="fixture-dep"\nversion="1.0.0"\n')
    (crate/'LICENSE').write_text('Fixture MIT license\n')
    print('[source.crates-io]\nreplace-with = "vendored-sources"\n[source.vendored-sources]\ndirectory = '+json.dumps(str(target)))
elif command == 'update':
    if os.environ.get('FIXTURE_FAIL_UPDATE') == '1':
        sys.exit('simulated update failure')
    (source/'Cargo.lock').write_text('# updated synthetic fixture\nversion = 4\n')
    if os.environ.get('FIXTURE_UPDATE_TAMPER') == '1':
        (source/'README.md').write_text('illegal resolver mutation')
elif command in ('check','test','fetch'):
    if command == 'test' and any(x in args for x in ('misc::support_tests::', 'storage_info::source_resolution_tests::')):
        print('SYNTHETIC Cargo fixture; no Rust tests executed')
        n = 10 if 'misc::support_tests::' in args else 8
        print(f'test result: ok. {n} passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;')
else:
    sys.exit('unexpected cargo command: '+repr(args))
'''


@unittest.skipUnless(all(shutil.which(name) for name in ("git", "cc", "readelf", "objcopy", "strip", "pkg-config", "c++")),
                     "Integration fixtures require Git, a C toolchain and binutils")
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_dir = tempfile.TemporaryDirectory()
        root = Path(cls.seed_dir.name)
        c = root / "fixture.c"
        # Synthetic executable exports the reviewed fixture bytes so real
        # Make subprocess tests exercise the acceptance gate. This is C, NOT
        # rd-agent or a Rust compilation; the fixture is never distributed.
        bodies = [(name, (ROOT / "upstream/rd-agent/src/misc" / name).read_text())
                  for name in bk.runtime_support.FILES]
        declarations = ",\n".join("{" + json.dumps(name) + "," + json.dumps(body) + "}" for name, body in bodies)
        c.write_text('''#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <limits.h>
struct asset { const char *name; const char *body; };
static const struct asset assets[] = {''' + declarations + '''};
int main(int argc, char **argv) {
  if (argc == 3 && strcmp(argv[1], "--export-support") == 0) {
    if (mkdir(argv[2], 0700) != 0) return 2;
    for (unsigned int i = 0; i < sizeof(assets)/sizeof(assets[0]); i++) {
      char path[PATH_MAX];
      if (snprintf(path, sizeof(path), "%s/%s", argv[2], assets[i].name) >= PATH_MAX) return 3;
      FILE *out = fopen(path, "wx");
      if (!out) return 4;
      if (fputs(assets[i].body, out) < 0 || fclose(out) != 0 || chmod(path, 0755) != 0) return 5;
    }
  }
  puts("fixture 0.1.0; not resctl-bench or Rust"); return 0;
}
''')
        cls.elf = root / "fixture"
        subprocess.run(["cc", "-g", "-O0", "-fPIE", "-pie", "-Wl,-z,relro,-z,now", str(c), "-o", str(cls.elf)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.seed_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "kit"
        self.root.mkdir()
        for name in bk.KIT_ITEMS:
            src, dest = ROOT / name, self.root / name
            if src.is_dir():
                shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copyfile(src, dest)
        self.remote = base / "remote"
        self.remote.mkdir()
        git(self.remote, "init", "-b", "main")
        (self.remote / "Cargo.toml").write_text('[workspace]\nmembers=["resctl-bench","rd-agent","rd-hashd","resctl-demo"]\n')
        (self.remote / "Cargo.lock").write_text('# fixture, NOT a real dependency graph\nversion = 3\n')
        (self.remote / "README.md").write_text("Fixture repository.\n")
        (self.remote / "LICENSE").write_text("MIT fixture\n")
        for binary in bk.BASE_BINS + ("resctl-demo",):
            crate = self.remote / binary
            (crate / "src").mkdir(parents=True)
            (crate / "Cargo.toml").write_text(f'[package]\nname="{binary}"\nversion="0.1.0"\nedition="2021"\n')
            (crate / "src/main.rs").write_text('fn main() {}\n')
        shutil.copytree(ROOT / "upstream/rd-agent/src/misc", self.remote / "rd-agent/src/misc")
        (self.remote / "resctl-bench/doc").mkdir()
        (self.remote / "resctl-bench/doc/common.md").write_text("Fixture documentation\n")
        git(self.remote, "add", ".")
        git(self.remote, "commit", "-m", "fixture initial")
        fakebin = base / "fakebin"
        fakebin.mkdir()
        for tool in ("cargo", "rustc", "rustdoc", "rustup", "sudo", "apt-get"):
            (fakebin / tool).write_text(FAKE_TOOL.replace("#!/usr/bin/env python3", "#!" + sys.executable))
            (fakebin / tool).chmod(0o755)
        self.log = base / "commands.jsonl"
        self.log.touch()
        self.env = patch.dict(os.environ, {"PATH": str(fakebin) + ":" + os.environ["PATH"],
                               "ALLOW_ROOT_BUILD": "1", "ALLOW_UNSUPPORTED_DEBIAN": "1", "FIXTURE_ELF": str(self.elf),
                               "FIXTURE_LOG": str(self.log), "CARGO_HOME": str(base / "cargo-home")})
        self.env.start()
        self.cfg = bk.Config.from_env({"UPSTREAM_URL": str(self.remote), "JOBS": "1"})
        self.builder = bk.Builder(self.root, self.cfg)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_complete_snapshot_contains_all_source_and_needs_no_rust(self):
        self.builder.fetch()
        with patch.object(self.builder, "tools", side_effect=AssertionError("snapshot must not need Rust")):
            archive = self.builder.snapshot_dist()
        unpack = Path(self.temp.name) / "snapshot extraction"
        unpack.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(unpack, filter="data")
        kit = next(unpack.iterdir())
        self.assertTrue((kit / "config.mk").is_file())
        self.assertTrue((kit / "scripts/host_rust.py").is_file())
        self.assertFalse((kit / "scripts/latest.py").exists())
        self.assertFalse((kit / "toolchain-selection.json").exists())
        info = bk.read_json(kit / "source-snapshot.json")
        self.assertFalse(info["vendored_dependencies"])
        self.assertFalse(info["contains_compiled_binaries"])
        self.assertEqual(self.builder.verify_source(), bk.Builder(kit, self.cfg).verify_source())
        for binary in self.cfg.binaries:
            self.assertTrue((kit / "upstream" / binary / "src/main.rs").is_file())
        result = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=kit, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), [])

    def test_source_pin_does_not_follow_branch(self):
        first = self.builder.fetch()
        (self.remote / "README.md").write_text("new revision\n")
        git(self.remote, "add", ".")
        git(self.remote, "commit", "-m", "advance branch")
        self.assertEqual(first["commit"], self.builder.fetch()["commit"])
        self.assertNotEqual(first["commit"], self.builder.fetch(update=True)["commit"])

    def test_source_edit_is_rejected(self):
        self.builder.fetch()
        (self.root / "upstream/Cargo.lock").write_text("tampered\n")
        with self.assertRaises(bk.BuildError):
            self.builder.fetch()

    def test_missing_worktree_restores_locked_sha(self):
        first = self.builder.fetch()
        shutil.rmtree(self.builder.src)
        self.assertEqual(first, self.builder.fetch())

    def test_full_pipeline_real_elf_debug_archive_install(self):
        archive = self.builder.package()
        last = bk.read_json(self.builder.work / "last-package.json")
        stage = Path(last["stage"])
        files = installer.verify(stage)
        for binary in self.cfg.binaries:
            self.assertIn(f"bin/{binary}", files)
            self.assertIn(f"bin/.debug/{binary}.debug", files)
            sections = subprocess.check_output(["readelf", "-S", str(stage / "bin" / binary)], text=True)
            self.assertIn(".gnu_debuglink", sections)
        with tarfile.open(archive) as tar:
            self.assertTrue(any(item.name.endswith("Cargo.lock") for item in tar.getmembers()))
        info = bk.read_json(stage / "share/resctl-bench/build/build-info.json")
        self.assertEqual(info["profile"]["CARGO_PROFILE_RELEASE_LTO"], "thin")
        self.assertEqual(info["profile"]["CARGO_PROFILE_RELEASE_PANIC"], "unwind")
        self.assertIn("-Ctarget-cpu=native", info["rustflags"])
        builds = [c for c in self.calls() if c["command"] == "build"]
        self.assertIn("--locked", builds[0]["args"])
        self.assertIn("--target", builds[0]["args"])
        prefix = Path(self.temp.name) / "install-prefix"
        installer.install(stage, prefix)
        self.assertTrue((prefix / "bin/resctl-bench").is_file())
        installer.uninstall(prefix)
        self.assertFalse((prefix / "bin/resctl-bench").exists())

    def test_failed_build_invalidates_success_record(self):
        _, out = self.builder.build()
        self.assertTrue((out / "result.json").exists())
        with patch.dict(os.environ, {"FIXTURE_FAIL": "1"}), self.assertRaises(bk.BuildError):
            self.builder.build()
        self.assertFalse((out / "result.json").exists())

    def test_host_compiler_change_records_new_identity_without_install(self):
        self.builder.tools()
        before = bk.read_json(self.root / "toolchain.lock.json")
        with patch.dict(os.environ, {"FIXTURE_CARGO_VERSION": "cargo CHANGED"}):
            tools = bk.Builder(self.root, self.cfg).tools()
            self.assertEqual(tools["cargo_version"], "cargo CHANGED")
        after = bk.read_json(self.root / "toolchain.lock.json")
        self.assertNotEqual(before, after)
        self.assertEqual(after["policy"], "host-installed-only")
        self.assertFalse(any("forbidden" in row for row in self.calls()))

    def test_vendor_tampering_is_rejected(self):
        self.builder.vendor()
        self.builder.verify_vendor()
        (self.builder.vendor_dir / "crates/fixture-dep-1.0.0/LICENSE").write_text("tampered\n")
        with self.assertRaises(bk.BuildError):
            self.builder.verify_vendor()

    def test_source_dist_relocates_with_true_git_identity_and_offline_flags(self):
        archive = self.builder.source_dist()
        unpack = Path(self.temp.name) / "unpacked"
        unpack.mkdir()
        with tarfile.open(archive) as tar:
            # Archive is generated by this test and has already been validated.
            tar.extractall(unpack, filter="data")
        kit = next(unpack.iterdir())
        offline = bk.Builder(kit, dataclasses.replace(self.cfg, offline=True))
        self.assertEqual(self.builder.verify_source()["commit"], offline.verify_source()["commit"])
        offline.build()
        configs = list(offline.work.glob("vendor-config.toml"))
        self.assertEqual(len(configs), 1)
        self.assertIn(str(kit / "vendor/crates"), configs[0].read_text())
        build_call = [c for c in self.calls() if c["command"] == "build"][-1]
        self.assertIn("--frozen", build_call["args"])

    def test_test_compile_never_executes_tests(self):
        self.builder.build("test-compile")
        call = [c for c in self.calls() if c["command"] == "test"][0]
        self.assertIn("--no-run", call["args"])

    def test_native_portable_cache_separation(self):
        _, first = self.builder.cargo_context()
        other = bk.Builder(self.root, dataclasses.replace(self.cfg, tune="portable"))
        _, second = other.cargo_context()
        self.assertNotEqual(first["build_id"], second["build_id"])

    def test_bench_only_build_excludes_demo(self):
        builder = bk.Builder(self.root, dataclasses.replace(self.cfg, demo=False))
        settings, _ = builder.build()
        self.assertNotIn("resctl-demo", settings["binaries"])

    def test_offline_fails_without_source(self):
        builder = bk.Builder(self.root, dataclasses.replace(self.cfg, offline=True))
        with self.assertRaises(bk.BuildError):
            builder.fetch()

    def test_install_refuses_conflict_and_modified_uninstall(self):
        stage, _ = self.builder.stage()
        prefix = Path(self.temp.name) / "install"
        (prefix / "bin").mkdir(parents=True)
        target = prefix / "bin/resctl-bench"
        target.write_text("unrelated local program\n")
        with self.assertRaises(installer.InstallError):
            installer.install(stage, prefix)
        self.assertEqual(target.read_text(), "unrelated local program\n")
        installer.install(stage, prefix, force=True)
        target.write_text("local edits\n")
        with self.assertRaises(installer.InstallError):
            installer.uninstall(prefix)
        self.assertTrue((prefix / "bin/rd-agent").exists())

    def test_installer_rejects_symlink_destination(self):
        stage, _ = self.builder.stage()
        prefix = Path(self.temp.name) / "install"
        prefix.mkdir()
        (prefix / "bin").symlink_to(Path(self.temp.name) / "elsewhere")
        with self.assertRaises(installer.InstallError):
            installer.install(stage, prefix, force=True)

    def test_package_checksum_tamper_rejected(self):
        stage, _ = self.builder.stage()
        (stage / "README.md").write_text("tampered\n")
        with self.assertRaises(installer.InstallError):
            installer.verify(stage)

    def test_ambient_flags_are_scoped_away_without_rejection_or_parent_mutation(self):
        with patch.dict(os.environ, {"RUSTFLAGS": "-Ctarget-cpu=generic"}):
            before = dict(os.environ)
            self.builder.tools()
            env, info = self.builder.cargo_context()
            self.assertEqual(dict(os.environ), before)
            self.assertNotIn("RUSTFLAGS", env)
            self.assertNotIn("generic", env["CARGO_ENCODED_RUSTFLAGS"])
            self.assertIn("RUSTFLAGS", info["overridden_ambient_variables"])

    def test_probe_uses_configured_c_and_cpp_flags(self):
        self.builder.doctor()

    def test_dependency_refresh_preserves_upstream_and_records_diff(self):
        original = self.builder.fetch()
        before = (self.builder.src / "Cargo.lock").read_bytes()
        self.builder.update_dependencies()
        self.assertEqual((self.builder.src / "Cargo.lock").read_bytes(), before)
        self.assertEqual(original, self.builder.verify_source())
        info = self.builder.verify_dependency_lock()
        self.assertNotEqual(info["effective_lock_sha256"], original["cargo_lock_sha256"])
        effective = self.builder.effective_source()
        self.assertNotEqual(effective, self.builder.src)
        self.assertEqual(git(effective, "rev-parse", "HEAD"), original["commit"])
        self.assertIn("Cargo.lock", git(effective, "status", "--porcelain"))
        self.assertIn("upstream/Cargo.lock", (self.builder.dependency_dir / "Cargo.lock.diff").read_text())
        self.builder.build()
        call = [c for c in self.calls() if c["command"] == "build"][-1]
        self.assertIn(str(effective / "Cargo.toml"), call["args"])
        self.assertIn("--locked", call["args"])

    def test_dependency_update_rejects_changes_to_source_code(self):
        with patch.dict(os.environ, {"FIXTURE_UPDATE_TAMPER": "1"}), self.assertRaises(bk.BuildError):
            self.builder.update_dependencies()
        self.builder.verify_source()
        self.assertFalse(self.builder.dependency_dir.exists())

    def test_failed_dependency_update_retains_last_lock(self):
        self.builder.update_dependencies()
        previous = self.builder.verify_dependency_lock()
        with patch.dict(os.environ, {"FIXTURE_FAIL_UPDATE": "1"}), self.assertRaises(bk.BuildError):
            self.builder.update_dependencies()
        self.assertEqual(previous, self.builder.verify_dependency_lock())

    def test_dependency_lock_tampering_is_rejected(self):
        self.builder.update_dependencies()
        (self.builder.dependency_dir / "Cargo.lock").write_text("tampered")
        with self.assertRaises(bk.BuildError):
            self.builder.build()

    def test_effective_source_tampering_is_rejected(self):
        self.builder.update_dependencies()
        (self.builder.effective_source() / "resctl-bench/src/main.rs").write_text("tampered")
        with self.assertRaises(bk.BuildError):
            self.builder.effective_source()

    def test_source_update_retires_old_lock_and_vendor(self):
        self.builder.update_dependencies()
        self.builder.vendor()
        self.builder.fetch(update=True)
        self.assertFalse(self.builder.dependency_dir.exists())
        self.assertFalse(self.builder.vendor_dir.exists())
        self.assertTrue(list((self.builder.work / "retired").glob("dependency-lock-*/dependency-lock")))
        self.assertTrue(list((self.builder.work / "retired").glob("vendor-*/vendor")))

    def test_populated_archive_preserves_updated_lock_and_offline_relocation(self):
        self.builder.update_dependencies()
        original = self.builder.verify_dependency_lock()
        archive = self.builder.source_dist()
        unpack = Path(self.temp.name) / "updated-unpack"
        unpack.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(unpack, filter="data")
        kit = next(unpack.iterdir())
        offline = bk.Builder(kit, dataclasses.replace(self.cfg, offline=True))
        self.assertEqual(original, offline.verify_dependency_lock())
        offline.package()
        call = [c for c in self.calls() if c["command"] == "build"][-1]
        self.assertIn("--frozen", call["args"])
        self.assertIn("--config", call["args"])

    def test_failed_package_removes_old_success_pointer(self):
        self.builder.package()
        with patch.dict(os.environ, {"FIXTURE_FAIL": "1"}), self.assertRaises(bk.BuildError):
            self.builder.package()
        self.assertFalse((self.builder.work / "last-package.json").exists())
        self.assertFalse((self.builder.dist / "resctl-bench-latest.tar.gz").exists())
        self.assertFalse((self.builder.dist / "resctl-bench-latest.tar.gz.sha256").exists())

    def test_existing_global_and_ancestor_configs_are_preserved(self):
        cargo = self.builder.cargo_home
        home = Path(self.temp.name) / "sentinel-home"
        files = {
            cargo / "config.toml": b'[net]\nretry = 2\n',
            cargo / "config": b'# Legacy Cargo configuration remains untouched\n',
            home / ".rustup/settings.toml": b'default_toolchain = "host-choice"\n',
            home / ".profile": b'# keep shell configuration unchanged\n',
            self.root.parent / ".cargo/config.toml": b'[build]\nrustflags=["-Ctarget-cpu=generic"]\n',
            self.root / ".cargo/config.toml": b'[net]\nretry = 3\n',
        }
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
        with patch.dict(os.environ, {"HOME": str(home), "RUSTUP_AUTO_INSTALL": "1"}):
            self.builder.doctor()
            self.builder.update_dependencies()
            self.builder.build("check")
            self.builder.build("test-compile")
            self.builder.package()
            self.builder.source_dist()
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
        self.assertEqual(before, after)
        self.assertFalse(any("forbidden" in row for row in self.calls()))
        for row in self.calls():
            self.assertEqual(row["rustup_auto_install"], "0")
            self.assertEqual(row["cargo_home"], str(cargo))
            self.assertTrue(Path(row["rustc"]).is_absolute())
            self.assertTrue(Path(row["cargo"]).is_absolute())

    def test_wrong_architecture_elf_rejected(self):
        with self.assertRaises(bk.BuildError):
            bk.validate_elf(self.elf, "aarch64-unknown-linux-gnu")

    def test_elf_without_full_relro_rejected(self):
        out = Path(self.temp.name) / "unhardened"
        source = Path(self.temp.name) / "unhardened.c"
        source.write_text("int main(void) { return 0; }\n")
        subprocess.run(["cc", "-fPIE", "-pie", "-Wl,-z,lazy", str(source), "-o", str(out)], check=True)
        with self.assertRaises(bk.BuildError):
            bk.validate_elf(out, "x86_64-unknown-linux-gnu")

    def test_offline_dependency_update_rejected(self):
        builder = bk.Builder(self.root, dataclasses.replace(self.cfg, offline=True))
        with self.assertRaises(bk.BuildError):
            builder.update_dependencies()


    def test_extracted_archive_make_package_entrypoint_offline(self):
        """Real Makefile + Python subprocess + real ELF/archive; Cargo is a fixture."""
        archive = self.builder.source_dist()
        unpack = Path(self.temp.name) / "fresh extraction with spaces"
        unpack.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(unpack, filter="data")
        kit = next(unpack.iterdir())
        shared = Path(self.temp.name) / "shared cache must remain absent"
        env = dict(os.environ, PYTHONSAFEPATH="1", UPSTREAM_URL=str(self.remote),
                   CARGO_TARGET_DIR=str(shared), CARGO_BUILD_TARGET_DIR=str(shared / "final"),
                   CARGO_BUILD_BUILD_DIR=str(shared / "intermediate"))
        result = subprocess.run(
            ["make", "--no-print-directory", "-C", str(kit), "package", "verify", "OFFLINE=1"],
            env=env, text=True, capture_output=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(shared.exists())
        alias = kit / "dist/resctl-bench-latest.tar.gz"
        self.assertTrue(alias.is_file())
        self.assertTrue(alias.is_symlink())
        with tarfile.open(alias) as tar:
            names = tar.getnames()
            for binary in self.cfg.binaries:
                self.assertTrue(any(name.endswith("/bin/" + binary) for name in names))
        checksum = alias.with_name(alias.name + ".sha256").read_text().split()[0]
        self.assertEqual(checksum, bk.digest(alias))


    def test_online_make_package_never_invokes_apt_or_rustup_or_updates_crates(self):
        """Actual Make/main/package, with host Rust simulated and real ELF output."""
        env = dict(os.environ, UPSTREAM_URL=str(self.remote), PYTHONSAFEPATH="1")
        result = subprocess.run(
            ["make", "--no-print-directory", "-C", str(self.root), "package"],
            env=env, text=True, capture_output=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Binary tarball:", result.stdout)
        alias = self.root / "dist/resctl-bench-latest.tar.gz"
        self.assertTrue(alias.is_file())
        self.assertFalse(any("forbidden" in row for row in self.calls()))
        commands = [row["command"] for row in self.calls()]
        self.assertNotIn("update", commands)
        self.assertFalse((self.root / "dependency-lock").exists())
        with tarfile.open(alias) as tar:
            names = tar.getnames()
            for binary in self.cfg.binaries:
                self.assertTrue(any(name.endswith("/bin/" + binary) for name in names))


    def test_make_package_accepts_absolute_ambient_target_dir_and_preserves_shared_cache(self):
        shared = Path(self.temp.name) / "host shared target with spaces"
        shared.mkdir()
        sentinel = shared / "do-not-touch"
        sentinel.write_bytes(b"unrelated project's build cache\n")
        before = (bk.file_manifest(shared), sentinel.stat().st_mtime_ns)
        env = dict(os.environ, UPSTREAM_URL=str(self.remote), CARGO_TARGET_DIR=str(shared))
        result = subprocess.run(["make", "--no-print-directory", "-C", str(self.root), "package", "verify"],
                                env=env, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NOTE: Using project-local build settings", result.stderr)
        self.assertNotIn("ERROR: Ambient", result.stderr)
        self.assertEqual(before, (bk.file_manifest(shared), sentinel.stat().st_mtime_ns))
        row = [row for row in self.calls() if row.get("command") == "build"][-1]
        self.assertTrue(Path(row["target"]).is_relative_to(self.root / ".work/target"))
        self.assertEqual(row["target"], row["build_target_dir"])
        self.assertEqual(row["target"], row["build_build_dir"])
        self.assertEqual(row["args"][row["args"].index("--target-dir") + 1], row["target"])
        self.assertFalse(any("forbidden" in row for row in self.calls()))
        info = bk.read_json(Path(bk.read_json(self.builder.work / "last-package.json")["stage"])
                            / "share/resctl-bench/build/build-info.json")
        self.assertIn("CARGO_TARGET_DIR", info["overridden_ambient_variables"])
        self.assertEqual(info["cargo_target_dir"], row["target"])

    def test_make_entrypoints_accept_combined_host_overrides_without_touching_configs(self):
        shared = Path(self.temp.name) / "external shared build"
        home = Path(self.temp.name) / "sentinel-home"
        files = {
            shared / "existing-cache": b"keep external cache\n",
            home / ".profile": b"export CARGO_TARGET_DIR=/my/cache\n",
            home / ".bashrc": b"# preserve user shell configuration\n",
            home / ".rustup/settings.toml": b'default_toolchain = "existing-host"\n',
            self.builder.cargo_home / "config.toml": b'[build]\ntarget-dir = "/shared/target"\n[net]\nretry = 2\n',
            self.builder.cargo_home / "credentials.toml": b'[registry]\ntoken = "fixture-only"\n',
            self.root / ".cargo/config.toml": b'[build]\nbuild-dir = "/shared/intermediate"\n',
        }
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
        overrides = {
            "UPSTREAM_URL": str(self.remote), "HOME": str(home),
            "CARGO_TARGET_DIR": str(shared), "CARGO_BUILD_TARGET_DIR": str(shared / "final"),
            "CARGO_BUILD_BUILD_DIR": str(shared / "intermediate"),
            "CARGO_BUILD_TARGET": "wasm32-unknown-unknown", "RUSTFLAGS": "--invalid-host-flag",
            "CARGO_ENCODED_RUSTFLAGS": "--invalid-encoded-host-flag", "CARGO_BUILD_RUSTFLAGS": "--invalid",
            "RUSTC_WRAPPER": "/missing/host-wrapper", "RUSTC_WORKSPACE_WRAPPER": "/missing/workspace-wrapper",
            "CARGO_BUILD_RUSTC_WRAPPER": "/missing/alternate-wrapper", "RUSTC_BOOTSTRAP": "1",
            "CARGO_PROFILE_RELEASE_LTO": "invalid", "CARGO_PROFILE_RELEASE_STRIP": "symbols",
            "CARGO_PROFILE_RELEASE_PANIC": "abort", "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER": "/missing/linker",
            "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS": "--invalid-target-flag",
            "CFLAGS": "--invalid-cflag", "CXXFLAGS": "--invalid-cxxflag", "LDFLAGS": "--invalid-linkerflag",
            "CFLAGS_x86_64_unknown_linux_gnu": "--invalid-target-cflag", "HOST_CFLAGS": "--invalid-host-cflag",
            "AR": "/missing/archiver", "ARFLAGS": "--invalid-archiverflag", "CRATE_CC_NO_DEFAULTS": "1",
        }
        env = dict(os.environ, **overrides)
        result = subprocess.run(["make", "--no-print-directory", "-C", str(self.root), "doctor",
                                 "fetch-deps", "check", "test-compile", "package", "verify"],
                                env=env, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files})
        self.assertEqual(set(shared.iterdir()), {shared / "existing-cache"})
        calls = self.calls()
        self.assertFalse(any("forbidden" in row for row in calls))
        for row in calls:
            self.assertTrue(Path(row["target"]).is_relative_to(self.root / ".work"))
            self.assertEqual(row["target"], row["build_target_dir"])
            self.assertEqual(row["target"], row["build_build_dir"])
            self.assertEqual(row["wrapper"], "")
            self.assertEqual(row["workspace_wrapper"], "")
            self.assertIsNone(row["ambient_rustflags"])
            self.assertIsNone(row["bootstrap"])
            self.assertEqual(row["panic"], "unwind")
            self.assertEqual(row["lto"], "thin")
            self.assertEqual(row["build_target"], "x86_64-unknown-linux-gnu")

    def test_relative_ambient_target_dir_does_not_write_under_source(self):
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": "../unexpected output",
                                    "CARGO_BUILD_TARGET_DIR": "./unexpected-final",
                                    "CARGO_BUILD_BUILD_DIR": "./unexpected-intermediate"}):
            before = dict(os.environ)
            self.builder.package()
            self.assertEqual(dict(os.environ), before)
            self.builder.verify_source()
        self.assertFalse((self.root / "unexpected output").exists())
        self.assertFalse((self.builder.src / "unexpected-final").exists())
        self.assertFalse((self.builder.src / "unexpected-intermediate").exists())

    def test_dependency_update_and_vendor_do_not_write_in_shared_target(self):
        shared = Path(self.temp.name) / "never-created-external-target"
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": str(shared), "CARGO_BUILD_TARGET_DIR": str(shared),
                                    "CARGO_BUILD_BUILD_DIR": str(shared), "RUSTFLAGS": "--invalid-ambient"}):
            self.builder.update_dependencies()
            self.builder.vendor()
        self.assertFalse(shared.exists())
        for row in self.calls():
            self.assertEqual(row["target"], row["build_target_dir"])
            self.assertEqual(row["target"], row["build_build_dir"])
            self.assertTrue(Path(row["target"]).is_relative_to(self.builder.work))

    def test_explicit_kit_flags_work_with_inherited_flags(self):
        cfg = bk.Config.from_env({"UPSTREAM_URL": str(self.remote), "EXTRA_RUSTFLAGS": "--cfg kit_explicit",
                                  "EXTRA_CFLAGS": "-DKIT_EXPLICIT_C=1", "EXTRA_CXXFLAGS": "-DKIT_EXPLICIT_CXX=1"})
        builder = bk.Builder(self.root, cfg)
        with patch.dict(os.environ, {"RUSTFLAGS": "--ambient-wrong", "CFLAGS": "--ambient-wrong",
                                    "CXXFLAGS": "--ambient-wrong"}):
            env, _ = builder.cargo_context()
            self.assertIn("kit_explicit", env["CARGO_ENCODED_RUSTFLAGS"])
            self.assertIn("-DKIT_EXPLICIT_C=1", env["CFLAGS"])
            self.assertIn("-DKIT_EXPLICIT_CXX=1", env["CXXFLAGS"])
            for name in ("CARGO_ENCODED_RUSTFLAGS", "CFLAGS", "CXXFLAGS"):
                self.assertNotIn("--ambient-wrong", env[name])

    def test_ignored_host_values_do_not_change_build_cache_identity(self):
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": "/first/host/cache", "RUSTFLAGS": "--first-ignored"}):
            _, first = self.builder.cargo_context()
        with patch.dict(os.environ, {"CARGO_TARGET_DIR": "/second/host/cache", "RUSTFLAGS": "--second-ignored"}):
            _, second = self.builder.cargo_context()
        self.assertEqual(first["build_id"], second["build_id"])

    def test_clean_removes_only_local_work_not_inherited_shared_cache(self):
        shared = Path(self.temp.name) / "shared-clean-sentinel"
        shared.mkdir()
        sentinel = shared / "preserve-me"
        sentinel.write_text("unrelated build output\n")
        env = dict(os.environ, UPSTREAM_URL=str(self.remote), CARGO_TARGET_DIR=str(shared))
        result = subprocess.run(["make", "--no-print-directory", "-C", str(self.root), "package", "clean"],
                                env=env, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.builder.work.exists())
        self.assertEqual(sentinel.read_text(), "unrelated build output\n")



if __name__ == "__main__":
    unittest.main()
