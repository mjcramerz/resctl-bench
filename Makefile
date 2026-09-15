# SPDX-License-Identifier: MIT
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:
.NOTPARALLEL:
PYTHON ?= python3
-include config.mk

UPSTREAM_URL ?= https://github.com/facebookexperimental/resctl-demo.git
UPSTREAM_REF ?= main
TOOLCHAIN ?= nightly
TUNE ?= native
LTO ?= thin
JOBS ?= auto
WITH_DEMO ?= 1
SPLIT_DEBUG ?= 1
OFFLINE ?= 0
HOST_CC ?= /usr/bin/gcc
HOST_CXX ?= /usr/bin/g++
PREFIX ?= /usr/local
DESTDIR ?=
FORCE ?= 0
export UPSTREAM_URL UPSTREAM_REF TOOLCHAIN TUNE LTO JOBS WITH_DEMO
export SPLIT_DEBUG OFFLINE HOST_CC HOST_CXX PREFIX DESTDIR FORCE
export EXTRA_RUSTFLAGS EXTRA_CFLAGS EXTRA_CXXFLAGS

DRIVER_TARGETS := deps deps-runtime deps-plan deps-llvm doctor fetch update-source \
 update-toolchain update-rustup update-deps lock-toolchain versions \
 latest latest-complete fetch-deps build check test-compile smoke stage package \
 verify vendor source-dist kit-dist install uninstall clean clean-vendor lint
.PHONY: help all $(DRIVER_TARGETS) test runtime-check

help:
	@$(PYTHON) scripts/build.py help
all: package

$(DRIVER_TARGETS):
	@$(PYTHON) scripts/build.py $@

test:
	@$(PYTHON) -m unittest discover -s tests -v

# Path is read from the environment by argparse's default, never shell-interpolated.
runtime-check:
	@$(PYTHON) scripts/runtime_check.py
export SCRATCH
