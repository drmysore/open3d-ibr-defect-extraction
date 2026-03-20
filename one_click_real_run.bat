@echo off
setlocal EnableDelayedExpansion
REM One-click runner for real-data study + API (Windows)
REM Author: Supreeth Mysore
REM Optional: set REAL_STL_PATH=...\file.stl before running this script.

cd /d "%~dp0"

echo ==============================================================
echo IBR Real Data One-Click Run
echo Project root: %CD%
echo ==============================================================

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
  exit /b 1
)

echo [1/6] Python check...
python -c "import sys; print('Using Python:', sys.version); raise SystemExit(1) if sys.version_info < (3, 9) else None" || exit /b 1

echo [2/6] Virtual environment setup...
if not exist ".venv\" (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
if errorlevel 1 (
  echo [ERROR] Could not activate .venv
  exit /b 1
)

echo [3/6] Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed
  exit /b 5
)

echo [4/6] Real data analysis (STL header + sampled stats)...
if defined REAL_STL_PATH (
  if exist "!REAL_STL_PATH!" (
    python src\analyze_real_stl.py --stl-path "!REAL_STL_PATH!" || echo [WARN] analyze_real_stl.py failed. Continuing.
  ) else (
    echo [WARN] REAL_STL_PATH set but file not found: !REAL_STL_PATH!
  )
) else (
  python src\analyze_real_stl.py || echo [WARN] STL not at default path. Set REAL_STL_PATH to analyze/convert raw STL.
)

echo [5/6] STL -^> PLY conversion + real pipeline run...
set "STL_CONVERTED="
if defined REAL_STL_PATH (
  if exist "!REAL_STL_PATH!" (
    python src\stl_to_ply_sampled.py --stl-path "!REAL_STL_PATH!" || exit /b 3
    set STL_CONVERTED=1
  ) else (
    echo [WARN] REAL_STL_PATH set but file not found: !REAL_STL_PATH!
  )
)
if not defined STL_CONVERTED (
  if exist "data\real_scan_4119905.ply" if exist "data\real_cad_4119905.ply" (
    echo [INFO] Reusing existing data\real_scan_4119905.ply and data\real_cad_4119905.ply
  ) else (
    python src\stl_to_ply_sampled.py || exit /b 3
  )
)
python src\run_real_data.py
if errorlevel 1 (
  echo [ERROR] run_real_data.py failed. Re-run with: python src\run_real_data.py --verbose
  exit /b 3
)

echo [6/6] Starting API server...
echo --------------------------------------------------------------
echo Dashboard:      http://127.0.0.1:8000/
echo 3D Viewer:      http://127.0.0.1:8000/viewer3d
echo Phase Viewer:   http://127.0.0.1:8000/phase-viewer
echo Inferno 3D:     http://127.0.0.1:8000/inferno-viewer
echo Compare:        http://127.0.0.1:8000/comparison
echo 2D Gallery:     http://127.0.0.1:8000/gallery
echo 2D Views API:   http://127.0.0.1:8000/api/2d-views
echo --------------------------------------------------------------
echo Press Ctrl+C to stop server.

python -m uvicorn web.app:app --host 127.0.0.1 --port 8000
exit /b %ERRORLEVEL%
