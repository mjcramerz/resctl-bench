# Changes

## 2.2.1 - 2026-09-16

- Fix `make package` failing solely because the host exports `CARGO_TARGET_DIR`.
  Replace the ambient-variable rejection with child-process-local overrides.
- Apply the same policy to related Rust/Cargo/C/C++ flags, targets, profiles,
  bootstrap settings, archivers and wrappers, rather than fail on the next
  inherited variable. Keep host executable selection and Cargo cache/network/
  registry/credential inputs available; never rewrite global configuration.
- Set both Cargo target-directory variables and the separate intermediate
  build-directory setting. Add explicit `--target-dir` to build/check/test.
- Apply the policy to doctor, dependency operations, vendoring and packaging.
  Disable Cargo compiler wrappers locally and record overridden names only.
- Add direct-environment and real Make entrypoint regression coverage,
  including extracted archives, paths with spaces, shared-cache sentinels,
  configuration content/mtime preservation, and explicit flag options.
- No change to the locked upstream source or the host-installed-only Rust policy.


## 2.2.0 - 2026-09-16

* Default to host-installed Rust; support native Debian tools and existing Rustup
  proxies, including symlinks/hardlinks and executable paths with spaces.
* Replace the nightly-manifest helper with host_rust.py. Remove all Rust install,
  update, self-update and forced-nightly paths from active build orchestration.
* Set RUSTUP_AUTO_INSTALL=0 for subprocesses; resolve proxies only using which.
  Preserve inherited host selection and use concrete tools for compilation.
* Accept existing Cargo home/ancestor configs without rewriting any config.
  Honor host CARGO_HOME and registry settings, including cargo vendor sources.
* Make package a locked build without APT or source/crate/toolchain updates.
  Keep source/crate refresh and system-package maintenance explicit and separate.
* Treat toolchain.lock.json as local host provenance; ignore obsolete nightly
  selections instead of asking to install or restore a different compiler.
* Restore missing config.mk.example and add snapshot-dist for the complete source
  tree without needing Rust/network. Keep the supplied upstream source unchanged.
* Disable Rust-provisioning in root real-build CI; require a provisioned runner.
* Expand regression coverage for host discovery, non-mutation, no installer paths,
  real Make entrypoints, full-source archives, checksums and relocation.

Earlier entries below describe superseded behavior, not 2.2.0 instructions.


## 2.1.0 - 2026-09-15

* Fix fragile top-level imports of latest/debian: load the bundled files directly,
  with private module names. Work under Python -P/-I/PYTHONSAFEPATH and avoid
  importing unrelated site-packages. Report incomplete extractions without a traceback.
* Use isolated system Python for Makefile and installer/verification entrypoints.
* Make plain `make` and `make package` the full online setup/build/binary-tarball
  workflow. Preserve latest/latest-complete; add `make rebuild` for locked inputs.
* Find the existing rustup without requiring a PATH export or config.mk edits.
* Authenticate sudo on the terminal before logging APT output; prevent hidden
  password-prompt hangs. Builds remain unprivileged.
* Publish dist/resctl-bench-latest.tar.gz plus its SHA256, clear stale convenience
  pointers after failed attempts, and preserve versioned historical artifacts.
* Validate helper presence and isolated startup in curated distribution trees.
* Add subprocess Makefile, isolated/safe-path, conflicting-module, missing-file,
  rustup-discovery, sudo-prompt and complete-workflow regression tests.
* Exercise make package from a relocated populated source archive using frozen
  dependencies; exercise the online Makefile with simulated APT/nightly/Cargo
  boundaries and real GCC ELF packaging. These are not real upstream Rust builds.

## 2.0.0 - 2026-09-15

* Target Debian Forky explicitly; reject accidental package installation on another release.
* Resolve newest declared APT package versions from Debian-origin Forky indexes,
  including the testing alias only when its Release codename is Forky. Check the
  solver's transitive installation plan, forbid removals, and verify installed versions.
* Add latest/latest-complete, update-toolchain, update-deps, versions, deps-plan,
  deps-llvm, and explicit update-rustup targets.
* Select the published nightly's exact dated minimal toolchain and verify rustc's
  full commit identity. Do not silently fall back or change rustup's global default.
* Update compatible crates in a separate lock, preserving pristine upstream source,
  real Git identity, update log, and a full Cargo.lock diff. No breaking manifest rewrites.
* Include effective and original lockfiles, installed package inventory, and latest
  resolution evidence in release metadata. Preserve overlays in populated source archives.
* Verify ELF architecture, PIE, full RELRO and non-executable stack; retain debug symbols.
* Reject hidden Cargo config and compiler overrides; invalidate stale package markers.
* Extend read-only diagnostics with io_uring availability, matching-kernel header/BTF visibility, CPU power policy and block-queue settings.
* Use the C locale for machine-parsed APT/dpkg output, including localized shells.
* Add Forky CI and newer immutable action revisions, extended regression tests and docs.

## 1.0.0

Initial source-fetch/build/stage/vendor/archive/install implementation. Broad Debian
12+ assumptions and no explicit current-nightly/dependency-refresh workflow.
