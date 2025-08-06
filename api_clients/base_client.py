# Ten plik może zawierać wspólną klasę bazową lub funkcje pomocnicze dla klientów API
# Na przykład, obsługę błędów, timeouty itp.
# Na razie zostawiamy go prostym.

# Definicje wyjątków specyficznych dla API, jeśli potrzebne
class APIConnectionError(Exception):
    pass

class APIResponseError(Exception):
    pass

class APITimeoutError(Exception):
    pass

# Zmniejszony timeout dla lepszego UX
DEFAULT_TIMEOUT = 15  # sekundy - zmniejszone z 60 na 15
QUICK_TIMEOUT = 8     # sekundy - dla szybszych odpowiedzi
CONNECTION_TIMEOUT = 5  # sekundy - dla nawiązania połączenia

# Konfiguracja retry
DEFAULT_RETRIES = 2   # zmniejszone z 3 na 2
QUICK_RETRIES = 1     # dla szybkich prób 