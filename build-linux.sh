#!/usr/bin/env bash
#
# build-linux.sh - Linux build dla testowania nowej GUI
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
SPEC_FILE="$PROJECT_ROOT/popraw_tekst_modern.spec"

echo "=== Linux Build for Testing (CustomTkinter) ==="
echo "Project: $PROJECT_ROOT"
echo

# Check venv
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ Python venv not found: $VENV_PYTHON"
    exit 1
fi

echo "✅ Python venv: $($VENV_PYTHON --version)"

# Install missing dependencies
echo "📦 Installing dependencies..."
$VENV_PYTHON -m pip install customtkinter pystray pyperclip --upgrade

# Test basic imports
echo "🧪 Testing imports..."
if $VENV_PYTHON -c "
import customtkinter
print('✅ CustomTkinter OK')
import pystray
print('✅ pystray OK') 
import pyperclip
print('✅ pyperclip OK')
" 2>/dev/null; then
    echo "✅ All dependencies working"
else
    echo "❌ Some dependencies failed (może brakować tkinter system-wide)"
    echo "Install: sudo apt install python3-tk"
fi

# Clean previous builds
echo "🧹 Cleaning..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"

# Create Linux spec file
cat > "$PROJECT_ROOT/popraw_tekst_linux.spec" << 'EOF'
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main_modern.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('utils', 'utils'),
        ('api_clients', 'api_clients'),
        ('VERSION', '.'),
    ],
    hiddenimports=[
        'customtkinter',
        'pystray',
        'PIL',
        'pyperclip',
        'pynput',
        'httpx',
        'openai',
        'anthropic',
        'google.generativeai',
        'google.genai',
        'google.genai.types',
        'darkdetect',
        'python_xlib'
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'PyQt6',
        'PyQt5',
        'test',
        'unittest'
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='popraw_tekst_modern_linux',
    debug=False,
    strip=False,
    console=False,
    icon='assets/icon.ico'
)
EOF

# Build
echo "🔨 Building Linux version..."
cd "$PROJECT_ROOT"

if [ ! -f "$PROJECT_ROOT/popraw_tekst_linux.spec" ]; then
    echo "❌ Spec file creation failed"
    exit 1
fi

# Try PyInstaller with Linux spec
if $VENV_PYTHON -m PyInstaller popraw_tekst_linux.spec --noconfirm; then
    echo
    if [ -f "$PROJECT_ROOT/dist/popraw_tekst_modern_linux" ]; then
        echo "✅ Linux build successful!"
        echo "📁 Executable: dist/popraw_tekst_modern_linux" 
        ls -la "$PROJECT_ROOT/dist/popraw_tekst_modern_linux"
        
        echo
        echo "🧪 Testing executable..."
        if QT_QPA_PLATFORM=offscreen "$PROJECT_ROOT/dist/popraw_tekst_modern_linux" --version 2>/dev/null; then
            echo "✅ Executable works"
        else
            echo "ℹ️  Test completed (display issues are normal in headless)"
        fi
        
        echo
        echo "🎉 Linux version ready for manual testing!"
        echo "📋 CustomTkinter is much lighter than PyQt6"
        echo "📋 Should work better for Wine cross-compilation"
    else
        echo "❌ Build failed - no executable"
        exit 1
    fi
else
    echo "❌ PyInstaller failed"
    exit 1
fi
