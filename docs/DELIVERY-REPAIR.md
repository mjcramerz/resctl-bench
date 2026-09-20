> Historical repair background. Current paired release instructions and native v3 requirements are in ../README.md and VALIDATION.md. Older markers/counts below are not the current runtime contract.

# September 16 failure repair - IOCost Lab 2.1.1 / build kit 2.3.3

For the follow-up `make package` executable-mode error and missing install
manifest, read **PACKAGING-REPAIR.md** first. The procedure below retains the
original host-requirement repair; none of its checks are bypassed.

## What the uploaded output actually established

Four saved attempts failed before starting a benchmark because `resctl-bench`
was not discoverable in the process's effective PATH. The final full-mode
attempt found the system installation under `/usr/local/bin` and reached
rd-agent. Its first load-bearing rejection was:

```
Missed sysreqs: NoOtherIoControllers, HostCriticalServices
```

The agent named `zram-writebackd.service` as an owner of a nonempty I/O policy,
and reported D-Bus services outside `hostcritical.slice`. The native job then
failed its requirements and deliberately panicked. During teardown, the latency
reader's disconnected channel produced a secondary panic. These are distinct
from a Rust compiler error. No Cargo compiler diagnostic is present in this
uploaded output. The successful/empty startup collector log does not demonstrate
that the later host-requirement checks passed.

No completed measured model/QoS tuning result can be recovered from those failed
sessions. This release does not invent one or turn a failed run into an
installable profile. Original private host logs are not republished here.

## Changes in the matched pair

The Lab searches the effective PATH first, then standard system binary paths,
including `/usr/local/bin`. An explicit `--bin-dir` is still exclusive. Unsafe
first matches are rejected, not skipped. Paths, permissions, fingerprints,
version agreement, and native companion lookup remain checked.

All three installed commands must return exactly `resctl-iocost-lab-v2` for
`--runtime-contract`. This file-only native interface runs before configuration,
systemd, BPF or workloads. It distinguishes this repair from an older binary
with the same upstream version and the same embedded helper bytes. The build
kit checks the marker and four helper hashes before and after stripping. The
Lab repeats those checks against the installed binaries. Rebuild and install
all three together; updating Python code or loose helper files is insufficient.

Lab preflight now reads competing I/O-controller policies and full-mode D-Bus
placement before native startup. Both the Lab and native agent recognize
`io.max` fields set to `max`, latency `target=0`, and zeroed legacy `io.low`
fields as disabled; they still reject finite, malformed or unreadable policies.
All device rows are checked, not only the first. The kernel's documented
`io.max` unlimited value is `max`; nonempty does not mean active.

`host-prepare` creates only reviewed service drop-ins, never replaces conflicting
administrator files, never restarts D-Bus and never reboots. Applying them is
explicit and a maintenance reboot is required before retrying. A dry-run plan
is not proof that current running services have moved.

`--quiesce-zram-writeback` explicitly requests a journaled stop and runtime mask
of **only** `zram-writebackd.service`. It is not zram formatting, a blanket
swapoff or a bypass of host requirements. The Lab rechecks policies after the
service stops. Cleanup removes only the recorded mask and restarts the service
only when it was previously active and its definition has not changed. Unknown
masks, changed boot IDs, changed unit definitions, active workloads, or pending
swap recovery require operator review. Pending transactions block new runs.
An interruption before mask identity is durably recorded intentionally requires
manual review rather than guessing mask ownership. SIGKILL/power-loss recovery
is not guaranteed.

The native agent refreshes sysinfo memory/process snapshots before reading them.
Ordinary native job failures now return a nonzero error instead of explicitly
panicking. Collector disconnect during an already-requested shutdown exits its
loop rather than generating a misleading second failure. Unexpected collector
failure during a running benchmark remains fatal; tracing is not bypassed.

The earlier embedded Python/BCC language-compatibility correction and structured
findmnt `--nofsroot` device resolution are retained. The coefficient generator,
BPF measurement program and four native benchmark stages are unchanged.

## Build and install the repaired native source first

Run from the resctl-bench source root as your ordinary build user, with an
installed compatible Rust/Cargo/rustdoc and the documented Debian dependencies:

```sh
sha256sum -c SHA256SUMS
./BUILD.sh fetch verify-source
./BUILD.sh native-validate
sudo ./BUILD.sh install
```

`native-validate` runs source verification, compiler/toolchain probes, Cargo
check, test-harness compilation, native packaging and payload verification.
Packaging runs only the 27 explicitly selected non-hardware Rust regressions:
10 helper tests, 8 device-resolution tests, 6 I/O-policy tests and 3 contract
parser tests. A filter that runs zero tests fails. It never runs unrestricted
upstream hardware tests. The four suites retain separate log files.

