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

# Zwiększone timeouty dla DeepSeek API
DEFAULT_TIMEOUT = 25  # sekundy - zwiększone dla DeepSeek
QUICK_TIMEOUT = 12    # sekundy - dla szybszych odpowiedzi
CONNECTION_TIMEOUT = 8  # sekundy - dla nawiązania połączenia
DEEPSEEK_TIMEOUT = 35   # sekundy - specjalny timeout dla DeepSeek

# Konfiguracja retry
DEFAULT_RETRIES = 2   # zmniejszone z 3 na 2
QUICK_RETRIES = 1     # dla szybkich prób 