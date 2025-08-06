#!/usr/bin/env bash
#
# build-pyside.sh - Build Windows executable using PySide6 instead of PyQt6
# This is a fallback for PyQt6 DLL loading issues in Wine

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
WINE_PYTHON="wine python"
WINE_PIP="wine python -m pip"

echo "=== Building with PySide6 (PyQt6 fallback) ==="
echo

# Install PySide6
echo "Installing PySide6 in Wine..."
$WINE_PIP install "PySide6>=6.4.0" --upgrade
$WINE_PIP install keyboard pynput httpx openai anthropic

# Test PySide6
echo "Testing PySide6 import..."
if wine python -c "import PySide6.QtCore; import PySide6.QtWidgets; print('PySide6 OK')"; then
    echo "✅ PySide6 working in Wine"
else
    echo "❌ PySide6 also has problems"
    exit 1
fi

# Clean previous builds
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"

# Build with PySide6
echo "Building with PySide6..."
$WINE_PYTHON -m PyInstaller main_pyside.py \
    --onefile \
    --noconsole \
    --name "popraw_tekst_pyside" \
    --icon "assets/icon.ico" \
    --add-data "assets:assets" \
    --hidden-import "PySide6.QtCore" \
    --hidden-import "PySide6.QtWidgets" \
    --hidden-import "PySide6.QtGui" \
    --hidden-import "keyboard" \
    --hidden-import "pynput" \
    --hidden-import "httpx" \
    --collect-submodules PySide6

# Verify build
if [ -f "$PROJECT_ROOT/dist/popraw_tekst_pyside.exe" ]; then
    echo "✅ PySide6 build successful!"
    ls -la "$PROJECT_ROOT/dist/popraw_tekst_pyside.exe"
else
    echo "❌ PySide6 build failed"
    exit 1
fi