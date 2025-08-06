#!/usr/bin/env bash
#
# build-modern.sh - Build moderne CustomTkinter wersji
# Lekka GUI biblioteka powinna działać lepiej pod Wine
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON_WIN="$PROJECT_ROOT/venv/Scripts/python.exe"
SPEC_FILE="$PROJECT_ROOT/popraw_tekst_modern.spec"

echo "=== PoprawiaczTekstuPy Modern Build (CustomTkinter) ==="
echo "Project: $PROJECT_ROOT"
echo

# Check if Windows Python exists
if [ ! -f "$VENV_PYTHON_WIN" ]; then
    echo "❌ Windows Python not found: $VENV_PYTHON_WIN"
    exit 1
fi

# Check spec file
if [ ! -f "$SPEC_FILE" ]; then
    echo "❌ Spec file not found: $SPEC_FILE"
    exit 1
fi

echo "✅ Using Windows Python: $VENV_PYTHON_WIN"
echo "✅ Using spec file: $SPEC_FILE"

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"

# Install dependencies w Windows venv (lighter package set)
echo "📦 Installing CustomTkinter dependencies..."
wine "$VENV_PYTHON_WIN" -m pip install customtkinter pystray pyperclip --upgrade

# Test basic imports
echo "🧪 Testing imports..."
if wine "$VENV_PYTHON_WIN" -c "
import customtkinter
import pystray
import pyperclip
print('✅ All CustomTkinter dependencies working')
" 2>/dev/null; then
    echo "✅ Dependencies test passed"
else
    echo "❌ Dependencies test failed"
    exit 1
fi

# Build with Wine
echo "🔨 Building with PyInstaller..."
cd "$PROJECT_ROOT"

if wine "$VENV_PYTHON_WIN" -m PyInstaller "$SPEC_FILE" --noconfirm; then
    echo
    if [ -f "$PROJECT_ROOT/dist/popraw_tekst_modern.exe" ]; then
        echo "✅ Modern build successful!"
        echo "📁 Executable: dist/popraw_tekst_modern.exe"
        ls -la "$PROJECT_ROOT/dist/popraw_tekst_modern.exe"
        
        echo
        echo "🎉 CustomTkinter Windows executable ready!"
        echo "📋 Much lighter than PyQt6 version"
    else
        echo "❌ Build failed - no executable"
        exit 1
    fi
else
    echo "❌ PyInstaller failed"
    exit 1
fi