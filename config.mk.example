# SPDX-License-Identifier: MIT
# Optional: copy to config.mk for reviewed overrides. Host-installed Rust is the default. GNU Make configuration is trusted executable input.
# Defaults intentionally do not pin outdated Debian package/Rust/source versions.
UPSTREAM_URL ?= https://github.com/facebookexperimental/resctl-demo.git
UPSTREAM_REF ?= main
TOOLCHAIN ?= host
TUNE ?= native
LTO ?= thin
JOBS ?= auto
WITH_DEMO ?= 1
SPLIT_DEBUG ?= 1
OFFLINE ?= 0
# Optional explicit installed Rust paths; otherwise PATH is used.
HOST_RUSTC ?=
HOST_CARGO ?=
HOST_RUSTDOC ?=
HOST_CC ?= /usr/bin/gcc
HOST_CXX ?= /usr/bin/g++
PREFIX ?= /usr/local
DESTDIR ?=
FORCE ?= 0

# Latest source/compatible dependencies (host Rust unchanged) + both release/source tarballs:
# make latest-complete
# Ordinary reproducible-intent rebuild with the already resolved inputs:
# make rebuild
# Compile relocated, populated source bundle without Cargo network access:
# make package OFFLINE=1
# LLVM is optional; install from Forky explicitly, not via third-party scripts:
# make deps-llvm
# make package HOST_CC=/usr/bin/clang HOST_CXX=/usr/bin/clang++
# Inherited CARGO_TARGET_DIR and other build overrides need not be unset.
# The kit scopes them away in child processes; output stays in .work/.
# Cargo home, registry/proxy settings and host config files remain unchanged.
# Use the explicit options below for additional flags for this kit.
# EXTRA_RUSTFLAGS =
# EXTRA_CFLAGS =
# EXTRA_CXXFLAGS =
