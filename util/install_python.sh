# This script can be extended to use util/github-requirements.txt for custom Python package installs if needed.
set -euo pipefail

# Install Python packages listed in util/python-requirements.txt,
# in the `pynq-venv` skipping any package that is already installed.

REQ="$(cd "$(dirname "$0")" && pwd)/python-requirements.txt"


# Ensure we are in the correct venv (pynq-venv)
if [ -f /etc/profile.d/pynq_venv.sh ]; then
  source /etc/profile.d/pynq_venv.sh
else
  echo "Error: /etc/profile.d/pynq_venv.sh not found. Aborting installation." >&2
  exit 1
fi
if [ -z "${VIRTUAL_ENV:-}" ] || [[ "$VIRTUAL_ENV" != *pynq-venv* ]]; then
  echo "Error: pynq-venv is not active. Aborting installation." >&2
  exit 1
fi

MISSING=()
while IFS= read -r pkg || [ -n "$pkg" ]; do
  # skip blank lines and comments; strip version specifiers for the name check
  [[ -z "$pkg" || "$pkg" == \#* ]] && continue
  pkg_name="${pkg%%[><=!]*}"
  if pip show "$pkg_name" > /dev/null 2>&1; then
    echo "  [ok]   $pkg_name"
  else
    echo "  [miss] $pkg_name"
    MISSING+=("$pkg")
  fi
done < "$REQ"

if [ "${#MISSING[@]}" -eq 0 ]; then
  echo "All Python packages already installed — nothing to do."
else
  echo "Installing: ${MISSING[*]}"
  pip install "${MISSING[@]}"
  echo "Python packages installed."
fi
