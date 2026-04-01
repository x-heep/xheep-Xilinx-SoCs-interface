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
# are left untouched


SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Robustly resolve path to github-requirements.txt relative to this script
GITHUB_REQ="$SCRIPT_DIR/github-requirements.txt"
# Extract x-heep repo from github-requirements.txt
XHEEP_REPO=$(awk '/x-heep\/x-heep/ {print $1}' "$GITHUB_REQ")
XHEEP_CHECKOUT=$(awk '/x-heep\/x-heep/ {print $2}' "$GITHUB_REQ")
SW_DIR="$(cd "$SCRIPT_DIR/../sw" && pwd)"
DEVICE_DIR="$SW_DIR/device"
SYNC_MARKER="$DEVICE_DIR/.xheep_sync_commit"

if [[ "$XHEEP_CHECKOUT" =~ ^[0-9a-fA-F]{40}$ ]]; then
    EXPECTED_COMMIT="$XHEEP_CHECKOUT"
else
    EXPECTED_COMMIT="$(git ls-remote "$XHEEP_REPO" "refs/heads/$XHEEP_CHECKOUT" | awk 'NR==1 {print $1}')"
fi

if [ -n "${EXPECTED_COMMIT:-}" ] && [ -f "$SYNC_MARKER" ] && [ -f "$DEVICE_DIR/lib/crt/crt0.S" ]; then
    CURRENT_SYNC="$(cat "$SYNC_MARKER" 2>/dev/null || true)"
    if [ "$CURRENT_SYNC" = "$EXPECTED_COMMIT" ]; then
        echo "SKIP: sw/device already synced at ${EXPECTED_COMMIT}."
        exit 0
    fi
fi

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
if [ -n "${XHEEP_CHECKOUT:-}" ]; then
    git checkout "$XHEEP_CHECKOUT"
fi
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

SYNC_COMMIT="$(git rev-parse HEAD)"
echo "$SYNC_COMMIT" > "$SYNC_MARKER"
echo "DONE: sync marker updated to ${SYNC_COMMIT}."
