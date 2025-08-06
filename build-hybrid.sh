#!/usr/bin/env bash
#
# build-hybrid.sh - Hybrid build using Linux PyInstaller for Windows target
# This avoids Wine Python issues by using Linux PyInstaller directly

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"
SPEC_FILE="$PROJECT_ROOT/popraw_tekst.spec"

echo "=== PoprawiaczTekstuPy Hybrid Build (Linux PyInstaller) ==="
echo "Project root: $PROJECT_ROOT"
echo

# Check venv
if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ BŁĄD: Python venv nie znaleziony: $VENV_PYTHON" >&2
    exit 1
fi
echo "✅ Python venv: $($VENV_PYTHON --version)"

# Check PyInstaller
if ! $VENV_PYTHON -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller w venv..."
    $VENV_PYTHON -m pip install pyinstaller
fi
echo "✅ PyInstaller available"

# Check dependencies
echo "🔍 Checking dependencies..."
critical_packages=("PyQt6" "keyboard" "pynput" "httpx")
for package in "${critical_packages[@]}"; do
    if $VENV_PYTHON -c "import $package" 2>/dev/null; then
        echo "✅ $package: OK"
    else
        echo "❌ Missing: $package"
        echo "Installing $package..."
        $VENV_PYTHON -m pip install "$package"
    fi
done

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"

# Try cross-platform build (may not work for all dependencies)
echo "🔨 Attempting cross-platform build..."
cd "$PROJECT_ROOT"

# Method 1: Direct PyInstaller (Linux build)
echo "Building Linux version first (for testing)..."
$VENV_PYTHON -m PyInstaller "$SPEC_FILE" \
    --noconfirm \
    --workpath "$PROJECT_ROOT/build" \
    --distpath "$PROJECT_ROOT/dist" \
    --log-level INFO

if [ -f "$PROJECT_ROOT/dist/popraw_tekst" ]; then
    echo "✅ Linux build successful: dist/popraw_tekst"
    
    # Test Linux version
    echo "🧪 Testing Linux version..."
    if QT_QPA_PLATFORM=offscreen "$PROJECT_ROOT/dist/popraw_tekst" --version 2>/dev/null; then
        echo "✅ Linux version works"
    else
        echo "⚠️  Linux version has issues (may be normal without display)"
    fi
else
    echo "❌ Linux build failed"
    exit 1
fi

echo
echo "📋 Summary:"
echo "✅ Linux executable: dist/popraw_tekst"
echo "⚠️  For Windows .exe, Wine with Windows Python is required"
echo
echo "To create Windows .exe manually:"
echo "1. Copy project to Windows machine"
echo "2. Install Python + dependencies"  
echo "3. Run: python -m PyInstaller popraw_tekst.spec"
echo