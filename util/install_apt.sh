#!/usr/bin/env bash
set -euo pipefail

# Install apt packages listed in this repository's util/apt-requirements.txt
REQ="$(cd "$(dirname "$0")" && pwd)/apt-requirements.txt"
if [ ! -f "$REQ" ]; then
  echo "Cannot find $REQ" >&2
  exit 1
fi

echo "Updating apt and installing packages from $REQ (sudo required)"
sudo apt-get update
xargs -r sudo apt-get install -y < "$REQ"

echo "Apt packages installed."
