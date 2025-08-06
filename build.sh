#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
if [ -x "$VENV_DIR/bin/python" ]; then
  VENV_PY="$VENV_DIR/bin/python"
elif [ -x "$VENV_DIR/Scripts/python.exe" ]; then
  VENV_PY="$VENV_DIR/Scripts/python.exe"
else
  VENV_PY=""
fi
ICON_PATH="$PROJECT_ROOT/assets/icon.ico"
MAIN_PATH="$PROJECT_ROOT/main.py"
ASSETS_PATH="$PROJECT_ROOT/assets"
SPEC_FILE="$PROJECT_ROOT/popraw_tekst.spec"

if [ ! -x "$VENV_PY" ]; then
  echo "Nie znaleziono venv – tworzę środowisko i instaluję zależności..."
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv "$VENV_DIR"
    VENV_PY="$VENV_DIR/bin/python"
    "$VENV_DIR/bin/pip" install -r "$PROJECT_ROOT/requirements.txt"
  elif command -v py >/dev/null 2>&1; then
    py -m venv "$VENV_DIR"
    if [ -x "$VENV_DIR/Scripts/python.exe" ]; then
      VENV_PY="$VENV_DIR/Scripts/python.exe"
      "$VENV_DIR/Scripts/pip.exe" install -r "$PROJECT_ROOT/requirements.txt"
    fi
  else
    echo "Błąd: Brak interpretera Python (python3/py). Zainstaluj Pythona." >&2
    exit 1
  fi
fi

if [ ! -f "$ICON_PATH" ]; then
  echo "Błąd: Nie znaleziono pliku ikony: $ICON_PATH" >&2
  exit 1
fi

echo "Czyszczenie poprzednich buildów..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build"
rm -f "$PROJECT_ROOT"/*.spec.tmp 2>/dev/null || true

echo "Budowanie aplikacji Popraw Tekst..."
if [ -f "$SPEC_FILE" ]; then
  echo "Używanie pliku spec: $SPEC_FILE"
  "$VENV_PY" -m PyInstaller "$SPEC_FILE" --noconfirm --workpath "$PROJECT_ROOT/build" --distpath "$PROJECT_ROOT/dist"
else
  echo "Plik spec nie znaleziony, używanie domyślnych ustawień..."
  "$VENV_PY" -m PyInstaller \
    --onefile \
    --noconsole \
    --name "popraw_tekst" \
    --icon "$ICON_PATH" \
    --add-data "$ASSETS_PATH:assets" \
    "$MAIN_PATH"
fi

if [ -f "$PROJECT_ROOT/dist/popraw_tekst" ] || [ -f "$PROJECT_ROOT/dist/popraw_tekst.exe" ]; then
  echo
  echo "Build zakończony pomyślnie!"
  echo "Plik wykonawczy: $(ls -1 "$PROJECT_ROOT/dist"/popraw_tekst* 2>/dev/null | head -n1)"
else
  echo
  echo "Build nie powiódł się!" >&2
  exit 1
fi
