# Changes

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
