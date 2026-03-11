@echo off
:: Create and use .venv (alternative to venv) - Windows
cd /d "%~dp0"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.9+ and add to PATH.
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Creating .venv...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt
if not exist "output" mkdir output
if not exist "output\2d_views" mkdir output\2d_views
if not exist "data" mkdir data
echo.
echo Done. To activate later:  .venv\Scripts\activate.bat
echo Run:  python run_sprint4.py   or   python web\app.py
pause
