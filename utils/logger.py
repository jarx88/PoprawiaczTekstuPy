import logging
import os
import sys
from datetime import datetime
from .paths import get_logs_dir_path # Importujemy funkcję z paths.py

def setup_logger():
    """Konfiguruje logger z zapisem do pliku i konsoli."""
    # Ścieżka do katalogu z logami - używamy paths.py
    log_dir = get_logs_dir_path()

    # Tworzenie katalogu jeśli nie istnieje (paths.py już to robi, ale podwójne sprawdzenie nie zaszkodzi)
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"BŁĄD: Nie udało się utworzyć katalogu logów po raz drugi: {e}")
            # Kontynuujemy, nawet jeśli tworzenie katalogu się nie powiodło - logowanie do pliku może po prostu nie działać

    # Nazwa pliku z datą
    log_file = os.path.join(log_dir, f'popraw_tekst_{datetime.now().strftime("%Y%m%d")}.log')

    # Konfiguracja loggera
    logger = logging.getLogger('PoprawTekst')
    logger.setLevel(logging.ERROR)

    # Format logów
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # Handler dla pliku
    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.ERROR)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Błąd podczas konfiguracji handlera pliku: {e}")

    # Handler dla konsoli
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# Tworzenie globalnego loggera
logger = setup_logger()

def log_error(error, context=None):
    """Loguje błąd z dodatkowym kontekstem."""
    error_msg = f"Błąd: {str(error)}"
    if context:
        error_msg = f"{context} - {error_msg}"
    
    # Logowanie pełnego stack trace dla błędów
    if isinstance(error, Exception):
        import traceback
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
    else:
        logger.error(error_msg)

def log_api_error(api_name, error, response=None):
    """Loguje błąd API z dodatkowymi informacjami."""
    error_msg = f"Błąd {api_name} API: {str(error)}"
    
    if response:
        try:
            error_msg += f"\nStatus: {response.status_code}"
            error_msg += f"\nOdpowiedź: {response.text}"
        except:
            pass
    
    log_error(error_msg, f"API {api_name}")

def log_connection_error(api_name, error):
    """Loguje błąd połączenia z API."""
    error_msg = f"Błąd połączenia z {api_name} API: {str(error)}"
    log_error(error_msg, f"Połączenie {api_name}")

def log_timeout_error(api_name, error):
    """Loguje błąd timeoutu API."""
    error_msg = f"Timeout podczas połączenia z {api_name} API: {str(error)}"
    log_error(error_msg, f"Timeout {api_name}") 