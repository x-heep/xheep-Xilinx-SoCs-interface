#!/bin/bash
set -euo pipefail

# Sync sw/device/ from the official x-heep repository
# {https://github.com/x-heep/x-heep}.
#
# This keeps the device library (drivers, BSP, runtime headers) aligned with
# the upstream x-heep project
#
# Only sw/device/ is touched; the custom sw/Makefile, sw/linker/,
# sw/applications/, and the FPGA-specific sw/device/lib/runtime/syscalls.c
# are left untouched.
#
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Robustly resolve path to github-requirements.txt relative to this script
GITHUB_REQ="$SCRIPT_DIR/github-requirements.txt"
# Extract x-heep repo from github-requirements.txt
XHEEP_REPO=$(awk '/x-heep\/x-heep/ {print $1}' "$GITHUB_REQ")
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
# No --delete: files not present in x-heep must be preserved
# --exclude the pynq-z2 target so we never overwrite the board-specific
# x-heep.h
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

# Restore the FPGA-specific syscalls.c
if [ "$RESTORE_SYSCALLS" -eq 1 ]; then
    cp "$SYSCALLS_BACKUP" "$DEVICE_DIR/lib/runtime/syscalls.c"
    echo "Restored custom syscalls.c"
fi

echo "sw/device/ updated from x-heep."
