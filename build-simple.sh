#!/usr/bin/env bash
#
# build-simple.sh - Simple Wine build script (mirrors build.ps1)
# 
# This script mimics the exact workflow of build.ps1 but through Wine

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON_WIN="$PROJECT_ROOT/venv/Scripts/python.exe"
ICON_PATH_WIN="$PROJECT_ROOT/assets/icon.ico"
SPEC_FILE_WIN="$PROJECT_ROOT/popraw_tekst.spec"

echo "=== Simple Wine Build (mimics build.ps1) ==="
echo "Project: $PROJECT_ROOT"
echo

# Check if Windows Python exists
if [ ! -f "$VENV_PYTHON_WIN" ]; then
    echo "❌ Windows Python not found: $VENV_PYTHON_WIN"
    exit 1
fi

# Check if icon exists
if [ ! -f "$ICON_PATH_WIN" ]; then
    echo "❌ Icon not found: $ICON_PATH_WIN"
    exit 1
fi

# Test Wine + Python
if ! wine "$VENV_PYTHON_WIN" --version >/dev/null 2>&1; then
    echo "❌ Wine cannot run Windows Python"
    echo "Try: winecfg (set Windows 10 mode)"
    exit 1
fi

echo "✅ Wine + Windows Python: $(wine "$VENV_PYTHON_WIN" --version)"

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"

# Build using spec file (exactly like build.ps1)
echo "🔨 Building with PyInstaller..."
cd "$PROJECT_ROOT"

if [ -f "$SPEC_FILE_WIN" ]; then
    echo "Using spec file: $SPEC_FILE_WIN"
    wine "$VENV_PYTHON_WIN" -m PyInstaller "$SPEC_FILE_WIN" --noconfirm
else
    echo "Spec file not found, using default settings..."
    wine "$VENV_PYTHON_WIN" -m PyInstaller \
        --onefile \
        --noconsole \
        --name "popraw_tekst" \
        --icon "$ICON_PATH_WIN" \
        --add-data "$PROJECT_ROOT/assets:assets" \
        main.py
fi

# Check if build succeeded
if [ -f "$PROJECT_ROOT/dist/popraw_tekst.exe" ]; then
    echo
    echo "✅ Build successful!"
    echo "📁 Executable: dist/popraw_tekst.exe"
    ls -la "$PROJECT_ROOT/dist/popraw_tekst.exe"
    
    # Show file info
    echo "🔍 File info:"
    file "$PROJECT_ROOT/dist/popraw_tekst.exe" || echo "file command not available"
    
    echo
    echo "🎉 Windows executable ready!"
    echo "Copy dist/popraw_tekst.exe to Windows to test"
else
    echo
    echo "❌ Build failed!"
    echo "Check logs above for errors"
    exit 1
fi