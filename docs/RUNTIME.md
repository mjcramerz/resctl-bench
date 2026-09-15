# Runtime preparation and NVMe/IOCost boundaries

Building and packaging do not prepare a production host for benchmarking.
Use a dedicated benchmark host with disposable scratch data, backups, a
maintenance window and out-of-band access. Review the README and resctl-bench
documentation packaged from the EXACT selected upstream revision. Latest
source/nightly/dependencies are moving inputs, not a tested compatibility matrix.

## Explicit dependency installation

`make deps-runtime` installs the newest declared runtime packages available in
configured Forky indexes, with the same no-removal/no-cross-release policy as
build dependencies. It does not install a kernel or flash NVMe firmware. Debian
maintainer scripts can start/restart services, including oomd; review the APT
plan. The project's oomd is not interchangeable with systemd-oomd.

The package list includes storage fio, stress, Python BCC, gnuplot-nox, oomd,
systemd/util-linux/coreutils, btrfs-progs, nvme-cli/smartmontools, and native
kernel-workload build dependencies. Do not replace storage fio with the unrelated
Python program named fio. Do not install arbitrary pip BCC packages over the
Debian python3-bpfcc module. A virtual environment or earlier PATH entry can
hide `/usr/bin/python3` and its system packages.

Keep Forky's running kernel and any required headers matched through ordinary
Debian administration. Headers for a different newly installed kernel are not
headers for the currently running kernel. BTF and successful Python imports
are evidence of specific prerequisites, not proof that a BCC program compiles
and attaches on that kernel. No driver or BPF program is loaded by this kit.

## Read-only inventory

```sh
make runtime-check SCRATCH=/existing/benchmark/filesystem
```

The directory must already exist. The checker never creates it or accepts a
raw block device as a scratch directory. Without SCRATCH it inventories only
the visible host. The JSON contains systemd PID1, cgroup-v2 controllers and
IOCost model/QoS interfaces, PSI, selected kernel config options, swap presence,
BCC import checks under Debian and PATH Python, storage fio identity and its
advertised io_uring engine, the global io_uring restriction setting, running
kernel/header/BTF visibility, CPU governors/frequency limits/boost policy, and
mount/backing-block-queue details when identifiable.

The io_uring engine listing does not issue workload IO. io_uring_disabled=1
still imposes permission restrictions even though the feature is not globally
disabled. BPF imports do not attach probes. CPU and storage settings are READ,
never changed. Missing interfaces in a container can reflect isolation rather
than absent kernel functionality. A namespace-local view cannot certify the
physical host configuration.

Exit 0 means the inspected checklist passed; exit 2 means prerequisites were
missing/unconfirmed; exit 1 indicates an inspection error. None means a device
is safe to benchmark, all jobs work, or an IOCost model is accurate. The
full-suite checklist can be stricter than an individual benchmark's needs.

## Review before running upstream manually

Identify the actual scratch filesystem and physical backing storage. Check
partitions, device-mapper/LVM/RAID layers, multi-device Btrfs, free space,
filesystem/mount options and swap placement. A `/dev/nvme...` name alone does
not identify the correct benchmark target, physical topology or cgroup block
accounting level. Verify that the target contains no production or irreplaceable
data. This kit deliberately supplies no automatic format, discard, sanitize,
firmware-update, raw-device-write, scheduler-write, or IOCost-write command.

Upstream's full resource-control demonstration expects a systemd/cgroup-v2
host, appropriate memory/IO accounting and pressure interfaces, Btrfs and swap
for jobs that exercise those features. An IOCost-enabled kernel must expose
the appropriate interfaces; inspect the actual kernel rather than assuming a
Debian version implies readiness. The included checker records relevant config
values when `/proc/config.gz` or `/boot/config-<running-kernel>` is readable.

Plan CPU power policy, temperature stabilization, SSD thermal throttling,
firmware, free-space/preconditioning state, background IO, swap and run order.
Do not blindly set a performance governor, disable CPU mitigations, toggle
write caches, or change block schedulers: those decisions affect host safety
and the meaning of measurements. Benchmark settings should model the intended
production conditions and remain consistent across comparisons.

Before any write-heavy calibration, read the current upstream CLI help and
job documentation, choose job scope and scratch path deliberately, and review
which settings the agent changes. `resctl-bench deps` is NOT this kit's read-only
checker; upstream documents that it starts the agent. Tests in this kit invoke
only --help and --version on release executables. No Make goal starts rd-agent,
runs fio workloads, or applies io.cost.model/io.cost.qos values.

After controlled runs, retain the exact inputs, result JSON, device topology,
thermal/power state and competing workloads with the generated model. Validate
IOCost behavior under representative loads before any separate deployment.
A build success is not an endorsement of a generated model for production.
