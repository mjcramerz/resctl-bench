# resctl-bench build kit 2.1.0 - Debian Forky

## Build and get the binary tarball

From the extracted directory, run as your ordinary rustup-owning user:

```sh
make package
```

That is the complete online workflow. It installs the declared Debian Forky
build dependencies (sudo prompts when necessary), fetches current upstream
`main`, selects the newest published nightly through your existing rustup,
resolves current compatible Cargo dependencies, compiles with native-host
release settings, checks and packages the executables, and prints the result:

```text
dist/resctl-bench-latest.tar.gz
dist/resctl-bench-latest.tar.gz.sha256
```

`resctl-bench-latest.tar.gz` points to the versioned runtime tarball in the same
`dist/` directory. The tarball contains `bin/resctl-bench`, `bin/rd-agent`,
`bin/rd-hashd`, and `bin/resctl-demo`, separate debug symbols, documentation,
licenses, checksums, and recorded source/compiler/dependency/build information.
It is not a source-only archive. It does not include Debian shared libraries.

Plain `make` does the same thing. No config file edits, PATH export, Python
virtual environment, pip installation, or separate preparation targets are
needed for the default workflow. Do not run `sudo make package`; elevation is
used only for APT. Network access, working Debian Forky APT repositories, GNU
Make, system Python 3.11+, an existing rustup installation, and permission to
install dependencies via sudo are prerequisites.

The driver finds rustup in PATH, `$CARGO_HOME/bin`, or `$HOME/.cargo/bin`.
It does not reinstall rustup or change your global Rust default. It can install
a new dated nightly using that manager. Builds run as your ordinary user.

## What was fixed

The 2.0.0 driver used fragile top-level imports of `latest` and `debian`.
Those imports assumed Python would put the scripts directory on its import
path, and could collide with an installed `debian` package. The helpers are
now loaded from their explicit bundled locations under private names.
The Makefile uses isolated system Python, as do installation/verification
subprocesses. Missing helper files report an incomplete extraction rather
than suggesting a pip dependency. Safe-path mode no longer breaks startup.

`make package` now includes setup, instead of assuming the user already ran
other targets. Sudo authentication is visible on the terminal before APT output
is logged. Distribution trees and actual extracted Makefile entrypoints are
covered by regression tests, including directories containing spaces.

## Download and build

```sh
tar -xzf resctl-bench-buildkit-2.1.0.tar.gz
cd resctl-bench-buildkit-2.1.0
make package
```

This downloadable archive contains the complete build-kit implementation,
not a precompiled resctl executable or an upstream source checkout. The command
above downloads upstream and generates the binary tarball on your Forky host.
No fixture or placeholder executable is shipped as a resctl program.

## Inputs, repeat builds, and optional source archive

The online `make package` command refreshes upstream main, the dated nightly,
compatible crate versions, and declared Forky build packages every time.
Exact inputs are recorded. Dependency updates respect upstream manifests;
this is not a forced migration to incompatible crate major versions. Failed
compilation is not retried with older sources or an unlocked dependency graph.

`make rebuild` rebuilds the already selected inputs without refreshing them.
`make latest` remains an alias for the online package workflow.
`make latest-complete` additionally creates a populated upstream-plus-vendored-
dependencies source tarball. Neither source vendoring nor this extra archive
is necessary to obtain the binary tarball with `make package`.

A populated source archive can be rebuilt with `make package OFFLINE=1` after
extracting it on a host with the matching compiler and Debian dependencies
already installed. Cargo then uses --frozen and local vendor sources. This is
not a network sandbox for upstream build scripts.

## Host optimization and safety

Defaults are native amd64/arm64 GNU/Linux code generation, release opt-level 3,
thin LTO, one codegen unit, frame pointers, panic unwinding, full RELRO, and
separate debug information. Rust uses `-Ctarget-cpu=native`; C/C++ use
`-march=native -mtune=native` on amd64 and `-mcpu=native` on arm64. Native
artifacts must be used on compatible CPUs. `TUNE=portable` removes native CPU
selection, not dependencies on the host's Debian shared-library ABI.

Optional reviewed overrides such as `JOBS=4`, `WITH_DEMO=0`, or `LTO=off` are
accepted on the command line. `config.mk.example` documents the defaults;
copying it is not a prerequisite. Unexpected ambient compiler flags and Cargo
configuration are rejected rather than silently changing the recorded build.

No build target launches a benchmark, starts rd-agent, selects or formats an
NVMe device, writes IOCost/CPU/kernel settings, or installs a kernel/firmware.
Runtime preparation and installation are separate. A successful compile is
not a claim that storage benchmarking is safe on the host.

## Validation

The 2.1.0 regression suite passes **86 tests**. It includes actual Makefile
subprocesses, independent archive extraction, local Git, real GCC-produced
ELF files, debug splitting, checksums, packaging, installation and removal.
External Rust/Cargo, nightly and APT services are simulated in the pipeline
tests. This authoring sandbox has no Rust toolchain and cannot resolve GitHub
for a source download, so a real upstream/nightly compilation was not executed
here. No precompiled upstream binaries are included in this download.

See [validation details](docs/VALIDATION.md), [build design](docs/BUILD.md),
[runtime precautions](docs/RUNTIME.md), [primary sources](docs/SOURCES.md),
and [changes](CHANGELOG.md). `make help` lists the advanced targets.
