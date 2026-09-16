# Build guide - repaired native source, build kit 2.3.0

## Mandatory native repair gates

`make package` uses actual host Cargo to compile the reviewed locked workspace;
then it runs the 10 rd-agent embedded-support tests and 8 rd-util findmnt-JSON
tests. It verifies exported helper bytes from the compiled agent before build
success and again after stripping. Results and logs are included in build
provenance. There is no fallback to the old binary or a successful source-only
check. See NATIVE-REPAIR.md for details and VALIDATION.md for what was possible
in the delivery environment. Build as an ordinary user; use sudo only for
explicit system/package changes and the benchmark launcher.

A source release hash check is not evidence of a successful native compile.
Host-only compilation and all dependencies still have to work on the build host.
`make doctor` checks real tools before the main build. No toolchain installation
or nightly fallback is performed. `make package` does not attach BPF or exercise
a disk; the explicit runtime probe and Lab handle those separate levels.


## Platform contract

This edition deliberately requires Debian Forky for APT transactions. It uses
`ID=debian` and `VERSION_CODENAME=forky`, not a hardcoded numeric VERSION_ID;
a testing installation may omit that field. Native amd64 and arm64 GNU targets
are supported. Musl, Windows, cross-compilation and arbitrary foreign sysroots
are rejected. The code is standard-library Python 3.11+ driven by GNU Make.

`ALLOW_UNSUPPORTED_DEBIAN=1` permits experimental compilation and fixture tests
on a different Debian environment. It NEVER allows the Forky APT installer to
run on Trixie, Bookworm or another distribution. `ALLOW_ROOT_BUILD=1` is solely
an explicit disposable-container override. Normal builds must be unprivileged.
Neither switch makes the host supported or establishes tested compatibility.

## Host-only builds and explicit refreshes

```sh
make doctor            # Probe already-installed host Rust/C/C++.
make package           # Build locked source; no APT, Rust update or cargo update.
make                   # Same as make package.
make test-runtime      # Run only the 18 safe native repair regressions.
make source-dist       # Vendor locked crates and produce a populated source tarball.
make rebuild           # Same locked build/package behavior as package.
make verify            # Check the last runtime archive and staged payload.
```

`TOOLCHAIN=host` is the default for every build. `make package` uses the bundled
source lock and Cargo.lock, and needs network only for uncached dependencies
(or an initial source fetch in a kit-only extraction). `OFFLINE=1` forbids Cargo
network access and requires existing sources and cached/vendored dependencies.
For this patched release, `latest`, `latest-complete` and `update-source` are
blocked: an automatic upstream refresh must not silently discard the repair.
Explicitly rebase and review a future patch rather than bypassing this guard. `UPSTREAM_URL`
defaults to the official repository; a custom URL is a trusted-input choice.
`UPSTREAM_REF` affects initial fetch or explicit source update. Afterwards the
full locked SHA is authoritative and source changes are rejected.

Each package attempt clears the previous success pointer/latest alias. Only
successful publication installs a new pointer. A later source-vendoring failure
does not invalidate an already successful binary archive. A failed compilation
does not silently retry with another compiler, unlocked dependencies or rewritten
source code. No command changes a global Rust/Cargo/shell configuration.

### Forky APT policy

`make deps` is explicit system maintenance, never called by package/latest. It performs `apt-get update --error-on=any`, then examines APT's Release
metadata and package versions. It accepts a `testing` source alias only while
that index says `o=Debian,n=forky`; it rejects Sid and other release indexes.
APT remains responsible for signature verification. Administrators must keep
secure sources and trust settings; the kit does not repair an insecure APT
configuration or add package keys/repositories.

Machine-parsed APT/dpkg commands use the C locale even in a localized shell.
Versions are compared with `dpkg --compare-versions`, including epochs and
Debian revisions. Exact package=version requests are generated. Current GCC
and optional LLVM implementation packages are followed from the unversioned
metapackages' dependencies, rather than baking a compiler major into the kit.
All packages listed in a simulated install/upgrade must also be found in the
accepted Forky indexes. Proposed removals and installed versions newer than
the selected Forky version are rejected. Both simulation and installation use
`--no-remove --no-install-recommends -t forky`; no downgrade, unauthenticated,
held-package bypass, or distribution upgrade flags are added.

