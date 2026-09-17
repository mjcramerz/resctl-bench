# Validation scope - resctl-bench build kit 2.3.3

## Current software results

The full root software suite ran **238 tests, all passed**. The same suite
ran again as an ordinary user after extracting the source archive with
**umask 077**, with **238 passed, 0 skipped, zero failures/errors**.

Current logs: **test-results.txt** and **test-results-unprivileged-077.txt**.
Machine-readable scope: **validation.json**. These logs are not copied passes
from the previous delivery; the previous records remain under **history/**.

## The reported packaging failure was reproduced and tested

**mode-reproduction.json** records ordinary-user extraction of the actual
previous 2.3.2 tarball with umasks 022, 027 and 077. The 027/077 extractions
produce the exact reported `biolatpcts.py` error. With the corrected validator,
all three pass source verification without changing source modes. A package
attempt then reaches the missing-Rust prerequisite instead of the mode error.
The missing manifest remains a failed build, never fabricated installation
success. The new install diagnostic describes the required build-first order.

**permission-regressions.txt** records 20 focused Python/filesystem tests.
The full build-kit suite includes actual GNU tar/Make/staging/checksum/installer
pipelines under all three umasks, with a real synthetic C ELF and a labelled
Cargo double. Those pipeline tests also check exact exported helper modes,
installed executable and newly created directory modes, retention of private
existing directories, and refusal to install after archive corruption.
They are NOT a real Rust or resctl benchmark build.

The Lab's two added regressions inspect synthetic installed commands under
restrictive umasks, verify that private source assets are not chmodded, and
continue rejecting mixed native repair markers. Existing report, model/QoS,
HWDB/deployment and host-recovery tests remain present. Fixture measurements
are labelled test data, not calibrations of the user's disk.

## Source integration and preservation

**pair-preservation.json** records byte-for-byte retention of all 163 native
source files, Cargo.lock, the reviewed patch, source lock/manifests and recovery
archive from 2.3.2. It also checks all four Lab/native helper hashes and the
shared `resctl-iocost-lab-v2` marker. No dependency, measurement program,
coefficient generator, native result schema or host-requirement bypass was
introduced by this packaging repair.

## Native/hardware limits

This container has no rustc, cargo or rustdoc, and cannot resolve the compiler/
package download host. **native-check-attempt.txt** is the actual ordinary-user
`native-validate` attempt: source verification passes, then doctor exits at
**Host rustc not found**, before any crate compiles. The explicit unsupported-
Debian override is used only because this validation container is Debian 13,
not the build kit's target Debian Forky environment.

Native Rust compilation, the 27 selected native Rust tests, BPF attachment,
normal rd-agent startup, real disk calibration, swap migration, service
stop/start, reboot and measured HWDB deployment were NOT performed. Native
compile/runtime success is not claimed. The CI workflow was not run here.

This is complete project source, not a binary package and not a vendored
third-party crate distribution. The first real build needs the documented
host toolchain/development dependencies plus Cargo registry/cache access.
Follow **PACKAGING-REPAIR.md** for build/install order and **DELIVERY-REPAIR.md**
for host preparation and the measured report/deployment workflow.
