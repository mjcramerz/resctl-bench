# Build design and operating guide

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

## Latest resolution versus locked rebuilds

The high-level commands are:

```sh
make package           # One command: setup, current inputs, compile and binary tarball.
make                   # Same as make package.
make latest            # Compatibility alias for make package.
make latest-complete   # Also vendor and produce the populated source tarball.
make rebuild           # Rebuild/package selected inputs; no input updates.
make verify            # Check the last runtime archive and staged payload.
```

`package` (unless OFFLINE=1), `latest`, and `latest-complete` require online operation, `UPSTREAM_REF=main`, and
`TOOLCHAIN=nightly`. `UPSTREAM_URL` defaults to the official repository. A
custom URL is a trusted-input choice, not a claim that it is official upstream.
`UPSTREAM_REF` controls only first fetch and explicit `update-source`; after
fetch the full SHA is authoritative. Changes to a locked checkout are rejected.

The newest path installs Forky build dependencies, refreshes source, resolves
and installs the exact official nightly, refreshes compatible crates, runs
compiler/linker probes, and builds/packages. `latest-complete` then vendors and
creates the source distribution. The workflow is NOT a transactional rollback
of all APT/rustup/Git side effects. Successful updates can remain after a later
compile failure. Each package attempt clears the prior runtime success pointer and latest alias;
only successful runtime publication creates a new one. A later source-archiving
failure does not delete an already successful runtime package. Old artifacts
are never silently presented as outputs of a failed new package attempt.

### Forky APT policy

`make deps` performs `apt-get update --error-on=any`, then examines APT's Release
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
provide pkg-config. The base Rust workspace does not require installing an old
Debian rustc/cargo package, Python pip dependencies, ncurses, or all LLVM tools.
Optional `make deps-llvm` provisions Forky's clang/lld/llvm/libclang development
stack. Select it deliberately with `HOST_CC=/usr/bin/clang
HOST_CXX=/usr/bin/clang++`; there is no automatic GCC-to-Clang fallback.

`make deps-runtime` is separate because installing runtime packages can start
or change distro services via Debian maintainer scripts. It is not a read-only
check. Dependency transactions may install/upgrade required shared libraries;
review the printed plan and use normal system-maintenance precautions.

### Rust and rustup

`make update-toolchain` reads the official nightly distribution manifest, checks
the host has rustc/cargo/rust-std in that published release, installs
`nightly-YYYY-MM-DD --profile minimal --no-self-update`, and compares rustc's
full commit/release with the manifest. A second manifest read detects a channel
change during installation. No `--allow-downgrade`, `--force`, default change,
or unversioned-nightly backtracking is used. Rustup performs distribution
artifact verification; the kit's recorded manifest SHA is provenance, not a
separate signature authority.

The dated selection lives in `toolchain-selection.json`; it overrides this
kit's `TOOLCHAIN=nightly`, not your global rustup default or existing nightly
alias. Explicitly selected other installed toolchains are not overridden by
that file. `make lock-toolchain` deliberately accepts an installed compiler
identity for locked rebuilds; it cannot make a stale compiler satisfy an existing
latest-nightly selection. `make update-rustup` separately calls the existing
manager's self-update; a manager built without self-update must be maintained
through its distributor. Online `make package` can install the selected dated
nightly through the existing rustup; it does not install or self-update rustup.

The resolver fails rather than guessing when it cannot retrieve or parse the
official manifest, a minimal component is missing, or identities do not match.
This authoring environment could not execute the live manifest/rustup path;
see VALIDATION.md. Accurate system time and normal HTTPS trust are required.

### Entrypoint and existing rustup discovery

The Makefile uses `/usr/bin/python3 -I -B`. Bundled `debian.py` and `latest.py`
are loaded by their paths next to `build.py`, under private module names.
Neither PYTHONPATH nor script-directory insertion is required. An incomplete
extraction reports the missing file explicitly; these are not pip dependencies.
Isolated mode is also used for the install/verify subprocesses.

The driver finds rustup in the existing PATH, `$CARGO_HOME/bin`, or
`$HOME/.cargo/bin`, in that order, without changing the user's shell. The kit
must be run by the user who owns that installation. `config.mk` is optional.

### Dependency overlay and Git provenance

