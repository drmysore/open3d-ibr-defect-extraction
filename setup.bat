@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   IBR Defect Extraction Pipeline - Setup
echo ============================================
echo.

:: Navigate to script directory
cd /d "%~dp0"

:: --- Check Python ---
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.9+ from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PYVER=%%v
for /f "tokens=*" %%v in ('python -c "import sys; print(sys.version_info.major)"') do set PYMAJOR=%%v
for /f "tokens=*" %%v in ('python -c "import sys; print(sys.version_info.minor)"') do set PYMINOR=%%v

if !PYMAJOR! lss 3 (
    echo [ERROR] Python !PYVER! found, but 3.9+ is required.
    pause
    exit /b 1
)
if !PYMAJOR! equ 3 if !PYMINOR! lss 9 (
    echo [ERROR] Python !PYVER! found, but 3.9+ is required.
    pause
    exit /b 1
)
echo [OK] Python !PYVER! found.

:: --- Create virtual environment ---
if exist "venv\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists.
) else (
    echo [...] Creating virtual environment...
    python -m venv venv
    echo [OK] Virtual environment created.
)

:: --- Activate virtual environment ---
echo [...] Activating virtual environment...
call venv\Scripts\activate.bat
echo [OK] Virtual environment activated.

:: --- Install dependencies ---
echo [...] Upgrading pip...
pip install --upgrade pip --quiet

echo [...] Installing dependencies (this may take a few minutes)...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed. Check errors above.
    pause
    exit /b 1
)
echo [OK] All dependencies installed.

:: --- Verify installation ---
echo.
echo [...] Verifying installation...
python -c "import importlib,sys; pkgs={'open3d':'open3d','numpy':'numpy','scipy':'scipy','sklearn':'scikit-learn','yaml':'pyyaml','openpyxl':'openpyxl','matplotlib':'matplotlib','fastapi':'fastapi','uvicorn':'uvicorn','jinja2':'jinja2','plotly':'plotly','pptx':'python-pptx','joblib':'joblib','PIL':'Pillow'}; bad=[p for m,p in pkgs.items() if not importlib.util.find_spec(m)]; print('[OK] All packages verified.' if not bad else f'[WARN] Missing: {chr(44).join(bad)}\n       Try: pip install '+' '.join(bad)); sys.exit(1 if bad else 0)"
if %errorlevel% neq 0 (
    echo [WARN] Some packages failed verification. See above.
)

:: --- Create output directories ---
if not exist "output" mkdir output
if not exist "output\2d_views" mkdir output\2d_views
if not exist "data" mkdir data
echo [OK] Output directories ready.

:: --- Done ---
echo.
echo ============================================
echo   Setup Complete!
echo ============================================
echo.
echo   The virtual environment is now active.
echo.
echo   Run the pipeline:
echo     python run_demo.py            # v1 pipeline demo
echo     python run_sprint4.py         # v2 pipeline (Sprint 4)
echo.
echo   Start the web dashboard:
echo     python web\app.py             # http://localhost:8000
echo.
echo ============================================
echo.
pause
