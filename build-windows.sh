#!/usr/bin/env bash
#
# build-windows.sh - Cross-compilation script dla generowania Windows .exe w WSL Ubuntu
# 
# Ten skrypt używa Wine do uruchamiania Windows Python i PyInstaller
# w środowisku WSL Ubuntu, generując natywny Windows executable.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON_WIN="$PROJECT_ROOT/venv/Scripts/python.exe"
VENV_PYINSTALLER_WIN="$PROJECT_ROOT/venv/Scripts/pyinstaller.exe"
WINE_PYTHON="wine $VENV_PYTHON_WIN"
WINE_PIP="wine $VENV_PYTHON_WIN -m pip"
WINE_PYINSTALLER="wine $VENV_PYINSTALLER_WIN"
SPEC_FILE="$PROJECT_ROOT/popraw_tekst.spec"
ICON_PATH="$PROJECT_ROOT/assets/icon.ico"
ASSETS_PATH="$PROJECT_ROOT/assets"

echo "=== PoprawiaczTekstuPy Windows Build Script (Wine) ==="
echo "Project root: $PROJECT_ROOT"
echo

# Funkcja sprawdzania wymagań
check_requirements() {
    echo "Sprawdzanie wymagań środowiska..."
    
    # Sprawdź Wine
    if ! command -v wine >/dev/null 2>&1; then
        echo "❌ BŁĄD: Wine nie jest zainstalowany" >&2
        echo "Zainstaluj: sudo apt install wine" >&2
        exit 1
    fi
    echo "✅ Wine: $(wine --version)"
    
    # Sprawdź Windows Python w venv
    if [ ! -f "$VENV_PYTHON_WIN" ]; then
        echo "❌ BŁĄD: Windows Python nie znaleziony: $VENV_PYTHON_WIN" >&2
        echo "To jest shared venv Windows/WSL?" >&2
        exit 1
    fi
    echo "✅ Windows Python w venv znaleziony"
    
    # Test Wine z Windows venv Python
    if ! $WINE_PYTHON --version >/dev/null 2>&1; then
        echo "❌ BŁĄD: Wine nie może uruchomić Windows venv Python" >&2
        echo "Sprawdź Wine installation" >&2
        exit 1
    fi
    echo "✅ Wine + Windows venv Python: $($WINE_PYTHON --version)"
    
    # Sprawdź PyInstaller w Windows venv
    if [ ! -f "$VENV_PYINSTALLER_WIN" ]; then
        echo "⚠️  PyInstaller.exe nie znaleziony: $VENV_PYINSTALLER_WIN" >&2
        echo "Instalowanie PyInstaller w Windows venv..."
        $WINE_PIP install pyinstaller
    fi
    echo "✅ PyInstaller w Windows venv: dostępny"
    
    # Sprawdź spec file
    if [ ! -f "$SPEC_FILE" ]; then
        echo "❌ BŁĄD: Nie znaleziono pliku spec: $SPEC_FILE" >&2
        exit 1
    fi
    echo "✅ Spec file: $SPEC_FILE"
    
    # Sprawdź icon
    if [ ! -f "$ICON_PATH" ]; then
        echo "❌ BŁĄD: Nie znaleziono ikony: $ICON_PATH" >&2
        exit 1
    fi
    echo "✅ Icon file: $ICON_PATH"
    
    echo
}

