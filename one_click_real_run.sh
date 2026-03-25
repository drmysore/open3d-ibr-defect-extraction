#!/usr/bin/env bash
set -euo pipefail

# One-click runner for real-data study + API
# Author: Supreeth Mysore

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "=============================================================="
echo "IBR Real Data One-Click Run"
echo "Project root: $ROOT_DIR"
echo "=============================================================="

PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[ERROR] Python not found. Install Python 3.10+ first."
  exit 1
fi

echo "[1/6] Python check..."
"$PYTHON_BIN" - <<'PY'
import sys
print(f"Using Python: {sys.version}")
if sys.version_info < (3, 9):
    raise SystemExit("Python 3.9+ required.")
PY

echo "[2/6] Virtual environment setup..."
if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

echo "[3/6] Installing dependencies..."
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

echo "[4/6] Real data analysis (STL header + sampled stats)..."
if [ -n "${REAL_STL_PATH:-}" ] && [ -f "${REAL_STL_PATH}" ]; then
  python src/analyze_real_stl.py --stl-path "${REAL_STL_PATH}" || {
    echo "[WARN] analyze_real_stl.py failed. Continuing."
  }
else
  python src/analyze_real_stl.py || {
    echo "[WARN] STL not found at default path. Set REAL_STL_PATH to analyze/convert raw STL."
  }
fi

echo "[5/6] STL -> PLY conversion + real pipeline run..."
if [ -n "${REAL_STL_PATH:-}" ] && [ -f "${REAL_STL_PATH}" ]; then
  python src/stl_to_ply_sampled.py --stl-path "${REAL_STL_PATH}"
elif [ -f "data/real_scan_4119905.ply" ] && [ -f "data/real_cad_4119905.ply" ]; then
  echo "[INFO] Reusing existing data/real_scan_4119905.ply and data/real_cad_4119905.ply"
else
  python src/stl_to_ply_sampled.py
fi
python src/run_real_data.py

echo "[6/6] Starting API server..."
echo "--------------------------------------------------------------"
echo "Dashboard:      http://127.0.0.1:8000/"
echo "3D Viewer:      http://127.0.0.1:8000/viewer3d"
echo "Phase Viewer:   http://127.0.0.1:8000/phase-viewer"
echo "Inferno 3D:     http://127.0.0.1:8000/inferno-viewer"
echo "Compare:        http://127.0.0.1:8000/comparison"
echo "2D Gallery:     http://127.0.0.1:8000/gallery"
echo "2D Views API:   http://127.0.0.1:8000/api/2d-views"
echo "--------------------------------------------------------------"
echo "Press Ctrl+C to stop server."

exec python -m uvicorn web.app:app --host 127.0.0.1 --port 8000

