# Validation scope - source release 2.3.1

## Performed in the delivery environment

The actual results are in `test-results.txt` and `validation.json`. All 204
Python/source/build-system tests passed in one complete run, with zero failures,
errors or skips. Interrupted development runs are not counted as completion.
There are 32 real source-recovery/archive tests and 10 additional Lab interface
tests. The latter use help-only shell fixtures and byte-identity fixtures, not
storage workloads. The actual IOCost Lab 2.0.0 help was also queried successfully. The supplied Git
objects restore the complete source, all original manifest hashes are checked,
and the final archive is extracted and its manifest/provenance reverified.

Real operations include Python syntax/AST checks, GNU Make entrypoints, Git
source/patch checks, C compilation to ELF, strip/objcopy/readelf, package and
installer checksum/conflict tests, extraction/relocation, real util-linux
findmnt output, and real Clang compilation of a small structure-layout fixture.

The Clang fixture fails the same `40 == 0` structure-layout assertion without
the required C language extension, also fails with warning suppression alone,
and passes structure-size/member-offset/access assertions with the correction.
It is not a compilation of the target host's complete Linux headers or a BPF
attachment. The real findmnt mountinfo fixture demonstrates that the old query
returns `/dev/nvme0n1p6[/@]` and --nofsroot returns `/dev/nvme0n1p6` without mounting
anything or using an actual block device.

BCC tests execute the actual helper's Python logic against a clearly marked
stub BCC constructor. Pipeline tests use synthetic Cargo/Rust scripts and tiny
real C ELF fixtures to check orchestration, error propagation and packaging.
Those fixtures are deliberately labelled. Their output is **not** proof of
native Rust compilation, and no fixture executable is shipped as resctl-bench.

## Not performed here

The delivery environment has no installed Rust/Cargo and cannot obtain a
compiler through its network. The modified Rust workspace and its 18 selected
Rust tests have therefore **not been compiled or executed here**. No modified
native rd-agent executable is supplied in this source-only archive. No actual
kernel BPF attachment, normal systemd-agent startup, swap preparation/restoration,
physical-device workload or measured IOCost configuration installation was
performed. No GitHub workflow was run. Native amd64/arm64 and different CPUs,
Debian releases or kernels do not constitute an exercised hardware matrix.

There is no native-build success log in this source archive because no such
build happened. The former user build metadata and raw journals are not
republished as evidence of this revision.

## Mandatory build-host checks

`make doctor` exercises the actual installed compiler/linker. `make package`
compiles the complete selected native binaries, requires their ELF identity and
compiled helper exports to match the reviewed source, runs the real 10
rd-agent helper and 8 rd-util parser tests, repeats compiled checks after strip,
runs CLI smoke checks, and verifies payload checksums before publishing a
success pointer. Empty native test filters are rejected. These are real checks
when executed with actual host Cargo, not a substitute for executing them here.

The stage includes `share/resctl-bench/build/runtime-unit-tests.json` and its
logs, `compiled-support.json`, exact source/flags/compiler metadata and hashes.
A source update cannot silently remove the reviewed patch. A failed package
attempt does not leave the old latest pointer masquerading as a successful build.

A further explicitly requested target-host check, `runtime_support.py
--probe-latency DEVICE`, initializes the actual BPF collector without a storage
workload. Full benchmarking remains a separate approved maintenance operation
through IOCost Lab. Its success, accurate measurements and safe restoration
cannot be established from file exports, imports, compilation or fixture tests.

## Post-archive checks

The separate downloadable release-validation record reports fresh-extraction
checksum verification, actual recovery after deleting the QA copy's upstream/
directory, and fresh extracted unprivileged recovery/interface tests. These
checks run against the finished artifact, not against a hand-populated source
path. They do not add a claim of native Rust compilation.
