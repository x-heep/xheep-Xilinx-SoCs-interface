#!/bin/bash
set -euo pipefail

# Download and install a CoreV RISC-V toolchain flavor for X-HEEP
# from the riscv-Xilinx-SoCs-toolchain GitHub release.
# Skips the flavor if it is already installed.
#
# Usage: install_riscv_toolchain.sh [base|float|zfinx]   (default: base)
#
# Available flavors and their symlinks under /opt:
#   base   (xheep-base)   → /opt/openhw-riscv-base   (rv32imc  / ilp32,  no FPU)
#   float  (xheep-float)  → /opt/openhw-riscv-float  (rv32imfc / ilp32f, hardware FPU)
#   zfinx  (xheep-zfinx)  → /opt/openhw-riscv-zfinx  (rv32imc  / ilp32,  Zfinx)

TOOLCHAIN_REPO="Christian-Conti/riscv-Xilinx-SoCs-toolchain"
INSTALL_BASE="/opt"

declare -A FLAVOR_SYMLINK=(
  [xheep-base]="/opt/openhw-riscv-base"
  [xheep-float]="/opt/openhw-riscv-float"
  [xheep-zfinx]="/opt/openhw-riscv-zfinx"
)

# Select flavor from first argument (base | float | zfinx), default: base
EXTENSION="${1:-base}"
case "$EXTENSION" in
  base|float|zfinx) ;;
  *)
    echo "Unknown extension '${EXTENSION}'. Valid values: base, float, zfinx" >&2
    exit 1
    ;;
esac
FLAVORS=("xheep-${EXTENSION}")

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

echo "Detected host architecture: ${ARCH_LABEL}"

# Fetch release metadata once
echo "Fetching latest release info from ${TOOLCHAIN_REPO}..."
LATEST_API="https://api.github.com/repos/${TOOLCHAIN_REPO}/releases/latest"
RELEASE_JSON=$(curl -fsSL "$LATEST_API")

for FLAVOR in "${FLAVORS[@]}"; do
  EXTRACTED_DIR="riscv-${ARCH_LABEL}-${FLAVOR}"
  INSTALL_DIR="${INSTALL_BASE}/${EXTRACTED_DIR}"
  ASSET_PREFIX="riscv-toolchain-${ARCH_LABEL}-${FLAVOR}-"
  SYMLINK="${FLAVOR_SYMLINK[$FLAVOR]}"

  echo ""
  echo "==> Flavor: ${FLAVOR}"

  EXISTING_GCC=$(find "${INSTALL_DIR}/bin" -maxdepth 1 -type f -name "*-gcc" 2>/dev/null | head -n 1) || true
  if [ -n "$EXISTING_GCC" ] && [ -x "$EXISTING_GCC" ]; then
    echo "    Already installed at ${INSTALL_DIR} ($(basename "$EXISTING_GCC")) — skipping."
    # Ensure the symlink is still correct even on re-runs
    sudo ln -sfn "${INSTALL_DIR}" "${SYMLINK}"
    continue
  fi

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
    echo "    Error: could not find asset matching '${ASSET_PREFIX}*' in the latest release." >&2
    exit 1
  fi

  ASSET_NAME=$(basename "$ASSET_URL")
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT

  echo "    Downloading ${ASSET_NAME}..."
  curl -fSL --progress-bar -o "${TMP}/${ASSET_NAME}" "$ASSET_URL"

  echo "    Extracting to ${INSTALL_DIR}..."
  sudo tar -xzf "${TMP}/${ASSET_NAME}" -C "${INSTALL_BASE}"

  sudo rm -rf "${INSTALL_DIR}/share" "${INSTALL_DIR}/doc" "${INSTALL_DIR}/man" 2>/dev/null || true
  if [ -d "${INSTALL_DIR}/bin" ]; then
    find "${INSTALL_DIR}/bin" -type f -executable \
      | xargs -r sudo strip --strip-all 2>/dev/null || true
  fi
  if [ -d "${INSTALL_DIR}/libexec" ]; then
    find "${INSTALL_DIR}/libexec" -type f -executable \
      | xargs -r sudo strip --strip-all 2>/dev/null || true
  fi
  if [ -d "${INSTALL_DIR}/lib" ]; then
    find "${INSTALL_DIR}/lib" -type f -name '*.so*' \
      | xargs -r sudo strip --strip-all 2>/dev/null || true
    find "${INSTALL_DIR}/lib" -type f -name '*.a' \
      | xargs -r sudo strip --strip-debug 2>/dev/null || true
  fi

  TOOL_BIN=$(find "${INSTALL_DIR}/bin" -maxdepth 1 -type f -name "*-gcc" 2>/dev/null | head -n 1) || true
  if [ -z "$TOOL_BIN" ] || [ ! -x "$TOOL_BIN" ]; then
    echo "    Error: no *-gcc binary found in ${INSTALL_DIR}/bin/ after extraction." >&2
    echo "    Check the archive structure (expected top-level: ${EXTRACTED_DIR}/)." >&2
    exit 1
  fi
  echo "    Found compiler: $(basename "$TOOL_BIN")"

  echo "    Creating symlink ${SYMLINK} -> ${INSTALL_DIR}"
  sudo ln -sfn "${INSTALL_DIR}" "${SYMLINK}"

  PATH_LINE="export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
  if ! grep -qF "$PATH_LINE" /root/.bashrc 2>/dev/null; then
    echo "$PATH_LINE" | sudo tee -a /root/.bashrc > /dev/null
  fi
  if [ "${USER:-}" != "root" ] && ! grep -qF "$PATH_LINE" "$HOME/.bashrc" 2>/dev/null; then
    echo "$PATH_LINE" >> "$HOME/.bashrc"
  fi

  echo "    Done: ${INSTALL_DIR}"
done

echo ""
echo "Deduplicating toolchain files with hardlinks..."
if command -v jdupes &>/dev/null; then
  TOOL_DIRS=()
  for FLAVOR in "${FLAVORS[@]}"; do
    D="${INSTALL_BASE}/riscv-${ARCH_LABEL}-${FLAVOR}"
    [ -d "$D" ] && TOOL_DIRS+=("$D")
  done
  if [ ${#TOOL_DIRS[@]} -gt 1 ]; then
    sudo jdupes -rH "${TOOL_DIRS[@]}"
    echo "Hardlink deduplication complete."
  fi
else
  echo "  (jdupes not found — skipping hardlink deduplication; install with: sudo apt-get install jdupes)"
fi

echo ""
echo "xheep toolchain flavor '${EXTENSION}' installed:"
echo "  ${FLAVOR_SYMLINK[xheep-${EXTENSION}]}  →  ${INSTALL_BASE}/riscv-${ARCH_LABEL}-xheep-${EXTENSION}"
echo ""
echo "Re-source your shell or open a new terminal to pick up the updated PATH."
