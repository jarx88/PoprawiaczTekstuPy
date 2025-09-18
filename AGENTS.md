# Repository Guidelines

## Zasady ogólne
- ZAWSZE odpowiadaj w języku **polskim**.
- Prośba o kod oznacza także polskie komentarze i nazwy, chyba że koliduje to z istniejącą konwencją.
- Lokalna dokumentacja (`README.md`, `CONTRIBUTING`, inne przewodniki) ma najwyższy priorytet przy ustalaniu stylu.

## Planowanie na hasło „szkic”
- Jeśli ostatnie polecenie zawiera słowo „szkic” (poza cytatami/kodem), przejdź w tryb planu.
- Tryb planu: przygotuj analizę, przedstaw plan w bloku ```markdown```, poczekaj na akceptację i dopiero potem modyfikuj repo.
- Plan obejmuje cel, zakres z plikami, kroki, wpływ na build/testy, komendy weryfikacji, ryzyka i kryteria akceptacji.
- Brak hasła „szkic” → realizuj zadanie bez planu, zachowując standardowe preambuły do komend.

## Project Structure & Module Organization
`main_corrector.py` uruchamia pełne GUI; `main_console.py` obsługuje tryb CLI. Adaptery providerów w `api_clients/`, widoki i prompty w `gui/`, helpery konfiguracji/modeli/hotkeyów w `utils/`, zasoby w `assets/`. Skrypty `build*.sh` i pliki `.spec` leżą w katalogu głównym, generując artefakty do `build/` (pośrednie) i `dist/` (release). Dane lokalne trzymaj w zignorowanym `config.ini`; do repo trafiają wyłącznie szablony jak `config_example_reasoning.ini`.

## Build, Test, and Development Commands
- `pip install -r requirements.txt` — bazowy zestaw zależności; warianty OS wybieraj przy budowaniu Wine/PySide.
- `python main_corrector.py` — pełna aplikacja desktopowa z czterema panelami AI.
- `python main_console.py` — szybki test providers w terminalu.
- `./build.sh` — rebuild zgodny z domyślnym specem PyInstaller.
- `pyinstaller popraw_tekst_corrector.spec --noconfirm` — ręczny build po zmianach w specu.

## Coding Style & Naming Conventions
Stosuj PEP 8: wcięcia 4 spacje, snake_case dla funkcji/modułów, PascalCase dla klas. Prefiksuj helpery nazwami providerów (`openai_`, `anthropic_`, ...), a stałe GUI trzymaj w `gui/`. Korzystaj z `get_assets_dir_path()` i podobnych helperów, a nowe moduły opatruj adnotacjami typów.

## Testing Guidelines
Dodając testy, twórz lustrzany katalog `tests/` i odpalaj `pytest`. Mockuj zewnętrzne API, dokumentuj wymagane zmienne środowiskowe na początku plików testowych. Po automatycznych testach wykonaj ręczny smoke run `python main_corrector.py`, aby sprawdzić hotkeys, preload GIF-ów, tray oraz anulowanie zapytań.

## Commit & Pull Request Guidelines
Commity pisz imperatywnie po polsku (np. `Popraw skalowanie podglądu diff`). Tytuły i opisy PR również po polsku, zaczynając od krótkiego streszczenia. W PR podaj zakres, dotknięte moduły/providery, linki do zgłoszeń, media Before/After dla UI oraz kroki weryfikacji i nowe klucze konfiguracyjne.

## Security & Configuration Tips
Nie commituj prawdziwych kluczy ani logów z danymi. Korzystaj z szablonów i zmiennych środowiskowych, a przed udostępnieniem czyszcz `logs/`. Debugging ujawniający dane otaczaj flagami, by buildy z `./build.sh` pozostały wolne od poufnych śladów.
