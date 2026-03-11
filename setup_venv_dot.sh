#!/usr/bin/env bash
# Create and use .venv (alternative to venv) - Linux/macOS
set -e
cd "$(dirname "$0")"

PYTHON=python3
command -v python3 &>/dev/null || PYTHON=python

echo "Creating .venv..."
$PYTHON -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt
mkdir -p output output/2d_views data
echo ""
echo "Done. To activate later:  source .venv/bin/activate"
echo "Run:  python run_sprint4.py   or   python web/app.py"
