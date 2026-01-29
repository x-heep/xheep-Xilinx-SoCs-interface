set -euo pipefail

# Install python packages listed in this repository's util/python-requirements.txt

REQ="$(cd "$(dirname "$0")" && pwd)/python-requirements.txt"

source /etc/profile.d/pynq_venv.sh
pip install -r "$REQ"
echo "Python packages installed."