#!/usr/bin/env bash
#
# build-wenv.sh - Build Windows exe using wenv (Windows Python Environment)
# wenv transparently uruchamia Python na Wine
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SPEC_FILE="$PROJECT_ROOT/popraw_tekst_modern.spec"

echo "=== PoprawiaczTekstuPy Build with WENV ==="
echo "Project: $PROJECT_ROOT"
echo

# Check if wenv is available
if ! ./venv/bin/python -c "import wenv" 2>/dev/null; then
    echo "❌ wenv not installed"
    echo "Run: ./setup-wenv.sh first"
    exit 1
fi

echo "✅ wenv available"

# Test wenv 
echo "🧪 Testing wenv environment..."
./venv/bin/python -c "
import wenv
try:
    platform = wenv.python('-c', 'import sys; print(sys.platform)')
    version = wenv.python('--version')
    print(f'✅ wenv Python: {version} on {platform}')
except Exception as e:
    print(f'❌ wenv test failed: {e}')
    exit(1)
"

# Check PyInstaller in wenv
echo "🔍 Checking PyInstaller in wenv..."
./venv/bin/python -c "
import wenv
try:
    result = wenv.python('-c', 'import PyInstaller; print(PyInstaller.__version__)')
    print(f'✅ PyInstaller in wenv: {result}')
except Exception as e:
    print(f'❌ PyInstaller not available: {e}')
    print('Installing PyInstaller in wenv...')
    try:
        wenv.pip('install', 'pyinstaller', '--upgrade')
        result = wenv.python('-c', 'import PyInstaller; print(PyInstaller.__version__)')
        print(f'✅ PyInstaller installed: {result}')
    except Exception as install_e:
        print(f'❌ Failed to install PyInstaller: {install_e}')
        exit(1)
"

# Test key dependencies in wenv
echo "🔍 Testing dependencies in wenv..."
./venv/bin/python -c "
import wenv

critical_packages = ['customtkinter', 'pystray', 'pyperclip', 'pynput', 'httpx']
failed = []

for package in critical_packages:
    try:
        wenv.python('-c', f'import {package}; print(\"✅ {package}: OK\")')
    except Exception as e:
        print(f'❌ {package}: missing')
        failed.append(package)

if failed:
    print(f'❌ Missing packages in wenv: {failed}')
    print('Install with: wenv pip install package_name')
else:
    print('✅ All critical packages available in wenv')
"

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"

# Create wenv-specific spec file
cat > "$PROJECT_ROOT/popraw_tekst_wenv.spec" << 'EOF'
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
        'keyboard',
        'httpx',
        'openai',
        'anthropic',
        'google.generativeai',
        'google.genai',
        'google.genai.types',
        'certifi',
        'urllib3',
        'idna',
        'charset_normalizer',
        'sniffio',
        'h11',
        'anyio',
        'typing_extensions',
        'darkdetect'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6',
        'PyQt5',
        'tkinter.test',
        'test',
        'unittest',
        'pydoc',
        'doctest'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='popraw_tekst_modern',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico'
)
EOF

# Build using wenv + PyInstaller
echo "🔨 Building Windows executable with wenv + PyInstaller..."
cd "$PROJECT_ROOT"

./venv/bin/python -c "
import wenv
import sys
import os

try:
    print('Running PyInstaller in wenv...')
    result = wenv.pyinstaller('popraw_tekst_wenv.spec', '--noconfirm')
    print('✅ PyInstaller completed')
except Exception as e:
    print(f'❌ PyInstaller failed: {e}')
    # Try manual command
    try:
        print('Trying manual PyInstaller command...')
        wenv.python('-m', 'PyInstaller', 'popraw_tekst_wenv.spec', '--noconfirm')
        print('✅ Manual PyInstaller completed')
    except Exception as manual_e:
        print(f'❌ Manual PyInstaller also failed: {manual_e}')
        sys.exit(1)
"

# Check if build succeeded
if [ -f "$PROJECT_ROOT/dist/popraw_tekst_modern.exe" ]; then
    echo
    echo "✅ Build successful with wenv!"
    echo "📁 Executable: dist/popraw_tekst_modern.exe"
    ls -la "$PROJECT_ROOT/dist/popraw_tekst_modern.exe"
    
    # Show file info
    echo "🔍 File info:"
    file "$PROJECT_ROOT/dist/popraw_tekst_modern.exe" || echo "file command not available"
    
    echo
    echo "🎉 Windows executable created using wenv!"
    echo "📋 wenv transparently używa Wine Python environment"
    echo "📋 Executable powinien działać natywnie na Windows"
else
    echo
    echo "❌ Build failed!"
    echo "Check logs above for errors"
    echo
    echo "Debug info:"
    ls -la dist/ 2>/dev/null || echo "No dist directory"
    ls -la build/ 2>/dev/null || echo "No build directory"  
    exit 1
fi
