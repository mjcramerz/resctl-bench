# resctl-bench build kit 2.0.0 - Debian Forky

A native, source-based build and release pipeline for Facebook Experimental's
`resctl-demo` workspace. This edition targets **Debian Forky (testing), amd64
or arm64, GNU/Linux**, and the Rust toolchains managed by your existing rustup.
It builds `resctl-bench`, `rd-agent`, `rd-hashd`, and, by default, `resctl-demo`.

## What this download contains

The `resctl-bench-buildkit-2.0.0.tar.gz` download is the complete **build-kit
implementation**, including Makefile, Python build driver, Forky APT resolver,
nightly resolver, installer, read-only runtime checks, regression tests, CI,
and documentation. It contains **no upstream Rust checkout, vendored crates,
or precompiled resctl executables**. No placeholder executable is presented as
resctl-bench. On a networked Forky host, `make latest-complete` creates both the
real executable release tarball and the populated upstream-plus-vendor source
tarball. See [validation boundaries](docs/VALIDATION.md).

## Start here on Forky

Run as the ordinary user who owns your rustup installation, not under sudo.
APT operations alone request sudo. No target changes your APT sources, performs
a distribution upgrade, selects an NVMe device, or starts a benchmark.

```sh
sha256sum -c resctl-bench-buildkit-2.0.0.tar.gz.sha256
tar -xzf resctl-bench-buildkit-2.0.0.tar.gz
cd resctl-bench-buildkit-2.0.0
export PATH="$HOME/.cargo/bin:$PATH"

# Explicitly update the existing rustup manager itself; do not reinstall it.
make update-rustup

# Refresh Forky build dependencies, upstream main, the latest published nightly,
# and compatible crate versions; compile, smoke-test, package, and vendor.
make latest-complete
make verify
make versions
```

GNU Make and Python 3.11+ are entrypoint prerequisites. On a minimal Forky
installation only, bootstrap them with `sudo apt-get update --error-on=any`
and `sudo apt-get install --no-install-recommends make python3 ca-certificates git`.
There are no Python packages to install with pip. `make test` additionally needs
Git, GCC, G++, binutils and pkg-config; `make deps` installs the build tools.
A distribution-managed rustup built without self-update may reject
`make update-rustup`; update that package through its owner rather than
installing a second Rust distribution over it.

## What "latest" means here

`make latest` / `make latest-complete` explicitly resolve moving inputs:

| Input | Policy |
| --- | --- |
| Upstream | Fetch the current `main` and record the full real Git commit. |
| Rust | Read Rust's current official nightly manifest; require the host's minimal components; install the exact dated nightly; verify the compiler commit and release. No older-nightly fallback. |
| Crates | Run `cargo update` in a separate source copy, respecting upstream manifest constraints and Cargo's resolver. Preserve the original upstream `Cargo.lock` and record the effective lock plus its diff. |
| Debian build packages | Refresh APT indexes and select the newest available versions in configured Debian-origin, `n=forky` indexes. Expand compiler metapackages to their current implementations without hardcoding GCC/LLVM major versions. |
| Subsequent builds | Use the resolved locks. `make package` does not silently advance source, toolchain, or dependencies. Run `make latest-complete` again to refresh them. |

These are **latest inputs at their recorded resolution times**, not a promise
that no publisher releases a new version during a long build. Package indexes
can lag upstream releases. A manifest requiring an older crate major version is
not rewritten: automatically forcing breaking dependency upgrades is a source
migration, not a reliable build flag. There is no hidden fallback to an older
nightly, upstream tag, Sid package, unlocked build, or permissive removal plan
when the current combination fails.

Only declared build dependencies and their resolved transaction are installed;
this is not a whole-system updater. Kernel, NVMe firmware, runtime packages,
and the rustup manager have separate lifecycles. `make deps-runtime` and
`make update-rustup` are explicit commands, not side effects of `make package`.

## Outputs

After `make latest-complete` succeeds:

```text
dist/
  resctl-bench-<version>-<host>-<tuning>-<build-id>.tar.gz
  resctl-bench-<version>-<host>-<tuning>-<build-id>.tar.gz.sha256
  resctl-bench-buildkit-2.0.0-source-<commit>-<identity>.tar.gz
  resctl-bench-buildkit-2.0.0-source-<commit>-<identity>.tar.gz.sha256
```

The runtime tarball includes the programs, split debug symbols, upstream and
third-party licenses available in dependency sources, dependency inventory,
real Git/compiler/package/CPU provenance, original and effective Cargo locks,
update evidence, build logs, ELF inspection and CLI smoke results, checksums,
a standalone installer, and read-only runtime checker. It does not bundle
glibc, Python, fio, BCC, or other Debian runtime libraries/tools.

The populated source tarball includes this kit, pristine upstream with its
real Git identity, source/compiler/dependency locks, and vendored Cargo source
dependencies. It does not contain a Rust compiler, Debian packages, firmware,
or build outputs. With the matching toolchain and native prerequisites already
installed, extract it elsewhere and run `make package OFFLINE=1`. Cargo uses
`--frozen` and relocated vendor configuration; this is not an OS-level network
sandbox for arbitrary upstream build scripts.

## Host tuning and configuration

The defaults are release `opt-level=3`, thin LTO, one codegen unit, no
incremental compilation, panic unwinding, frame pointers, full RELRO, and
separate debug symbols. Rust uses `-Ctarget-cpu=native`; C/C++ use native
x86-64 or AArch64 flags as appropriate, with stack protection and fortification.
No guessed CPU model, fast-math, unstable `build-std`, or cross-language LLVM
LTO is forced. These are explicit defaults, not a measured optimum for all jobs.

```sh
make latest-complete JOBS=4   # Bound compiler concurrency.
make latest-complete TUNE=portable   # No native CPU tuning; not a static build.
make package WITH_DEMO=0     # Keep benchmark plus required agent/hashd helpers.
make package LTO=off         # Diagnostic alternative to thin LTO.
cp config.mk.example config.mk   # Optional persistent configuration.
```

A native artifact is intended for the build machine or verified compatible
hardware. `TUNE=portable` does not remove glibc/libstdc++/OpenSSL dependencies
or guarantee compatibility with older Debian systems. Keep the upstream
benchmark version, input files, CPU policy, and storage environment consistent
when comparing benchmark results; changing the build can change the workload.

## Install and diagnose separately

```sh
sudo make install PREFIX=/usr/local   # Installs last successful package; no build.
sudo make uninstall PREFIX=/usr/local # Removes only unchanged tracked payloads.

# Explicit APT installation: distro package maintainer scripts may start services.
make deps-runtime
# Inspect only an existing filesystem directory, never a raw device node.
make runtime-check SCRATCH=/existing/benchmark/filesystem
```

There is no `make benchmark` target. Read [runtime preparation](docs/RUNTIME.md)
before invoking upstream manually on a dedicated, disposable benchmark host.

## Development and further documentation

`make lint test` checks this build kit using synthetic Rust/Cargo fixtures,
real local Git and GCC-produced ELF programs. It does not certify that an
arbitrary current upstream/nightly combination compiles. `make check` compiles
upstream checks and `make test-compile` compiles upstream tests without executing
them. An opt-in CI job runs a real online build and relocated offline rebuild.

See [build design and all targets](docs/BUILD.md),
[validation evidence](docs/VALIDATION.md),
[primary sources](docs/SOURCES.md), and [changes](CHANGELOG.md).
