#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only host inventory. Does not run resctl-bench deps or any workload.

Exit 0: inspected prerequisites found; 2: missing/unknown prerequisites.
Neither result certifies that a particular benchmark can run safely.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


def command(argv: list[str]) -> dict[str, Any]:
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=15, check=False,
                           env={**os.environ, "LC_ALL": "C"})
        return {"returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": -1, "error": str(exc)}


def read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def inventory(path: Path | None = None) -> dict[str, Any]:
    controllers = read("/sys/fs/cgroup/cgroup.controllers")
    checks: dict[str, bool] = {
        "systemd_is_pid1": read("/proc/1/comm") == "systemd",
        "cgroup_v2_visible": controllers is not None,
        "io_controller_visible": "io" in (controllers or "").split(),
        "memory_controller_visible": "memory" in (controllers or "").split(),
        "iocost_model_interface": Path("/sys/fs/cgroup/io.cost.model").is_file(),
        "iocost_qos_interface": Path("/sys/fs/cgroup/io.cost.qos").is_file(),
        "psi_cpu": Path("/proc/pressure/cpu").is_file(),
        "psi_memory": Path("/proc/pressure/memory").is_file(),
        "psi_io": Path("/proc/pressure/io").is_file(),
    }
    programs = ("dd", "stdbuf", "findmnt", "python3", "fio", "stress", "gnuplot",
                "systemctl", "systemd-run", "oomd")
    tools = {name: shutil.which(name) for name in programs}
    checks.update({f"tool_{name}": value is not None for name, value in tools.items()})
    bcc = command(["/usr/bin/python3", "-B", "-c", "import bcc; print(bcc.__file__)"])
    checks["debian_python_bcc_import"] = bcc["returncode"] == 0
    fio = command([tools["fio"], "--version"]) if tools["fio"] else {"returncode": -1}
    checks["fio_is_storage_fio"] = bool(re.match(r"^fio-\d", fio.get("stdout", "")))
    fio_engines = command([tools["fio"], "--enghelp"]) if checks["fio_is_storage_fio"] else {"returncode": -1}
    checks["fio_io_uring_engine_available"] = bool(re.search(r"\bio_uring\b", fio_engines.get("stdout", "")))
    disabled = read("/proc/sys/kernel/io_uring_disabled")
    checks["io_uring_not_globally_disabled"] = disabled in ("0", "1")
    path_bcc = command([tools["python3"], "-B", "-c", "import bcc; print(bcc.__file__)"]) if tools["python3"] else {"returncode": -1}
    checks["path_python_bcc_import"] = path_bcc["returncode"] == 0
    swaps = read("/proc/swaps")
    checks["swap_present_for_full_suite"] = bool(swaps and len(swaps.splitlines()) > 1)
    report: dict[str, Any] = {
        "read_only": True, "certifies_benchmark_readiness": False,
        "kernel": os.uname().release, "checks": checks,
        "cgroup_controllers": controllers, "tools": tools, "bcc_import": bcc,
        "fio_version": fio, "fio_engines": fio_engines, "path_python_bcc_import": path_bcc,
        "io_uring_disabled": disabled, "os_release": read("/etc/os-release"),
        "kernel_headers_present": Path(f"/lib/modules/{os.uname().release}/build").exists(),
        "kernel_btf_present": Path("/sys/kernel/btf/vmlinux").is_file(),
        "swap": swaps, "memory": read("/proc/meminfo"),
        "iocost_model": read("/sys/fs/cgroup/io.cost.model"),
        "iocost_qos": read("/sys/fs/cgroup/io.cost.qos"),
        "warnings": ["No benchmark, BPF attachment, disk write, or kernel configuration change was performed.",
                     "Missing container-visible interfaces may reflect isolation, not the host kernel.",
                     "A successful BCC import does not establish that BPF compilation/attachment works.",
                     "oomd is not interchangeable with systemd-oomd.",
                     "Full-suite requirements are stricter than those of individual jobs."],
    }
    report["cpu_frequency"] = {
        policy.name: {key: read(policy / key) for key in
                     ("scaling_driver", "scaling_governor", "scaling_min_freq", "scaling_max_freq", "energy_performance_preference")}
        for policy in sorted(Path("/sys/devices/system/cpu/cpufreq").glob("policy*"))
    }
    report["cpu_power_settings"] = {key: read(value) for key, value in {
        "cpufreq_boost": "/sys/devices/system/cpu/cpufreq/boost",
        "intel_no_turbo": "/sys/devices/system/cpu/intel_pstate/no_turbo",
        "amd_pstate_status": "/sys/devices/system/cpu/amd_pstate/status"}.items()}
    report["warnings"].extend([
        "fio --enghelp checks engine availability only; no io_uring workload was executed.",
        "io_uring_disabled=1 permits only privileged or configured-group use; benchmark privileges still matter.",
        "Kernel headers/BTF observations do not prove that this BCC version can attach to this kernel.",
        "CPU governor/turbo settings are reported, never modified."])
    for config_path in (Path(f"/boot/config-{os.uname().release}"), Path("/proc/config.gz")):
        try:
            text = gzip.open(config_path, "rt").read() if config_path.suffix == ".gz" else config_path.read_text()
            wanted = ("CONFIG_BLK_CGROUP_IOCOST", "CONFIG_CGROUPS", "CONFIG_MEMCG", "CONFIG_PSI", "CONFIG_BPF", "CONFIG_BPF_SYSCALL", "CONFIG_IO_URING", "CONFIG_BLK_CGROUP", "CONFIG_BLK_CGROUP_IOLATENCY", "CONFIG_DEBUG_INFO_BTF")
            report["kernel_config"] = {name: next((line for line in text.splitlines()
                                        if line.startswith(name + "=") or line == f"# {name} is not set"), "unknown")
                                       for name in wanted}
            break
        except OSError:
            continue
    if path is not None:
        resolved = path.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("--path must name an existing directory, not a raw block device")
        report["scratch_directory"] = str(resolved)
        report["scratch_free_bytes"] = shutil.disk_usage(resolved).free
        mounted = command(["findmnt", "--json", "--target", str(resolved),
                           "--output", "SOURCE,FSTYPE,TARGET,MAJ:MIN"])
        report["scratch_mount"] = mounted
        if mounted["returncode"] == 0:
            fs = json.loads(mounted["stdout"])["filesystems"][0]
            checks["scratch_btrfs_for_full_suite"] = fs["fstype"] == "btrfs"
            source = fs["source"].split("[", 1)[0]
            if source.startswith("/dev/"):
                report["storage_ancestry"] = command(["lsblk", "--json", "--inverse", "--output",
                                                      "NAME,PATH,TYPE,MAJ:MIN", source])
            major_minor = fs.get("maj:min", "")
            if re.fullmatch(r"\d+:\d+", major_minor):
                block = Path("/sys/dev/block") / major_minor
                if block.exists():
                    resolved_block = block.resolve()
                    if (resolved_block / "partition").exists():
                        resolved_block = resolved_block.parent
                    report["block_queue"] = {key: read(resolved_block / "queue" / key) for key in
                        ("scheduler", "nr_requests", "read_ahead_kb", "logical_block_size", "physical_block_size", "rotational")}
            report["warnings"].append("Manually verify the physical backing device, partitions, multi-device Btrfs, RAID/LVM/dm layers, free space and swap placement.")
        else:
            checks["scratch_mount_identified"] = False
    report["missing_or_unconfirmed"] = [name for name, okay in checks.items() if not okay]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=os.environ.get("SCRATCH") or None, help="Existing scratch filesystem directory; never a block-device node")
    args = parser.parse_args()
    result = inventory(args.path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result["missing_or_unconfirmed"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
