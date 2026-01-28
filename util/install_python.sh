#!/usr/bin/env bash
set -euo pipefail

# Install python packages into PYNQ virtualenv. The PYNQ venv must be enabled
# by sourcing /etc/profile.d/pynq_venv.sh as requested by the project.
REQ="$(cd "$(dirname "$0")" && pwd)/requirements.txt"

if [ ! -f "$REQ" ]; then
  echo "Cannot find $REQ" >&2
  exit 1
fi

if [ ! -f /etc/profile.d/pynq_venv.sh ]; then
  echo "/etc/profile.d/pynq_venv.sh not found. Ensure PYNQ venv is installed." >&2
  exit 1
fi

echo "Sourcing PYNQ venv and installing Python packages from $REQ"
bash -lc "source /etc/profile.d/pynq_venv.sh && python -m pip install --upgrade pip setuptools wheel && pip install -r '$REQ'"

echo "Python packages installed in PYNQ venv."
