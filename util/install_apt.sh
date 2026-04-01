#!/bin/bash
set -euo pipefail

# Install apt packages listed in util/apt-requirements.txt,
# skipping any package that is already correctly installed

REQ="$(cd "$(dirname "$0")" && pwd)/apt-requirements.txt"
if [ ! -f "$REQ" ]; then
  echo "Cannot find $REQ" >&2
  exit 1
fi

MISSING=()
while IFS= read -r pkg || [ -n "$pkg" ]; do
  # skip blank lines and comments
  [[ -z "$pkg" || "$pkg" == \#* ]] && continue
  if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
    echo "  [ok]   $pkg"
  else
    echo "  [miss] $pkg"
    MISSING+=("$pkg")
  fi
done < "$REQ"

if [ "${#MISSING[@]}" -eq 0 ]; then
  echo "SKIP: apt requirements already satisfied."
else
  echo "Installing: ${MISSING[*]}"
  sudo apt-get update -qq
  sudo apt-get install -y "${MISSING[@]}"
  echo "DONE: apt packages installed."
fi
