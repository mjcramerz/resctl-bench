# resctl-bench build kit 2.2.1 - host Rust, no toolchain installation

**2.2.1 fixes the inherited `CARGO_TARGET_DIR` failure.** Keep your existing
shell environment and global Cargo configuration. `make package` now scopes
conflicting build variables away in its child processes instead of rejecting
them. Final and intermediate output stays under project-local `.work/`; your
shared Cargo target directory is not touched. Registry/proxy/credential settings
and `CARGO_HOME` remain available. Host Rust is still used without installation.


This version builds with Rust already installed on your host. It does not
install, update, or select a new Rust release, change a Rustup default/override,
rewrite a Cargo configuration, or edit a shell startup file.

## Build the included source

Run from the extracted directory as your ordinary user:

```sh
sha256sum -c SHA256SUMS
make doctor
make package
make verify
```

`make doctor` checks the selected tools and compiles small Rust/C/C++ probes.
`make package` builds and packages the locked source. It does **not** invoke
APT, sudo, a Rust installer, `cargo update`, or a source refresh. It may download
missing **crate dependencies**, using your existing Cargo registry/cache settings.
The output is `dist/resctl-bench-latest.tar.gz`, plus its `.sha256` sidecar and a
versioned archive. Packaging runs only the binaries' `--help` and `--version`;
it does not run benchmarks or modify IOCost, cgroups, systemd, or devices.

The default is `TOOLCHAIN=host`. Native Rust tools on PATH take precedence;
Rustup is **not required**. Existing Rustup symlink/hardlink proxies are resolved
to their already-installed concrete tools with read-only `rustup which` queries.
`RUSTUP_AUTO_INSTALL=0` is set for the build subprocesses. A missing compiler
causes an error, never an installation attempt. The host compiler must still
support the locked source and dependencies; no nightly or compiler upgrade is
silently substituted for an incompatible host.

Explicit Debian executable paths are supported:

```sh
make package HOST_RUSTC=/usr/bin/rustc HOST_CARGO=/usr/bin/cargo HOST_RUSTDOC=/usr/bin/rustdoc
```

Those paths must exist. Otherwise leave the variables unset to use PATH. Standard
`RUSTC`, `CARGO`, and `RUSTDOC` environment values are also accepted; `HOST_*`
values take precedence. Fallback executable discovery checks the existing
`$CARGO_HOME/bin` and `$HOME/.cargo/bin`, without changing your shell PATH.
`TOOLCHAIN=<name>` is an optional request for an **already-installed** Rustup
selection; it never installs that name. An inherited `RUSTUP_TOOLCHAIN` is
respected when resolving host Rustup proxies.

## Existing Cargo configuration stays in place

Your `CARGO_HOME` is honored; when unset, the usual `$HOME/.cargo` is used.
Existing `config`/`config.toml` files in Cargo home and `.cargo` configurations
in parent directories are accepted as trusted Cargo inputs, not rejected,
renamed, removed, truncated, or rewritten. Registry/mirror settings remain
available. Cargo may update its normal dependency cache; that is distinct from
rewriting configuration files. The kit's build flags, selected executables and
output directory are set only for child processes. Generated vendor settings
are written only to `.work/vendor-config.toml` and supplied through `--config`.

The former error about an existing Cargo config has been removed. You do not
need to move or delete `/pool/cache/.../cargo/config.toml` or replace your global
configuration. To deliberately use a separate cache, pass a project-local
`CARGO_HOME="$PWD/.work/cargo-home"`; this is optional, not required.

## Complete source, not a patch-only kit

The `resctl-bench-buildkit-2.2.1-host-rust.tar.gz` source snapshot includes the
full supplied upstream workspace, Cargo manifests/lock, documentation, licenses,
minimal real Git object store, build scripts, tests, and host-only defaults.
The source commit is `bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b`. All 163 upstream
source files in the supplied source manifest remain byte-for-byte unchanged.
The build orchestration is modified; no substitute or synthetic resctl-bench
implementation is supplied.

Third-party Cargo crate sources were not in the supplied ZIP and are **not
vendored in this delivered snapshot**. A first build requires registry access
or a sufficiently populated host cache. `make package OFFLINE=1` uses frozen,
network-disabled Cargo commands and requires those dependencies already available.

```sh
make snapshot-dist     # Full selected project source; no Rust or network needed.
make source-dist       # Full selected source plus vendored Cargo dependencies.
make kit-dist          # Build-driver code only; not the complete source snapshot.
```

`source-snapshot.json` describes the delivered snapshot's dependency coverage.
Old local caches/logs and the obsolete nightly-selection file are not shipped.
The included upstream workflows/docs are preserved source material; only the
root Makefile and root build-kit workflow implement this host-only build policy.
Do not run the separate upstream Lambda deployment workflow as a local build.

## Explicit maintenance only

`make latest` and `make latest-complete` deliberately refresh upstream `main`
and compatible crates, still using unchanged host Rust. They do not run APT.
`make update-source` and `make update-deps` provide the separate refresh steps.
`make update-toolchain` and `make update-rustup` are disabled with explanatory
errors. `make lock-toolchain` records host tool versions in project-local
`toolchain.lock.json`; that file is provenance, not an installation prescription.
Legacy `toolchain-selection.json` files are ignored.

Build prerequisites must already be installed. The original Forky-only APT
helper remains available **only** as explicit `make deps`, `make deps-llvm`, or
`make deps-runtime` actions. Such actions change system packages and may trigger
Debian maintainer scripts; do not invoke them as read-only checks. The build
requires GNU Make, Python 3.11+, Git, C/C++ tools, binutils, pkg-config, OpenSSL
development files, and a suitable installed Rust/Cargo/rustdoc set. See
`packages/build.txt` for the non-Rust package list. No target installs Rust.

The platform policy remains Debian Forky on native amd64/arm64 GNU/Linux.
`ALLOW_UNSUPPORTED_DEBIAN=1` is an explicit experimental-build override for other
Debian environments, never permission to run Forky APT transactions there.
Do not use `sudo make package`. `ALLOW_ROOT_BUILD=1` is for disposable CI only.

`TUNE=native` and thin LTO are defaults. Use `TUNE=portable` for no native CPU
flags; shared-library compatibility remains your responsibility. See
`config.mk.example`, `make help`, and `docs/BUILD.md` for all controls.

## Verification and limitations

Run `make lint test`. The regression suite validates host tool discovery,
no-installer behavior, preservation of configuration bytes/mtimes, real Make
entrypoints, real Git/ELF/debug packaging, source completeness, and relocation.
Rust/Cargo operations in pipeline tests are explicitly simulated; generated test
ELFs are tiny C fixtures, not resctl-bench. No fixture binaries are included.

This authoring environment has no installed Rust/Cargo, so a real upstream Rust
compilation was not performed and is not claimed. `docs/VALIDATION.md` and
`docs/test-results.txt` contain the actual checks and limitations. Read
`docs/RUNTIME.md` before any benchmark execution; a successful build is not a
runtime safety or IOCost measurement certification.
