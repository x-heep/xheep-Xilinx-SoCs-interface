# This script can be extended to use util/github-requirements.txt for custom git installs if needed.
set -euo pipefail

# Clone, patch, build and install OpenOCD v0.12.0
# Skips the build entirely if OpenOCD is already installed at the expected commit.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OPENOCD_DIR="/usr/local/src/openocd"
PATCH_SCRIPT="$ROOT_DIR/scripts/install_openocd.sh"

if [ ! -x "$PATCH_SCRIPT" ]; then
  echo "Making $PATCH_SCRIPT executable"
  chmod +x "$PATCH_SCRIPT" || true
fi

echo "Preparing OpenOCD in ${OPENOCD_DIR}. This will checkout v0.12.0, apply patch and build."

bash "$PATCH_SCRIPT" "$OPENOCD_DIR"
