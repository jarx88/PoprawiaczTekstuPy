import sys
import os
# Dodaj to na samym początku, zanim zaimportujesz cokolwiek z PyQt6
os.environ['QT_DPI_AWARENESS'] = 'system'
# Możesz też spróbować 'permonitor' lub 'system' jeśli 'permonitorv2' nie zadziała
# os.environ['QT_DPI_AWARENESS'] = 'permonitor'
# os.environ['QT_DPI_AWARENESS'] = 'system'

import logging
from datetime import datetime
from PyQt6.QtWidgets import QApplication, QMessageBox
from gui.main_window import MainWindow
import threading
import keyboard # Zachowane dla compatibility z symulacją klawiszy
import time
from utils import config_manager
from utils.hotkey_manager import get_hotkey_processor, cleanup_global_hotkey
from api_clients import openai_client, anthropic_client, gemini_client, deepseek_client
import httpx

main_window_instance = None

# Konfiguracja logowania
def setup_logging():
    try:
        # Tworzymy katalog logs jeśli nie istnieje
        log_dir = os.path.join(os.path.expanduser("~"), "PoprawiaczTekstu_logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # Nazwa pliku z datą i czasem
        log_file = os.path.join(log_dir, f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        # Konfiguracja loggera
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()  # Dodatkowo wyświetla w konsoli jeśli jest
            ]
        )
        logging.info(f"Logi zapisywane do: {log_file}")
    except Exception as e:
        print(f"Błąd podczas konfiguracji logowania: {e}")

# --- Nowa logika globalnego skrótu klawiszowego używająca pynput ---
def setup_global_hotkey():
    """Konfiguruje globalny hotkey używając nowego thread-safe hotkey manager."""
    logging.info("Konfiguracja globalnego skrótu Ctrl+Shift+C (pynput)...")
    
    try:
        hotkey_processor = get_hotkey_processor()
        
        # Callback który będzie wywołany gdy hotkey zostanie wykryty
        def hotkey_callback():
            if main_window_instance:
                main_window_instance.handle_hotkey_event()
        
        # Setup hotkey z fallback mechanisms
        success = hotkey_processor.setup_hotkey_with_fallback(hotkey_callback)
        
        if success:
            logging.info("Globalny skrót klawiszowy skonfigurowany pomyślnie (pynput)")
        else:
            logging.warning("Nie udało się skonfigurować żadnego hotkey - tryb manualny")
            
    except Exception as e:
        logging.error(f"Błąd podczas konfiguracji globalnego skrótu: {e}")
        logging.error("Możliwe przyczyny: uprawnienia administratora, konflikty z innymi aplikacjami")
        logging.error("Aplikacja będzie działać w trybie manualnym")

def log_debug_info():
    logging.info(f"Ścieżka wykonywania: {os.getcwd()}")
    logging.info(f"Ścieżka do pliku: {os.path.abspath(__file__)}")
    logging.info(f"Ścieżka do config.ini: {config_manager.get_config_path()}")
    logging.info(f"Uprawnienia do katalogu: {oct(os.stat(os.getcwd()).st_mode)[-3:]}")
    try:
        logging.info(f"Zawartość katalogu: {os.listdir()}")
    except Exception as e:
        logging.error(f"Błąd odczytu katalogu: {e}")

def show_connection_error():
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle("Błąd połączenia")
    msg.setText("Nie można nawiązać połączenia z serwerem API")
    msg.setInformativeText("Możliwe przyczyny:\n"
                          "1. Brak połączenia z internetem\n"
                          "2. Firewall lub antywirus blokuje połączenie\n"
                          "3. Brak uprawnień administratora\n\n"
                          "Rozwiązania:\n"
                          "1. Uruchom program jako administrator\n"
                          "2. Dodaj wyjątek w Firewallu Windows\n"
                          "3. Sprawdź ustawienia antywirusa")
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.show()

def handle_api_error(e):
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
        logging.error(f"Błąd połączenia: {str(e)}")
        show_connection_error()
        return True
    return False

