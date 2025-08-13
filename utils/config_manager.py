import configparser
import os
import winreg
import ctypes
import sys
from pathlib import Path
from .paths import get_config_file_path
from .logger import logger

CONFIG_FILE = "config.ini"
DEFAULT_MODELS = {
    "OpenAI": "o1-mini",  # o1-mini - stabilny model z reasoning capabilities
    "Anthropic": "claude-3-7-sonnet-latest",
    "Gemini": "gemini-2.5-flash-preview-04-17", 
    "DeepSeek": "deepseek-chat",
}

def get_config_value(config, section_name, key_name, fallback=''):
    """
    Pobiera wartość z config, ignorując wielkość liter w nazwach sekcji.
    Próbuje różne warianty nazwy sekcji (wielkie/małe litery).
    """
    # Lista możliwych wariantów nazwy sekcji
    section_variants = [
        section_name,           # oryginalna nazwa
        section_name.upper(),   # WIELKIE LITERY
        section_name.lower(),   # małe litery
        section_name.title(),   # Pierwsza Wielka
    ]
    
    for variant in section_variants:
        if config.has_section(variant):
            return config.get(variant, key_name, fallback=fallback)
    
    # Jeśli żadna sekcja nie istnieje, zwróć fallback
    return fallback

DEFAULT_CONFIG = {
    "API_KEYS": {
        "OpenAI": "",
        "Anthropic": "",
        "Gemini": "",
        "DeepSeek": ""
    },
    "MODELS": {
        "OpenAI": "o1-mini", 
        "Anthropic": "claude-3-7-sonnet-latest",
        "Gemini": "gemini-2.5-flash-preview-04-17",
        "DeepSeek": "deepseek-chat"
    },
    "SETTINGS": {
        "AutoStartup": "0",
        "DefaultStyle": "normal"
    },
    "AI_SETTINGS": {
        "ReasoningEffort": "high",  # minimal, low, medium, high - dla modeli GPT-5
        "Verbosity": "medium"       # low, medium, high - szczegółowość odpowiedzi
    }
}

def get_config_path():
    """Zwraca ścieżkę do pliku config.ini w katalogu aplikacji (przez paths.py)."""
    # logger.debug("DEBUG: Wywołano get_config_path.")
    return get_config_file_path()

def create_default_config():
    """Tworzy domyślny plik konfiguracyjny, jeśli nie istnieje."""
    config_path = get_config_path()
    logger.info(f"Próba utworzenia domyślnego config.ini w: {config_path}")
    
    if not os.path.exists(config_path):
        logger.info("Plik config.ini nie istnieje, tworzę nowy...")
        config = configparser.ConfigParser()
        
        for section, options in DEFAULT_CONFIG.items():
            config[section] = options
            logger.debug(f"Dodano sekcję {section} z opcjami: {options}")
        
        try:
            with open(config_path, 'w') as configfile:
                config.write(configfile)
            
            logger.info(f"Pomyślnie utworzono domyślny plik konfiguracyjny: {config_path}")
            return True
        except Exception as e:
            logger.error(f"Nie udało się utworzyć pliku konfiguracyjnego: {e}", exc_info=True)
            return False
    else:
        logger.info(f"Plik config.ini już istnieje w: {config_path}")
    
    return False

