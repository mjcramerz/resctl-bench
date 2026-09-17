# Validation scope - resctl-bench source/build kit 2.3.2

## Actually executed for this revision

The full software suite ran **216 tests: zero failures, errors or skips**.
Actual output is retained in test-results.txt. Machine-readable scope is in
validation.json. These are current results, not copied previous-release passes.

The suite includes real GNU Make subprocesses, isolated Python loading, actual
Git/source manifests and offline recovery, package conflict and integrity gates,
real small C ELF/strip/readelf fixtures and Clang layout checks, and the actual
embedded Python helper logic with a stub BCC constructor. The full Cargo/Rust
build pipeline uses deliberately synthetic scripts/C ELF programs. It is not
a Rust compile, regardless of a fixture printing a simulated Cargo success line.
Existing 204 tests remain, with 12 added cases. Native sources and the repaired
helper hashes are checked against the resealed source lock and patch.

On a real build host, make native-validate runs compiler probes, cargo check,
compilation of test harnesses, packaging and payload verification. Packaging
executes exactly the four reviewed test filters (27 native Rust tests total),
requires a real v2 contract response from all three native commands, checks
embedded helper bytes before/after strip and runs CLI smoke checks. Each Rust
test suite has its own log, and empty/missing test filters fail the build.

## Not executed and not certified

The delivery container has no installed rustc, cargo or rustdoc, and the attempted
compiler download was unavailable. The actual native check attempt is recorded
in native-check-attempt.txt: it exited 2 at tool discovery ("Host rustc not
found") **before compiling any crate**. No current native binary is included.
The modified Rust workspace and its 27 selected Rust tests have NOT been
compiled or executed in this environment. Compilation success is not claimed.

No live BPF attachment, rd-agent startup, D-Bus relocation, writeback service
stop/start, physical disk workload, real swap migration, reboot or persistent
measured IOCost deployment was performed. No CI workflow was executed here.
The repaired pair is not hardware-validated by these software tests. Follow
DELIVERY-REPAIR.md and run the real build/host checks before calibration.

## Source release and extraction

The source release includes checksums and retains licences and the full project
code. Private uploaded host logs, old native executables, Cargo caches, generated
workload files and Python bytecode are not part of the release. The resctl source
snapshot includes its pinned Cargo.lock and a self-contained project-source
recovery archive, but not third-party vendored crates. A clean first build needs
those crate sources or registry access.

Final extraction/checksum/recovery checks are performed against the final tarballs
by the delivery run; they do not establish native compilation. Historical input
validation records are labelled under history/ and are not current evidence.
