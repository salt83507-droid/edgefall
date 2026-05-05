#!/usr/bin/env bash
# ================================================================
#  Edgefall Index — macOS standalone build
#  Run this ONCE on a Mac. Output: dist/EdgefallIndex.app
#  The resulting .app runs on any macOS 11+ Mac WITHOUT Python
#  installed. Drag-and-drop into /Applications, send to friends.
# ================================================================
set -e
cd "$(dirname "$0")"

echo
echo " [ Edgefall Index — macOS build ]"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo " ERROR: python3 not found."
    echo " Install Python 3.10+ from https://www.python.org/downloads/macos/"
    echo " or via Homebrew:  brew install python@3.12"
    exit 1
fi

if [ ! -d ".venv-build" ]; then
    echo " Creating build virtual environment..."
    python3 -m venv .venv-build
fi
# shellcheck disable=SC1091
source .venv-build/bin/activate

echo " Installing dependencies..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo
echo " Building EdgefallIndex.app (this takes 2-5 minutes)..."
echo

# --windowed: produces a .app bundle (no terminal)
# --collect-all customtkinter: bundle theme JSON files
pyinstaller \
    --onefile \
    --windowed \
    --name EdgefallIndex \
    --collect-all customtkinter \
    --collect-data matplotlib \
    --hidden-import yfinance \
    --hidden-import requests \
    --hidden-import pandas \
    --hidden-import numpy \
    --hidden-import scipy \
    app.py

echo
if [ -d "dist/EdgefallIndex.app" ]; then
    echo " [ DONE ]  Standalone bundle:"
    echo " $(pwd)/dist/EdgefallIndex.app"
    echo
    echo " Drag it into /Applications, or zip and send to others on macOS."
    echo " No Python required on their machine."
    echo
    echo " First-launch note: macOS Gatekeeper may say 'unidentified developer'."
    echo " Right-click → Open → Open to bypass once. Or run:"
    echo "   xattr -dr com.apple.quarantine dist/EdgefallIndex.app"
else
    echo " [ ERROR ]  Build did not produce dist/EdgefallIndex.app"
    echo " Scroll up to see what PyInstaller reported."
fi
