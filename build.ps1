# --- AUTO-UNBLOCK EXECUTION POLICY (tylko dla tej sesji) ---
if ((Get-ExecutionPolicy) -in @('Restricted', 'AllSigned', 'Undefined')) {
    Write-Host "Polityka uruchamiania PowerShell blokuje skrypty." -ForegroundColor Yellow
    $answer = Read-Host "Czy chcesz tymczasowo zezwolić na uruchamianie skryptów w tej sesji? (T/N)"
    if ($answer -match '^[TtYy]') {
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
        Write-Host "Tymczasowo zezwolono na uruchamianie skryptów (tylko w tym oknie PowerShell)." -ForegroundColor Green
    } else {
        Write-Host "Przerwano wykonywanie skryptu." -ForegroundColor Red
        exit 1
    }
}

# Skrypt do budowania aplikacji Popraw Tekst

# Ścieżki
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$IconPath = Join-Path $ProjectRoot "assets\icon.ico"
$MainPath = Join-Path $ProjectRoot "main.py"
$AssetsPath = Join-Path $ProjectRoot "assets"

# Sprawdź czy venv istnieje
if (-not (Test-Path $VenvPath)) {
    Write-Host "Błąd: Nie znaleziono Pythona w venv: $VenvPath" -ForegroundColor Red
    Write-Host "Upewnij się, że venv jest utworzone i aktywne." -ForegroundColor Yellow
    exit 1
}

# Sprawdź czy istnieje ikona
if (-not (Test-Path $IconPath)) {
    Write-Host "Błąd: Nie znaleziono pliku ikony: $IconPath" -ForegroundColor Red
    exit 1
}

# Wyczyść poprzednie buildy
Write-Host "Czyszczenie poprzednich buildów..." -ForegroundColor Yellow
Remove-Item -Path (Join-Path $ProjectRoot "dist") -Recurse -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $ProjectRoot "build") -Recurse -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $ProjectRoot "*.spec") -ErrorAction SilentlyContinue

# Buduj aplikację
Write-Host "Budowanie aplikacji Popraw Tekst..." -ForegroundColor Green

# Usuń stary plik spec, aby upewnić się, że będzie użyty nowy
$specFile = Join-Path $ProjectRoot "popraw_tekst.spec"
if (Test-Path $specFile) {
    Write-Host "Używanie pliku spec: $specFile" -ForegroundColor Cyan
    & $VenvPath -m PyInstaller "$specFile" --noconfirm
} else {
    # Fallback do starej metody, jeśli plik spec nie istnieje
    Write-Host "Plik spec nie znaleziony, używanie domyślnych ustawień..." -ForegroundColor Yellow
    & $VenvPath -m PyInstaller `
        --onefile `
        --noconsole `
        --name "popraw_tekst" `
        --icon $IconPath `
        --add-data "$AssetsPath;assets" `
        $MainPath
}

# Sprawdź czy build się powiódł
if (Test-Path (Join-Path $ProjectRoot "dist\popraw_tekst.exe")) {
    Write-Host "`nBuild zakonczony pomyslnie!" -ForegroundColor Green
    Write-Host "Plik wykonawczy: dist\popraw_tekst.exe" -ForegroundColor Cyan
} else {
    Write-Host "`nBuild nie powiodl sie!" -ForegroundColor Red
}
