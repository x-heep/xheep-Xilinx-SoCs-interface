#!/bin/bash
set -euo pipefail

# Copyright 2026 Politecnico di Torino.
#
# File: install_xheep_sw.sh
# Author: Christian Conti {christian.conti@polito.it}
# Date: 31/03/2026
# Description: Fetch, patch, build and install OpenOCD v0.12.0
# Skips the build if the binary at /usr/local/bin/openocd was already built
# from the expected commit
#
# Usage: ./install_openocd.sh [target_dir]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GITHUB_REQ="$SCRIPT_DIR/github-requirements.txt"
# Extract OpenOCD repo and commit from github-requirements.txt
REPO_URL=$(awk '/openocd-org\/openocd/ {print $1}' "$GITHUB_REQ")
TAG=$(awk '/openocd-org\/openocd/ {print $2}' "$GITHUB_REQ")
PATCH_PATH="$(cd "$(dirname "$0")/.." && pwd)/patch/openocd.patch"
TARGET_DIR="${1:-/usr/local/src/openocd}"
OPENOCD_BIN="/usr/local/bin/openocd"
PATCH_COMMIT_MSG="Apply x-heep patch"
BUILD_BRANCH="xheep-openocd-${TAG:0:8}"

echo "OpenOCD target: ${TARGET_DIR} (repo: $REPO_URL, commit: $TAG)"

if [ -f "$OPENOCD_BIN" ] && [ -d "${TARGET_DIR}/.git" ]; then
  INSTALLED_COMMIT="$(cd "${TARGET_DIR}" && git rev-parse HEAD 2>/dev/null || true)"
  INSTALLED_PARENT="$(cd "${TARGET_DIR}" && git rev-parse HEAD^ 2>/dev/null || true)"
  INSTALLED_SUBJECT="$(cd "${TARGET_DIR}" && git log -1 --pretty=%s 2>/dev/null || true)"

  if [ "$INSTALLED_COMMIT" = "$TAG" ] || { [ "$INSTALLED_PARENT" = "$TAG" ] && [ "$INSTALLED_SUBJECT" = "$PATCH_COMMIT_MSG" ]; }; then
    echo "SKIP: OpenOCD already built from target commit ${TAG}..."
    exit 0
  fi

  echo "OpenOCD present but from a different commit (${INSTALLED_COMMIT}), rebuilding..."
fi

if [ -d "${TARGET_DIR}/.git" ]; then
  echo "Repository already exists at ${TARGET_DIR}, fetching tags..."
  cd "${TARGET_DIR}"
  git fetch --tags --all
else
  git clone "${REPO_URL}" "${TARGET_DIR}"
  cd "${TARGET_DIR}"
  git fetch --tags --all
fi

echo "Checking out ${TAG}"
git checkout -B "${BUILD_BRANCH}" "${TAG}"
git reset --hard "${TAG}"

echo "Applying patch: ${PATCH_PATH}"
patch -p1 --no-backup-if-mismatch --force < "${PATCH_PATH}" >/dev/null 2>&1 || true

git add -A || true
# Set local git identity if not already set 
if ! git config user.email >/dev/null; then
  git config user.email "x-heep@localhost"
fi
if ! git config user.name >/dev/null; then
  git config user.name "x-heep"
fi
git commit -m "$PATCH_COMMIT_MSG" || true

echo "Initializing and updating submodules"
git submodule update --init --recursive

echo "Preparing build"
./bootstrap

echo "Configuring build with FTDI, bitbang, XVC and internal JimTcl support"
./configure --enable-ftdi --enable-bitbang --enable-xlnx-axi-xvc --enable-internal-jimtcl

echo "Building OpenOCD..."
make -j"$(nproc)"
sudo make install
make clean

echo "DONE: OpenOCD ${TAG} installed..."
