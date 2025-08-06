import os
import sys

def get_app_dir():
    """Zwraca absolutną ścieżkę do głównego katalogu aplikacji."""
    if getattr(sys, 'frozen', False):
        # Aplikacja jest uruchomiona jako skompilowany plik .exe
        return os.path.dirname(sys.executable)
    else:
        # Aplikacja jest uruchomiona jako skrypt .py
        # Zakładamy, że paths.py jest w PoprawiaczTekstuPy/utils/
        # więc .. wraca do PoprawiaczTekstuPy/
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_config_file_path():
    """Zwraca ścieżkę do pliku config.ini w katalogu aplikacji."""
    return os.path.join(get_app_dir(), 'config.ini')

def get_assets_dir_path():
    """Zwraca ścieżkę do katalogu assets, uwzględniając tryb skompilowany PyInstallerem."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Jesteśmy w skompilowanym EXE (np. tryb --onefile)
        # Zasoby są spakowane w tymczasowym katalogu _MEIPASS
        # i dostępne w podkatalogu 'assets' (zgodnie z --add-data "assets;assets")
        assets_dir = os.path.join(sys._MEIPASS, 'assets')
        # print(f"DEBUG paths: Tryb frozen, assets_dir = {assets_dir}") # Linia debugująca
        return assets_dir
    else:
        # Jesteśmy w trybie skryptu Python
        # Zasoby są w katalogu 'assets' w głównym katalogu projektu
        app_dir = get_app_dir()
        assets_dir = os.path.join(app_dir, 'assets')
        # print(f"DEBUG paths: Tryb skryptu, assets_dir = {assets_dir}") # Linia debugująca
        return assets_dir

def get_logs_dir_path():
    """Zwraca ścieżkę do katalogu logs w katalogu aplikacji."""
    app_dir = get_app_dir()
    logs_dir = os.path.join(app_dir, 'logs')
    if not os.path.exists(logs_dir):
        try:
            os.makedirs(logs_dir)
        except OSError as e:
            # W przypadku problemu z utworzeniem katalogu logów w katalogu aplikacji
            # (np. brak uprawnień), spróbuj utworzyć go w katalogu tymczasowym użytkownika.
            print(f"OSTRZEŻENIE: Nie można utworzyć katalogu logów w {logs_dir}: {e}")
            print("Próba utworzenia katalogu logów w katalogu tymczasowym.")
            try:
                # Bardziej standardowa lokalizacja dla plików tymczasowych/konfiguracyjnych specyficznych dla użytkownika
                user_data_dir = os.path.join(os.getenv('APPDATA', os.path.expanduser("~")), 'PoprawTekst')
                if not os.path.exists(user_data_dir):
                    os.makedirs(user_data_dir, exist_ok=True)
                logs_dir = os.path.join(user_data_dir, 'logs')
                if not os.path.exists(logs_dir):
                     os.makedirs(logs_dir, exist_ok=True)
            except Exception as e_temp:
                print(f"BŁĄD: Nie można utworzyć katalogu logów także w katalogu danych użytkownika: {e_temp}")
                # Ostateczny fallback, jeśli wszystko inne zawiedzie - logi w katalogu aplikacji
                logs_dir = os.path.join(app_dir, 'logs') # Próba bez tworzenia, jeśli istnieje
                if not os.path.exists(logs_dir):
                    try:
                        os.makedirs(logs_dir)
                    except Exception as e_final_app_dir:
                        print(f"KRYTYCZNY BŁĄD: Nie można utworzyć katalogu logów nigdzie: {e_final_app_dir}")
                        # W tym momencie logowanie do pliku może nie działać, ale próbujemy zwrócić ścieżkę
    return logs_dir

if __name__ == '__main__':
    print(f"Katalog aplikacji: {get_app_dir()}")
    print(f"Ścieżka do config.ini: {get_config_file_path()}")
    print(f"Ścieżka do katalogu assets: {get_assets_dir_path()}")
    print(f"Ścieżka do katalogu logs: {get_logs_dir_path()}") 