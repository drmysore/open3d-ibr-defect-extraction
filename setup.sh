#!/usr/bin/env bash
set -e

echo "============================================"
echo "  IBR Defect Extraction Pipeline - Setup"
echo "============================================"
echo ""

MIN_PYTHON="3.9"

check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON=python3
    elif command -v python &>/dev/null; then
        PYTHON=python
    else
        echo "[ERROR] Python not found. Install Python ${MIN_PYTHON}+ from https://www.python.org/downloads/"
        exit 1
    fi

    VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
    MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

    if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 9 ]; }; then
        echo "[ERROR] Python ${VERSION} found, but ${MIN_PYTHON}+ is required."
        exit 1
    fi

    echo "[OK] Python ${VERSION} found at $(command -v $PYTHON)"
}

create_venv() {
    if [ -d "venv" ]; then
        echo "[OK] Virtual environment already exists."
    else
        echo "[...] Creating virtual environment..."
        $PYTHON -m venv venv
        echo "[OK] Virtual environment created."
    fi
}

activate_venv() {
    echo "[...] Activating virtual environment..."
    source venv/bin/activate
    echo "[OK] Virtual environment activated."
}

install_deps() {
    echo "[...] Upgrading pip..."
    pip install --upgrade pip --quiet

    echo "[...] Installing dependencies (this may take a few minutes)..."
    pip install -r requirements.txt
    echo "[OK] All dependencies installed."
}

verify_install() {
    echo ""
    echo "[...] Verifying installation..."
    $PYTHON -c "
import importlib, sys
packages = {
    'open3d': 'open3d',
    'numpy': 'numpy',
    'scipy': 'scipy',
    'sklearn': 'scikit-learn',
    'yaml': 'pyyaml',
    'openpyxl': 'openpyxl',
    'matplotlib': 'matplotlib',
    'fastapi': 'fastapi',
    'uvicorn': 'uvicorn',
    'jinja2': 'jinja2',
    'plotly': 'plotly',
    'pptx': 'python-pptx',
    'joblib': 'joblib',
    'PIL': 'Pillow',
}
failed = []
for mod, pkg in packages.items():
    try:
        importlib.import_module(mod)
    except ImportError:
        failed.append(pkg)

if failed:
    print(f'[WARN] Failed to import: {', '.join(failed)}')
    print('       Try: pip install ' + ' '.join(failed))
    sys.exit(1)
else:
    print('[OK] All packages verified.')
"
}

create_dirs() {
    mkdir -p output output/2d_views data
    echo "[OK] Output directories ready."
}

print_usage() {
    echo ""
    echo "============================================"
    echo "  Setup Complete!"
    echo "============================================"
    echo ""
    echo "  Activate the environment (if not already):"
    echo "    source venv/bin/activate"
    echo ""
    echo "  Run the pipeline:"
    echo "    python run_demo.py            # v1 pipeline demo"
    echo "    python run_sprint4.py         # v2 pipeline (Sprint 4)"
    echo ""
    echo "  Start the web dashboard:"
    echo "    python web/app.py             # http://localhost:8000"
    echo ""
    echo "============================================"
}

cd "$(dirname "$0")"

check_python
create_venv
activate_venv
install_deps
verify_install
create_dirs
print_usage
