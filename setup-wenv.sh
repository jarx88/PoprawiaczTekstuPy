#!/usr/bin/env bash
#
# setup-wenv.sh - Setup wenv (Windows Python Environment) for cross-compilation
# wenv umożliwia uruchamianie Python na Wine w sposób transparentny
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "=== Setup WENV (Windows Python Environment) ==="
echo "Project: $PROJECT_ROOT"
echo

# Check if wenv is installed
if ! ./venv/bin/python -c "import wenv" 2>/dev/null; then
    echo "📦 Installing wenv..."
    ./venv/bin/pip install wenv
else
    echo "✅ wenv already installed"
fi

# Initialize wenv (creates Wine Python environment)
echo "🔧 Initializing wenv (Wine Python environment)..."
echo "This will download and install Python in Wine..."

if ./venv/bin/python -c "import wenv; wenv.init()" 2>/dev/null; then
    echo "✅ wenv initialized successfully"
else
    echo "⚠️  wenv initialization had issues, trying manual setup..."
    
    # Try with verbose output
    ./venv/bin/python -c "
import wenv
try:
    wenv.init()
    print('✅ wenv initialization successful')
except Exception as e:
    print(f'❌ wenv initialization failed: {e}')
    print('This might be due to Wine installation issues')
"
fi

# Test wenv
echo "🧪 Testing wenv environment..."

if ./venv/bin/python -c "
import wenv
try:
    result = wenv.python('-c', 'import sys; print(sys.platform)')
    print(f'✅ wenv Python platform: {result}')
    
    result = wenv.python('--version')
    print(f'✅ wenv Python version: {result}')
except Exception as e:
    print(f'❌ wenv test failed: {e}')
"; then
    echo "✅ wenv is working"
else
    echo "❌ wenv test failed"
fi

# Install dependencies in wenv
echo "📋 Installing dependencies in wenv Windows environment..."

# Create requirements for wenv
cat > "$PROJECT_ROOT/requirements_wenv.txt" << 'EOF'
customtkinter>=5.2.0
pystray>=0.19.0  
Pillow>=10.0.0
pyperclip>=1.8.0
pynput>=1.7.6
httpx>=0.24.0
openai>=1.0.0
anthropic>=0.5.0
google-generativeai==0.1.0rc1
pyinstaller>=5.0.0
EOF

./venv/bin/python -c "
import wenv
import sys

packages = []
with open('$PROJECT_ROOT/requirements_wenv.txt', 'r') as f:
    packages = [line.strip() for line in f if line.strip() and not line.startswith('#')]

print(f'Installing {len(packages)} packages in wenv...')

failed_packages = []
for package in packages:
    try:
        print(f'Installing {package}...')
        result = wenv.pip('install', package, '--upgrade')
        print(f'✅ {package}: OK')
    except Exception as e:
        print(f'❌ {package}: {e}')
        failed_packages.append(package)

if failed_packages:
    print(f'❌ Failed packages: {failed_packages}')
else:
    print('✅ All packages installed successfully in wenv')
"

echo
echo "🔧 wenv setup complete!"
echo "📋 Next steps:"
echo "   1. Run: ./build-wenv.sh to build Windows exe"
echo "   2. Test with: wenv python main_modern.py"
echo