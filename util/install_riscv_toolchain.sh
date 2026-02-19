set -euo pipefail

# Download and install the PULP RISC-V toolchain for ARM (armhf/PYNQ-Z2 hosts).
# Skips installation entirely if the toolchain binary is already present.
#
# Requires: curl, python3, sudo (called by install target which already has sudo -v).
# The toolchain repo CI must publish a GitHub Release with pulp-toolchain-armhf.tar.gz
# as a release asset (tag "latest"). See docs for the required CI snippet.

TOOLCHAIN_REPO="Christian-Conti/riscv-pulp-Xilinx-SoCs-toolchain"
INSTALL_DIR="/opt/pulp-riscv"
TOOL_BIN="${INSTALL_DIR}/bin/riscv32-unknown-elf-gcc"
ASSET_NAME="pulp-toolchain-armhf.tar.gz"

# ── Skip if already installed ─────────────────────────────────────────────────
if [ -x "$TOOL_BIN" ]; then
  echo "RISC-V PULP toolchain already installed at ${INSTALL_DIR} — skipping."
  exit 0
fi

# ── Resolve download URL from the latest GitHub Release ──────────────────────
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

# ── Download ──────────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "Downloading ${ASSET_NAME} from:"
echo "  ${ASSET_URL}"
curl -fSL --progress-bar -o "${TMP}/${ASSET_NAME}" "$ASSET_URL"

# ── Install ───────────────────────────────────────────────────────────────────
# The archive is expected to contain a top-level "pulp-riscv/" directory,
# i.e. it was created with: tar -czf pulp-toolchain-armhf.tar.gz -C /opt pulp-riscv
echo "Installing toolchain to ${INSTALL_DIR}..."
sudo mkdir -p /opt
sudo tar -xzf "${TMP}/${ASSET_NAME}" -C /opt

if [ ! -x "$TOOL_BIN" ]; then
  echo "Error: installation finished but ${TOOL_BIN} not found." >&2
  echo "Check the archive structure (expected top-level directory: pulp-riscv/)." >&2
  exit 1
fi

# ── PATH entry ────────────────────────────────────────────────────────────────
PATH_LINE="export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
if ! grep -qF "$PATH_LINE" /root/.bashrc 2>/dev/null; then
  echo "$PATH_LINE" | sudo tee -a /root/.bashrc > /dev/null
  echo "Added ${INSTALL_DIR}/bin to /root/.bashrc"
fi

echo "RISC-V PULP toolchain installed at ${INSTALL_DIR}."
echo "Re-source your shell or run: export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
