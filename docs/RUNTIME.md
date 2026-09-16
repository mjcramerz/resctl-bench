# Runtime and benchmarking boundaries

## Select the rebuilt runtime, not the old vendor archive

After `make package verify`, use the source root's `RUN-IOCOST-LAB.sh --lab
/absolute/path/to/iocost-lab`. It verifies the package and actual embedded helpers
and passes --runtime-dir explicitly. The existing Lab 1.5.0 handles the full
benchmark and reports. The bridge does not rewrite the Lab, replace its archive,
autoformat media, or grant maintenance permissions silently.

The build tree can be on any suitable filesystem. The **invocation directory
for the Lab** must be on the selected calibration disk because the Lab puts
output, work files and any temporary swap there. No scratch argument is needed.
Using USB for the repository is optional; launching in a USB output directory
while selecting a different disk is intentionally rejected by the Lab.

## Separate levels of verification

`make doctor` tests the installed compiler/linker tools. `make package` compiles
and tests reviewed source, checks real embedded files and creates the runtime.
Neither action starts a storage workload or attaches BPF. The optional
`make runtime-check` reads a host checklist and cannot prove BPF attachment.

The generated runtime's `python3 -I -B runtime_support.py` is a file-only compiled
helper check, safe to run as an ordinary user. `sudo /usr/bin/python3 -I -B
runtime_support.py --probe-latency DEVICE` is a distinct explicit kernel probe:
it exports and verifies the exact helpers, then executes the actual collector
with interval zero. It requires a physical whole-device sysfs identity, prints
structured diagnostics, and fails on real compiler/attach errors. It does not
run fio, touch swap, run the ordinary agent lifecycle or fabricate observations.

Normal benchmarking retains the real agent's BPF initialization. The build
checks never substitute --no-iolat or a fake collector. The supplied header
failure is corrected with C language flags, not by removing kernel assertions.

## Host prerequisites remain real requirements

The full supplied resctl suite uses systemd, cgroup v2/IOCost kernel support,
Btrfs features, appropriate directly attributable storage/swap and the packages
listed in packages/runtime.txt. A package/compiler success cannot add missing
kernel features or make unsupported RAID/multi-device layouts valid.

Storage fio is used internally by upstream iocost-params; it is not an
independent replacement benchmark. Use Debian's python3-bpfcc under system
Python, not an unrelated pip package called bcc. The running kernel, header
sources where required, compiler and BCC must work together. The target-host
collector probe is the check of that combination.

Zram is not the disk target. During the full storage/protection workload, its
active RAM-backed swap would divert paging activity. The Lab's reviewed
maintenance plan handles needed temporary disk swap and restoration. The build
kit itself neither changes swap nor removes the original topology guards.
Read the existing Lab recovery instructions and keep failed sessions with
unfinished restoration. Do not manually delete a possibly active swapfile.

The Btrfs lookup repair removes display-root suffixes by using findmnt's
--nofsroot API and JSON, then verifies the actual block device. It does not
invent a device for overlay/tmpfs/network filesystems or add support for
ambiguous stacked/multi-device storage. Native swap-parser errors are reported
rather than silently omitted.

## Maintenance operation, not a harmless speed test

The full plan remains iocost-params, hashd-params, iocost-qos and iocost-tune. A
complete QoS sweep can be substantially longer than coefficient calibration;
there is no timer that falsely declares it complete. Full mode is not silently
reduced to basic calibration.

Back up data, close unrelated workloads, use an appropriate maintenance window
and keep recovery access. Upstream may trim the whole workload filesystem,
write substantial data, create memory pressure and change host settings/services.
A private output directory does not limit filesystem-wide trim. Recovery is
best effort, especially after crashes or power loss. Existing system-disk
and installation approvals remain in effect.

All reports/measurements come from an actual successful Lab run. This source
archive contains no precomputed coefficients for the user's drive and makes no
claim that a physical benchmark has been completed. Validate resulting IOCost
behavior on representative workloads before persistent deployment.
