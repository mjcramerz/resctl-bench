# Validation status - build kit 2.2.0 (host Rust)

Validation date: 2026-09-16. This report distinguishes orchestration tests from
actual Rust compilation. No benchmark, IOCost change, device operation, Rust
installation, APT installation, or global configuration edit was performed.

## Executed checks

`make lint test` completed successfully: **99 tests passed**. The actual combined
stdout/stderr is in `docs/test-results.txt`. Syntax/whitespace checks cover all
nine Python files in scripts/ and tests/.

The tests include native host tools without Rustup; PATH precedence; explicit
executable paths with spaces; standard RUSTC/CARGO/RUSTDOC variables; existing
Rustup symlink and hardlink proxies; inherited host selection; read-only named
toolchain queries; disabled automatic installation; missing tools; obsolete
nightly selections; disabled update targets; and project-local tool provenance.

Pipeline tests run real GNU Make/Python entrypoints, Git operations, C compilation,
ELF validation, objcopy/strip debug separation, binary/source tar generation,
checksum verification, installer conflict checks, and source-bundle relocation.
Rust/Cargo programs in these pipeline tests are **simulated executables**; their
produced ELF files are tiny C fixtures, not real resctl-bench binaries. Rustup,
sudo and apt-get fixture traps fail if invoked by ordinary packaging.

A preservation test runs doctor, dependency refresh, Cargo check/test compilation,
packaging and source vendoring with pre-existing Cargo-home config/config.toml,
ancestor/project Cargo configurations, Rustup settings, and a shell profile.
It verifies configuration bytes and modification times are unchanged. It also
asserts that all simulated Cargo subprocesses receive RUSTUP_AUTO_INSTALL=0,
concrete host tool paths, and the existing custom CARGO_HOME.

The complete-source snapshot test forbids toolchain discovery during archiving,
checks that the actual workspace implementations, host helper and defaults are
included, extracts the tarball, verifies source identity, and runs SHA256SUMS.
It caught an optional Git-index refresh after extraction; the driver now sets
GIT_OPTIONAL_LOCKS=0 so its read-only source checks do not rewrite that index.

The supplied upstream snapshot was independently checked against its original
source manifest and ZIP contents: all **163 upstream source files** are preserved.
The locked commit is `bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b` and the original
Cargo.lock is unchanged. Minimal Git metadata is retained for build provenance;
host reflogs, hooks and old local .work logs/caches are not redistributed.

## What this does not establish

This authoring environment is Debian 13 (Trixie) and has no installed rustc,
Cargo or Rustup. A real upstream Rust compilation/link was **not performed**.
No Rust toolchain was downloaded or installed to replace that missing prerequisite.
Fixture success does not establish compatibility with a particular host compiler,
all configured registry mirrors, the full real Cargo dependency graph, or every
possible user wrapper/configuration. Existing configured tools and upstream
build scripts are trusted code executed with the build user's permissions.

The delivered complete-project source archive does **not** contain vendored
third-party Cargo crates: those sources were absent from the supplied ZIP.
A real first build therefore requires registry access or an existing dependency
cache. Offline mode needs cached or previously vendored dependencies. Missing
or incompatible host Rust fails without installing a replacement.

No live Forky APT transaction, real-upstream CI job, AWS workflow, or IOCost
benchmark was run. Root CI no longer provisions Rust; its real-build job requires
a provisioned self-hosted runner. The upstream nested Lambda workflow is retained
as pristine upstream source and is not part of root Make/build-kit execution.
The original CI action pins are retained, not newly verified release assertions.

## Reproduce on the intended host

From a fresh extraction as the ordinary host user:

```sh
sha256sum -c SHA256SUMS
make lint test
make doctor
make package
make verify
```

Use explicit HOST_RUSTC/HOST_CARGO/HOST_RUSTDOC paths when PATH does not identify
the desired already-installed tools. Read README.md for configuration and host
requirements. Never interpret a CLI smoke pass as permission to run workloads
against an unreviewed scratch device or production host.
