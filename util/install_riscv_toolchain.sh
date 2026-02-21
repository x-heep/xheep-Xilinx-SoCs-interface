#!/bin/bash
set -euo pipefail

# Download and install the CoreV RISC-V toolchain for X-HEEP (xheep-base flavor)
# from the riscv-Xilinx-SoCs-toolchain GitHub release.
# Skips installation entirely if the toolchain binary is already present.

TOOLCHAIN_REPO="Christian-Conti/riscv-Xilinx-SoCs-toolchain"
FLAVOR="xheep-base"
INSTALL_BASE="/opt"
SYMLINK="/opt/pulp-riscv"

# Detect host architecture
MACHINE=$(uname -m)
case "$MACHINE" in
  armv7l|armhf) ARCH_LABEL="armhf" ;;
  aarch64)       ARCH_LABEL="aarch64" ;;
  *)
    echo "Unsupported host architecture: $MACHINE" >&2
    exit 1
    ;;
esac

EXTRACTED_DIR="riscv-${ARCH_LABEL}-${FLAVOR}"
INSTALL_DIR="${INSTALL_BASE}/${EXTRACTED_DIR}"
TOOL_BIN="${INSTALL_DIR}/bin/riscv32-corev-elf-gcc"
ASSET_PREFIX="riscv-toolchain-${ARCH_LABEL}-${FLAVOR}-"

echo "Detected host architecture: ${ARCH_LABEL}"
echo "Toolchain flavor: ${FLAVOR}"

if [ -x "$TOOL_BIN" ]; then
  echo "CoreV RISC-V toolchain already installed at ${INSTALL_DIR} — skipping."
  exit 0
fi

echo "Fetching latest release info from ${TOOLCHAIN_REPO}..."
LATEST_API="https://api.github.com/repos/${TOOLCHAIN_REPO}/releases/latest"

ASSET_URL=$(curl -fsSL "$LATEST_API" | python3 -c "
import sys, json
data = json.load(sys.stdin)
prefix = '${ASSET_PREFIX}'
for a in data.get('assets', []):
    if a['name'].startswith(prefix):
        print(a['browser_download_url'])
        break
" 2>/dev/null || true)

if [ -z "$ASSET_URL" ]; then
  echo "" >&2
  echo "Error: Could not find asset matching '${ASSET_PREFIX}*' in the latest release of ${TOOLCHAIN_REPO}." >&2
  echo "Make sure the CI workflow has published a GitHub Release with the xheep-base flavor." >&2
  exit 1
fi

ASSET_NAME=$(basename "$ASSET_URL")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${ASSET_NAME} from:"
echo "  ${ASSET_URL}"
curl -fSL --progress-bar -o "${TMP}/${ASSET_NAME}" "$ASSET_URL"

echo "Extracting toolchain to ${INSTALL_DIR}..."
sudo tar -xzf "${TMP}/${ASSET_NAME}" -C "${INSTALL_BASE}"

# Create symlink so the generic /opt/pulp-riscv path works in sw/Makefile
echo "Creating symlink ${SYMLINK} -> ${INSTALL_DIR}"
sudo ln -sfn "${INSTALL_DIR}" "${SYMLINK}"

if [ ! -x "$TOOL_BIN" ]; then
  echo "Error: installation finished but ${TOOL_BIN} not found." >&2
  echo "Check the archive structure (expected top-level directory: ${EXTRACTED_DIR}/)." >&2
  exit 1
fi

PATH_LINE="export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
if ! grep -qF "$PATH_LINE" /root/.bashrc 2>/dev/null; then
  echo "$PATH_LINE" | sudo tee -a /root/.bashrc > /dev/null
  echo "Added ${INSTALL_DIR}/bin to /root/.bashrc"
fi

# Also add to the current user's bashrc in case they aren't root
if [ "${USER:-}" != "root" ] && ! grep -qF "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
  echo "$PATH_LINE" >> "$HOME/.bashrc"
  echo "Added ${INSTALL_DIR}/bin to $HOME/.bashrc"
fi

echo "CoreV RISC-V toolchain (${FLAVOR} / ${ARCH_LABEL}) successfully installed at ${INSTALL_DIR}."
echo "Re-source your shell or run: export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
