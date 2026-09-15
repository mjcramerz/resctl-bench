# Validation status - build kit 2.1.0

## Regression fixed

The supplied 2.0.0 archive contains scripts/latest.py and scripts/debian.py,
but the driver imported their names as top-level modules. This depends on
sys.path and can import an unrelated installed debian package first. Running
the old driver with PYTHONSAFEPATH=1 reproduced a missing local helper import.
The exact environmental trigger on the reported user's host is not established
from the traceback alone. The fix does not require determining that trigger:
it loads bundled helpers by their explicit paths under private names and uses
isolated system Python for Makefile and installer/verification subprocesses.
A truly missing helper gives an explicit incomplete-archive error.

## Executed tests

Validation date: 2026-09-15 UTC. Authoring host: Debian 13 (Trixie), x86_64.
This host is not Debian Forky and has no installed Rust toolchain.

All **86 tests passed**, with no failures or skips. `make lint` passes syntax
and whitespace checks for all eight Python source/test files. The suite was
also rerun from an independently extracted copy of the generated distribution.
`test-results.txt` contains the captured development-tree run; the extracted
archive run is supplied as a separate download next to the final archive.

New coverage includes:

* Actual Makefile subprocesses with -I, PYTHONSAFEPATH, corrupted PYTHONHOME,
  conflicting external modules, and project-directory names containing spaces.
* Explicit errors for missing latest.py/debian.py, without ModuleNotFoundError.
* Plain make selecting package, online/locked/offline target dispatch, automatic
  rustup discovery, and visible sudo authentication before logged APT execution.
* The real online Makefile/main/newest sequence with only APT, nightly and Cargo
  boundaries simulated; it creates a real tarball of explicitly synthetic ELF files.
* A relocated populated source archive executing make package OFFLINE=1 and
  make verify through actual subprocesses, producing all expected payload files.
* Matching debug links, latest archive alias and checksum, and removal of stale
  success pointers following a failed build.

Retained tests cover source locking, recovery and tamper detection; dependency
lock overlays and update evidence; compiler identity and drift; vendor checks
and relocation; amd64/arm64/portable flag selection; ELF architecture, PIE,
RELRO and stack policy; archive normalization; installation path, symlink,
conflict and modified-uninstall protections; Forky origin/codename selection,
version comparison, compiler metapackage expansion, localization, no-removal
and no-cross-suite APT policy; nightly selection, component availability,
identity checks and channel-race rejection.

The tests use real local Git, GCC ELF compilation, GNU binutils, archive
creation/extraction/checksums and filesystem installation/removal. Rustup,
rustc, Cargo, APT package data, and nightly manifests are SIMULATED. Synthetic
fixture versions and commit strings are not claims about current releases.
No generated fixture executable is included in the distributed codebase.

Distribution creation itself checks that the copied driver starts under
isolated Python and that its syntax/whitespace checks pass. The final archive
was independently extracted, its SHA256SUMS checked, and its Makefile tests
executed. This guards the downloadable artifact rather than only a development
working directory that might conceal missing files or import-path problems.

## Not verified here

A network attempt to github.com failed with DNS resolution error. Rust/rustup
are not installed in the authoring sandbox. Therefore no real current upstream
Rust compilation, live nightly installation, Forky APT transaction, real
resctl CLI smoke run, benchmark, hardware tuning or IOCost calibration has been
executed here. The opt-in Forky CI build has not been run either. ARM flag data
is tested, not executed on ARM hardware.

This download is the build-and-packaging implementation. A networked Forky host
with the user's existing rustup is required for the real `make package` build.
Only successful compilation, ELF validation, smoke checks and packaging publish
a binary archive. No silent old-nightly fallback or pretend binary is used.