`make deps-plan` only simulates with the CURRENT indexes; it does not claim
freshness or run `apt-get update`. Actual install plans, logs and verified
versions are recorded under `.work/apt-*.json` and `.work/logs/`.

For an unprivileged user, `sudo -v` authenticates with an inherited terminal
before APT output is captured. Subsequent APT commands use `sudo -n`, so a
password prompt cannot disappear into the log pipe. Only APT receives sudo.

The default compiler drivers are `/usr/bin/gcc` and `/usr/bin/g++`, avoiding
unreviewed alternatives such as a custom `cc` wrapper. `pkgconf`/`pkgconf-bin`
provide pkg-config. The kit never installs Debian rustc/cargo packages or provisions Rustup. A
suitable Rust/Cargo/rustdoc installation must already exist. The base workspace
does not require Python pip dependencies, ncurses, or all LLVM tools.
Optional `make deps-llvm` provisions Forky's clang/lld/llvm/libclang development
stack. Select it deliberately with `HOST_CC=/usr/bin/clang
HOST_CXX=/usr/bin/clang++`; there is no automatic GCC-to-Clang fallback.

`make deps-runtime` is separate because installing runtime packages can start
or change distro services via Debian maintainer scripts. It is not a read-only
check. Dependency transactions may install/upgrade required shared libraries;
review the printed plan and use normal system-maintenance precautions.

### Host Rust selection and non-mutation policy

The default discovery order for each tool is explicit `HOST_RUSTC`, `HOST_CARGO`,
`HOST_RUSTDOC`; the corresponding standard `RUSTC`, `CARGO`, `RUSTDOC` value;
PATH; then existing `$CARGO_HOME/bin` and `$HOME/.cargo/bin` directories.
Explicit paths are executable paths, not shell command strings. Paths containing
spaces are supported. A missing explicit path is an error, not a fallback to a
different compiler. Native/distro tools work without Rustup, even when another
Rustup installation also exists on the host.

Rustup symlink and hardlink proxies are detected before symlinks are resolved.
Only `rustup which [--toolchain NAME] rustc|cargo|rustdoc` queries are made;
`--install` is never passed. Queries run from the build-kit root, before entering
the upstream tree. The resulting concrete executable paths are then used by
Cargo, probes and build scripts. All build subprocesses receive
`RUSTUP_AUTO_INSTALL=0`. No Rust manifest download, installer, component/target
addition, self-update, default mutation or directory-override write exists in
the build driver. An already-installed `TOOLCHAIN=NAME` can be explicitly chosen;
it cannot be combined with explicit host tool paths. In host mode, the user's
existing `RUSTUP_TOOLCHAIN` is not replaced by the literal string `host`.

`toolchain.lock.json` schema 2 records the selected executable paths, rustc -vV,
and Cargo version. It does not pin the user's compiler or request installation.
A host upgrade changes the metadata and build identity. The old
`toolchain-selection.json` is ignored even when it names a missing nightly.
`make lock-toolchain` refreshes only this local record. `update-toolchain` and
`update-rustup` are intentionally disabled, including explicit invocations.
An insufficient or missing host compiler fails with no automatic upgrade,
nightly fallback, `RUSTC_BOOTSTRAP`, or `--ignore-rust-version` workaround.

Existing Cargo home and ancestor `.cargo/config`/`config.toml` files are trusted
read-only inputs. Their presence is no longer a build error. No global config
is copied, renamed, removed or rewritten. Direct config-file hashes (not file
contents or credentials) are included in build provenance. This is not a full
capture of included configuration files or all environment variables. Normal
Cargo cache writes remain normal cache writes. `cargo vendor` uses
`--respect-source-config` to keep existing registry source settings available.
The generated vendor configuration is local `.work/vendor-config.toml`, passed
with `--config`; it never replaces Cargo home's config.

### Entrypoint and bundled helpers