def load_config():
    """Ładuje konfigurację z pliku, tworząc domyślny jeśli nie istnieje."""
    config_path = get_config_path()
    logger.info(f"Próba załadowania konfiguracji z: {config_path}")
    new_config = False
    
    if not os.path.exists(config_path):
        logger.info(f"Plik konfiguracyjny nie znaleziono w {config_path}. Próba utworzenia domyślnego.")
        new_config = create_default_config()
        if not os.path.exists(config_path):
             logger.error(f"Krytyczny błąd: Plik konfiguracyjny nadal nie istnieje po próbie utworzenia: {config_path}")
             logger.warning("Powracanie do pustej konfiguracji z powodu błędu tworzenia/ładowania configu.")
             return DEFAULT_CONFIG['API_KEYS'], DEFAULT_CONFIG['MODELS'], DEFAULT_CONFIG['SETTINGS'], new_config
    
    config = configparser.ConfigParser()
    
    try:
        config.read(config_path)
        logger.info(f"Pomyślnie załadowano konfigurację z: {config_path}")
    except Exception as e:
        logger.error(f"Błąd podczas ładowania istniejącego pliku konfiguracyjnego {config_path}: {e}", exc_info=True)
        logger.warning("Powracanie do pustej konfiguracji z powodu błędu ładowania.")
        return DEFAULT_CONFIG['API_KEYS'], DEFAULT_CONFIG['MODELS'], DEFAULT_CONFIG['SETTINGS'], new_config

    
    # Pobierz klucze API i nazwy modeli (ignorując wielkość liter w sekcjach)
    api_keys = {
        "OpenAI": get_config_value(config, 'API_KEYS', 'OpenAI', ''),
        "Anthropic": get_config_value(config, 'API_KEYS', 'Anthropic', ''),
        "Gemini": get_config_value(config, 'API_KEYS', 'Gemini', ''),
        "DeepSeek": get_config_value(config, 'API_KEYS', 'DeepSeek', '')
    }
    
    models = {
        "OpenAI": get_config_value(config, 'MODELS', 'OpenAI', 'o4-mini'),
        "Anthropic": get_config_value(config, 'MODELS', 'Anthropic', 'claude-3-7-sonnet-latest'),
        "Gemini": get_config_value(config, 'MODELS', 'Gemini', 'gemini-2.5-flash-preview-04-17'),
        "DeepSeek": get_config_value(config, 'MODELS', 'DeepSeek', 'deepseek-chat')
    }
    
    # Pobierz ustawienia
    settings = {
        "AutoStartup": get_config_value(config, 'SETTINGS', 'AutoStartup', '0'),
        "DefaultStyle": get_config_value(config, 'SETTINGS', 'DefaultStyle', 'normal')
    }

    # Logowanie wczytanych kluczy i modeli (opcjonalnie, może być zbyt szczegółowe dla INFO)
    logger.debug("Wczytano klucze API z konfiguracji")
    logger.debug(f"Wczytane modele: {models}")
    logger.debug(f"Wczytane ustawienia: {settings}")
    
    return api_keys, models, settings, new_config

def save_config(api_keys, models, settings=None, ai_settings=None):
    """Zapisuje konfigurację do pliku."""
    config_path = get_config_path()
    config = configparser.ConfigParser()
    
    # Spróbuj wczytać istniejący config, aby zachować inne sekcje/ustawienia
    if os.path.exists(config_path):
        try:
            config.read(config_path)
            logger.debug(f"Wczytano istniejący config do modyfikacji z: {config_path}")
        except Exception as e:
            logger.warning(f"Nie udało się wczytać istniejącego configu do modyfikacji: {e}. Tworzenie nowego configu.", exc_info=True)
            # Kontynuujemy z pustym obiektem config, co nadpisze plik, jeśli istnieje i jest uszkodzony
    else:
        logger.debug(f"Plik config.ini nie istnieje do wczytania przed zapisem w: {config_path}. Tworzenie nowego.")
    
    # Upewnij się, że sekcje istnieją przed zapisem
    if 'API_KEYS' not in config:
        config['API_KEYS'] = {}
    if 'MODELS' not in config:
        config['MODELS'] = {}
    if 'SETTINGS' not in config:
        config['SETTINGS'] = {}
    if 'AI_SETTINGS' not in config:
        config['AI_SETTINGS'] = {}
    
    # Zapisz klucze API
    for key, value in api_keys.items():
        config['API_KEYS'][key] = value
    
    # Zapisz modele
    for key, value in models.items():
        config['MODELS'][key] = value
    
    # Zapisz ustawienia, jeśli podano
    if settings:
        for key, value in settings.items():
            config['SETTINGS'][key] = str(value)
    
    # Zapisz ustawienia AI, jeśli podano
    if ai_settings:
        for key, value in ai_settings.items():
            config['AI_SETTINGS'][key] = str(value)
    
    # Zapisz do pliku
    with open(config_path, 'w') as configfile:
        config.write(configfile)
    
    print(f"Zapisano konfigurację do: {config_path}")

