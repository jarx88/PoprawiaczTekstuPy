#!/usr/bin/env bash
#
# setup-wine-env.sh - Setup Wine environment dla Windows cross-compilation
#
# Ten skrypt automatycznie konfiguruje Wine environment potrzebny do 
# generowania Windows executables w WSL Ubuntu.

set -euo pipefail

PYTHON_VERSION="3.8.5"
PYTHON_INSTALLER_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-amd64.exe"
PYTHON_INSTALLER_FILE="/tmp/python-${PYTHON_VERSION}-amd64.exe"

echo "=== Wine Environment Setup dla PoprawiaczTekstuPy ==="
echo

# Funkcja instalacji Wine
install_wine() {
    echo "🍷 Instalowanie Wine..."
    
    if command -v wine >/dev/null 2>&1; then
        echo "✅ Wine już zainstalowany: $(wine --version)"
        return 0
    fi
    
    # Update package list
    sudo apt update
    
    # Install Wine
    sudo apt install -y wine
    
    # Verify installation
    if command -v wine >/dev/null 2>&1; then
        echo "✅ Wine zainstalowany pomyślnie: $(wine --version)"
    else
        echo "❌ Błąd instalacji Wine" >&2
        exit 1
    fi
    
    echo
}

# Funkcja konfiguracji Wine
configure_wine() {
    echo "⚙️  Konfigurowanie Wine..."
    
    # Initialize wine prefix (silent)
    echo "Inicjalizowanie Wine prefix..."
    WINEDLLOVERRIDES="mscoree,mshtml=" wine wineboot --init
    
    # Set Windows version to Windows 10
    echo "Ustawianie Windows 10 compatibility..."
    wine reg add "HKEY_CURRENT_USER\\Software\\Wine" /v Version /t REG_SZ /d "win10" /f
    
    echo "✅ Wine skonfigurowany (Windows 10 mode)"
    echo
}

# Funkcja pobierania Python installer
download_python() {
    echo "🐍 Pobieranie Python ${PYTHON_VERSION} installer..."
    
    if [ -f "$PYTHON_INSTALLER_FILE" ]; then
        echo "✅ Python installer już pobrany: $PYTHON_INSTALLER_FILE"
        return 0
    fi
    
    echo "Pobieranie z: $PYTHON_INSTALLER_URL"
    
    if command -v wget >/dev/null 2>&1; then
        wget -O "$PYTHON_INSTALLER_FILE" "$PYTHON_INSTALLER_URL"
    elif command -v curl >/dev/null 2>&1; then
        curl -L -o "$PYTHON_INSTALLER_FILE" "$PYTHON_INSTALLER_URL"
    else
        echo "❌ Brak wget ani curl - zainstaluj jeden z nich" >&2
        echo "sudo apt install wget" >&2
        exit 1
    fi
    
    if [ -f "$PYTHON_INSTALLER_FILE" ]; then
        echo "✅ Python installer pobrany: $PYTHON_INSTALLER_FILE"
    else
        echo "❌ Błąd pobierania Python installer" >&2
        exit 1
    fi
    
    echo
}

# Funkcja instalacji Python w Wine
install_python_in_wine() {
    echo "🐍 Instalowanie Python ${PYTHON_VERSION} w Wine..."
    
    # Check if Python already installed
    if wine python --version >/dev/null 2>&1; then
        echo "✅ Python już zainstalowany w Wine: $(wine python --version)"
        return 0
    fi
    
    if [ ! -f "$PYTHON_INSTALLER_FILE" ]; then
        echo "❌ Brak Python installer: $PYTHON_INSTALLER_FILE" >&2
        exit 1
    fi
    
    echo "Uruchamianie Python installer w Wine..."
    echo "(To może potrwać kilka minut...)"
    
    # Install Python silently
    wine "$PYTHON_INSTALLER_FILE" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    
    # Wait a moment for installation to complete
    sleep 5
    
    # Verify Python installation
    if wine python --version >/dev/null 2>&1; then
        echo "✅ Python zainstalowany w Wine: $(wine python --version)"
    else
        echo "❌ Błąd instalacji Python w Wine" >&2
        echo "Spróbuj ręcznej instalacji: wine $PYTHON_INSTALLER_FILE" >&2
        exit 1
    fi
    
    echo
}

