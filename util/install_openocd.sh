set -euo pipefail

# Script to fetch, patch, build and install OpenOCD v0.12.0
# Skips the build if the binary at /usr/local/bin/openocd was already built
# from the expected commit.
#
# Usage: ./install_openocd.sh [target_dir]

# Robustly resolve path to github-requirements.txt relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GITHUB_REQ="$SCRIPT_DIR/github-requirements.txt"
# Extract OpenOCD repo and commit from github-requirements.txt
REPO_URL=$(awk '/openocd-org\/openocd/ {print $1}' "$GITHUB_REQ")
TAG=$(awk '/openocd-org\/openocd/ {print $2}' "$GITHUB_REQ")
PATCH_PATH="$(cd "$(dirname "$0")/.." && pwd)/patch/openocd.patch"
TARGET_DIR="${1:-/usr/local/src/openocd}"
OPENOCD_BIN="/usr/local/bin/openocd"

echo "OpenOCD target: ${TARGET_DIR} (repo: $REPO_URL, commit: $TAG)"

# ── Skip if already installed at the expected commit ─────────────────────────
if [ -f "$OPENOCD_BIN" ] && [ -d "${TARGET_DIR}/.git" ]; then
  INSTALLED_COMMIT="$(cd "${TARGET_DIR}" && git rev-parse HEAD 2>/dev/null || true)"
  if [ "$INSTALLED_COMMIT" = "$TAG" ]; then
    echo "OpenOCD already built from commit ${TAG} — skipping."
    exit 0
  else
    echo "OpenOCD present but from a different commit (${INSTALLED_COMMIT}), rebuilding."
  fi
fi

# ── Clone or reuse existing directory ────────────────────────────────────────
if [ -d "${TARGET_DIR}/.git" ]; then
  echo "Repository already exists at ${TARGET_DIR}, fetching tags."
  cd "${TARGET_DIR}"
  git fetch --tags --all
else
  git clone "${REPO_URL}" "${TARGET_DIR}"
  cd "${TARGET_DIR}"
  git fetch --tags --all
fi

echo "Checking out ${TAG}"
git checkout "${TAG}" || git checkout -B "build-${TAG}" "${TAG}"
git reset --hard "${TAG}"

echo "Applying patch: ${PATCH_PATH}"
patch -p1 --no-backup-if-mismatch --force < "${PATCH_PATH}" >/dev/null 2>&1 || true

git add -A || true
git commit -m "Apply x-heep patch" || true

echo "Initializing and updating submodules"
git submodule update --init --recursive

echo "Preparing build"
./bootstrap

echo "Configuring build with FTDI, bitbang, XVC and internal JimTcl support"
./configure --enable-ftdi --enable-bitbang --enable-xlnx-axi-xvc --enable-internal-jimtcl

echo "Building OpenOCD (this may take a while)"
make -j"$(nproc)"
sudo make install
make clean

echo "OpenOCD ${TAG} installed."