def is_in_startup():
    """Sprawdza czy aplikacja jest w autostarcie."""
    try:
        # Ścieżka do programu
        if getattr(sys, 'frozen', False):
            app_path = sys.executable
        else:
            app_path = sys.argv[0]
        
        # Nazwa skrótu w autostarcie
        shortcut_name = "PoprawTekst"
        
        # Klucz rejestru autostartu
        key = winreg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        # Otwórz klucz
        registry_key = winreg.OpenKey(key, key_path, 0, winreg.KEY_READ)
        
        try:
            # Spróbuj odczytać wartość
            value, regtype = winreg.QueryValueEx(registry_key, shortcut_name)
            # Jeśli wartość istnieje i jest równa ścieżce programu
            return value == f'"{app_path}"'
        except WindowsError:
            # Wartość nie istnieje
            return False
        finally:
            winreg.CloseKey(registry_key)
    except Exception as e:
        print(f"Błąd podczas sprawdzania autostartu: {e}")
        return False

def add_to_startup():
    """Dodaje aplikację do autostartu."""
    try:
        # Ścieżka do programu
        if getattr(sys, 'frozen', False):
            app_path = sys.executable
        else:
            app_path = sys.argv[0]
        
        # Nazwa skrótu w autostarcie
        shortcut_name = "PoprawTekst"
        
        # Klucz rejestru autostartu
        key = winreg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        # Otwórz klucz z prawem zapisu
        registry_key = winreg.OpenKey(key, key_path, 0, winreg.KEY_WRITE)
        
        # Zapisz wartość
        winreg.SetValueEx(registry_key, shortcut_name, 0, winreg.REG_SZ, f'"{app_path}"')
        winreg.CloseKey(registry_key)
        
        return True
    except Exception as e:
        print(f"Błąd podczas dodawania do autostartu: {e}")
        return False

def remove_from_startup():
    """Usuwa aplikację z autostartu."""
    try:
        # Nazwa skrótu w autostarcie
        shortcut_name = "PoprawTekst"
        
        # Klucz rejestru autostartu
        key = winreg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        
        # Otwórz klucz z prawem zapisu
        registry_key = winreg.OpenKey(key, key_path, 0, winreg.KEY_WRITE)
        
        # Usuń wartość
        winreg.DeleteValue(registry_key, shortcut_name)
        winreg.CloseKey(registry_key)
        
        return True
    except WindowsError:
        # Wartość już nie istnieje
        return True
    except Exception as e:
        print(f"Błąd podczas usuwania z autostartu: {e}")
        return False

def is_admin():
    """Sprawdza czy program jest uruchomiony z prawami administratora."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

if __name__ == "__main__":
    print(f"Domyślna ścieżka config: {get_config_path()}")
    # Testowanie modułu
    keys, current_models, current_settings, _ = load_config()
    print("Wczytane klucze API:", keys)
    print("Wczytane modele:", current_models)
    print("Wczytane ustawienia:", current_settings)
    
    # Przykładowy zapis
    # keys["OpenAI"] = "test_key_123_openai" # Zmiana klucza
    # current_models["OpenAI"] = "gpt-4-test"
    # save_config(keys, current_models)
    # print("Zapisano zmodyfikowaną konfigurację.")
    
    # keys, current_models, _ = load_config()
    # print("Ponownie wczytane klucze API:", keys)
    # print("Ponownie wczytane modele:", current_models)
