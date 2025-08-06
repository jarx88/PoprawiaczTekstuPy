# PoprawiaczTekstuPy

Nowoczesna aplikacja do automatycznej korekty tekstu z wykorzystaniem AI. Obsługuje OpenAI, Anthropic, Gemini i DeepSeek APIs.

![Build Status](https://github.com/YOUR_USERNAME/PoprawiaczTekstuPy/workflows/Build%20Windows%20EXE/badge.svg)

## ✨ Funkcje

- 🎨 **Nowoczesny interfejs** - CustomTkinter z dark/light mode
- ⚡ **Globalny hotkey** - Ctrl+Shift+C do szybkiej korekty
- 🔄 **System tray** - aplikacja w zasobniku systemowym
- 🤖 **Wielokrotne AI** - OpenAI, Anthropic, Gemini, DeepSeek
- 📋 **Schowek** - automatyczna korekta tekstu ze schowka
- 🔧 **Łatwe ustawienia** - graficzny interfejs konfiguracji

## 🚀 Instalacja

### Option 1: Pobierz gotowy executable
1. Idź do [Releases](https://github.com/YOUR_USERNAME/PoprawiaczTekstuPy/releases)
2. Pobierz najnowszą wersję dla swojego systemu:
   - **Windows**: `popraw_tekst_modern.exe`
   - **Linux**: `popraw_tekst_modern_linux`

### Option 2: Uruchom z kodu źródłowego
```bash
git clone https://github.com/YOUR_USERNAME/PoprawiaczTekstuPy.git
cd PoprawiaczTekstuPy
pip install -r requirements.txt
python main_modern.py
```

## ⚙️ Konfiguracja

1. Uruchom aplikację
2. Kliknij **Ustawienia**
3. Wpisz swoje API keys:
   - OpenAI: `sk-...`
   - Anthropic: `sk-ant-...`
   - Gemini: `AIza...`
   - DeepSeek: `sk-...`

## 🎯 Użycie

### Globalny skrót klawiszowy
1. Skopiuj tekst do schowka (Ctrl+C)
2. Naciśnij **Ctrl+Shift+C**
3. Poprawiony tekst zastąpi zawartość schowka

### Interfejs graficzny
1. Wklej tekst w górnym polu
2. Kliknij **Popraw tekst**
3. Skopiuj wynik z dolnego pola

## 🔧 Development

### Budowanie lokalnie (Linux)
```bash
# Linux version
./build-linux.sh

# Test Wine build (problematyczny)
./build-modern.sh
```

### GitHub Actions
Projekt używa GitHub Actions do automatycznego budowania:
- **Push na main/master** - automatyczny build
- **Tags (v*.*.*)** - tworzenie release z executables
- **Manual trigger** - ręczne uruchomienie workflow

## 📦 Technologie

- **GUI**: CustomTkinter (nowoczesny design)
- **System Tray**: pystray
- **Hotkeys**: pynput (thread-safe)
- **AI APIs**: OpenAI, Anthropic, Gemini, DeepSeek
- **Build**: PyInstaller + GitHub Actions

## 🐛 Rozwiązywanie problemów

### Windows
- Jeśli antywirus blokuje: dodaj wyjątek
- Jeśli hotkey nie działa: uruchom jako administrator

### Linux
- Zainstaluj tkinter: `sudo apt install python3-tk`
- Problemy z X11: ustaw `export DISPLAY=:0`

## 📝 Historia zmian

### v2.0.0 (Aktualny)
- ✅ Migracja z PyQt6 na CustomTkinter
- ✅ Nowoczesny design z dark/light mode
- ✅ Lepsza wydajność i stabilność
- ✅ GitHub Actions dla automatycznych builds
- ✅ System tray integration

### v1.0.0
- ✅ Podstawowa funkcjonalność z PyQt6
- ✅ Thread-safe hotkey handling
- ✅ Obsługa wielu AI providers

## 🤝 Współpraca

1. Fork projektu
2. Stwórz branch dla swojej funkcji
3. Commit zmiany
4. Push do brancha
5. Otwórz Pull Request

## 📄 Licencja

[MIT License](LICENSE)

## ❓ FAQ

**Q: Dlaczego Wine build nie działa?**
A: Wine ma problemy z shared WSL/Windows venv. Użyj GitHub Actions do budowania Windows exe.

**Q: Jak dodać nowy AI provider?**
A: Dodaj klienta w `api_clients/` i zaktualizuj `main_modern.py`.

**Q: Czy mogę używać bez internetu?**
A: Nie, aplikacja wymaga połączenia z internetem dla AI APIs.

---

💡 **Pro tip**: Użyj GitHub Actions do automatycznego budowania - rozwiązuje wszystkie problemy z cross-compilation!