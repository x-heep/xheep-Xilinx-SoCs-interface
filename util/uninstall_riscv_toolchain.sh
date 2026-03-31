# This script can be extended to use util/github-requirements.txt for custom uninstall logic if needed.
#!/bin/bash
set -euo pipefail

# Removes $HOME/.riscv and cleans up PATH entries in shell rc files.
# Also removes any legacy /opt installs from older versions of the script.

INSTALL_DIR="${HOME}/.riscv"

# Remove the toolchain directory
if [ -d "${INSTALL_DIR}" ]; then
    echo "Removing ${INSTALL_DIR}..."
    rm -rf "${INSTALL_DIR}"
else
    echo "${INSTALL_DIR} not found, skipping."
fi

# Remove PATH entry from shell rc files
PATH_LINE="export PATH=\"${INSTALL_DIR}/bin:\$PATH\""
for RC in "${HOME}/.bashrc" "${HOME}/.zshrc"; do
    if [ -f "$RC" ] && grep -qF "$PATH_LINE" "$RC" 2>/dev/null; then
        sed -i "\|${PATH_LINE}|d" "$RC"
        echo "Removed PATH entry from ${RC}"
    fi
done

# Remove legacy /opt installs from older versions of this script
LEGACY_FLAVORS=(xheep-base xheep-float xheep-zfinx)
LEGACY_SYMLINKS=(/opt/openhw-riscv-base /opt/openhw-riscv-float /opt/openhw-riscv-zfinx)

for ARCH_LABEL in armhf aarch64; do
    for FLAVOR in "${LEGACY_FLAVORS[@]}"; do
        LEGACY_DIR="/opt/riscv-${ARCH_LABEL}-${FLAVOR}"
        if [ -d "$LEGACY_DIR" ]; then
            echo "Removing legacy install ${LEGACY_DIR}..."
            sudo rm -rf "$LEGACY_DIR"
        fi
    done
done

for SYMLINK in "${LEGACY_SYMLINKS[@]}"; do
    if [ -L "$SYMLINK" ]; then
        echo "Removing legacy symlink ${SYMLINK}..."
        sudo rm -f "$SYMLINK"
    fi
done
