# resctl-bench build kit 2.4.0 validation - 2026-09-20

| Executed check | Result |
| --- | --- |
| Full root software suite | 261 passed; 38.462 s |
| Source tar extracted as uid 65534 with umask 077 | 261 passed; 39.823 s; 0 skipped |
| Source integrity | Complete workspace, Cargo.lock, patch, source manifest and recovery hash passed |
| Syntax/whitespace | 19 builder/test Python files passed |
| Exact native balloon Python tests | 23 passed, including real small touched mappings and notification sockets |
| Paired Lab | 1,064 passed as root; 1,058 passed plus 6 root-only skips as ordinary user |
| Actual native build | Source verification passed, then missing rustc; exit 2 |
| Rust regression/hardware benchmark | NOT executed |

Current logs are in validation-2.4.0/, with convenient copies at test-results.txt,
test-results-unprivileged-077.txt and native-check-attempt.txt.

## What the executed tests do and do not establish

Real Python allocations, local Unix notification sockets, harmless child processes,
atomic filesystem transactions, Git, Make, C/ELF packaging fixtures, command-line
parsing and failure injection were exercised. The build tests use explicitly
labelled synthetic Cargo doubles/C binaries for pipeline scenarios. None of those
passes is represented as compiling the actual Rust workspace or calibrating a disk.
Memory-control tests use temporary files, not the host's real sysctls. Legacy swap
restoration fixtures explicitly select an old policy; new production policy allows
zero in-run growth. No real swapfile was activated by these tests.

The original 2.4 Lab suite had 1,087 tests. Replacing its 75 adaptive-repair tests
with 24 fail-closed tests, adding 26 memory-policy transaction tests and two final
verdict/resume tests produces 1,064 current tests. The old adaptive expectations
are deliberately not retained as current behavior. Historical source/tests/docs
remain labelled under history/. The buildkit adds 23 exact-balloon Python tests
to its original 238 software tests, producing 261.

## Native/hardware boundary: NOT executed

The modified Rust workspace was not compiled. The real ordinary-user
native-validate attempt verifies the complete patched source and then exits 2 at
`Host rustc not found`, before compiling a crate. The attempt uses an explicit
unsupported-Debian override only because this container is Debian 13 rather than
the retained Forky build target. No automatic compiler installation or package
change was performed. The separate installed-native test attempt ran zero tests:
resctl-bench was not installed. These are recorded unavailable gates, not passes.

The 34 selected Rust regressions (10 helper, 8 storage-resolution, 6 IO-policy,
3 runtime-contract, 3 lifecycle and 4 balloon-identity tests) are mandatory in the
real package gate on the build host; they have NOT run in this delivery container.
No live systemd transient-unit lifecycle, BPF attachment, hardware coefficient/QoS
tuning, reboot, real swap activation or measured-profile deployment was executed.
No successful user-host outcome is claimed. A host-native compile failure remains
possible until that gate is actually run; do not treat source inspection as proof.

## Source and archive provenance

All production/test/fixture sources compared against the ordinary-user tested
copies are byte-identical; the file counts are in tested-source-comparison*.json.
Only documentation/evidence was added afterward. The full native workspace,
real base Git object/history needed for version identity, aggregate reviewed patch,
source lock/manifest, Cargo.lock and a hash-pinned local recovery archive are
included. The working tree honestly remains dirty relative to the original base.
The BPF collector, coefficient generator and IOCost stage sources are unchanged
from the supplied ZIP; preserved-measurement-source*.json records their hashes.

Old compiled archives, build caches, private toolchain paths and the user's support
bundle are excluded. Third-party Cargo dependencies are locked but not vendored;
normal cache/network access is needed for the first native build. `make source-dist`
can vendor dependencies on the provisioned host. Checksums are regenerated for
this delivery. Historical test logs are not current-result claims.
