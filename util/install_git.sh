#!/bin/bash
set -euo pipefail

# Clone, patch, build and install OpenOCD v0.12.0
# Skips the build entirely if OpenOCD is already installed at the expected commit

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OPENOCD_DIR="/usr/local/src/openocd"
PATCH_SCRIPT="$ROOT_DIR/util/install_openocd.sh"
GITHUB_REQ="$ROOT_DIR/util/github-requirements.txt"
OPENOCD_BIN="/usr/local/bin/openocd"
TAG=$(awk '/openocd-org\/openocd/ {print $2}' "$GITHUB_REQ")

if [ -f "$OPENOCD_BIN" ] && [ -d "${OPENOCD_DIR}/.git" ]; then
  INSTALLED_COMMIT="$(cd "${OPENOCD_DIR}" && git rev-parse HEAD 2>/dev/null || true)"
  if [ "$INSTALLED_COMMIT" = "$TAG" ]; then
    echo "SKIP: OpenOCD already installed at commit ${TAG}."
    exit 0
  fi
fi

if [ ! -x "$PATCH_SCRIPT" ]; then
  echo "Making $PATCH_SCRIPT executable"
  chmod +x "$PATCH_SCRIPT" || true
fi

echo "Preparing OpenOCD in ${OPENOCD_DIR}. Checkout v0.12.0, apply patch and build..."

bash "$PATCH_SCRIPT" "$OPENOCD_DIR"
echo "DONE: OpenOCD prepared."
