# Source recovery repair - build kit 2.3.1

## The reported failure

The 2.3.0 driver contained this deliberate failure in `Builder.fetch()`:

```text
Patched source tree is missing. Re-extract the complete source tarball;
the base remote commit alone does not contain the repair.
```

It ran before Cargo. The guard prevented a silent return to unpatched upstream,
but supplied no recovery path. `upstream/` was also ignored by the kit's Git
rules, so a Git-based transfer could retain the source lock and patch while
omitting the populated working tree. The current error alone does not establish
which copy/extraction/cleanup step removed the user's directory.

The new release fixes the missing recovery mechanism, not the native patch by
replacing it with a remote base commit.

## Contents and recovery

The distribution includes BOTH the full 163-file patched `upstream/` tree and
`source-cache/upstream.tar.gz`. The latter contains the same full source and a
minimal real upstream Git identity. Its SHA-256 is recorded in `source.lock.json`.
It is intentionally tracked even when the mutable `upstream/` checkout is ignored.
There is no git submodule, symlink to another checkout, Git LFS pointer, network
bootstrap script, or placeholder source in this snapshot.

`make fetch` and every native build path verify the existing source. If source
is absent/incomplete, or exact source has lost its local Git metadata, the driver:

1. Checks the source manifest and refuses conflicting/untracked working files.
2. Verifies the bundled recovery archive against its pinned hash.
3. Extracts into a private staging directory. It rejects absolute/escaping paths,
   duplicate entries, links, devices, unsafe modes, and oversized contents.
4. Checks all 163 file hashes/modes, the locked Cargo.lock, real Git HEAD,
   reviewed patch/diff, and the native embedded-helper contract.
5. Publishes the validated tree by rename. An existing incomplete tree is retained
   in `source-recovery-backups/`, outside `.work/`, so `make clean` cannot erase it.

The visible source in each release archive uses the recovery copy's exact Git
metadata as well. A refreshed local Git index is not substituted: that would
cause a false SHA256SUMS failure after recovery despite identical source code.
The driver's Git diff checks explicitly disable diff.autoRefreshIndex: Git can
otherwise rewrite the stat cache even when GIT_OPTIONAL_LOCKS=0 is set. Source
verification therefore remains read-only. The final-archive regression checks
the full manifest, including Git metadata, before AND after recovery.

No source network access is used, including with `OFFLINE=1`. Modified source or
unknown files are NOT overwritten. An invalid/missing recovery archive is a real
integrity/availability failure, not permission to fetch unpatched source. A fully
valid existing source tree does not need the redundant cache in order to build;
`make verify-source` additionally checks the release's recovery asset.

Useful commands:

```sh
./BUILD.sh fetch verify-source
./BUILD.sh restore-source
./BUILD.sh snapshot-dist
```

No routine invocation of `restore-source` is required: builds do this when needed.
`BUILD.sh` resolves its own real path. The Makefile also anchors scripts and
config.mk to its location, including `make -f /path/to/Makefile` and paths with
spaces. Build output still belongs to this repository's `.work/` and `dist/`.

`kit-dist` is no longer an incomplete kit for this reviewed patched release:
it produces the same complete source snapshot as `snapshot-dist`. `source-dist`
still includes vendored Cargo dependencies and therefore needs the actual host
Cargo/cache/network required to obtain those dependencies.

## What is not changed

The 163 Rust/project source files, Cargo.lock and native repair patch are
byte-for-byte identical to the reviewed 2.3.0 repaired source. The fixes for BCC
compiler flags, reset-safe embedded support files and native Btrfs source lookup
are retained. The package version is still 2.2.6; 2.3.1 versions the build kit.
No tracing bypass, fabricated benchmark result or unpatched executable is added.

All third-party crates are not vendored in this delivery. Offline recovery of
PROJECT SOURCE does not imply that a machine with an empty Cargo cache can
compile offline. Rust, Cargo, rustdoc and the documented Debian development
packages must already be installed; this kit does not change Rust installations.

## IOCost Lab 2.x integration

After successful compilation/package verification, install the runtime:

```sh
sudo ./BUILD.sh install
```

IOCost Lab 2.x normally uses those root-owned commands on PATH directly. It must
not be passed the legacy `--runtime-dir` switch or a user-owned build stage.
The optional bridge now probes only the Lab's `run --help` to select the correct
interface: `--runtime-dir` for Lab 1.5.x, `--bin-dir` for Lab 2.x. For Lab 2.x it
checks the installed command bytes against this successful build and refuses an
old/missing installation before launching. The Lab retains its own root-ownership,
path, companion-version, maintenance-consent and benchmark checks.

## Regression evidence

`tests/test_source_recovery.py` uses the actual patched source, real Git and Make,
not a mock Rust compiler, to verify missing/empty/partial source, lost/corrupt
Git metadata, offline Git-clone recovery, relocation, make-clean preservation,
archive integrity and refusal to overwrite edits. `tests/test_lab_interfaces.py`
checks the help-only interface handoff and stale-installation rejection.

The complete suite also retains the previous clearly labelled fake-Cargo
orchestration tests. Those do not constitute native Rust compilation. Refer to
VALIDATION.md for the exact execution boundary.