The Makefile uses `/usr/bin/python3 -I -B`. Bundled `debian.py`, `host_rust.py` and `runtime_support.py`
are loaded by their paths next to `build.py`, under private module names.
Neither PYTHONPATH nor script-directory insertion is required. Missing helpers
produce an incomplete-extraction error, not a request to pip-install a module.
Isolated Python is also used for install/verify subprocesses. `config.mk` is
optional, project-local, trusted Make code. Nothing modifies shell startup files.

### Dependency overlay and Git provenance

`make update-deps` copies the verified source and its real Git identity into a
temporary workspace. It runs ordinary `cargo update` (the only dependency
resolution phase without `--locked`), and verifies that only Cargo.lock changed.
Upstream manifest version constraints and Cargo's resolver/rust-version rules
remain authoritative. There is no `--breaking`, `--ignore-rust-version`,
all-features toggle, sed rewrite of crate versions, or unlocked build retry.

The resulting `dependency-lock/` holds Cargo.lock, its unified diff, update
log, hashes, toolchain identity and source linkage. The reviewed `upstream/`
checkout retains its source patch and true base Git identity. A generated build workspace uses the new
lock with the original Git HEAD: Git correctly reports that lock modification
as dirty. No fake clean commit or overridden VERGEN SHA is supplied.

Both source and dependency trees are rechecked before use. On a successful
source/dependency refresh, stale generated dependency/vendor trees are moved
to `.work/retired/`, not reused. A failed refresh preserves the previous
published dependency lock. `make clean` removes `.work/`, including those
retired copies and caches; archive anything you need before cleaning.

## Compilation and diagnostics

| Control | Default |
| --- | --- |
| Host target | Explicit native x86_64-unknown-linux-gnu or aarch64-unknown-linux-gnu |
| Rust profile | Release, opt-level 3, codegen-units 1, thin LTO, panic unwind |
| Rust flags | Native CPU; force frame pointers; full RELRO; ELF build-id; prefix remapping |
| C/C++ common | -O3 -g1 -fno-omit-frame-pointer -fstack-protector-strong -D_FORTIFY_SOURCE=3 |
| amd64 C/C++ | -march=native -mtune=native |
| arm64 C/C++ | -mcpu=native |
| Debug | Cargo debug=1; retain target outputs; split packaged debug using GNU objcopy/strip |
| Incremental | Disabled |
| Jobs | CPU affinity/quota and visible memory headroom heuristic; override JOBS=N |

Native code generation applies to the compiled crates/dependencies, not to
rebuilding the host compiler's already compiled standard library. CPU-specific flags do
not promise a speedup on every workload. No fast-math, panic-abort, forced AVX
level, unstable compiler flags or mismatched cross-language LLVM LTO is enabled.
`TUNE=portable` removes native CPU flags; shared-library compatibility is still
required. Flags and effective compiler configuration are recorded with the
host CPU signature, selected source/dependency locks and installed packages.

### Inherited Cargo/Rust/C/C++ settings (2.2.1 correction)

An exported `CARGO_TARGET_DIR` is valid host configuration, not a build error.
Do **not** unset it or modify your shell or Cargo config. The driver replaces
conflicting build settings only in a copied child-process environment. It never
mutates `os.environ`, your parent shell, or a global config file. A single `NOTE`
lists overridden variable names, not their values; they are also recorded in
`build-info.json` and `make doctor` output.

Final and intermediate artifacts use the same project-local directory:
`.work/target/<build-id>` for builds, checks and test compilation. The driver sets
`CARGO_TARGET_DIR`, `CARGO_BUILD_TARGET_DIR` and `CARGO_BUILD_BUILD_DIR` together;
compile commands also receive `--target-dir`. Auxiliary Cargo operations use
`.work/cargo` or their own temporary directory under `.work/`. Existing shared
build directories are not created, written to or cleaned by the driver.

