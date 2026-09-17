# Packaging follow-up: build kit 2.3.3 / IOCost Lab 2.1.1

## The two reported errors are one failed build followed by an install attempt

The reported commands were:

```
make package
ERROR: Support file does not have the required executable mode: biolatpcts.py
sudo ./BUILD.sh install
ERROR: Cannot read .../.work/last-package.json: ... No such file or directory
```

The second command cannot install an unsuccessful build. The package driver
intentionally removes its success pointer before starting a new attempt, then
publishes `.work/last-package.json` only after staging and checks succeed.
Creating this JSON by hand or falling back to an old stage would install an
unverified or stale result. This repair does neither.

## Reproduced cause and corrected boundary

The previous source tarball contains all four embedded helper assets with mode
0755. An ordinary-user GNU tar extraction honors the user's umask: 027 produces
0750, and 077 produces 0700. The prior build driver treated those safe source
permissions as an invalid *runtime export*. This was a defect in the supplied
validator, not evidence that the user had damaged the scripts.

We reproduced the exact `biolatpcts.py` rejection from the 2.3.2 tarball using
ordinary-user extraction and Make with both restrictive umasks. The user's
actual umask was not provided; the reproduction demonstrates a sufficient cause
for this exact message, not a measurement of that host's settings.

`runtime_support.validate_source()` now verifies regular source files and their
reviewed hashes without requiring runtime-export mode 0755. Rust `include_bytes!`
reads these assets at compile time; it does not execute the source scripts.
The builder still independently verifies the entire source manifest, Git
executable-bit identity, reviewed patch, helper hashes, BPF program hash and
Cargo.lock. Removing the recorded source executable bit still fails source-lock
verification. User source permissions are not widened or rewritten.

`run_export()` and latency-probe verification still require exact mode 0755 on
all four *exported* helpers. The existing native exporter sets that mode
explicitly. Hash mismatch, unexpected files, nonregular files, links, wrong
native markers and mixed companions remain errors. This change does not mask
an unsafe or faulty native export.

GNU tar reference: https://www.gnu.org/software/tar/manual/html_node/Setting-Access-Permissions.html
Rust reference: https://doc.rust-lang.org/stable/std/macro.include_bytes.html

## Installation/publication handling

`make install` and `make verify` share a completed-package loader. It checks the
publication record, its field types, the stage and archive paths, absence of
path symlinks, the stage's existence and the archive hash. Missing, malformed,
relocated or damaged state stops before the installer runs, with instructions
to finish `make package verify` as an ordinary user. Payload checksums and
conflict-safe installation remain enforced by the existing installer.

Newly created install directories are explicitly set to 0755 so a restrictive
umask cannot make a new system bin/ inaccessible. Existing directories, including
private DESTDIR ancestors, retain their original permissions.

Installation still does not compile, download or change Rust; it must not start
an implicit root build. `FORCE=1` remains an explicit overwrite choice for the
installer, never a benchmark-requirements bypass.

## Use the new source pair

Extract each new source tarball into a new directory, rather than merging it
with an old `.work/` or `dist/`. Keep any existing calibration outputs/backups.
No chmod workaround or global umask change is needed.

From the new **resctl-bench** source root, as your ordinary user:

```sh
sha256sum -c SHA256SUMS
make verify-source
make package verify && sudo ./BUILD.sh install
```

The `&&` is deliberate: installation is attempted only after the build and
verification succeed. For the expanded compiler gate, replace `make package
verify` with `./BUILD.sh native-validate`. Both need an already installed Rust,
Cargo, rustdoc, C/C++ toolchain and the documented dependencies. Cargo crates
are not vendored in this source snapshot; registry access or a populated cache
is needed for a first build. No Cargo dependency was updated in this repair.

A conflicting old installation is not silently overwritten. Inspect/back up it
first, then use `sudo ./BUILD.sh install FORCE=1` only for deliberate replacement.
If the build fails for a different reason, its FIRST error is the relevant
failure; do not run install or create `.work/last-package.json` yourself.

Then check the matching **iocost-lab** tree:

```sh
sudo /absolute/path/to/iocost-lab/RUN.sh doctor
```

See DELIVERY-REPAIR.md for the previously repaired host I/O-policy, D-Bus,
writeback-service and report/HWDB workflow. This packaging change does not
remove any of those protections or authorize a disk workload.

## What is incorporated and what is verified

The complete native source tree, pinned Cargo.lock, source lock, reviewed
native patch, offline project-source recovery asset and native v2 marker are
retained byte-for-byte from 2.3.2. The four helper hashes match the Lab's adapter.
The Lab companion is 2.1.1, with the new build-kit recommendation and restrictive
umask runtime-interface regressions; it does not invent a new native protocol.
Previously compiled v2 binaries are not made incompatible merely by this
build-kit patch-level change.

Regressions exercise actual GNU tar, source verification, Make entrypoints,
staging, publication, checksum checking and installation under umasks 022, 027
and 077. The packaging pipeline uses explicitly labelled C ELF/Cargo test
doubles, not compiled resctl binaries. The Lab tests use synthetic installed
commands and reject mixed old/new native markers.

Read VALIDATION.md and the accompanying current logs for actual results.
Native Rust compilation and live hardware calibration are not certified by
these tests. The delivery environment has no Rust toolchain and cannot resolve
the download host. A real source build reaches that explicit prerequisite
failure after the repaired source check; it does not silently claim success.
