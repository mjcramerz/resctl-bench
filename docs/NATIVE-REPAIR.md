> Historical repair background retained from the supplied source. For the
> current uploaded failures and this revision, read DELIVERY-REPAIR.md.

# Native runtime repair: evidence and implementation

## Evidence supplied for this repair

The latest uploaded output archive contains these independently useful records:

| Relative session record | Observation |
| --- | --- |
| `agent-startup/iolat-probe.json` | The patched IO-latency initialization returned 0, with no stderr. |
| `agent-diagnostics/while-failing/agent-journal.txt` | The service command includes `--reset`; it removes the generated misc-bin directory. |
| The same service journal | The subsequent Python traceback shows the original `BPF(text=bpf_source)` call without the reviewed cflags, and the `40 == 0` kernel-header assertion. |
| `diagnostics-before/findmnt.json` | Btrfs SOURCE fields include filesystem-root suffixes such as `/dev/nvme0n1p6[/@]`. |
| The same service journal | rd-hashd reports native filesystem/swap device lookup failures before the fatal BPF initialization failure. |

The fatal failure is not a zram benchmark and not evidence that the earlier
cflags correction itself failed. It is a lifecycle mismatch: the preflight
helper passed, but the old executable subsequently replaced it. The earlier
wrapper re-preparation test did not exercise reset and therefore missed this.

The second problem is independently visible in the provided source:
`path_to_devname()` took findmnt's display SOURCE string and passed it directly
to `fs::metadata()`. A Btrfs suffix is not part of a device-node filename. That
lookup is also used by `swap_devnames()`, which the agent's prerequisite checks
call with `?`; retaining the broken lookup would leave a further startup failure
after repairing BPF. The journal's lookup warnings are evidence of this path,
not a completed benchmark or proof that no additional host prerequisites remain.

## Source changes

### rd-agent/src/misc/biolatpcts.py and biolatpcts_wrapper.sh

The Python entry point uses Debian `/usr/bin/python3`. BCC receives
`-fms-extensions` and `-Wno-microsoft-anon-tag`. These are C language options used
by BCC's upstream kernel-build helper for Linux's anonymous tagged members:
https://raw.githubusercontent.com/iovisor/bcc/master/src/cc/frontends/clang/kbuild_helper.cc

The complete `bpf_source` string is unchanged, as are timestamp selection, disk
filter substitution, histograms and result output. The coefficient generator
and sideloader source are unchanged. The wrapper delegates with exec to system
Python in isolated/no-bytecode mode. Comments and bytes match the already
reviewed IOCost Lab 1.5.0 compatibility form so its known-hash guard accepts the
new native helper. They are intentionally not gratuitously reformatted.

### rd-agent/src/misc.rs and src/main.rs

The executable embeds the corrected source through the existing include_bytes
mechanism. `write_misc_bins()` is shared by normal materialization and a new
file-only export path. It compares bytes and mode, refuses nonregular or
symlinked generated files/directories, and installs changes by exclusive
same-directory temporary file + sync + atomic rename. It does not truncate a
live helper or chmod an external hardlink. These are generated assets, not
administrator configuration; deliberate local edits are replaced from the
running binary and should instead be made in reviewed source.

`rd-agent --export-support NEW_DIRECTORY` is processed before setup_prog_state,
normal args files, Config, systemd, storage lookup or BPF. It accepts no other
options and requires a new destination below an existing parent. Only the four
support files are written. It does not introduce a readiness-check bypass.
The native interface README/help documents the option.

The benchmark's reset behavior is **retained**, not disabled to hide the bug.
After reset, the corrected executable recreates the corrected helpers.

### rd-util/src/storage_info.rs

The existing path is canonicalized and queried using explicit
`findmnt --json --first-only --evaluate --nofsroot --output SOURCE --target PATH`.
The result must contain exactly one local /dev SOURCE and that source must
actually be a block node. JSON preserves paths with spaces without ad-hoc shell
splitting. No Btrfs suffix is manually chopped from an arbitrary device name.
The existing device-number-to-whole-queue mapping is retained.

Malformed swap entries now propagate an error instead of being silently omitted.
This is not new support for RAID, multi-device Btrfs, encrypted mappings or zram
as calibration targets. Topology restrictions and the Lab's device checks remain.

The util-linux interface contract is documented at:
https://man7.org/linux/man-pages/man8/findmnt.8.html

## Build and package acceptance gates

The original base Git commit and Cargo.lock are preserved. The approved delta
is recorded as a patch, with original and patched manifests and a helper-byte
contract. Every build checks the full manifest, Cargo.lock, base Git identity,
patch hash/diff, original manifest hash and runtime-contract hash. The version
is honestly based on the real commit with a dirty suffix. No synthetic clean
commit, fake upstream version or VERGEN override is introduced.

`make build` requires a real executable to export the expected support bytes
before publishing its result record. `make package` additionally requires:

1. `cargo test` for `rd-agent`'s 10 `misc::support_tests` regressions.
2. `cargo test` for `rd-util`'s 8 `storage_info::source_resolution_tests` regressions.
3. Post-strip executable help/version checks and compiled helper-byte comparison.
4. Package checksums and installer verification before publishing latest pointers.

Cargo's `--target-dir` is placed before the `--` test-harness separator. Both
native test filters operate only on files/parser data, not the existing suite's
hardware-oriented tests. A missing/empty native test filter is rejected.
The 10 helper tests cover reset/recreation, stale upgrades, byte/mode fidelity,
symlinks, hardlinks, export-only operation and conflicting CLI options. The 8
storage tests cover fixed findmnt options, NVMe/eMMC/USB device names, spaces,
empty/ambiguous/malformed JSON, pseudo filesystems and embedded NUL input.

The post-link check invokes a compiled-binary interface, not strings(1), a source
hash alone, a substituted script, or normal startup with bypass flags. Old
binaries without --export-support cannot satisfy it. Both unstripped and staged
binaries are checked. Native test logs and exported helper hashes are shipped
in build provenance.

## Lab handoff and compatibility

For IOCost Lab 2.x, install with `sudo ./BUILD.sh install` and run the Lab normally.
The bridge detects Lab 2.x and verifies the installed binaries before using
`--bin-dir`. The following describes its retained Lab 1.5.x path.
Use `RUN-IOCOST-LAB.sh --lab /path/to/iocost-lab` after a successful build. The
bridge verifies this build's stage and passes it explicitly as --runtime-dir.
The old Lab's default vendor archive is not modified and is never the bridge's
fallback. With --plan it verifies/prints the command without launching it.
It preserves cwd, the full four-job plan, interactive disk selection, one
maintenance approval and separate installation approval. It does not add --yes,
force flags, tracing bypasses, raw writes or manual scratch arguments.

Result data stays compatible with the supplied Lab 1.5.0 parser. Retaining the
true 2.2.6/base Git identity and exact helper form is intentional. It does not
mean the patched source is an unmodified official release.

## Unverified operations

The target host must still compile and link the actual modified workspace and
initialize BPF against its running kernel. Neither a Python import, a C fixture,
a source-level check nor an embedded-file export establishes that all benchmark
jobs complete on that hardware. No live modified-binary run or hardware benchmark
was possible in the delivery environment. See VALIDATION.md.
