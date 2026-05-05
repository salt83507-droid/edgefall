@echo off
setlocal EnableDelayedExpansion
REM ================================================================
REM  Edgefall Index - Windows standalone build (v2)
REM
REM  Uses `python -m PyInstaller` so it works regardless of whether
REM  pyinstaller.exe is on PATH (which it isn't on Python 3.14 by
REM  default). No venv - relies on the system Python where all your
REM  deps already live.
REM ================================================================
cd /d "%~dp0"
set LOG=%CD%\build_log.txt
echo. > "%LOG%"
echo Edgefall Index Windows build  -  %DATE% %TIME% >> "%LOG%"
echo Working directory: %CD% >> "%LOG%"
echo. >> "%LOG%"

echo.
echo  ============================================================
echo    EDGEFALL INDEX  //  Windows standalone build
echo  ============================================================
echo    Working directory:  %CD%
echo    Build log:          build_log.txt
echo  ============================================================
echo.

REM --- [1/5] Verify Python ---
echo  [ 1/5 ]  Checking Python...
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo  [ FAIL ]  Python is not on your PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo          %%v
python --version >> "%LOG%" 2>&1

REM --- [2/5] Install PyInstaller (idempotent) ---
echo.
echo  [ 2/5 ]  Ensuring PyInstaller is installed...
python -m pip install --upgrade pip pyinstaller >> "%LOG%" 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo  [ FAIL ]  Could not install PyInstaller. See build_log.txt
    powershell -Command "Get-Content '%LOG%' -Tail 30"
    pause
    exit /b 1
)

REM --- Verify PyInstaller is callable as a module ---
python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)" >> "%LOG%" 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo  [ FAIL ]  PyInstaller module not importable. See build_log.txt
    pause
    exit /b 1
)

REM --- [3/5] Test-import the app ---
echo.
echo  [ 3/5 ]  Test-importing app.py...
python -c "import app; print('app imports cleanly')" >> "%LOG%" 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo  [ FAIL ]  app.py does not import. Last 30 log lines:
    powershell -Command "Get-Content '%LOG%' -Tail 30"
    pause
    exit /b 1
)
echo          app imports cleanly.

REM --- Clean prior artifacts ---
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist EdgefallIndex.spec del /q EdgefallIndex.spec

REM --- [4/5] Try --onefile ---
echo.
echo  [ 4/5 ]  Building with PyInstaller (--onefile)...
echo          this takes 3-6 minutes. Do not close this window.
echo. >> "%LOG%"
echo === PyInstaller --onefile attempt === >> "%LOG%"

python -m PyInstaller --onefile --windowed --noconfirm --clean ^
    --name EdgefallIndex ^
    --collect-all customtkinter ^
    --collect-all yfinance ^
    --collect-data matplotlib ^
    --hidden-import requests ^
    --hidden-import pandas ^
    --hidden-import numpy ^
    --hidden-import scipy ^
    --hidden-import scipy.stats ^
    --hidden-import multitasking ^
    --hidden-import platformdirs ^
    --hidden-import frozendict ^
    --hidden-import peewee ^
    --hidden-import beautifulsoup4 ^
    --hidden-import websockets ^
    --hidden-import curl_cffi ^
    --hidden-import protobuf ^
    --hidden-import PIL ^
    app.py >> "%LOG%" 2>&1

if exist "dist\EdgefallIndex.exe" (
    set MODE=onefile
    set OUT=%CD%\dist\EdgefallIndex.exe
    goto :success
)

echo          --onefile did not produce an exe. Trying --onedir...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist EdgefallIndex.spec del /q EdgefallIndex.spec

REM --- [5/5] Fallback --onedir ---
echo.
echo  [ 5/5 ]  Building with PyInstaller (--onedir fallback)...
echo. >> "%LOG%"
echo === PyInstaller --onedir attempt === >> "%LOG%"

python -m PyInstaller --onedir --windowed --noconfirm --clean ^
    --name EdgefallIndex ^
    --collect-all customtkinter ^
    --collect-all yfinance ^
    --collect-data matplotlib ^
    --hidden-import requests ^
    --hidden-import pandas ^
    --hidden-import numpy ^
    --hidden-import scipy ^
    app.py >> "%LOG%" 2>&1

if exist "dist\EdgefallIndex\EdgefallIndex.exe" (
    set MODE=onedir
    set OUT=%CD%\dist\EdgefallIndex\EdgefallIndex.exe
    goto :success
)

REM --- Both attempts failed ---
echo.
echo  ============================================================
echo    [ FAIL ]  PyInstaller did not produce an .exe.
echo  ============================================================
echo.
echo    Last 60 lines of build_log.txt below.
echo.
powershell -Command "Get-Content '%LOG%' -Tail 60"
echo.
pause
exit /b 1

:success
echo.
echo  ============================================================
echo    [ DONE ]  Build mode: !MODE!
echo  ============================================================
echo.
echo    Output: !OUT!
echo.
if "!MODE!"=="onefile" (
    echo    Single .exe - just send this file. No Python needed.
) else (
    echo    --onedir mode produced a folder containing the .exe plus DLLs.
    echo    To share: zip the entire dist\EdgefallIndex folder and send.
    echo    The recipient unzips it and runs EdgefallIndex.exe.
)
echo.
echo    Opening the dist folder...
start "" "%CD%\dist"
echo.
pause
endlocal