Inherited Rust/C/C++ flags, target/profile overrides, archiver overrides,
compiler wrappers and bootstrap settings no longer cause an ambient-variable
error. They are scoped away for this native, explicitly configured build. Rust
compiler wrappers are disabled for kit Cargo invocations, including wrappers
specified in Cargo config files. Use `EXTRA_RUSTFLAGS`, `EXTRA_CFLAGS`,
`EXTRA_CXXFLAGS`, `TUNE`, `LTO`, `JOBS`, `HOST_CC` and `HOST_CXX` for intentional
kit build choices. RUSTC/CARGO/RUSTDOC remain accepted host-tool selectors.
Existing Cargo **configuration files** are not rejected. Cargo still reads
registry, mirror, credential and proxy configuration; project-local process
options take precedence for the settings controlled above. Those files are
hashed for provenance, not rewritten. The exact controlled environment set is
`CONTROLLED_BUILD_VARIABLES` plus the patterns in `controlled_build_variable()`.
`CARGO_HOME` defaults to the host's `$HOME/.cargo`; an explicitly supplied value
is honored, including configurations for mirrors/proxies. Project outputs are
under `.work/`. A symlinked `.work` is refused. The build is not hermetic or a
sandbox: upstream build scripts and any selected host-tool executables run as the user.
Forced `[env]` entries or third-party executable side effects are trusted user
inputs, not contained by this driver.

`make doctor` compiles and executes tiny Rust/C/C++ probes; it is not a workload
or a check of upstream compilation. `make check` runs Cargo check for selected
binaries. `make test-compile` uses Cargo test --no-run, never executes upstream
tests. `make smoke` first builds and verifies exported embedded files, then
runs --help and --version with temporary HOME.
No build target invokes `resctl-bench deps` or starts the agent.

Every real executable must be ELF64 little-endian for the selected machine,
PIE, full RELRO, and have a non-executable GNU stack. Packaging verifies input
hashes, runs the two filtered Rust regression suites, performs debug separation,
checks compiled helper exports again, runs CLI smoke checks and records readelf
output. Default binaries are resctl-bench, rd-agent, rd-hashd, resctl-demo.
`WITH_DEMO=0` omits only the interactive demo. AWS Lambda is not enabled.

## Target reference

| Target | Purpose |
| --- | --- |
| help / all | Show available operations / alias package. |
| deps / deps-plan / deps-runtime / deps-llvm | Install build dependencies / simulate / install runtime / optional LLVM. |
| fetch / update-source | Fetch once at requested ref / deliberately move the source lock. |
| update-toolchain / update-rustup / lock-toolchain | Disabled / disabled / record host identity locally. |
| update-deps / fetch-deps | Refresh compatible dependency overlay / fetch locked dependencies. |
| versions / doctor | Print provenance / probe compiler and linker. |
| package / latest / latest-complete | Locked repaired runtime build / blocked for this patch / blocked for this patch. |
| test-runtime | Compile and execute the 18 isolated native repair tests; no hardware workload. |
| build / check / test-compile | Release binary build / check / compile tests without running. |
| smoke / stage / rebuild / verify | CLI checks / stage payload / package selected inputs / verify latest result. |
| vendor / source-dist / kit-dist | Vendor locked crates / vendored source archive / build-kit-only archive. |
| snapshot-dist | Complete selected source snapshot without needing Rust or vendoring. |
| lint / test | Syntax/whitespace checks / orchestration fixture tests. |
| runtime-check | Read-only inventory, optional SCRATCH existing directory. |
| install / uninstall | Install last packaged payload / remove only tracked unchanged payloads. |
| clean / clean-vendor | Delete generated work state / delete checked vendor directory. |

`JOBS`, `TUNE`, `LTO`, `WITH_DEMO`, `SPLIT_DEBUG`, `OFFLINE`, `HOST_CC`,
`HOST_CXX`, `HOST_RUSTC`, `HOST_CARGO`, `HOST_RUSTDOC`, `UPSTREAM_URL`, `UPSTREAM_REF`, `TOOLCHAIN`, `PREFIX`, `DESTDIR`,
`FORCE`, and extra flags can be set as Make arguments or in config.mk. Multiple
Make goals are serialized. A project-level advisory lock serializes drivers.

## Release/source distributions and installation

