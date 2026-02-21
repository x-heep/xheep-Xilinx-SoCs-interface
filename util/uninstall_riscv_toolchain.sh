#!/bin/bash
set -euo pipefail

# Remove the CoreV RISC-V toolchain installed by install_riscv_toolchain.sh

FLAVOR="xheep-base"
INSTALL_BASE="/opt"
SYMLINK="/opt/pulp-riscv"

for ARCH_LABEL in armhf aarch64; do
  INSTALL_DIR="${INSTALL_BASE}/riscv-${ARCH_LABEL}-${FLAVOR}"
  if [ -d "$INSTALL_DIR" ]; then
    echo "Removing ${INSTALL_DIR}..."
    sudo rm -rf "$INSTALL_DIR"
  fi

  PATH_LINE="export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
  if grep -qF "$PATH_LINE" /root/.bashrc 2>/dev/null; then
    sudo sed -i "\|${PATH_LINE}|d" /root/.bashrc
    echo "Removed PATH entry from /root/.bashrc"
  fi
  if [ "${USER:-}" != "root" ] && grep -qF "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
    sed -i "\|${PATH_LINE}|d" "$HOME/.bashrc"
    echo "Removed PATH entry from $HOME/.bashrc"
  fi
done

if [ -L "$SYMLINK" ]; then
  echo "Removing symlink ${SYMLINK}..."
  sudo rm -f "$SYMLINK"
fi

echo "CoreV RISC-V toolchain (${FLAVOR}) uninstalled."
