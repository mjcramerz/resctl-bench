#!/bin/sh
# SPDX-License-Identifier: MIT
# Resolve this repository, not the caller's current working directory.
set -eu
SELF=$(readlink -f -- "$0")
ROOT=$(CDPATH= cd -- "$(dirname -- "$SELF")" && pwd -P)
if ! command -v make >/dev/null 2>&1; then
    printf '%s\n' 'ERROR: GNU make is required to build this source repository.' >&2
    exit 127
fi
exec make --no-print-directory -C "$ROOT" "$@"
