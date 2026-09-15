# Primary references reviewed

Review date: 2026-09-15. These references establish upstream interfaces and
published documentation, not successful compilation in this authoring sandbox.
Package and channel versions are intentionally resolved on the user's host;
no fixed GCC, LLVM, nightly date or upstream SHA is advertised as permanently
newest. The live nightly manifest could not be downloaded in this sandbox.

## Debian

- Forky release status: https://www.debian.org/releases/forky/
- Testing release notes: https://www.debian.org/releases/testing/release-notes/
- APT transaction controls: https://manpages.debian.org/testing/apt/apt-get.8.en.html
- GCC metapackage: https://packages.debian.org/forky/gcc
- Clang metapackage: https://packages.debian.org/forky/clang
- pkgconf: https://packages.debian.org/forky/pkgconf
- Python BCC package: https://packages.debian.org/forky/python3-bpfcc
- oomd package: https://packages.debian.org/forky/oomd
- fio package: https://packages.debian.org/forky/fio

Package web pages can be cached and are not an APT-resolution authority. The
code uses local refreshed indexes and recorded Release origin/codename instead.

## Upstream resctl-demo

- Repository: https://github.com/facebookexperimental/resctl-demo
- Workspace manifest: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/Cargo.toml
- README: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/README.md
- Benchmark manifest: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/resctl-bench/Cargo.toml
- Agent manifest: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/rd-agent/Cargo.toml
- Hashd manifest: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/rd-hashd/Cargo.toml
- Interactive demo: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/resctl-demo/Cargo.toml
- Utility manifest/build identity: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/rd-util/Cargo.toml
- Build script: https://raw.githubusercontent.com/facebookexperimental/resctl-demo/main/rd-util/build.rs

The reviewed manifest declares optional AWS Lambda functionality; it is not
enabled for local benchmarking. The demo selects the termion backend, not a
mandatory ncurses dependency. The utility build script uses actual Git metadata.
The repository's old runtime/kernel examples are context, not fixed current
Forky versions to install. Build artifacts capture docs from the fetched commit.

## Rust and Linux

- Rustup updates: https://rust-lang.github.io/rustup/basics.html
- Minimal profile: https://rust-lang.github.io/rustup/concepts/profiles.html
- Toolchain selection: https://rust-lang.github.io/rustup/overrides.html
- Cargo update semantics: https://doc.rust-lang.org/cargo/commands/cargo-update.html
- Cargo build: https://doc.rust-lang.org/cargo/commands/cargo-build.html
- Cargo profiles: https://doc.rust-lang.org/cargo/reference/profiles.html
- Cargo vendor: https://doc.rust-lang.org/cargo/commands/cargo-vendor.html
- Compiler flags: https://doc.rust-lang.org/rustc/codegen-options/
- Linux cgroup-v2/IOCost: https://docs.kernel.org/admin-guide/cgroup-v2.html

## CI dependencies

Official action releases reviewed for the provided workflow:

- https://github.com/actions/checkout/releases/tag/v7.0.1
  Commit 3d3c42e5aac5ba805825da76410c181273ba90b1.
- https://github.com/actions/upload-artifact/releases/tag/v7.0.1
  Commit 043fb46d1a93c77aae656e7c1c64a875d1fc6a0a.

The actions are immutable-pinned and Dependabot checks daily; it proposes
updates rather than silently merging them. CI uses the moving debian:forky
container tag deliberately. Container/action execution has not been run here.

## 2.1.0 import/entrypoint fix

Python documents that -P/PYTHONSAFEPATH omits the script directory from the
import path, while -I also ignores PYTHON environment settings. The driver
therefore loads its bundled helpers by absolute file location rather than
requiring users to disable these settings.

https://docs.python.org/3/using/cmdline.html#cmdoption-P
https://docs.python.org/3/using/cmdline.html#cmdoption-I
https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly

The original failure is reproducible when safe-path mode omits scripts/ from
sys.path. Its exact trigger on the reported host is not established from the
traceback alone. The replacement also handles a genuinely missing helper with
a precise incomplete-extraction error; it never substitutes a pip package.
