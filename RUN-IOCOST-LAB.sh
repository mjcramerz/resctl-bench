#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
SCRIPT=$(/usr/bin/readlink -f -- "$0")
BASE=$(CDPATH= cd -- "$(/usr/bin/dirname -- "$SCRIPT")" && pwd -P)
# Resolve the source directory in a subshell; do not change workload/output cwd.
exec /usr/bin/python3 -I -B "$BASE/scripts/launch_iocost.py" "$@"
