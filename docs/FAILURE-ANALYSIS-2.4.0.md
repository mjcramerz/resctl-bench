# Failure analysis - paired release 2.5.0 / build kit 2.4.0

Analyzed inputs: the supplied iocost-lab.zip, resctl-bench.zip and support.tar.gz.
This report is based on their code and logs, not a reproduced hardware run.

## What is confirmed

The supplied kernel is 7.2.6-x64v3-xanmod1 (#0~20260914.g08752fb). The session
reports 7,852,240,896 bytes of physical RAM (about 7.31 GiB), a 4-GiB native profile,
Btrfs root and the selected NVMe device. The native programs had already reached
calibration; the reported failure is NOT a Cargo compiler diagnostic.

The support bundle's balloon-runtime/events.jsonl contains 290 starts and 290
exits, including 274 OOM/abnormal exits and 16 normal exits; 169 readiness events
were recorded. Its memory-telemetry-tail.jsonl has 925 samples and shows oom_kill
rising from 88 to 363: 275 new kernel kills in that retained window. Minimum
reported MemAvailable is 819,441,664 bytes, so apparently positive headroom did
not prevent these OOMs. Kernel dmesg identifies global CONSTRAINT_NONE OOM kills
with rd-balloon victims, not merely a wrapper's speculative OOM classification.

The old native stderr/journal then reports:

    Failed to set balloon size to 4.28G
    org.freedesktop.systemd1.TransactionIsDestructive
    rd-balloon.service/stop is destructive (has 'start' job queued)

The agent panic is followed by repeated destructor stop failures and a poisoned
reporter mutex. This is the concrete lifecycle chain to fix, not an instruction
to increase retries or label a terminated calibration successful.

The 2.4 Lab drop-in enabled Restart=on-failure, RestartSec=250ms and disabled start
rate limiting. The native agent independently owned the same transient unit and
used StopUnit mode fail. A queued automatic start conflicted with its attempted
stop. The Lab also replaced the generated allocator with an adaptive one: target
reductions and partial readiness could leave fewer pages held than native
calibration arithmetic assumed. The native agent did not continuously validate
balloon health during hashd calibration. Together, these mechanisms allowed
repeated OOM/restart/re-estimation rather than a trustworthy completed benchmark.

Primary local evidence: resctl-run.log, resctl-service-live.log,
balloon-service.json, balloon-runtime/events.jsonl, memory-telemetry-tail.jsonl,
agent-diagnostics/, diagnostics-before/dmesg.json and diagnostics-after/dmesg.json.
The delivery does not republish the user's private support archive.

## Likely contributor, not proven from the old bundle

The kernel dump reports little free memory near zone minimums, substantial file
cache and unreclaimable zones despite remaining swap. XanMod advertises le9uo;
that patch can hard-protect a percentage of clean cache. A 15% clean-cache floor
would be about 1.10 GiB on this host, consistent with the retained cache observed
in OOM dumps. However, the OLD bundle did not capture workingset_protection,
clean_min_ratio or MGLRU min_ttl_ms, so their actual values and causal role are
NOT established. A positive MGLRU TTL can separately cause early OOM. The new
bundle records those interfaces plus buddy/zone information. vm.stat_interval=10
was captured; preparation now uses the standard one-second statistics interval.

The repair does not assume every XanMod kernel has the same patch/control names.
It inspects exact known optional interfaces, requires explicit approved preparation,
verifies them without changing settings in flight and restores their original
values. A regular kernel without those optional interfaces is supported.

## Repair map

Native rd-agent/src/side.rs: one lifecycle owner; Restart=no, MemorySwapMax=0;
identity/liveness checks during hashd and running states; explicit resize teardown.
Native rd-agent/src/misc/memory-balloon.py: page-rounded exact touched allocation;
no partial READY, no adaptive release, bounded allocation, OOM evidence checks.
Native rd-util/src/systemd.rs: replace conflicting stop jobs, checked waits,
explicit missing-unit semantics, refuse replacing static units, stop retries end
on success. Native cmd/main: propagate ordinary failures outside held reporter
locks. Storage re-estimation: checked integer arithmetic and physical bounds.

Lab live_recovery/resilience/reporting: one invocation, no in-run host repairs,
sticky invalidation, no reuse/deployment of damaged measurements. Lab memory_host:
reviewed preparation, per-write crash journal, drift verification and conditional
restoration. Native/runtime integration: v3 marker plus five SHA-256-pinned
compiled helpers, checked both before and after stripped binary packaging.

The BPF measurement program, coefficient generator, native benchmark stages,
result interfaces and measured-value deployment design are retained. Complete
source is delivered, not a patch-only replacement. Cargo.lock is unchanged.

## Evidence limits and acceptance criteria

Software passes are listed in VALIDATION.md. Rust compilation, native Rust tests,
live systemd/BPF, full NVMe calibration and hardware restoration have not been
executed in this container. The mandatory native build gate must succeed on a
properly provisioned build host before installation. After old tracked restoration,
a NEW target-host run must complete all four stages with stable balloon identity,
no new OOM count, no invalidation marker, valid native memory/model/QoS outputs and
successful host restoration before its profile becomes installable.

This is not a guarantee that an undersized, noisy, constrained or failing host can
never stop. The repair removes the demonstrated restart race and invalid
continuation policy; genuine resource/kernel errors remain explicit failures.

Primary external references and their scope are in MEMORY-INTEGRITY.md (Lab copy)
or the paired Lab documentation: systemd job modes, kernel cgroup v2/MGLRU/VM
sysctls, and the le9uo/XanMod maintainers. The le9uo hypothesis is distinguished
from direct log evidence throughout this report.
