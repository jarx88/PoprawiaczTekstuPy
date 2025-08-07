# Rozwiązywanie problemu SmartScreen "Unknown Publisher"

## Problem
Windows SmartScreen blokuje uruchamianie aplikacji z komunikatem "Unknown Publisher" lub "Unrecognized app".

## Rozwiązania

### 1. 🏢 Profesjonalne rozwiązania (płatne)

#### Code Signing Certificate - Standard ($100-500/rok)
- Kupić certyfikat od autoryzowanego CA (DigiCert, Comodo, Sectigo)  
- Wymaga 2-8 tygodni na zbudowanie reputacji u Microsoft
- Dodać do GitHub Secrets:
  - `CODE_SIGNING_CERT` (certyfikat w base64)
  - `CODE_SIGNING_PASSWORD` (hasło do certyfikatu)

#### EV Code Signing Certificate - Extended Validation ($250-700/rok)  
- Tylko dla zarejestrowanych firm
- Wcześniej dawał natychmiastową reputację, od 2024/2025 już niekoniecznie
- Microsoft może wymagać dodatkowej weryfikacji aplikacji

#### Microsoft Trusted Signing (nowa opcja 2024/2025)
- Usługa Microsoft do podpisywania aplikacji
- Zapewnia obejście SmartScreen nawet bez EV

### 2. 🔧 Rozwiązania tymczasowe dla użytkowników

#### Dla końcowych użytkowników:
1. **Kliknij "More info"** → **"Run anyway"**
2. **Alternatywnie:**
   - Kliknij prawym przyciskiem na .exe
   - Properties → General → "Unblock" (jeśli dostępne)
   - Apply → OK

#### Dystrybucja przez ZIP:
- Zapakować .exe w .zip
- Użytkownicy pobierają ZIP i uruchamiają EXE z środka
- Omija część kontroli SmartScreen

### 3. 📋 Instrukcje dla użytkowników

Dodać do README aplikacji:
```
⚠️ WAŻNE: Windows może pokazać ostrzeżenie SmartScreen
Jest to normalne dla nowych aplikacji bez certyfikatu.
Aby uruchomić aplikację:
1. Kliknij "More info" 
2. Kliknij "Run anyway"
Aplikacja jest bezpieczna i można ją uruchomić.
```

### 4. 🔮 Perspektywy na przyszłość

- Kupno certyfikatu to jedyne trwałe rozwiązanie
- Self-signed certificates NIE działają z SmartScreen
- Darmowe certyfikaty SSL NIE działają do podpisywania kodu
- Microsoft coraz bardziej utrudnia obejście SmartScreen

## Rekomendacja

**Dla aplikacji komercyjnych/biznesowych:** Kup Standard Code Signing Certificate (~$150/rok)

**Dla projektów hobbystycznych:** Dodaj instrukcje dla użytkowników jak ominąć SmartScreen

**Opcjonalnie:** Możesz skonfigurować automatyczne podpisywanie w GitHub Actions (po kupnie certyfikatu)

### 5. 🔒 GitHub Artifact Attestations (dodatkowe bezpieczeństwo)

**⚠️ UWAGA: NIE pomaga z SmartScreen, ale zwiększa bezpieczeństwo**

- `actions/attest-build-provenance` generuje poświadczenie pochodzenia
- Pozwala użytkownikom zweryfikować, że EXE pochodzi z oryginalnego kodu
- Darmowe, ale wymaga narzędzi do weryfikacji
- **Nie zastępuje** code signing certificate dla SmartScreen

Weryfikacja przez użytkowników:
```bash
gh attestation verify popraw_tekst_corrector.exe --owner nazwaużytkownika
```