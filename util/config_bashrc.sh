#!/bin/bash
set -euo pipefail

# Copyright 2026 Politecnico di Torino.
#
# File: install_xheep_sw.sh
# Author: Christian Conti {christian.conti@polito.it}
# Date: 31/03/2026
# Description: Add the source line for the PYNQ virtual environment 
# to the specified shell RC file

RC_FILE="${1:-/root/.bashrc}"

append_if_missing() {
  local line="$1"
  local file="$2"
  grep -qxF "$line" "$file" 2>/dev/null || echo "$line" >> "$file"
}

append_if_missing "source /etc/profile.d/pynq_venv.sh" "$RC_FILE"
append_if_missing "cd /home/xilinx" "$RC_FILE"
