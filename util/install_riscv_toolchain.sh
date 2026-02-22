#!/bin/bash
set -euo pipefail

# Download and install the CORE-V RISC-V toolchain for X-HEEP
# from the riscv-Xilinx-SoCs-toolchain GitHub release.
# This is the same toolchain used by x-heep (riscv32-corev-elf-gcc /
# riscv32-unknown-elf-gcc depending on how riscv-gnu-toolchain was configured).
# Skips installation if already present.
#
# The toolchain is installed to $HOME/.riscv, matching x-heep's convention.
# The sw/Makefile defaults to RISCV=$(HOME)/.riscv and will find it there.
#
# Usage: install_riscv_toolchain.sh

TOOLCHAIN_REPO="Christian-Conti/riscv-Xilinx-SoCs-toolchain"
INSTALL_DIR="${HOME}/.riscv"

# Detect host architecture
MACHINE=$(uname -m)
case "$MACHINE" in
  armv7l|armhf) ARCH_LABEL="armhf" ;;
  aarch64)       ARCH_LABEL="aarch64" ;;
  x86_64)        ARCH_LABEL="x86_64" ;;
  *)
    echo "Unsupported host architecture: $MACHINE" >&2
    exit 1
    ;;
esac

echo "Detected host architecture: ${ARCH_LABEL}"

# Locate the GCC binary — riscv-gnu-toolchain may produce either
# riscv32-corev-elf-gcc (CORE-V patched) or riscv32-unknown-elf-gcc (default).
find_gcc() {
  local dir="$1"
  for name in riscv32-corev-elf-gcc riscv32-unknown-elf-gcc; do
    if [ -x "${dir}/bin/${name}" ]; then
      echo "${dir}/bin/${name}"
      return 0
    fi
  done
  return 1
}

# Check if already installed
if TOOL_BIN=$(find_gcc "${INSTALL_DIR}"); then
  echo "Already installed at ${INSTALL_DIR}:"
  echo "  $("${TOOL_BIN}" --version 2>&1 | head -1)"
  exit 0
fi

# Fetch release metadata
echo "Fetching latest release info from ${TOOLCHAIN_REPO}..."
LATEST_API="https://api.github.com/repos/${TOOLCHAIN_REPO}/releases/latest"
RELEASE_JSON=$(curl -fsSL "$LATEST_API")

# rv32i-imac provides plain rv32imc multilibs (no xcv) — same as embecosm's libc.
# xheep-base only has xcv multilibs; with -march=rv32imc_zicsr the linker would
# fall back to an xcv-flavoured libc which may behave differently or have bugs
# in the development branch. rv32i-imac is the correct match.
ASSET_PREFIX="riscv-toolchain-${ARCH_LABEL}-rv32i-imac-"

ASSET_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
prefix = '${ASSET_PREFIX}'
for a in data.get('assets', []):
    if a['name'].startswith(prefix):
        print(a['browser_download_url'])
        break
" 2>/dev/null || true)

if [ -z "$ASSET_URL" ]; then
  echo "Error: could not find asset matching '${ASSET_PREFIX}*' in the latest release." >&2
  echo "Check the releases at: https://github.com/${TOOLCHAIN_REPO}/releases" >&2
  exit 1
fi

ASSET_NAME=$(basename "$ASSET_URL")
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${ASSET_NAME}..."
curl -fSL --progress-bar -o "${TMP}/${ASSET_NAME}" "$ASSET_URL"

echo "Installing to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
tar -xzf "${TMP}/${ASSET_NAME}" -C "${INSTALL_DIR}" --strip-components=1

if ! TOOL_BIN=$(find_gcc "${INSTALL_DIR}"); then
  echo "Error: no riscv32-*-elf-gcc found in ${INSTALL_DIR}/bin/ after extraction." >&2
  echo "Contents of ${INSTALL_DIR}/bin/:" >&2
  ls "${INSTALL_DIR}/bin/" 2>/dev/null || echo "  (bin/ directory not found)" >&2
  echo "Check the archive structure (expected top-level directory stripped by --strip-components=1)." >&2
  exit 1
fi

GCC_NAME=$(basename "${TOOL_BIN}")
echo "Installed: $(\"${TOOL_BIN}\" --version 2>&1 | head -1)"
echo "Compiler binary: ${GCC_NAME}"

# Add to PATH in shell rc files
PATH_LINE="export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
for RC in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
  if [ -f "$RC" ] && ! grep -qF "$PATH_LINE" "$RC" 2>/dev/null; then
    echo "$PATH_LINE" >> "$RC"
    echo "Added PATH entry to ${RC}"
  fi
done

echo ""
echo "CORE-V RISC-V toolchain installed at ${INSTALL_DIR}"
echo "Re-source your shell or open a new terminal to pick up the updated PATH."
