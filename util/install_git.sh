#!/usr/bin/env bash
set -euo pipefail

# Clone, patch, build and install OpenOCD v0.12.0
# Uses scripts/install_openocd.sh for the build and util/git-diff.py to check diffs

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OPENOCD_DIR="/usr/local/src/openocd"
PATCH_SCRIPT="$ROOT_DIR/scripts/install_openocd.sh"
GIT_DIFF_PY="$ROOT_DIR/util/git-diff.py"

if [ ! -x "$PATCH_SCRIPT" ]; then
  echo "Making $PATCH_SCRIPT executable"
  chmod +x "$PATCH_SCRIPT" || true
fi

echo "Preparing OpenOCD in ${OPENOCD_DIR}. This will checkout v0.12.0, apply patch and build."

bash "$PATCH_SCRIPT" "$OPENOCD_DIR"

echo "OpenOCD install script finished. Running util/git-diff.py in target repo to report any local changes."
if [ -f "$GIT_DIFF_PY" ]; then
  (cd "$OPENOCD_DIR" && python "$GIT_DIFF_PY") || true
else
  echo "Warning: util/git-diff.py not found at $GIT_DIFF_PY"
fi

echo "OpenOCD build/install requested; if 'sudo make install' was run, OpenOCD should be available as 'openocd'."
