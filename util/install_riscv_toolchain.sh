#!/bin/bash
set -euo pipefail

# Download and install the CORE-V RISC-V toolchain for X-HEEP
# from the riscv-Xilinx-SoCs-toolchain GitHub release
# {https://github.com/vlsi-lab/riscv-Xilinx-SoCs-toolchain}
#
# This is the same toolchain used by x-heep (riscv32-corev-elf-gcc /
# riscv32-unknown-elf-gcc depending on how riscv-gnu-toolchain was configured)
# Skips installation if already present
#
# The toolchain is installed to $HOME/.riscv, matching x-heep's convention
# The sw/Makefile defaults to RISCV=$(HOME)/.riscv and will find it there

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GITHUB_REQ="$SCRIPT_DIR/github-requirements.txt"
TOOLCHAIN_REPO=$(awk '/vlsi-lab\/riscv-Xilinx-SoCs-toolchain/ {match($1, /github.com\/([^/]+\/[^.]+)(.git)?/, m); print m[1]}' "$GITHUB_REQ")
# Optionally extract checkout (not used in this script, but available)
TOOLCHAIN_CHECKOUT=$(awk '/vlsi-lab\/riscv-Xilinx-SoCs-toolchain/ {print $2}' "$GITHUB_REQ")
INSTALL_ROOT="${HOME}/.riscv"

FLAVOR_ARG="${1:-base}"
case "$FLAVOR_ARG" in
  base|float|zfinx)
    REQUESTED_FLAVORS=("$FLAVOR_ARG")
    ;;
  all)
    REQUESTED_FLAVORS=(base float zfinx)
    ;;
  *)
    echo "Unsupported FLAVOR: ${FLAVOR_ARG}. Use one of: base, float, zfinx, all" >&2
    exit 1
    ;;
esac

asset_suffix_for_flavor() {
  local flavor="$1"
  case "$flavor" in
    base)  echo "rv32i-imac" ;;
    float) echo "rv32i-imafc" ;;
    zfinx) echo "rv32i-imac-zfinx" ;;
    *)
      echo "Unknown flavor: ${flavor}" >&2
      return 1
      ;;
  esac
}

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
# riscv32-corev-elf-gcc (CORE-V patched) or riscv32-unknown-elf-gcc (default)
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

# Fetch release metadata
echo "Fetching latest release info from ${TOOLCHAIN_REPO}..."
LATEST_API="https://api.github.com/repos/${TOOLCHAIN_REPO}/releases/latest"
RELEASE_JSON=$(curl -fsSL "$LATEST_API")

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

INSTALLED_ANY=0
for FLAVOR in "${REQUESTED_FLAVORS[@]}"; do
  INSTALL_DIR="${INSTALL_ROOT}/${FLAVOR}"

  if TOOL_BIN=$(find_gcc "${INSTALL_DIR}"); then
    echo "Flavor '${FLAVOR}' already installed at ${INSTALL_DIR}:"
    echo "  $("${TOOL_BIN}" --version 2>&1 | head -1)"
    continue
  fi

  ASSET_SUFFIX=$(asset_suffix_for_flavor "$FLAVOR")
  ASSET_PREFIX="riscv-toolchain-${ARCH_LABEL}-${ASSET_SUFFIX}-"

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
  echo "Downloading ${ASSET_NAME} for flavor '${FLAVOR}'..."
  curl -fSL --progress-bar -o "${TMP}/${FLAVOR}.tar.gz" "$ASSET_URL"

  echo "Installing flavor '${FLAVOR}' to ${INSTALL_DIR}..."
  mkdir -p "${INSTALL_DIR}"
  tar -xzf "${TMP}/${FLAVOR}.tar.gz" -C "${INSTALL_DIR}" --strip-components=1

  if ! TOOL_BIN=$(find_gcc "${INSTALL_DIR}"); then
    echo "Error: no riscv32-*-elf-gcc found in ${INSTALL_DIR}/bin/ after extraction." >&2
    echo "Contents of ${INSTALL_DIR}/bin/:" >&2
    ls "${INSTALL_DIR}/bin/" 2>/dev/null || echo "  (bin/ directory not found)" >&2
    echo "Check the archive structure (expected top-level directory stripped by --strip-components=1)." >&2
    exit 1
  fi

  GCC_NAME=$(basename "${TOOL_BIN}")
  echo "Installed (${FLAVOR}): $(\"${TOOL_BIN}\" --version 2>&1 | head -1)"
  echo "Compiler binary: ${GCC_NAME}"
  INSTALLED_ANY=1
done

# Keep a compatibility symlink for terminal users; default to requested flavor,
# and to base when installing all.
ACTIVE_FLAVOR="$FLAVOR_ARG"
if [ "$ACTIVE_FLAVOR" = "all" ]; then
  ACTIVE_FLAVOR="base"
fi
if [ -d "${INSTALL_ROOT}/${ACTIVE_FLAVOR}" ]; then
  ln -sfn "${INSTALL_ROOT}/${ACTIVE_FLAVOR}" "${INSTALL_ROOT}/current"
fi

# Add to PATH in shell rc files
PATH_LINE="export PATH=\"${INSTALL_ROOT}/current/bin:\$PATH\""
LEGACY_PATH_LINE="export PATH=\"${INSTALL_ROOT}/bin:\$PATH\""
for RC in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
  if [ -f "$RC" ] && grep -qF "$LEGACY_PATH_LINE" "$RC" 2>/dev/null; then
    sed -i "\|${LEGACY_PATH_LINE}|d" "$RC"
    echo "Removed legacy PATH entry from ${RC}"
  fi
  if [ -f "$RC" ] && ! grep -qF "$PATH_LINE" "$RC" 2>/dev/null; then
    echo "$PATH_LINE" >> "$RC"
    echo "Added PATH entry to ${RC}"
  fi
done

echo ""
echo "CORE-V RISC-V toolchain flavors under ${INSTALL_ROOT}:"
for FLAVOR in base float zfinx; do
  if [ -d "${INSTALL_ROOT}/${FLAVOR}" ]; then
    echo "  - ${FLAVOR}: ${INSTALL_ROOT}/${FLAVOR}"
  fi
done
if [ "$INSTALLED_ANY" -eq 0 ]; then
  echo "No new flavor was installed (requested flavors already present)."
fi
echo "Active flavor for shell PATH: ${ACTIVE_FLAVOR}"
echo "Re-source your shell or open a new terminal to pick up the updated PATH..."