The ordinary build does not install/upgrade Rust or alter package sources.
Third-party Cargo dependencies were not supplied in the uploaded ZIP and are
not vendored in this source snapshot. A first build needs those locked crates
in the cache or registry access. The complete **project source**, Cargo.lock,
real base Git metadata, reviewed patch and hash-pinned offline source-recovery
archive are included. `OFFLINE=1` is not a way to conjure absent crate sources.

For a build intended for a different compatible CPU, use
`./BUILD.sh native-validate TUNE=portable`. Reuse the same tuning variables for
all later build steps; the resulting binaries still require compatible shared
libraries.

The installer refuses conflicting old files. After inspecting and backing up
an existing installation, `sudo ./BUILD.sh install FORCE=1` explicitly authorizes
replacement under the selected prefix. This installer option is unrelated to
native benchmark `--force`; do **not** bypass calibration requirements. Symlink
conflicts are still refused and need deliberate administrator resolution.

## Prepare the reported host requirements

Use a disposable maintenance host, back up important data and stop other work.
From an existing directory on the physical disk selected for calibration, use
the absolute path to the new Lab. The output/workload stays in that invocation
directory; no USB output directory or separate scratch argument is required.

```sh
sudo /path/to/iocost-lab/RUN.sh doctor
sudo /path/to/iocost-lab/RUN.sh host-prepare
```

Review the drop-in plan and existing D-Bus service overrides. To explicitly
write the displayed placement files:

```sh
sudo /path/to/iocost-lab/RUN.sh host-prepare --apply --accept-system-changes
```

Then perform a maintenance reboot under your own control. Do not restart
D-Bus in an active session. After reboot, verify the running ControlGroup and
rerun doctor/preflight. For the host in the supplied logs, opt into temporary
writeback-service quiescence during this check and the later run:

```sh
sudo /path/to/iocost-lab/RUN.sh preflight --device /dev/nvme0n1 --mode full --quiesce-zram-writeback
sudo /path/to/iocost-lab/RUN.sh run --device /dev/nvme0n1 --mode full --quiesce-zram-writeback
```

`/dev/nvme0n1` reflects the uploaded failed attempt, not an assurance that it is
the right current target. Verify the physical-device identity. For a disk with
system/home/boot mounts, preflight also requires the separate explicit
`--allow-system-disk` override. Do not add it casually. Resource, filesystem,
swap, BPF and capacity errors must still be resolved. Interactive runs display
the complete maintenance plan; only the typed approval permits host changes.
Unattended approvals remain explicit and are documented in the main README.

No-argument menu actions 16 and 17 expose full-mode writeback quiescence without
changing the older menu choices. Action 15 shows the D-Bus preparation plan.
The optional build-kit bridge also accepts `--quiesce-zram-writeback`; it never
provides unattended benchmark approval.

## Reports and installation remain separate

Full mode still runs `iocost-params`, `hashd-params`, `iocost-qos` and
`iocost-tune`. A complete validated run generates REPORT.md/REPORT.json,
measured model and QoS entries, and the existing HWDB/configuration/deployment
bundle. Do not confuse a preflight/failure report with completed calibration.
The `hwdb`, `report`, `install` and `verify` actions operate on saved sessions;
installation remains independently approved and bound to the measured device.
Basic mode continues to label its QoS heuristic and does not masquerade as full
tuning. No native `--force`, bypassed BPF, substituted workload or synthetic
result is used by production code.

If cleanup reports pending state, preserve the session and use its `restore`
action after ensuring no resctl workload remains active. Review FAILURE.txt,
host-requirements.json, host-services.json and recovery.json. The support bundle
now includes those diagnostics, but excludes workload/swapfile contents.

## Verification limits

See each archive's docs/VALIDATION.md and actual test logs. The delivery
container has no rustc/cargo/rustdoc. The native check was attempted and failed
at tool discovery; it did not compile a crate. No live BPF, D-Bus relocation,
service stop/start, disk calibration, real swap migration, reboot or measured
configuration deployment was executed here. Synthetic C/Cargo/BCC fixtures
exercise build orchestration and error handling, not native compilation.
Successful software tests are not a guarantee of safe or accurate target-host
calibration. The build-host compiler gate and maintenance-host tests remain
mandatory before treating this pair as hardware-validated.

## Primary technical references

- Linux cgroup v2 documentation: https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html
- Locked sysinfo 0.30.13 crate documentation: https://docs.rs/crate/sysinfo/0.30.13
- Upstream source and requirements: https://github.com/facebookexperimental/resctl-demo
- Cargo configuration behavior: https://doc.rust-lang.org/cargo/reference/config.html
