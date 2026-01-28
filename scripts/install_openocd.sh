#!/usr/bin/env bash
set -euo pipefail

# Script to fetch, patch, build and install OpenOCD v0.12.0
# Usage: ./install_openocd.sh [target_dir]

REPO_URL="https://github.com/openocd-org/openocd.git"
TAG="v0.12.0"
# patch file in repository root
PATCH_PATH="$(cd "$(dirname "$0")/.." && pwd)/patch/openocd.patch"
TARGET_DIR="${1:-/usr/local/src/openocd}"
GIT_DIFF_PY="$(cd "$(dirname "$0")/.." && pwd)/util/git-diff.py"

echo "OpenOCD target: ${TARGET_DIR}"

if [ ! -d "${TARGET_DIR}" ]; then
  git clone "${REPO_URL}" "${TARGET_DIR}"
fi

cd "${TARGET_DIR}"
git fetch --tags --all

echo "Checking out ${TAG}"
git checkout "${TAG}" || git checkout -B "build-${TAG}" "${TAG}"
git reset --hard "${TAG}"

if [ -f "${PATCH_PATH}" ]; then
  echo "Applying patch: ${PATCH_PATH}"
  # Apply patch using patch command with force flag to skip interactive prompts
  patch -p1 --no-backup-if-mismatch --force < "${PATCH_PATH}" 2>&1 || {
    echo "Warning: Patch application had issues, but continuing..."
  }
  git add -A || true
  git commit -m "Apply x-heep patch" || true
else
  echo "No patch file found at ${PATCH_PATH}; skipping"
fi

echo "Initializing and updating submodules"
git submodule update --init --recursive

echo "Preparing build"
if [ -x ./bootstrap ]; then
  ./bootstrap
else
  echo "No bootstrap script found, attempting autoreconf"
  autoreconf -fi || true
fi

echo "Configuring build with FTDI, bitbang and internal JimTcl support"
./configure --enable-ftdi --enable-bitbang --enable-jim || true

echo "Building OpenOCD (this may take a while)"
make -j"$(nproc)"

echo "Installing OpenOCD globally (sudo required)"
sudo make install

echo "OpenOCD ${TAG} should now be installed."