`make update-deps` copies the verified source and its real Git identity into a
temporary workspace. It runs ordinary `cargo update` (the only dependency
resolution phase without `--locked`), and verifies that only Cargo.lock changed.
Upstream manifest version constraints and Cargo's resolver/rust-version rules
remain authoritative. There is no `--breaking`, `--ignore-rust-version`,
all-features toggle, sed rewrite of crate versions, or unlocked build retry.

The resulting `dependency-lock/` holds Cargo.lock, its unified diff, update
log, hashes, toolchain identity and source linkage. The pristine `upstream/`
checkout stays untouched and clean. A generated build workspace uses the new
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
rebuilding rustup's already compiled standard library. CPU-specific flags do
not promise a speedup on every workload. No fast-math, panic-abort, forced AVX
level, unstable compiler flags or mismatched cross-language LLVM LTO is enabled.
`TUNE=portable` removes native CPU flags; shared-library compatibility is still
required. Flags and effective compiler configuration are recorded with the
host CPU signature, selected source/dependency locks and installed packages.

Ambient RUSTFLAGS/CFLAGS, target/profile overrides, compiler wrappers and
shadow Cargo configuration are rejected when they could override controlled
settings. Use `EXTRA_RUSTFLAGS`, `EXTRA_CFLAGS`, `EXTRA_CXXFLAGS` only as reviewed
trusted configuration. A config.mk is trusted Make code, not untrusted data.
CARGO_HOME defaults to an isolated `.work/cargo-home`; using your own cache is
allowed only without a conflicting Cargo config. No claim of a hermetic build
is made: upstream build scripts execute with the build user's permissions.

`make doctor` compiles and executes tiny Rust/C/C++ probes; it is not a workload
or a check of upstream compilation. `make check` runs Cargo check for selected
binaries. `make test-compile` uses Cargo test --no-run, never executes upstream
tests. `make smoke` runs only --help and --version with temporary HOME.
No build target invokes `resctl-bench deps` or starts the agent.

Every real executable must be ELF64 little-endian for the selected machine,
PIE, full RELRO, and have a non-executable GNU stack. Packaging verifies input
hashes, performs debug separation, runs CLI smoke checks and records readelf
output. Default binaries are resctl-bench, rd-agent, rd-hashd, resctl-demo.
`WITH_DEMO=0` omits only the interactive demo. AWS Lambda is not enabled.

## Target reference

| Target | Purpose |
| --- | --- |
| help / all | Show available operations / alias package. |
| deps / deps-plan / deps-runtime / deps-llvm | Install build dependencies / simulate / install runtime / optional LLVM. |
| fetch / update-source | Fetch once at requested ref / deliberately move the source lock. |
| update-toolchain / update-rustup / lock-toolchain | Resolve latest nightly / update manager / accept installed compiler. |
| update-deps / fetch-deps | Refresh compatible dependency overlay / fetch locked dependencies. |
| versions / doctor | Print provenance / probe compiler and linker. |
| package / latest / latest-complete | Refresh inputs and make runtime / runtime plus populated source distributions. |
| build / check / test-compile | Release binary build / check / compile tests without running. |
| smoke / stage / rebuild / verify | CLI checks / stage payload / package selected inputs / verify latest result. |
| vendor / source-dist / kit-dist | Vendor locked crates / populated source archive / build-kit-only archive. |
| lint / test | Syntax/whitespace checks / orchestration fixture tests. |
| runtime-check | Read-only inventory, optional SCRATCH existing directory. |
| install / uninstall | Install last packaged payload / remove only tracked unchanged payloads. |
| clean / clean-vendor | Delete generated work state / delete checked vendor directory. |

`JOBS`, `TUNE`, `LTO`, `WITH_DEMO`, `SPLIT_DEBUG`, `OFFLINE`, `HOST_CC`,
`HOST_CXX`, `UPSTREAM_URL`, `UPSTREAM_REF`, `TOOLCHAIN`, `PREFIX`, `DESTDIR`,
`FORCE`, and extra flags can be set as Make arguments or in config.mk. Multiple
Make goals are serialized. A project-level advisory lock serializes drivers.

## Release/source distributions and installation

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
LTO=off only as an explicit diagnostic. A strict latest failure is not evidence
that an older toolchain was tried or accepted. Resolving API changes in a
future upstream/nightly/dependency combination can require reviewed source
patches. This kit intentionally does not invent them automatically.

For host-readiness concerns see RUNTIME.md. A compile or CLI smoke pass is not
evidence of valid IOCost measurements, NVMe health, or runtime BPF compatibility.
