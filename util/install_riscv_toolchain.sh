#!/bin/bash
set -euo pipefail

# Download and install the PULP RISC-V toolchain for ARM (armhf/aarch64)
# Skips installation entirely if the toolchain binary is already present

TOOLCHAIN_REPO="Christian-Conti/riscv-pulp-Xilinx-SoCs-toolchain"
INSTALL_DIR="/opt/pulp-riscv"
TOOL_BIN="${INSTALL_DIR}/bin/riscv32-unknown-elf-gcc"

if [ "${BOARD:-}" = "Pynq-Z2" ]; then
  ASSET_NAME="pulp-toolchain-host-armhf-xheep-rv32imc.tar.gz"
  EXTRACTED_DIR="pulp-riscv-armhf"
else
  ASSET_NAME="pulp-toolchain-host-aarch64-xheep-rv32imc.tar.gz"
  EXTRACTED_DIR="pulp-riscv-aarch64"
fi
echo "Board: ${BOARD:-<not set>} → using asset: ${ASSET_NAME}"

if [ -x "$TOOL_BIN" ]; then
  echo "RISC-V PULP toolchain already installed at ${INSTALL_DIR} — skipping."
  exit 0
fi

echo "Fetching latest release info from ${TOOLCHAIN_REPO}..."
LATEST_API="https://api.github.com/repos/${TOOLCHAIN_REPO}/releases/latest"

ASSET_URL=$(curl -fsSL "$LATEST_API" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for a in data.get('assets', []):
    if a['name'] == '${ASSET_NAME}':
        print(a['browser_download_url'])
        break
" 2>/dev/null || true)

if [ -z "$ASSET_URL" ]; then
  echo "" >&2
  echo "Error: Could not find asset '${ASSET_NAME}' in the latest release of ${TOOLCHAIN_REPO}." >&2
  echo "Make sure the toolchain CI workflow publishes a GitHub Release." >&2
  echo "See the CI snippet in the project docs." >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${ASSET_NAME} from:"
echo "  ${ASSET_URL}"
curl -fSL --progress-bar -o "${TMP}/${ASSET_NAME}" "$ASSET_URL"

echo "Extracting toolchain to /opt/${EXTRACTED_DIR}..."
sudo mkdir -p /opt
sudo tar -xzf "${TMP}/${ASSET_NAME}" -C /opt

# Create a symlink so the generic INSTALL_DIR points to the arch-specific folder
echo "Creating symlink ${INSTALL_DIR} -> /opt/${EXTRACTED_DIR}"
sudo ln -sfn "/opt/${EXTRACTED_DIR}" "${INSTALL_DIR}"

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

# Also add to the current user's bashrc just in case they aren't root
if [ "$USER" != "root" ] && ! grep -qF "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
  echo "$PATH_LINE" >> "$HOME/.bashrc"
  echo "Added ${INSTALL_DIR}/bin to $HOME/.bashrc"
fi

echo "RISC-V PULP toolchain successfully installed at ${INSTALL_DIR}."
echo "Re-source your shell or run: export PATH=\"${INSTALL_DIR}/bin:\$PATH\""