The delivered host-rust snapshot is produced by `make snapshot-dist`: it includes
all supplied upstream source files and the modified build kit, a real minimal
Git object store and source locks. It does not need Rust/network to create.
It includes a vendor/dependency-lock tree only when already present and verified.
`source-snapshot.json` records whether dependencies are vendored. This particular
delivery has no vendored third-party crates; first-build registry access or an
existing cache is required. `config.mk` in a snapshot is copied from the shipped
example, never from the source host's private overrides.

Upstream source, including its separate CI/Lambda workflow definitions, is
preserved unchanged under `upstream/`. Those nested workflow definitions are
not the root build-kit workflow and are never invoked by this driver. Use the
root Makefile for the host-only policy. The root real-build CI job now requires
a pre-provisioned self-hosted runner rather than installing Rust.


A runtime package contains regular files only. SHA256SUMS covers payload files;
the archive has its own .sha256 sidecar. These detect accidental changes, not
malicious replacement of both payload and checksums. A trusted distribution
channel or separately managed signature is still necessary.

The runtime package includes original/effective Cargo locks, update evidence,
compiler and source identity, build logs, metadata, dependency tree, CPU flags,
ELF details, CLI output, documentation, and available upstream/dependency license
files. THIRD-PARTY.json is an inventory, not a certified SBOM or license clearance.
Missing license files are recorded rather than fabricated.

The populated source tarball includes upstream's true minimal Git object store
and full vendor tree, allowing vergen Git identity and vendored Git dependencies
to work after extraction elsewhere. Root checksum verification applies before
use. Absolute vendor paths are regenerated at the new location. `OFFLINE=1`
uses --frozen; any required compiler/Debian packages must be installed already.
Reapply original non-default options such as TOOLCHAIN, TUNE, WITH_DEMO,
HOST_CC and a custom UPSTREAM_URL when rebuilding. Local config.mk is not
bundled because it is trusted executable configuration that may contain private
settings; record reviewed values separately. A source archive identity includes
source, effective dependency lock and compiler lock to distinguish refreshes
at the same Git SHA. The download called
kit-dist is intentionally different: it has no upstream/vendor snapshots.

Packaging sorts entries and normalizes owner, group, file modes and archive
mtime. SOURCE_DATE_EPOCH defaults to the source commit time. This gives a
deterministic envelope for a given staged tree, not universally byte-identical
binaries/tarballs: logs, resolution timestamps, build scripts, CPU/library/compiler
versions and native tuning can affect contents. Do not confuse provenance with
a proven reproducible build.

Install from the build root with `sudo make install PREFIX=/usr/local`, or from
an extracted runtime release using `sudo python3 install.py --package .
--prefix /usr/local`. Use an absolute DESTDIR for packaging/staging. Files are
copied atomically individually, but the entire install is not an all-or-nothing
filesystem transaction. Conflicting files are refused unless FORCE=1/--force
is explicitly provided. The installer verifies checksums and permitted paths,
rejects symlink traversal, records an installation manifest and never runs
services, ldconfig, or benchmarks. Keep the prefix protected from untrusted
concurrent writers. Uninstall refuses modified tracked files rather than
deleting local changes or unrelated files.

The convenience path `dist/resctl-bench-latest.tar.gz` is a relative symlink to
the successfully generated versioned binary tarball. Its matching `.sha256`
uses the convenience filename. It is published only after successful staging
and packaging, and cleared at the beginning of the next attempt. Tarballs with different build IDs remain available; rebuilding the same ID
replaces its archive. A source-vendoring
failure after binary packaging does not invalidate that successful binary archive.

## Failure handling

For an upstream failure, inspect `.work/builds/<build-id>/build.log` and
`.work/logs/`; keep the recorded inputs. Reduce JOBS for memory pressure; try
LTO=off only as an explicit diagnostic. A compilation failure never triggers
another toolchain installation. Resolving API or minimum-Rust-version changes
in a source/dependency combination can require reviewed host maintenance or
source patches. This kit intentionally does not invent them automatically.

For host-readiness concerns see RUNTIME.md. A compile or CLI smoke pass is not
evidence of valid IOCost measurements, NVMe health, or runtime BPF compatibility.
