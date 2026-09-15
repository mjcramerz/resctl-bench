# Validation status - build kit 2.0.0

## Executed in the authoring environment

Validation date: 2026-09-15 (UTC). Host: Debian GNU/Linux 13 (Trixie),
x86_64, Python 3.13.5. This environment is NOT Debian Forky.

**66 of 66 tests passed**, no failures or skips, in the final `make test`
run. The captured unittest summary reports 126.943 seconds. The complete
fixture log is in `test-results.txt`. `make lint` passed syntax and whitespace
checks on all seven Python source/test files. Earlier development runs are not
substituted for this final result.

Coverage includes native amd64/arm64 flag selection, portable mode, configuration
and path checks, clean source/Git identity enforcement, missing-checkout recovery,
compiler drift, failed-build invalidation, build isolation, test compilation
without test execution, vendor tampering and relocation, original/effective
lock separation, dependency-update failure and source-tampering rejection,
source-refresh retirement, dynamic compiler metapackage expansion, Forky Release
origin/codename selection, Debian version ordering, localized-shell APT parsing,
no downgrade/removal/cross-suite policy, latest-nightly selection, required
components, compiler-identity checks and channel-race rejection.

The pipeline tests actually create local Git repositories and real GCC ELF
executables, check ELF architecture/PIE/RELRO, split debug symbols with GNU
binutils, construct/check tarballs, and install/uninstall filesystem payloads
with conflict/symlink/tamper protections. A populated synthetic source bundle
is extracted at a new path and rebuilt through the frozen vendor workflow.
Archive envelope reproducibility is tested for a fixed input tree.

Rustup, rustc, Cargo and network/APT package data in these tests are explicitly
SIMULATED. Version strings and commits in the fixtures are NOT current release
claims, actual nightly executions or actual upstream binary provenance.
No fixture executable is included in the downloadable build-kit archive.

Two additional read-only checks were performed on the actual authoring host:
`make deps-plan` refused Trixie before any APT update/install operation;
`make runtime-check SCRATCH=/mnt/data` returned an unconfirmed-prerequisites
status, including absent BCC and unsuitable benchmark-host conditions. The
checker did not perform workloads or alter devices/cgroups/sysctls.

## Not verified here

The authoring sandbox has no installed Rust toolchain and direct GitHub source
downloads failed. Public primary documentation and available upstream manifests
were reviewed through the web, but a real upstream checkout could not be
obtained for compilation. The official live nightly manifest download, rustup
installation, Forky APT installation, actual resctl workspace compilation,
real executable CLI behavior and benchmark execution have NOT been verified
in this environment.

The provided Forky CI workflow and its opt-in online upstream build plus
relocated offline rebuild were NOT run. ARM flags were tested as data, not
executed on an ARM CPU. No claim is made of runtime BCC/kernel compatibility,
a nightly/upstream/dependency compatibility matrix, universally reproducible
binaries, cross-Debian ABI portability, benchmark validity or correct IOCost
calibration. No benchmark, service startup, BPF attachment, raw-device write,
format, firmware update, kernel upgrade or performance-setting write was run.

## Artifact boundary and host validation

The supplied download contains the complete build-and-packaging codebase, not
upstream Rust sources, vendored crates or precompiled resctl programs. On a
networked Forky host with rustup, `make latest-complete` attempts the real
current-input compile and produces both executable and populated source
archives only through their respective success paths. It refuses stale
nightly fallback and does not convert an upstream compiler error into success.

Run `make verify` after packaging and inspect the recorded logs, effective
flags, source SHA, nightly identity, dependency diff, ELF report and smoke
results. `make check test-compile` provides additional upstream compile checks
without executing upstream tests. The optional CI provides another place to
perform actual compilation, but neither a compile nor a CLI check establishes
safe or meaningful NVMe/IOCost benchmarking. See RUNTIME.md.
