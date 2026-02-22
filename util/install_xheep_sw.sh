#!/bin/bash
set -euo pipefail

# Sync sw/device/ from the official x-heep repository.
#
# This keeps the device library (drivers, BSP, runtime headers) aligned with
# the upstream x-heep project.  The sync is ADDITIVE: files from x-heep are
# added or updated, but files that exist in this repo but not in x-heep are
# left untouched.  This is intentional because several files (crt0.S,
# vectors.S, core_v_mini_mcu.h, ...) are generated from templates and are
# committed here for PYNQ-Z2 but are NOT committed in the upstream repo.
#
# Only sw/device/ is touched; the custom sw/Makefile, sw/linker/,
# sw/applications/, and the FPGA-specific sw/device/lib/runtime/syscalls.c
# are left untouched.
#
# Usage: install_xheep_sw.sh [XHEEP_REPO_URL]
#   Default URL: https://github.com/x-heep/x-heep

XHEEP_REPO="${1:-https://github.com/x-heep/x-heep}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SW_DIR="$(cd "$SCRIPT_DIR/../sw" && pwd)"
DEVICE_DIR="$SW_DIR/device"

# Save the custom syscalls.c before the sync
SYSCALLS_BACKUP=$(mktemp)
if [ -f "$DEVICE_DIR/lib/runtime/syscalls.c" ]; then
    cp "$DEVICE_DIR/lib/runtime/syscalls.c" "$SYSCALLS_BACKUP"
    RESTORE_SYSCALLS=1
else
    RESTORE_SYSCALLS=0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$SYSCALLS_BACKUP"' EXIT

echo "Cloning x-heep (sparse) from ${XHEEP_REPO}..."
git clone --depth=1 --filter=blob:none --sparse "$XHEEP_REPO" "$TMP/x-heep"
cd "$TMP/x-heep"
git sparse-checkout set sw/device

echo "Syncing sw/device/ from x-heep..."
# No --delete: files not present in x-heep (generated files like crt0.S,
# vectors.S, core_v_mini_mcu.h that are committed here but not upstream)
# must be preserved.
# --exclude the pynq-z2 target so we never overwrite the board-specific
# x-heep.h (safety net for future divergence).
rsync -a \
    --exclude='target/pynq-z2/' \
    "$TMP/x-heep/sw/device/" \
    "$DEVICE_DIR/"

# If x-heep also ships a pynq-z2 target, merge it (add new files, skip existing ones)
if [ -d "$TMP/x-heep/sw/device/target/pynq-z2" ]; then
    rsync -a --ignore-existing \
        "$TMP/x-heep/sw/device/target/pynq-z2/" \
        "$DEVICE_DIR/target/pynq-z2/"
fi

# Restore the FPGA-specific syscalls.c (picolibc-compatible, lazy uart init)
if [ "$RESTORE_SYSCALLS" -eq 1 ]; then
    cp "$SYSCALLS_BACKUP" "$DEVICE_DIR/lib/runtime/syscalls.c"
    echo "Restored custom syscalls.c"
fi

echo "sw/device/ updated from x-heep."
