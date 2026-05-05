@echo off
REM Edgefall Index launcher (Windows) — runs from source.
REM For a standalone .exe to share, run build_windows.bat instead.
cd /d "%~dp0"
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Python is not on your PATH. Install Python 3.10+ from python.org and re-run.
    pause
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
echo Installing dependencies (first run only)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
echo.
echo Launching Edgefall Index...
python app.py
