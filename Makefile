# SPDX-License-Identifier: MIT
.DEFAULT_GOAL := package
.DELETE_ON_ERROR:
.NOTPARALLEL:
# Anchor all entrypoints and configuration to this Makefile, even with make -f.
# At this point MAKEFILE_LIST contains this Makefile (before project includes).
PROJECT_DIR := $(shell CDPATH= cd -- "$$(dirname -- "$(MAKEFILE_LIST)")" && pwd -P)
empty :=
space := $(empty) $(empty)
# System Python + isolated mode: no venv, pip, PYTHONPATH or shell edits.
PYTHON ?= /usr/bin/python3
PYTHON_FLAGS ?= -I -B
-include $(subst $(space),\$(space),$(PROJECT_DIR))/config.mk

UPSTREAM_URL ?= https://github.com/facebookexperimental/resctl-demo.git
UPSTREAM_REF ?= main
TOOLCHAIN ?= host
TUNE ?= native
LTO ?= thin
JOBS ?= auto
WITH_DEMO ?= 1
SPLIT_DEBUG ?= 1
OFFLINE ?= 0
HOST_RUSTC ?=
HOST_CARGO ?=
HOST_RUSTDOC ?=
HOST_CC ?= /usr/bin/gcc
HOST_CXX ?= /usr/bin/g++
PREFIX ?= /usr/local
DESTDIR ?=
FORCE ?= 0
export UPSTREAM_URL UPSTREAM_REF TOOLCHAIN TUNE LTO JOBS WITH_DEMO
export SPLIT_DEBUG OFFLINE HOST_CC HOST_CXX PREFIX DESTDIR FORCE
export EXTRA_RUSTFLAGS EXTRA_CFLAGS EXTRA_CXXFLAGS
export HOST_RUSTC HOST_CARGO HOST_RUSTDOC RUSTC CARGO RUSTDOC

DRIVER_TARGETS := deps deps-runtime deps-plan deps-llvm doctor fetch verify-source restore-source update-source \
 update-toolchain update-rustup update-deps lock-toolchain versions \
 latest latest-complete fetch-deps build check test-compile smoke stage package \
 test-runtime rebuild verify vendor source-dist snapshot-dist kit-dist install uninstall clean clean-vendor lint
.PHONY: help all $(DRIVER_TARGETS) test runtime-check

help:
	@cd "$(PROJECT_DIR)" && $(PYTHON) $(PYTHON_FLAGS) scripts/build.py help
all: package

$(DRIVER_TARGETS):
	@cd "$(PROJECT_DIR)" && $(PYTHON) $(PYTHON_FLAGS) scripts/build.py $@

test:
	@cd "$(PROJECT_DIR)" && if [ -f source.lock.json ]; then $(PYTHON) $(PYTHON_FLAGS) scripts/build.py fetch; fi
	@cd "$(PROJECT_DIR)" && $(PYTHON) $(PYTHON_FLAGS) -m unittest discover -s tests -v

# Path is read from the environment by argparse's default, never shell-interpolated.
runtime-check:
	@cd "$(PROJECT_DIR)" && $(PYTHON) $(PYTHON_FLAGS) scripts/runtime_check.py
export SCRATCH
