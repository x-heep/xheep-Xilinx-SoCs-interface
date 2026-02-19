set -euo pipefail

# Install Python packages listed in util/python-requirements.txt,
# skipping any package that is already installed.

REQ="$(cd "$(dirname "$0")" && pwd)/python-requirements.txt"

source /etc/profile.d/pynq_venv.sh

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