# Funkcja instalacji dependencies w venv
install_wine_dependencies() {
    echo "🔧 Sprawdzanie i instalowanie dependencies w venv..."
    
    # Upgrade pip w Windows venv
    echo "Updating pip w Windows venv..."
    $WINE_PIP install --upgrade pip
    
    # Sprawdź czy requirements.txt istnieje
    if [ -f "$PROJECT_ROOT/requirements.txt" ]; then
        echo "📋 Instalowanie z requirements.txt: $PROJECT_ROOT/requirements.txt"
        echo "Dependencies do zainstalowania:"
        cat "$PROJECT_ROOT/requirements.txt"
        echo
        
        # Install z requirements.txt w Windows venv
        echo "Installing dependencies w Windows venv..."
        if ! $WINE_PIP install -r "$PROJECT_ROOT/requirements.txt" --upgrade; then
            echo "⚠️  Błąd podczas instalacji z requirements.txt"
            echo "Próba instalacji individual packages..."
            
            # Try installing packages individually
            while IFS= read -r package; do
                # Skip empty lines and comments
                [[ -z "$package" || "$package" =~ ^#.*$ ]] && continue
                
                echo "Trying to install: $package"
                if ! $WINE_PIP install "$package" --upgrade; then
                    echo "⚠️  Failed to install $package, trying without version constraint..."
                    # Try without version constraint
                    package_name=$(echo "$package" | cut -d'>' -f1 | cut -d'=' -f1 | cut -d'<' -f1)
                    $WINE_PIP install "$package_name" --upgrade || echo "❌ Failed: $package_name"
                fi
            done < "$PROJECT_ROOT/requirements.txt"
        fi
        
        # Install PyInstaller w Windows venv jeśli nie ma
        if [ ! -f "$VENV_PYINSTALLER_WIN" ]; then
            echo "Installing PyInstaller w Windows venv..."
            $WINE_PIP install pyinstaller
        fi
        
        # Check Qt installation w Windows venv
        echo "Sprawdzanie PyQt6 installation w Windows venv..."
        $WINE_PYTHON -c "
import PyQt6.QtCore
print('✅ PyQt6 available in Windows venv')
" || echo "❌ PyQt6 not working in Windows venv"
        
    else
        echo "❌ BŁĄD: Nie znaleziono requirements.txt w: $PROJECT_ROOT/requirements.txt" >&2
        echo "Tworząc plik requirements.txt z podstawowymi dependencies..." >&2
        
        # Create basic requirements.txt
        cat > "$PROJECT_ROOT/requirements.txt" << 'EOF'
PyQt6>=6.4.0
keyboard>=0.13.5
pynput>=1.7.6
httpx>=0.24.0
openai>=1.0.0
anthropic>=0.5.0
google-generativeai>=0.3.0
google-genai>=0.4.0
certifi>=2023.7.22
urllib3>=2.0.0
idna>=3.4
charset-normalizer>=3.2.0
sniffio>=1.3.0
h11>=0.14.0
anyio>=3.7.1
typing-extensions>=4.7.0
EOF
        
        echo "✅ Utworzono requirements.txt"
        echo "Instalowanie z utworzonego requirements.txt..."
        $WINE_PIP install -r "$PROJECT_ROOT/requirements.txt" --upgrade
    fi
    
    # Verify installations
    echo
    echo "🔍 Weryfikacja zainstalowanych dependencies..."
    
    local critical_packages=("PyQt6" "keyboard" "pynput" "httpx" "openai" "anthropic")
    local failed_packages=()
    
    for package in "${critical_packages[@]}"; do
        echo -n "Sprawdzanie $package... "
        if $WINE_PYTHON -c "import $package; print('✅ OK')" 2>/dev/null; then
            continue
        else
            echo "❌ BRAK"
            failed_packages+=("$package")
        fi
    done
    
    if [ ${#failed_packages[@]} -eq 0 ]; then
        echo "✅ Wszystkie dependencies zainstalowane poprawnie w Wine"
    else
        echo "⚠️  Następujące packages nie zostały zainstalowane poprawnie:"
        for package in "${failed_packages[@]}"; do
            echo "  - $package"
        done
        
        echo "Próba re-instalacji problematycznych packages..."
        for package in "${failed_packages[@]}"; do
            echo "Re-instalowanie $package..."
            $WINE_PIP install --upgrade --force-reinstall "$package"
        done
    fi
    
    # Show final pip list
    echo
    echo "📦 Installed packages w Windows venv:"
    $WINE_PIP list | grep -E "(PyQt6|keyboard|pynput|httpx|openai|anthropic|google)"
    
    echo
    echo "✅ Dependencies installation w Windows venv zakończona"
    echo
}

# Funkcja czyszczenia poprzednich buildów
clean_previous_builds() {
    echo "Czyszczenie poprzednich buildów..."
    
    rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"
    rm -f "$PROJECT_ROOT"/*.spec.tmp 2>/dev/null || true
    
    echo "✅ Poprzednie buildy wyczyszczone"
    echo
}

# Funkcja buildowania
build_windows_exe() {
    echo "Budowanie Windows executable za pomocą Wine..."
    echo "Spec file: $SPEC_FILE"
    echo
    
    cd "$PROJECT_ROOT"
    
    # Uruchom Windows PyInstaller przez Wine
    echo "Uruchamianie Windows PyInstaller przez Wine..."
    $WINE_PYINSTALLER "$SPEC_FILE" \
        --noconfirm \
        --workpath "$PROJECT_ROOT/build" \
        --distpath "$PROJECT_ROOT/dist" \
        --log-level INFO
    
    echo
}

# Funkcja weryfikacji buildu
verify_build() {
    echo "Weryfikacja buildu..."
    
    local exe_file="$PROJECT_ROOT/dist/popraw_tekst.exe"
    
    if [ -f "$exe_file" ]; then
        echo "✅ Build zakończony pomyślnie!"
        echo "📁 Plik wykonawczy: $exe_file"
        
        # Pokaż informacje o pliku
        echo "📊 Informacje o pliku:"
        ls -lh "$exe_file"
        
        # Sprawdź czy to Windows PE executable
        if command -v file >/dev/null 2>&1; then
            echo "🔍 Typ pliku: $(file "$exe_file")"
        fi
        
        echo
        echo "🎉 Windows executable gotowy do uruchomienia na Windows!"
        echo "📋 Aby przetestować na Windows, skopiuj plik na system Windows i uruchom."
        
        return 0
    else
        echo "❌ Build nie powiódł się - brak pliku executable" >&2
        echo "Sprawdź logi powyżej dla szczegółów błędu" >&2
        return 1
    fi
}

# Funkcja pomocy
show_help() {
    cat << 'EOF'
Usage: build-windows.sh [OPTIONS]

Options:
  --install-deps    Force install dependencies
  --skip-deps       Skip dependency installation (default: smart check)
  --clean-only      Tylko wyczyść poprzednie buildy (bez budowania)
  --help           Pokaż tę pomoc

Examples:
  ./build-windows.sh                     # Build z smart dependency check
  ./build-windows.sh --install-deps      # Force install deps + build
  ./build-windows.sh --skip-deps         # Build bez dependency check
  ./build-windows.sh --clean-only        # Tylko wyczyść

Note: Domyślnie sprawdza czy dependencies są zainstalowane

Requirements:
  - Wine zainstalowany: sudo apt install wine
  - Python 3.8.5 w Wine: wine python-3.8.5-amd64.exe
  - PyInstaller w Wine: wine python -m pip install pyinstaller

EOF
}

# Main execution
main() {
    local install_deps=false  # Changed back to false by default
    local clean_only=false
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --install-deps)
                install_deps=true
                shift
                ;;
            --skip-deps)
                install_deps=false
                shift
                ;;
            --clean-only)
                clean_only=true
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
    
    # Execute steps
    check_requirements
    
    # Smart dependency checking - tylko jeśli explicitly requested lub missing packages
    if [ "$install_deps" = true ]; then
        echo "🔄 Force installing dependencies..."
        install_wine_dependencies
    else
        echo "🔍 Checking if dependencies are installed..."
        local missing_deps=false
        
        # Check critical packages in Windows venv
        local critical_packages=("PyQt6" "keyboard" "pynput" "httpx")
        for package in "${critical_packages[@]}"; do
            if ! $WINE_PYTHON -c "import $package" 2>/dev/null; then
                echo "❌ Missing in Windows venv: $package"
                missing_deps=true
                break
            fi
        done
        
        if [ "$missing_deps" = true ]; then
            echo "⚠️  Missing dependencies detected, installing..."
            install_wine_dependencies
        else
            echo "✅ All critical dependencies available, skipping installation"
        fi
    fi
    
    clean_previous_builds
    
    if [ "$clean_only" = false ]; then
        build_windows_exe
        
        if verify_build; then
            echo "🚀 Build process completed successfully!"
            exit 0
        else
            echo "💥 Build process failed!"
            exit 1
        fi
    else
        echo "✅ Clean completed (build skipped)"
    fi
}

# Uruchom main function z wszystkimi argumentami
main "$@"
