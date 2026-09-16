# Validation status - build kit 2.2.1 (host Rust, ambient Cargo correction)

Validation date: 2026-09-16. This report distinguishes build-driver validation
from actual upstream Rust compilation. No benchmark, IOCost setting change,
device operation, Rust installation, APT installation or global configuration
edit was performed.

## Exact reported failure reproduced and corrected

The 2.2.0 `scripts/build.py` was placed in an integration-test workspace with
an exported `CARGO_TARGET_DIR` pointing at a shared directory containing a
sentinel file. Actual `make package` failed with the reported message:

```text
ERROR: Ambient CARGO_TARGET_DIR makes the build ambiguous. Unset it; use documented kit options/EXTRA_*FLAGS.
```

Only the driver was replaced with 2.2.1; the same command and inherited
environment then passed. `make verify` also passed. The shared directory gained
no files; its sentinel and Cargo config retained identical bytes and nanosecond
modification times. Rustup, sudo and APT traps were not invoked. All three Cargo
output-directory variables agreed with the project-local target directory, and
the compile command included `--target-dir`.

These reproduction runs use simulated Rust/Cargo, real Make/Python/Git,
real C-compiled ELF fixture binaries and real binutils/archive verification.
They do not pretend to compile the upstream Rust workspace. Machine-readable
results and full output are in `docs/cargo-target-regression.json` and
`docs/cargo-target-regression.txt`.

## Executed suite

`make lint test`: **116 tests passed**. Full output is `docs/test-results.txt`.
Syntax/whitespace checks cover all ten Python source/test files. The suite adds
17 environment-policy tests and replaces the old test that incorrectly expected
inherited Rust flags to be rejected. Existing extraction coverage now exports
both target-directory aliases and the intermediate-directory setting.

Coverage includes:

- Actual `make package verify` with exported absolute and relative target
  directories, paths containing spaces, existing shared caches and nonexistent
  shared directories. `make clean` is checked not to delete external caches.
- Actual Make entrypoints for doctor, fetch-deps, check, test-compile, package
  and verify with combined target, flag, profile, wrapper, bootstrap, archiver
  and C/C++ environment overrides. Dependency update and vendoring are tested
  with inherited output overrides as well.
- Exported values are not copied into the parent Python environment or written
  to config files. Notices contain variable names only. Private values are not
  logged as part of the override report. Explicit EXTRA_*FLAGS still work.
- Existing Cargo-home, ancestor and project configs, credential files, Rustup
  settings and shell startup files retain identical bytes and mtimes. Registry,
  mirror, proxy, certificate and Cargo-home environment settings remain present.
- Native host tool selection without Rustup, PATH and explicit-path precedence,
  paths with spaces, Rustup symlink/hardlink proxy resolution using only `which`,
  disabled auto-install and update targets, missing tools and obsolete lock data.
- Real Git source checks, ELF architecture/hardening checks, split debug symbols,
  archive checksums, install conflict handling, source-bundle relocation and
  offline-mode command flags. Cargo/Rust are fixtures for these pipeline tests.

The supplied ZIP was independently compared again: all **163 upstream source
files**, their source manifest and the locked Cargo.lock are unchanged. The
commit remains `bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b`. The complete workspace
and minimal Git metadata are retained. Old local build output is not shipped.
The final archive is extracted separately and its checksums and suite rerun;
the separately delivered validation report records those results.

## Limits

This authoring environment is Debian 13 (Trixie), not the intended Forky host,
and has no installed rustc/Cargo. A real upstream Rust compilation/link was
**not performed**. No Rust toolchain was downloaded or installed to fill that
gap. Passing fixtures establishes the tested driver behavior, not compatibility
with every host compiler or arbitrary Cargo configuration. Existing host tools
and upstream build scripts are trusted code, not sandboxed by the build driver.
Forced Cargo `[env]` entries and external executable side effects are not a
security boundary this driver can contain. Tests do not simulate every detail
of real Cargo configuration parsing.

Third-party Cargo dependencies were absent from the supplied ZIP and are not
vendored in this archive. First compilation needs registry access or a populated
Cargo cache. `OFFLINE=1` needs previously cached or vendored dependencies.
Missing or incompatible host Rust fails without installing a replacement.
No live Forky APT transaction, real-upstream CI job or IOCost benchmark was run.
The root CI still requires a pre-provisioned runner for its real-upstream job;
retained upstream CI files are not root build-kit entrypoints. Existing action
pins were not revalidated as part of this targeted correction.

## Reproduce on the intended host

Keep the existing host environment, including `CARGO_TARGET_DIR`, unchanged.
From a fresh extraction as the ordinary user:

```sh
sha256sum -c SHA256SUMS
make lint test
make doctor
make package
make verify
```

Use HOST_RUSTC/HOST_CARGO/HOST_RUSTDOC only when explicit installed paths are
needed. The driver does not require Rustup for native Debian tools. Do not run
packaging under sudo. No build target launches the IOCost benchmark workload.
