# resctl-bench complete source release - build kit 2.3.0

This is the complete supplied resctl workspace, with a reviewed **native source
repair**, not another IOCost Lab wrapper or a substitute benchmark. The upstream
package version remains 2.2.6. The base commit is
`bef3b59c01ec79f3601ae6cf43ed2e34ad8fc45b`; the intentional local patch is recorded
in `patches/` and `source.lock.json` and the native version retains its honest
`-dirty` suffix.

## What failed and what changed

The supplied output records a successful patched latency probe, then
`resctl-bench` starts `rd-agent --reset`. Reset deletes `work/misc-bin/` and the
old binary regenerates the original, incompatible BCC helper. Its compiler then
fails the `sizeof(struct filename) % 64 == 0` assertion. A wrapper-only file
patch cannot survive that lifecycle.

This release embeds the Python 3/BCC language-option correction **in rd-agent's
source**. Startup also atomically reconciles old generated helpers with the
executable's embedded bytes. Reset and ordinary restarts therefore use the same
reviewed source. The BPF measurement program, coefficient generator, benchmark
jobs and result schema are unchanged.

The archive also exposed native Btrfs device-lookup warnings. The old native
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
make doctor
make package
make verify
```

Do **not** run compilation with sudo. The default is the installed host Rust,
`TUNE=native`, thin LTO, all four binaries and split debug information. Choose
`make package TUNE=portable` to omit native CPU tuning when distributing to other
compatible CPUs; that does not remove shared-library requirements.

`make doctor` compiles small Rust/C/C++ probes and checks the actual selected
host tools. `make package` compiles locked source, runs the 18 new file-only and
JSON-parsing Rust regressions, exports the compiled embedded helpers and verifies
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

## Actually use the new build with IOCost Lab

**Running the old Lab menu without selecting the new runtime will still use its
old bundled binaries.** The included executable bridge prevents that mistake.
After the successful build above, as root for the benchmark only:

```sh
sudo ./RUN-IOCOST-LAB.sh --lab /absolute/path/to/iocost-lab
```

It checks the staged package, contract and actual embedded helper bytes, then
shows full report / full report and install / preflight actions. It passes the
new runtime through the Lab's existing `--runtime-dir`; it never silently falls
back to the old archive. The existing IOCost Lab 1.5.0 maintenance plan, device
selection, reports and recovery stay in control. There is no scratch prompt.
`--lab` identifies your existing Lab code directory, not a workload directory.

To verify the handoff without launching anything:

```sh
./RUN-IOCOST-LAB.sh --lab /absolute/path/to/iocost-lab --action full --plan
```

The bridge preserves the directory from which it is invoked. **Launch on the
disk you intend to calibrate** because IOCost Lab writes `output/`, including
its workload files, below that directory. A USB repository or USB boot is not
required. The source/build tree may be elsewhere:

```sh
cd /existing/directory/on/the/selected/disk
sudo /absolute/path/to/this-source/RUN-IOCOST-LAB.sh --lab /absolute/path/to/iocost-lab
```

The default four linked full-mode stages remain `iocost-params`, `hashd-params`,
`iocost-qos`, `iocost-tune`. Storage fio is an internal upstream coefficient
calibration dependency, not a replacement entry point. Zram is not a calibration
target; temporary swap handling remains the approved Lab maintenance operation.

## Runtime verification without a workload

Extract the generated runtime archive to a new directory. From its root:

```sh
python3 -I -B runtime_support.py
```

This exports and hashes the actual binary's four embedded helpers, as an
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

All 163 upstream working-tree files are present. The ZIP's missing 160 files
were recovered from its own Git objects and checked against its original
manifest before applying the repair. Original notices and licenses are retained.
Only the reviewed files recorded in the patch differ from the base. No uploaded
host logs, private user Git configuration, old binaries or build caches ship.

`make lint test` runs the Python/source/packaging suite, including real Git,
Make, C ELF, findmnt and Clang fixtures. Synthetic Cargo/BCC fixtures are clearly
labelled and are not native Rust or live BPF tests. `make test-runtime` uses
**real Cargo** on a build host to compile and execute the 18 selected Rust tests.

The delivery environment had no Rust/Cargo and could not fetch a toolchain;
**this modified Rust workspace was not compiled here**. No live kernel BPF test,
physical benchmark, systemd-agent startup or swap transaction was performed here.
See `docs/VALIDATION.md` and the actual `docs/test-results.txt` rather than
interpreting fixture passes as target-host success. Packaging is configured to
require the real native gates on your build host.
