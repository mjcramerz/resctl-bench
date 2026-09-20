# resctl-bench complete source release - build kit 2.4.1

**Current matched pair: IOCost Lab 2.6.0, build kit 2.4.1, native marker
resctl-iocost-lab-v3.** Read docs/FAILURE-ANALYSIS-2.4.0.md for the supplied
OOM/restart/TransactionIsDestructive failure. This release moves balloon lifetime
and exact allocation back into rd-agent, checks its identity during calibration,
uses checked systemd stop/replace operations and propagates errors cleanly.
The Lab no longer repairs memory conditions while continuing a measurement.

**Validation:** current results are in docs/VALIDATION.md; these include labelled
Cargo/C fixtures and do NOT establish Rust compilation. This delivery environment
has no Rust compiler. The modified Rust workspace and its 34 mandatory native
regressions are not executed here. No live disk/systemd/BPF calibration is claimed.
Run the real native-validate gate before installation. Old compiled archives from
the upload are deliberately excluded. See docs/VALIDATION.md.

This is the complete supplied resctl workspace, with a reviewed **native source
repair**, not another IOCost Lab wrapper or a substitute benchmark. The upstream
package version remains 2.2.6. The base commit is
`bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b`; the intentional local patch is recorded
in `patches/` and `source.lock.json` and the native version retains its honest
`-dirty` suffix.

## Git recovery regression fixed in 2.4.1

`./BUILD.sh lint test` now runs from unpacked sources, an already committed Git
checkout, or a linked worktree. The offline recovery fixture excludes only the
outer `.git`; the locked `upstream/.git` remains required source metadata.
The fixture's Git commands do not inherit unrelated `GIT_*` routing, user/system
configuration, signing requirements, hooks or templates. The first commit remains
a real non-empty commit; the failure is not hidden with `--allow-empty`.

The exact old clean-checkout failure was reproduced, then tested with the repair.
See docs/GIT-TEST-ISOLATION.md. All production native source, source lock, recovery
asset and helper hashes remain unchanged. Native Rust compilation is still a
separate required gate on the build host, not a result of these Python tests.

## Retained repair for the original PATH / host-requirement / panic failures

Read **docs/DELIVERY-REPAIR.md** for the historical IOCost Lab 2.1.1 procedure.
The previous repair added the native v2 contract, correct disabled-policy detection,
fresh sysinfo snapshots and orderly ordinary-job/shutdown failure handling.
The original output.zip showed a host-requirement rejection, not a Cargo
compiler diagnostic. The new package-mode error is covered above. Actual native compilation remains unverified here because
the delivery container has no Rust toolchain; the attempt is recorded.

## Source recovery retained from 2.3.1

The previous build driver rejected a missing `upstream/` directory instead of
restoring the reviewed source. That was a build-system defect, not a Rust
compiler diagnostic. This archive includes **both the complete patched source
and a hash-pinned local recovery copy**. A normal build automatically restores
absent/incomplete source without contacting upstream and without dropping the
native repair. Existing edited/untracked files are never overwritten.

```sh
./BUILD.sh fetch verify-source
./BUILD.sh package verify
```

Run these as your ordinary user. `BUILD.sh` works from another directory too;
source, scripts, config.mk and build output stay anchored to this repository.
`upstream/Cargo.toml` is the actual complete Rust workspace, not a placeholder.
See **docs/SOURCE-RECOVERY.md** for recovery behavior, retained backups, integrity
checks and the distinction between bundled source and third-party Cargo crates.

## Earlier native repairs retained

The earlier 2.3.0 repair addressed a successful patched latency probe followed by
`resctl-bench` starts `rd-agent --reset`. Reset deletes `work/misc-bin/` and the
old binary regenerates the original, incompatible BCC helper. Its compiler then
fails the `sizeof(struct filename) % 64 == 0` assertion. A wrapper-only file
patch cannot survive that lifecycle.

This release embeds the Python 3/BCC language-option correction **in rd-agent's
source**. Startup also atomically reconciles old generated helpers with the
executable's embedded bytes. Reset and ordinary restarts therefore use the same
reviewed source. The BPF measurement program, coefficient generator, benchmark
jobs and result schema are unchanged.

That earlier archive also exposed native Btrfs device-lookup warnings. The old native
lookup tried to stat display strings such as `/dev/nvme0n1p6[/@]`. It now requests
structured findmnt JSON with `--nofsroot --target` and validates the resolved
block device. This applies to both the workload filesystem and swapfiles.

See **docs/NATIVE-REPAIR.md** for evidence, source paths, limitations and the
verification design. No kernel header, system-wide Python link or BCC installation
is patched. No tracing assertion is removed and no latency data is fabricated.

## Build as your ordinary user

From the extracted source directory:

```sh
sha256sum -c SHA256SUMS
./BUILD.sh fetch verify-source
./BUILD.sh native-validate
```

Do **not** run compilation with sudo. The default is the installed host Rust,
`TUNE=native`, thin LTO, all four binaries and split debug information. Choose
`make package TUNE=portable` to omit native CPU tuning when distributing to other
compatible CPUs; that does not remove shared-library requirements.

`make doctor` compiles small Rust/C/C++ probes and checks the actual selected
host tools. `make package` compiles locked source, runs the 34 selected file-only,
JSON-parsing, I/O-policy and contract-parser Rust regressions, exports the compiled embedded helpers and verifies
them byte-for-byte before and after stripping, runs CLI smoke checks, and only
then publishes the runtime archive. Build tests do not run storage workloads,
change swap, invoke normal rd-agent startup, or attach BPF.