def check_first_run():
    """Sprawdza czy to pierwsze uruchomienie aplikacji i inicjuje odpowiednie akcje."""
    try:
        logging.info("=== Rozpoczynam check_first_run ===")
        log_debug_info()
        
        # Ładuje konfigurację
        api_keys, models, settings, new_config = config_manager.load_config()
        logging.info("Wczytano konfigurację kluczy API")
        logging.info(f"Wczytane modele: {models}")
        logging.info(f"Czy nowa konfiguracja: {new_config}")
        
        if new_config:
            logging.info("Pierwsze uruchomienie - utworzono plik konfiguracyjny.")
            
            if not config_manager.is_in_startup():
                msg = QMessageBox(None)
                msg.setIcon(QMessageBox.Icon.Question)
                msg.setWindowTitle("Autostart")
                msg.setText("Czy chcesz, aby program uruchamiał się automatycznie przy starcie systemu?")
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.show()
                response = msg.exec()
                
                if response == QMessageBox.StandardButton.Yes:
                    if config_manager.add_to_startup():
                        info_msg = QMessageBox(None)
                        info_msg.setIcon(QMessageBox.Icon.Information)
                        info_msg.setWindowTitle("Autostart")
                        info_msg.setText("Program został dodany do autostartu.")
                        info_msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                        info_msg.show()
                        settings['AutoStartup'] = '1'
                        config_manager.save_config(api_keys, models, settings)
                    else:
                        warn_msg = QMessageBox(None)
                        warn_msg.setIcon(QMessageBox.Icon.Warning)
                        warn_msg.setWindowTitle("Autostart")
                        warn_msg.setText("Nie udało się dodać programu do autostartu.")
                        warn_msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                        warn_msg.show()
        
        return api_keys, models
    except Exception as e:
        if handle_api_error(e):
            return None, None
        logging.error(f"Błąd w check_first_run: {str(e)}")
        logging.error(f"Typ błędu: {type(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        error_msg = QMessageBox(None)
        error_msg.setIcon(QMessageBox.Icon.Critical)
        error_msg.setWindowTitle("Błąd")
        error_msg.setText(f"Nie udało się załadować konfiguracji: {str(e)}")
        error_msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        error_msg.show()
        return None, None

def main():
    try:
        setup_logging()
        logging.info("=== Rozpoczynam main ===")
        log_debug_info()
        
        # Ustawienia DPI i skalowania
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
        os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
        os.environ["QT_SCALE_FACTOR"] = "1.0"
        
        global main_window_instance
        app = QApplication(sys.argv)
        
        # Wymuś styl Fusion dla lepszego skalowania
        app.setStyle('Fusion')
        
        # Sprawdź pierwsze uruchomienie
        api_keys, models = check_first_run()
        
        if api_keys is None or models is None:
            logging.error("Błąd podczas inicjalizacji - brak kluczy API lub modeli")
            return
        
        # Utworzenie i wyświetlenie głównego okna
        main_window_instance = MainWindow()
        
        setup_global_hotkey()
        app.setQuitOnLastWindowClosed(False)
        
        exit_code = app.exec()
        
        logging.info("Zamykanie aplikacji, czyszczenie hotkey manager...")
        try:
            cleanup_global_hotkey()
            logging.info("Hotkey manager wyczyszczony pomyślnie")
        except Exception as e:
            logging.warning(f"Błąd podczas czyszczenia hotkey manager: {e}")
        
        sys.exit(exit_code)
    except Exception as e:
        logging.error(f"Błąd w main: {str(e)}")
        logging.error(f"Typ błędu: {type(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        critical_msg = QMessageBox(None)
        critical_msg.setIcon(QMessageBox.Icon.Critical)
        critical_msg.setWindowTitle("Błąd krytyczny")
        critical_msg.setText(f"Wystąpił błąd krytyczny: {str(e)}")
        critical_msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        critical_msg.show()
        sys.exit(1)

if __name__ == '__main__':
    # Ważne: Na Windows, biblioteka `keyboard` może wymagać pewnego czasu na zarejestrowanie hooków,
    # zwłaszcza jeśli są konflikty. Czasami mały `time.sleep` na początku może pomóc,
    # ale idealnie nie powinno być to potrzebne.
    # time.sleep(0.1)
    main()