#!/bin/bash
set -euo pipefail

RC_FILE="${1:-/root/.bashrc}"

# Idempotent append helper (quiet by design).
append_if_missing() {
  local line="$1"
  local file="$2"
  grep -qxF "$line" "$file" 2>/dev/null || echo "$line" >> "$file"
}

append_if_missing "source /etc/profile.d/pynq_venv.sh" "$RC_FILE"
append_if_missing "cd /home/xilinx" "$RC_FILE"