# Funkcja instalacji PyInstaller
install_pyinstaller() {
    echo "📦 Instalowanie PyInstaller w Wine..."
    
    # Check if PyInstaller already installed
    if wine python -c "import PyInstaller" 2>/dev/null; then
        echo "✅ PyInstaller już zainstalowany w Wine"
        return 0
    fi
    
    echo "Instalowanie PyInstaller..."
    wine python -m pip install --upgrade pip
    wine python -m pip install pyinstaller
    
    # Verify installation
    if wine python -c "import PyInstaller" 2>/dev/null; then
        echo "✅ PyInstaller zainstalowany w Wine"
    else
        echo "❌ Błąd instalacji PyInstaller" >&2
        exit 1
    fi
    
    echo
}

# Funkcja instalacji podstawowych dependencies
install_basic_dependencies() {
    echo "📚 Instalowanie podstawowych dependencies w Wine..."
    
    local packages=(
        "PyQt6>=6.4.0"
        "keyboard>=0.13.5" 
        "pynput>=1.7.6"
        "httpx>=0.24.0"
    )
    
    for package in "${packages[@]}"; do
        echo "Instalowanie: $package"
        wine python -m pip install "$package"
    done
    
    echo "✅ Podstawowe dependencies zainstalowane"
    echo
}

# Funkcja testowania setup
test_setup() {
    echo "🧪 Testowanie Wine environment..."
    
    echo "Wine version: $(wine --version)"
    echo "Python w Wine: $(wine python --version)"
    echo "Pip w Wine: $(wine python -m pip --version)"
    
    # Test PyInstaller
    if wine python -c "import PyInstaller; print('PyInstaller version:', PyInstaller.__version__)" 2>/dev/null; then
        echo "✅ PyInstaller działa poprawnie"
    else
        echo "❌ Problem z PyInstaller" >&2
    fi
    
    # Test PyQt6
    if wine python -c "import PyQt6; print('PyQt6 available')" 2>/dev/null; then
        echo "✅ PyQt6 działa poprawnie"
    else
        echo "⚠️  PyQt6 nie zainstalowane lub problemy z importem"
    fi
    
    echo
    echo "🎉 Wine environment gotowy do użycia!"
    echo "Użyj: ./build-windows.sh aby zbudować Windows executable"
    echo
}

# Funkcja pomocy
show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Konfiguruje Wine environment dla cross-compilation Windows executables.

Options:
  --skip-wine       Pomiń instalację Wine (jeśli już zainstalowany)
  --skip-python     Pomiń instalację Python (jeśli już zainstalowany w Wine)
  --basic-deps      Zainstaluj tylko podstawowe dependencies
  --test-only       Tylko przetestuj istniejący setup
  --help           Pokaż tę pomoc

Examples:
  $0                    # Pełny setup
  $0 --skip-wine        # Setup bez instalacji Wine
  $0 --test-only        # Tylko test environment

EOF
}

# Main function
main() {
    local skip_wine=false
    local skip_python=false
    local basic_deps=false
    local test_only=false
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-wine)
                skip_wine=true
                shift
                ;;
            --skip-python)
                skip_python=true
                shift
                ;;
            --basic-deps)
                basic_deps=true
                shift
                ;;
            --test-only)
                test_only=true
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                echo "Unknown option: $1" >&2
                show_help
                exit 1
                ;;
        esac
    done
    
    if [ "$test_only" = true ]; then
        test_setup
        exit 0
    fi
    
    # Execute setup steps
    if [ "$skip_wine" = false ]; then
        install_wine
        configure_wine
    fi
    
    if [ "$skip_python" = false ]; then
        download_python
        install_python_in_wine
    fi
    
    install_pyinstaller
    
    if [ "$basic_deps" = true ]; then
        install_basic_dependencies
    fi
    
    test_setup
    
    echo "✅ Wine environment setup completed!"
    echo "Możesz teraz użyć: ./build-windows.sh"
}

# Run main with all arguments
main "$@"