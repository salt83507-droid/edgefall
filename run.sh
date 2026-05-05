#!/usr/bin/env bash
# Edgefall Index launcher (macOS/Linux) — runs from source.
# For a standalone .app to share, run build_mac.sh instead.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found. Install Python 3.10+ and re-run."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "Installing dependencies (first run only)..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt
echo
echo "Launching Edgefall Index..."
python app.py
