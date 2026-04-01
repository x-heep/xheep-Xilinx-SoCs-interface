#!/bin/bash
set -euo pipefail

# Sync sw/ from the official x-heep repository
# {https://github.com/x-heep/x-heep}.
#
# This keeps software sources aligned with upstream x-heep, while syncing only
# the selected board target under sw/device/target.
#
# BOARD options: AUP-ZU3 or PYNQ-Z2


SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Robustly resolve path to github-requirements.txt relative to this script
GITHUB_REQ="$SCRIPT_DIR/github-requirements.txt"
# Extract x-heep repo from github-requirements.txt
XHEEP_REPO=$(awk '/x-heep\/x-heep/ {print $1}' "$GITHUB_REQ")
XHEEP_CHECKOUT=$(awk '/x-heep\/x-heep/ {print $2}' "$GITHUB_REQ")
SW_DIR="$(cd "$SCRIPT_DIR/../sw" && pwd)"
DEVICE_DIR="$SW_DIR/device"
SYNC_MARKER="$SW_DIR/.xheep_sync_marker"

BOARD_RAW="${BOARD:-PYNQ-Z2}"
BOARD_NORM=$(echo "$BOARD_RAW" | tr '[:lower:]' '[:upper:]')
case "$BOARD_NORM" in
    PYNQ-Z2)
        BOARD_TARGET="pynq-z2"
        ;;
    AUP-ZU3)
        BOARD_TARGET="aup-zu3"
        ;;
    *)
        echo "Unsupported BOARD: ${BOARD_RAW}. Use one of: PYNQ-Z2, AUP-ZU3" >&2
        exit 1
        ;;
esac

if [[ "$XHEEP_CHECKOUT" =~ ^[0-9a-fA-F]{40}$ ]]; then
    EXPECTED_COMMIT="$XHEEP_CHECKOUT"
else
    EXPECTED_COMMIT="$(git ls-remote "$XHEEP_REPO" "refs/heads/$XHEEP_CHECKOUT" | awk 'NR==1 {print $1}')"
fi

EXPECTED_SYNC_KEY="${EXPECTED_COMMIT}:${BOARD_TARGET}"

if [ -n "${EXPECTED_COMMIT:-}" ] && [ -f "$SYNC_MARKER" ] && [ -f "$DEVICE_DIR/lib/crt/crt0.S" ]; then
    CURRENT_SYNC="$(cat "$SYNC_MARKER" 2>/dev/null || true)"
    if [ "$CURRENT_SYNC" = "$EXPECTED_SYNC_KEY" ]; then
        echo "SKIP: sw already synced at ${EXPECTED_COMMIT} for board ${BOARD_TARGET}."
        exit 0
    fi
fi

TMP=$(mktemp -d)
PRESERVE_DIR=$(mktemp -d)
trap 'rm -rf "$TMP" "$PRESERVE_DIR"' EXIT

echo "Cloning x-heep (sparse) from ${XHEEP_REPO}..."
git clone --depth=1 --filter=blob:none --sparse "$XHEEP_REPO" "$TMP/x-heep"
cd "$TMP/x-heep"
if [ -n "${XHEEP_CHECKOUT:-}" ]; then
    git checkout "$XHEEP_CHECKOUT"
fi
git sparse-checkout set sw

echo "Collecting local sw custom files to preserve (excluding syscalls.c)..."
diff -qr "$TMP/x-heep/sw" "$SW_DIR" | awk -v sw="$SW_DIR" '
/^Files / && / differ$/ {
    b=$4
    if (index(b, sw"/")==1) { sub(sw"/", "", b); print b }
}
/^Only in / {
    d=$3; sub(/:$/, "", d)
    n=$4
    if (index(d, sw)==1) {
        sub(sw"/?", "", d)
        if (d=="" || d==".") print n; else print d"/"n
    }
}
' | sort -u | while IFS= read -r rel_path; do
        [ -z "$rel_path" ] && continue
        [ "$rel_path" = "device/lib/runtime/syscalls.c" ] && continue
        if [ -e "$SW_DIR/$rel_path" ]; then
                mkdir -p "$PRESERVE_DIR/$(dirname "$rel_path")"
                cp -a "$SW_DIR/$rel_path" "$PRESERVE_DIR/$rel_path"
        fi
done

echo "Syncing sw/ from x-heep (board target: ${BOARD_TARGET})..."
# Sync full sw/, but exclude all board targets first.
rsync -a \
        --delete \
    --exclude='build/' \
    --exclude='device/target/*' \
    "$TMP/x-heep/sw/" \
    "$SW_DIR/"

# Sync only the selected board target directory.
if [ -d "$TMP/x-heep/sw/device/target/${BOARD_TARGET}" ]; then
    mkdir -p "$DEVICE_DIR/target/${BOARD_TARGET}"
    rsync -a --delete \
        "$TMP/x-heep/sw/device/target/${BOARD_TARGET}/" \
        "$DEVICE_DIR/target/${BOARD_TARGET}/"
else
    echo "Warning: board target '${BOARD_TARGET}' not found upstream."
fi

# Restore only local custom files detected before sync.
if [ -n "$(find "$PRESERVE_DIR" -type f 2>/dev/null)" ]; then
    rsync -a "$PRESERVE_DIR/" "$SW_DIR/"
fi

echo "sw/ updated from x-heep."

SYNC_COMMIT="$(git rev-parse HEAD)"
echo "${SYNC_COMMIT}:${BOARD_TARGET}" > "$SYNC_MARKER"
echo "DONE: sync marker updated to ${SYNC_COMMIT} (board ${BOARD_TARGET})."
