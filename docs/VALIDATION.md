# resctl-bench buildkit 2.4.1 validation - 2026-09-20

| Executed check | Result |
| --- | --- |
| Root `./BUILD.sh lint test`, clean committed outer checkout | 266 passed; 57.69 s |
| Ordinary user, tar extraction, umask 077 | 266 passed; 57.884 s |
| Original reported test on old implementation | Exact clean-tree commit failure reproduced |
| Five new Git isolation regressions | Passed, included in full suites |
| Paired Lab suite | 1,100 root passes; 1,094 user passes plus 6 skips |
| Actual native build / installed-native tests | Unavailable, not passed |

Current logs and JSON are in `validation-2.4.1/`. The old regression reproduction
is deliberately a failing historical test and is labelled as such; it is not
a failure in the repaired suite. The root full suite ran from a real committed
`mcr/main` checkout, rather than only an unversioned archive.

The previous 261-test suite gained five real Git cases: clean committed source,
linked worktree, root Git symlink, inherited Git environment, and user hooks /
commit-signing / template settings. Existing recovery tests still require a
real nonempty first commit and retain `upstream/.git`; no `--allow-empty` or
blanket error suppression was added. See `GIT-TEST-ISOLATION.md`.

Both complete buildkit suites were additionally run with inherited `OFFLINE=1`.
The four local-source fixture assumptions exposed by that environment are fixed
without weakening the separate production/offline tests. The original failure
log is retained as `ambient-offline-fixture-failure-reproduced.txt`.

## Scope and limitations

The tests exercise real Python, local files, Unix notification sockets, Git, Make,
harmless subprocesses and signal delivery, including interrupted transactions.
Kernel-control tests use temporary fake proc/sys trees; they do not change the
delivery host's real memory controls. No real swap was activated. Build-pipeline
fixtures use explicitly labelled synthetic Cargo/C executables; their passes do
not count as compiling the real Rust workspace.

The ordinary-user runs used uid 65534 and source extracted under umask 077.
All production/test/fixture files compared to that tested copy are byte-identical;
only documentation and validation evidence were added afterward. Detailed hashes
are recorded in tested-source-comparison.json.

## Native and hardware gates: unavailable, NOT passed

The real `./BUILD.sh native-validate` attempt verified locked native source and
then exited 2 at `Host rustc not found`. It was run as an ordinary user with the
unsupported-Debian override solely to reach the availability check in this
container; that is not a deployment recommendation. No Rust/compiler installation
or package change was performed. `make check-installed` ran zero tests because
the native executables were absent. Both actual failure logs are included.

The previously patched native workspace still has NOT been compiled here.
The real build-host gate must pass all 34 required native regressions and the
package checks before installation. No live XanMod/le9uo control test, systemd
transient-unit lifecycle, BPF attachment, physical-disk calibration, real OOM
experiment, reboot or measured-profile deployment was performed.

## Source provenance

All 163 native workspace files are byte-identical to the preceding delivery.
The source lock, manifest, local recovery archive and Lab compiled-helper
contract module are also unchanged. Existing successfully built and validated
v3 executables remain compatible; this is not a claim that this environment
compiled them. Native Git stat-cache metadata is excluded from source comparison
and is normalized by the builder's source-snapshot packaging command.

Both complete project source trees, tests, reviewed native patches, Cargo.lock
and pinned source recovery are included. Third-party Cargo crates are locked
but not vendored, so the first native build needs its normal cache/network and
installed toolchain. No old binaries, private support bundle, build caches, or
outer developer Git checkout are included. Older versioned validation folders
are retained as explicitly historical records, not current-test claims.