The verified runtime archive is:

```text
dist/resctl-bench-latest.tar.gz
dist/resctl-bench-latest.tar.gz.sha256
```

The versioned archive is alongside it. `.work/last-package.json` records the
verified stage. A failed package attempt removes stale latest/success pointers;
it does not reuse an old executable as a successful build.

Build logs, exact commands, compiler/CPU flags, ELF information, source and
Cargo hashes, and embedded-support/test results are included in the runtime
package under `share/resctl-bench/build/`.

### Existing toolchains and dependencies

The kit does not install or update Rust, change a rustup default, rewrite Cargo
configuration, unset variables in your shell, or switch compilers after a
failure. Already installed native Rust or rustup-managed tools are supported.
Explicit `HOST_RUSTC`, `HOST_CARGO`, and `HOST_RUSTDOC` paths are optional.
Inherited Cargo output/flag overrides are scoped away only in child processes;
all build output stays in `.work/`. Normal registry/cache configuration is kept.

GNU Make, Python 3.11+, Git, C/C++ tools, binutils, pkg-config, OpenSSL development
files and compatible installed Rust/Cargo/rustdoc are prerequisites. The existing
Debian Forky build policy is retained. `make deps-plan` previews its optional
package transaction; `make deps` and `make deps-runtime` are explicit package
changes and are never invoked by `make package`. See `packages/` and docs/BUILD.md.

On other Debian versions, `ALLOW_UNSUPPORTED_DEBIAN=1 make package` is an
explicit experimental build override, not permission to use Forky APT commands
or a claim of verified platform support.

The full project source is included. Third-party Cargo crates were not in the
uploaded ZIP and are **not vendored in this source snapshot**. A first build
needs a populated cache or access to the locked crate sources. After obtaining
those dependencies, `make source-dist` produces a source distribution with
vendored crates. `OFFLINE=1` requires those dependencies already available.
`latest`, `latest-complete`, and `update-source` are intentionally blocked for
this patched release so they cannot silently discard the repair. Rebase and
revalidate a future source update explicitly.

## Install and use with IOCost Lab 2.5.0

After `./BUILD.sh package verify` succeeds, install the actual new binaries:

```sh
sudo ./BUILD.sh install
```

IOCost Lab 2.x uses the installed `resctl-bench`, `rd-agent` and `rd-hashd` on
PATH. Set the Lab run.env TARGET_OUTPUT_DIR to an existing directory on the selected disk, then launch:

```sh
cd /absolute/path/to/iocost-lab
sudo ./RUN.sh doctor
sudo ./RUN.sh
```

No runtime directory or scratch-directory prompt is needed. The Lab checks its
own prerequisites, shows its maintenance plan, and handles workload/report
placement and restoration. Output on the disk being calibrated is intentional;
USB boot or a USB repository is not required.

The Lab verifies the compiled v3 marker on all three installed programs, plus
the five helper hashes. Restore any old tracked session before a fresh run; do
not resume OOM-affected calibration. See the Lab README for the full procedure.

The optional `RUN-IOCOST-LAB.sh --lab /path/to/iocost-lab` bridge is retained. It
uses help-only interface detection: Lab 1.5.x receives the verified package via
`--runtime-dir`; Lab 2.x receives the matching root-owned installed directory
via `--bin-dir`. It never supplies the removed legacy option to Lab 2.x or falls
back to old binaries. For Lab 2.x, install first: a user-owned build stage is not
an installed runtime. `--action full --plan` verifies/prints without launching.

The four native full-mode stages remain `iocost-params`, `hashd-params`,
`iocost-qos`, and `iocost-tune`. Storage fio remains an internal coefficient
calibration dependency, not a replacement benchmark entry point. Temporary
swap handling remains the Lab's approved maintenance operation.

## Runtime verification without a workload

Extract the generated runtime archive to a new directory. From its root:

```sh
python3 -I -B runtime_support.py
```

This exports and hashes the actual binary's five embedded helpers, as an
ordinary user. It cannot establish that your kernel accepts the BPF program.
For a separate, explicitly requested real collector initialization test:

```sh
sudo /usr/bin/python3 -I -B runtime_support.py --probe-latency nvme0n1
```

Replace the example with the selected whole disk. The probe attaches real BPF
but does not start a storage workload or change swap. A failure is reported,
never bypassed. Normal benchmarking retains its own startup check. Read
`docs/RUNTIME.md` before benchmarking: it remains a write-heavy whole-host
maintenance operation with filesystem trim and potential data-loss risks.

## Source completeness and validation

All 163 upstream working-tree files are present, both directly and in the offline recovery archive. The preserved base manifest and real Git objects anchor the reviewed local
delta. The current tarball is usable directly without reconstructing a missing
workspace. Original notices and licenses are retained.
Only the reviewed files recorded in the patch differ from the base. No uploaded
host logs, private user Git configuration, old binaries or build caches ship.

`make lint test` runs the Python/source/packaging suite, including real Git,
Make, C ELF, findmnt and Clang fixtures. Synthetic Cargo/BCC fixtures are clearly
labelled and are not native Rust or live BPF tests. `make test-runtime` uses
**real Cargo** on a build host to compile and execute the 34 selected Rust tests.

The delivery environment had no Rust/Cargo and could not fetch a toolchain;
**this modified Rust workspace was not compiled here**. No live kernel BPF test,
physical benchmark, systemd-agent startup or swap transaction was performed here.
See `docs/VALIDATION.md` and the actual `docs/test-results.txt` rather than
interpreting fixture passes as target-host success. Packaging is configured to
require the real native gates on your build host.
