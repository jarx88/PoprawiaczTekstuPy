import sys
import subprocess
# import keyboard  # Usunięto - hotkey zarządzany przez main.py
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QComboBox, QPushButton, QTextEdit, QGroupBox,
    QSizePolicy, QScrollArea, QDialog, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QStatusBar, QMessageBox, QProgressBar, QStackedWidget
)
from PyQt6.QtGui import QIcon, QFont, QColor, QPalette, QAction, QMovie
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QEvent
from PyQt6.QtWidgets import QStyle
import os
import re
import logging # Importujemy moduł logging
import time
from .settings_dialog import SettingsDialog
import configparser
import webbrowser
import threading
import keyboard
import time
from utils import config_manager
from utils.model_loader import ModelLoader
from . import prompts
from utils.paths import get_app_dir, get_assets_dir_path
from utils import clipboard_manager
from utils.logger import logger # Importujemy instancję loggera

# Próba importu config_manager z odpowiednią ścieżką
# Define project_dir consistently
# current_file_path is .../PoprawiaczTekstuPy/gui/main_window.py
# Używamy teraz paths.py zamiast ręcznego obliczania project_dir
# current_file_path_for_utils = os.path.abspath(__file__)
# gui_dir_for_utils = os.path.dirname(current_file_path_for_utils)
# project_dir_for_utils = os.path.dirname(gui_dir_for_utils)

# Add project_dir to sys.path if not already there,
# useful if main_window.py is run directly for testing.
# if project_dir_for_utils not in sys.path:
#     sys.path.insert(0, project_dir_for_utils)

from utils import config_manager

# Importy naszych klientów API
from api_clients.openai_client import correct_text_openai
from api_clients.anthropic_client import correct_text_anthropic
from api_clients.gemini_client import correct_text_gemini
from api_clients.deepseek_client import correct_text_deepseek

# Enum dla API (możemy go też trzymać tutaj dla uproszczenia dostępu)
API_OPENAI = 0
API_ANTHROPIC = 1
API_GEMINI = 2
API_DEEPSEEK = 3


# Klasa Worker do obsługi zapytań API w osobnym wątku
class ApiWorker(QThread):
    # Sygnały: finished_signal(api_index, result_text, is_error, session_id)
    finished_signal = pyqtSignal(int, str, bool, int)
    # Sygnał do sygnalizacji anulowania (api_index, session_id)
    cancelled_signal = pyqtSignal(int, int)

    def __init__(self, api_index, api_function, api_key, model, text, style, system_prompt, session_id=0):
        super().__init__()
        self.api_index = api_index
        self.api_function = api_function
        self.api_key = api_key
        self.model = model
        self.text = text
        self.style = style
        self.system_prompt = system_prompt
        self.session_id = session_id  # ID sesji

    def run(self):
        try:
            # Sprawdź flagę anulowania przed rozpoczęciem
            if hasattr(self, '_is_cancelled') and self._is_cancelled:
                logger.info(f"Wątek API ({self.api_index}) anulowany przed rozpoczęciem.")
                self.cancelled_signal.emit(self.api_index, self.session_id)
                return # Zakończ wątek

            # Ustaw krótszy timeout w przypadku wątków - unikaj długiego oczekiwania
            start_time = time.time()
            result = self.api_function(self.api_key, self.model, self.text, self.style, self.system_prompt)
            
            # Sprawdź czy nie przekroczono czasu i czy nie anulowano
            if hasattr(self, '_is_cancelled') and self._is_cancelled:
                logger.info(f"Wątek API ({self.api_index}) anulowany podczas przetwarzania.")
                self.cancelled_signal.emit(self.api_index, self.session_id)
                return
                
            elapsed_time = time.time() - start_time
            logger.info(f"API ({self.api_index}) odpowiedział w {elapsed_time:.2f}s")
            
            # Sprawdzamy, czy wynik nie jest komunikatem o błędzie od samego klienta (np. brak klucza)
            if isinstance(result, str) and result.lower().startswith("błąd:"):
                self.finished_signal.emit(self.api_index, result, True, self.session_id)
            elif hasattr(self, '_is_cancelled') and self._is_cancelled:
                # Sprawdź flagę anulowania po otrzymaniu wyniku
                logger.info(f"Wątek API ({self.api_index}) anulowany po otrzymaniu wyniku.")
                self.cancelled_signal.emit(self.api_index, self.session_id)
            else:
                self.finished_signal.emit(self.api_index, result, False, self.session_id)
        except Exception as e:
            # Obsługa timeout i innych błędów
            if hasattr(self, '_is_cancelled') and self._is_cancelled:
                logger.info(f"Wątek API ({self.api_index}) przerwany podczas obsługi błędu - anulowany.")
                self.cancelled_signal.emit(self.api_index, self.session_id)
                return
                
            # Ogólny wyjątek, jeśli coś pójdzie nie tak w samym wywołaniu funkcji klienta
            error_message = f"Krytyczny błąd wątku API ({self.api_index}): {e}"
            logger.error(error_message, exc_info=True) # Używamy loggera z pełnym tracebackiem
            # Sprawdź czy nie anulowano przed emitowaniem błędu
            if not (hasattr(self, '_is_cancelled') and self._is_cancelled):
                self.finished_signal.emit(self.api_index, error_message, True, self.session_id)

    def cancel(self):
        """Ustawia flagę anulowania dla wątku."""
        self._is_cancelled = True
        logger.info(f"Ustawiono flagę anulowania dla wątku API ({self.api_index}).")
        
    def is_cancelled(self):
        """Sprawdza czy wątek został anulowany."""
        return hasattr(self, '_is_cancelled') and self._is_cancelled


class ModelLoaderThread(QThread):
    model_loaded = pyqtSignal(str, str)  # nazwa modelu, status
    loading_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)  # komunikat błędu

    def __init__(self, model_loader):
        super().__init__()
        self.model_loader = model_loader

    def run(self):
        try:
            # Ładowanie modeli
            logger.info("Rozpoczęto ładowanie modeli.")
            self.model_loaded.emit("GPT-4", "Ładowanie...")
            self.model_loader.load_gpt4_model()
            logger.info("Załadowano model GPT-4.")
            self.model_loaded.emit("GPT-4", "Gotowy")

            self.model_loaded.emit("Claude", "Ładowanie...")
            self.model_loader.load_claude_model()
            logger.info("Załadowano model Claude.")
            self.model_loaded.emit("Claude", "Gotowy")

            self.model_loaded.emit("Mistral", "Ładowanie...")
            self.model_loader.load_mistral_model()
            logger.info("Załadowano model Mistral.")
            self.model_loaded.emit("Mistral", "Gotowy")

            self.loading_finished.emit()
            logger.info("Zakończono ładowanie wszystkich modeli.")
        except Exception as e:
            logger.error(f"Błąd podczas ładowania modeli: {e}", exc_info=True)
            self.error_occurred.emit(str(e))


class MainWindow(QMainWindow):
    # Dodajemy sygnał, który będzie emitowany z wątku `keyboard`
    # a obsługiwany w głównym wątku Qt.
    hotkey_triggered_signal = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Flagi zamykania aplikacji
        self._is_closing = False
        self._really_closing = False
        self._tray_message_shown = False

        # project_dir for resources like icons
        # Używamy teraz paths.py
        self.project_dir = get_app_dir() # Use the path from paths.py

        self.api_keys, self.current_models, self.settings, _ = config_manager.load_config()
        self.s_original_text = ""
        self.s_current_style = "normal"
        self.api_clients_enum = {"OPENAI": 0, "ANTHROPIC": 1, "GEMINI": 2, "DEEPSEEK": 3} # Zgodnie z AutoIt Enum

        # Konfiguracja dostawców API
        self.api_providers_config = [
            ("OpenAI", self.current_models["OpenAI"], "#f0f8ff", "#0050a0"),
            ("Anthropic", self.current_models["Anthropic"], "#f0fff0", "#006400"),
            ("Google Gemini", self.current_models["Gemini"], "#fffacd", "#8b4513"),
            ("DeepSeek", self.current_models["DeepSeek"], "#fff0f5", "#800080")
        ]

        self.s_original_text_content = "" # Inicjalizacja pustym tekstem
        self.is_processing = False # Flaga informująca, czy trwa przetwarzanie
        self.api_threads = {} # Słownik do przechowywania aktywnych wątków
        self.last_clipboard_text = "" # Do monitorowania linków obrazków
        self.current_session_id = 0  # ID sesji zapytań - do rozróżniania starych od nowych

        # Atrybuty dla animacji statusu API (QMovie)
        # self.api_loader_labels = [] # Lista QLabelów dla QMovie - ZASTĄPIONE
        self.api_loader_widgets = [] # Lista QLabelów (z QMovie) umieszczonych w QStackedWidget
        self.api_text_edit_stacks = [] # Lista QStackedWidgetów dla każdego panelu API
        self.api_movies = {}      # Słownik dla aktywnych obiektów QMovie (pozostaje)

        # Przeniesiono self._create_toolbar() i self._create_api_panels() wyżej
        # Inicjalizacja GUI przed próbą odczytu wartości z kontrolek
        self.central_widget = QWidget()
        self.central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # KROK 1: Inicjalizacja paska statusu i paska postępu
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        # Usprawniony pasek statusu z ikonami i dodatkowymi informacjami
        self._create_enhanced_status_bar()

        # KROK 2: Tworzenie reszty UI, która może z nich korzystać
        self._create_toolbar()      # Tworzy m.in. self.style_combo
        self._create_api_panels()

        # KROK 3: Inicjalizacja stylu, ale nie wywołuj _start_api_requests tutaj
        self._style_changed_called = False

        icon_path = os.path.join(self.project_dir, "assets", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            print(f"Nie znaleziono ikony: {icon_path}")
        
        # Zwiększamy domyślną wysokość okna
        self.setGeometry(100, 100, 1200, 850) # Zwiększona wysokość okna
        self.setWindowTitle("Poprawiacz Tekstu Multi-API (PyQt)")

        self.setStyleSheet("""
            /* === Globalne Ustawienia === */
            QMainWindow, QWidget#CentralWidget, QScrollArea, QWidget {
                background-color: #f0f0f0; /* Jasnoszare tło dla większości elementów */
                color: #202020; /* Domyślny kolor tekstu */
                font-family: "Segoe UI", Arial, sans-serif; /* Standardowa czcionka */
            }

            /* === QGroupBox === */
            QGroupBox {
                font-weight: bold;
                font-size: 10pt;
                background-color: #e9e9e9; /* Jaśniejsze tło dla GroupBox */
                border: 1px solid #c5c5c5; /* Subtelna ramka */
                border-radius: 5px;
                margin-top: 10px; /* Zwiększony margines dla tytułu */
                padding: 15px 10px 10px 10px; /* Góra, Reszta */
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px; /* Padding wokół tekstu tytułu */
                left: 10px; /* Odsunięcie tytułu od lewej krawędzi */
                top: -2px; /* Korekta pozycji tytułu, aby "siedział" na ramce */
                color: #101010; /* Ciemny kolor tytułu */
            }

            /* === QLabel === */
            QLabel, QLabel#StatusLabel {
                font-size: 9pt;
                color: #303030; /* Ciemnoszary tekst */
                background-color: transparent;
                padding: 2px;
            }
            QLabel#StatusLabel {
                 min-height: 1.2em; /* Wystarczająco dla jednej linii */
                 font-style: italic;
            }

            /* === QTextEdit === */
            QTextEdit {
                font-size: 10pt;
                color: #000000; /* Czarny tekst w polu edycji */
                background-color: #ffffff; /* Białe tło */
                border: 1px solid #bababa; /* Ciemniejsza ramka dla kontrastu */
                border-radius: 4px;
                padding: 4px;
            }
            QTextEdit::placeholder {
                color: #808080; /* Stonowany placeholder */
            }

            /* === QPushButton === */
            QPushButton {
                font-size: 9pt; /* Nieco mniejsza czcionka dla przycisków */
                font-weight: normal;
                padding: 6px 12px;
                background-color: #dddddd; /* Jasnoszare tło */
                border: 1px solid #b0b0b0; /* Ramka */
                color: #181818; /* Ciemny tekst */
                border-radius: 4px;
                min-height: 20px; 
            }
            QPushButton:hover {
                background-color: #cacaca;
                border-color: #909090;
            }
            QPushButton:pressed {
                background-color: #b5b5b5;
            }

            /* === QComboBox === */
            QComboBox {
                font-size: 9pt;
                color: #181818;
                padding: 5px 8px;
                border: 1px solid #b0b0b0;
                border-radius: 4px;
                background-color: #f0f0f0; /* Dopasowane do tła */
            }
            QComboBox:hover {
                border-color: #909090;
            }
            QComboBox::drop-down { /* Strzałka rozwijania */
                border: none;
                background-color: transparent;
            }
            QComboBox QAbstractItemView { /* Rozwijana lista */
                background-color: #ffffff;
                color: #181818;
                border: 1px solid #b0b0b0;
                selection-background-color: #cce5ff; /* Jasnoniebieskie zaznaczenie */
                selection-color: #101010;
                padding: 2px;
            }

            /* === QScrollArea === */
            QScrollArea {
                border: none; /* Bez ramki dla obszaru przewijania */
            }
            
            /* === QStatusBar === */
            QStatusBar {
                background-color: #e8e8e8;
                border-top: 1px solid #c0c0c0;
                color: #333333;
                font-size: 9pt;
                padding: 2px 5px;
            }
            QStatusBar::item {
                border: none;
            }
        """)

        self._init_clipboard_monitoring() # Inicjalizacja monitorowania schowka dla linków obrazków
        self._create_tray_icon() # Odkomentowano tworzenie ikony w zasobniku

        # Połączenie sygnału ze slotem
        self.hotkey_triggered_signal.connect(self._process_hotkey_event_in_qt_thread)

        # Ustawienie początkowego statusu - teraz jest to bezpieczne
        self._update_status("Gotowy", "ready")

        # Inicjalizacja model_loader
        self.model_loader = ModelLoader()
        
        # Rozpocznij asynchroniczne ładowanie modeli
        self._start_model_loading()

        self.adjust_window_size()  # Automatyczne dopasowanie rozmiaru na starcie
        # Podłącz automatyczne skalowanie do sygnałów ekranu
        screen = self.screen()
        if screen:
            screen.geometryChanged.connect(self.adjust_window_size)
            screen.logicalDotsPerInchChanged.connect(self.adjust_window_size)

    def _create_enhanced_status_bar(self):
        """Tworzy usprawniony pasek statusu z dodatkowymi elementami."""
        # Główny widget statusu z ikoną
        self.status_widget = QWidget()
        status_layout = QHBoxLayout(self.status_widget)
        status_layout.setContentsMargins(5, 2, 5, 2)
        status_layout.setSpacing(8)
        
        # Ikona statusu
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(16, 16)
        ready_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        self.status_icon.setPixmap(ready_icon.pixmap(16, 16))
        status_layout.addWidget(self.status_icon)
        
        # Tekst statusu
        self.status_label = QLabel("Gotowy")
        self.status_label.setStyleSheet("color: #2d5016; font-weight: bold;")
        status_layout.addWidget(self.status_label)
        
        # Separator
        separator1 = QLabel("|")
        separator1.setStyleSheet("color: #999999;")
        status_layout.addWidget(separator1)
        
        # Licznik aktywnych API
        self.api_counter_icon = QLabel()
        api_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.api_counter_icon.setPixmap(api_icon.pixmap(14, 14))
        status_layout.addWidget(self.api_counter_icon)
        
        self.api_counter_label = QLabel("API: 0/4")
        self.api_counter_label.setStyleSheet("color: #666666; font-size: 9pt;")
        status_layout.addWidget(self.api_counter_label)
        
        # Separator
        separator2 = QLabel("|")
        separator2.setStyleSheet("color: #999999;")
        status_layout.addWidget(separator2)
        
        # Informacja o sesji
        self.session_icon = QLabel()
        session_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self.session_icon.setPixmap(session_icon.pixmap(14, 14))
        status_layout.addWidget(self.session_icon)
        
        self.session_label = QLabel("Sesja: 0")
        self.session_label.setStyleSheet("color: #666666; font-size: 9pt;")
        status_layout.addWidget(self.session_label)
        
        status_layout.addStretch(1)  # Rozciągnij do prawej
        
        # Dodaj główny widget do paska statusu
        self.statusBar.addWidget(self.status_widget, 1)
        
        # Pasek postępu (po prawej stronie)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #999999;
                border-radius: 3px;
                background-color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4a90e2, stop:1 #357abd);
                border-radius: 2px;
            }
        """)
        self.statusBar.addPermanentWidget(self.progress_bar)
        
        # Informacja o wersji (po prawej)
        version_label = QLabel("v2.0")
        version_label.setStyleSheet("color: #999999; font-size: 8pt; margin-right: 5px;")
        self.statusBar.addPermanentWidget(version_label)

    def _update_status(self, message, status_type="info"):
        """Aktualizuje status na pasku statusu z ikoną."""
        try:
            # Sprawdź czy aplikacja nie jest zamykana
            if hasattr(self, '_is_closing') and self._is_closing:
                return
                
            logger.info(f"STATUS GUI: {message}") # Używamy loggera
            
            if hasattr(self, 'status_label') and self.status_label:
                self.status_label.setText(message)
                
                # Ustaw ikonę i kolor w zależności od typu statusu
                if status_type == "ready":
                    icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
                    self.status_label.setStyleSheet("color: #2d5016; font-weight: bold;")
                elif status_type == "processing":
                    icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
                    self.status_label.setStyleSheet("color: #1a5490; font-weight: bold;")
                elif status_type == "error":
                    icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
                    self.status_label.setStyleSheet("color: #c62d42; font-weight: bold;")
                elif status_type == "warning":
                    icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning)
                    self.status_label.setStyleSheet("color: #f39c12; font-weight: bold;")
                else:  # info
                    icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
                    self.status_label.setStyleSheet("color: #34495e; font-weight: bold;")
                    
                if hasattr(self, 'status_icon') and self.status_icon:
                    self.status_icon.setPixmap(icon.pixmap(16, 16))
            
            # Fallback do starego systemu
            if hasattr(self, 'statusBar') and self.statusBar:
                self.statusBar.showMessage("", 1)  # Wyczyść stary komunikat
        except Exception as e:
            logger.error(f"Błąd w _update_status: {e}", exc_info=True)
    
    def _update_api_counter(self, active_count, total_count):
        """Aktualizuje licznik aktywnych API."""
        try:
            # Sprawdź czy aplikacja nie jest zamykana
            if hasattr(self, '_is_closing') and self._is_closing:
                return
                
            if hasattr(self, 'api_counter_label') and self.api_counter_label:
                self.api_counter_label.setText(f"API: {active_count}/{total_count}")
                if active_count > 0:
                    self.api_counter_label.setStyleSheet("color: #1a5490; font-size: 9pt; font-weight: bold;")
                else:
                    self.api_counter_label.setStyleSheet("color: #666666; font-size: 9pt;")
        except Exception as e:
            logger.error(f"Błąd w _update_api_counter: {e}", exc_info=True)
    
    def _update_session_info(self, session_id):
        """Aktualizuje informację o sesji."""
        try:
            # Sprawdź czy aplikacja nie jest zamykana
            if hasattr(self, '_is_closing') and self._is_closing:
                return
                
            if hasattr(self, 'session_label') and self.session_label:
                self.session_label.setText(f"Sesja: {session_id}")
                if session_id > 0:
                    self.session_label.setStyleSheet("color: #27ae60; font-size: 9pt; font-weight: bold;")
                else:
                    self.session_label.setStyleSheet("color: #666666; font-size: 9pt;")
        except Exception as e:
            logger.error(f"Błąd w _update_session_info: {e}", exc_info=True)

    def _create_toolbar(self):
        toolbar_group = QGroupBox("Opcje")
        # Usunięto indywidualny stylesheet, polegamy na globalnym
        toolbar_layout = QHBoxLayout()

        style_label = QLabel("Styl poprawy:")
        style_label.setFont(QFont("Segoe UI", 10))
        toolbar_layout.addWidget(style_label)

        self.style_combo = QComboBox()
        self.style_combo.setFont(QFont("Segoe UI", 10))
        self.style_combo.addItems(["Normalny", "Profesjonalny", "Angielski", "Polski", "Zmiana sensu", "Podsumowanie", "Prompt AI"])
        self.style_combo.setToolTip("Wybierz styl poprawy tekstu")
        self.style_combo.currentTextChanged.connect(self._style_changed)
        toolbar_layout.addWidget(self.style_combo)

        self.refresh_button = QPushButton("Popraw tekst ze schowka")
        self.refresh_button.setFont(QFont("Segoe UI", 10))
        self.refresh_button.setToolTip("Kopiuje tekst ze schowka i rozpoczyna poprawianie")
        # Dodajemy ikonę do przycisku odświeżania
        refresh_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self.refresh_button.setIcon(refresh_icon)
        self.refresh_button.clicked.connect(lambda: self._start_api_requests(text_source="clipboard"))
        toolbar_layout.addWidget(self.refresh_button)

        self.settings_button = QPushButton("Ustawienia")
        self.settings_button.setFont(QFont("Segoe UI", 10))
        # Dodajemy ikonę do przycisku ustawień
        settings_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.settings_button.setIcon(settings_icon)
        self.settings_button.clicked.connect(self.open_settings)
        toolbar_layout.addWidget(self.settings_button)

        self.show_original_button = QPushButton("Oryginalny tekst")
        self.show_original_button.setFont(QFont("Segoe UI", 10))
        self.show_original_button.setToolTip("Pokaż cały oryginalny tekst w osobnym oknie")
        # Dodajemy ikonę do przycisku oryginalnego tekstu
        original_text_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.show_original_button.setIcon(original_text_icon)
        self.show_original_button.clicked.connect(self.show_original_text_dialog)
        toolbar_layout.addWidget(self.show_original_button)

        # Dodajemy przycisk do wymuszenia dostosowania rozmiaru
        self.adjust_size_button = QPushButton("Dostosuj rozmiar okna")
        self.adjust_size_button.setFont(QFont("Segoe UI", 10))
        self.adjust_size_button.setToolTip("Dostosuj rozmiar okna do aktualnego ekranu")
        # Można użyć innej ikony, np. QStyle.StandardPixmap.SP_DesktopIcon
        adjust_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon) # Zmieniono ikonę na SP_DesktopIcon
        self.adjust_size_button.setIcon(adjust_icon)
        self.adjust_size_button.clicked.connect(self.adjust_window_size)
        toolbar_layout.addWidget(self.adjust_size_button)

        toolbar_layout.addStretch(1) # Dodaje rozciągliwą przestrzeń na końcu
        toolbar_group.setLayout(toolbar_layout)
        toolbar_group.setFixedHeight(85) # Slightly taller toolbar
        self.main_layout.addWidget(toolbar_group)

    def _create_api_panels(self):
        api_panel_container_widget = QWidget()
        self.api_grid_layout = QGridLayout(api_panel_container_widget)
        self.api_grid_layout.setSpacing(15)
        self.api_grid_layout.setContentsMargins(5, 10, 5, 5)

        self.api_edits = []
        self.api_status_labels = []
        self.api_select_buttons = []
        self.api_movies = {}  # Słownik do przechowywania QMovie dla każdego API
        self.api_loader_widgets = [] # Lista do przechowywania QLabel z animacją GIF dla każdego API
        self.api_text_edit_stacks = [] # Lista do przechowywania QStackedWidget dla każdego API

        for i, (name, model, panel_bg_hex, title_text_hex) in enumerate(self.api_providers_config):
            group_box = QGroupBox(f"{name} ({model})")
            group_box.setStyleSheet(f"""
                QGroupBox {{ background-color: {panel_bg_hex}; }}
                QGroupBox::title {{ color: {title_text_hex}; }}
            """)
            
            panel_layout = QVBoxLayout()
            panel_layout.setContentsMargins(6, 6, 6, 6) 
            panel_layout.setSpacing(6)

            # Nagłówek panelu z etykietą statusu i przyciskiem anuluj w układzie poziomym
            header_layout = QHBoxLayout()
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(10)

            status_label = QLabel("Status: Oczekiwanie...")
            status_label.setObjectName("StatusLabel")
            status_label.setWordWrap(True)
            self.api_status_labels.append(status_label)
            header_layout.addWidget(status_label)

            # Przycisk Anuluj (ikona) dla pojedynczego API
            cancel_single_button_icon = QPushButton("") # Pusty tekst, tylko ikona
            cancel_single_button_icon.setFixedSize(24, 24) # Mały, stały rozmiar
            cancel_single_button_icon.setToolTip(f"Anuluj żądanie do {name}")
            # Używamy ikony anulowania dialogu
            cancel_single_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton) # Ikona anulowania dialogu
            cancel_single_button_icon.setIcon(cancel_single_icon)
            cancel_single_button_icon.setStyleSheet("QPushButton { background-color: transparent; border: none; }") # Płaski styl bez tła/ramki
            cancel_single_button_icon.setFlat(True)
            cancel_single_button_icon.setEnabled(False) # Domyślnie wyłączony
            # Przechowujemy przyciski anulowania pojedynczego API (teraz ikonki)
            if not hasattr(self, 'api_cancel_single_buttons'):
                 self.api_cancel_single_buttons = []
            self.api_cancel_single_buttons.append(cancel_single_button_icon)

            header_layout.addWidget(cancel_single_button_icon, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            panel_layout.addLayout(header_layout) # Dodaj nagłówek do panelu

            # QStackedWidget dla QTextEdit i animacji GIF
            text_edit_stack = QStackedWidget()
            text_edit_stack.setMinimumHeight(80) # Nieco mniejsza minimalna wysokość
            
            # QTextEdit (pierwszy widget w stacku)
            text_edit = QTextEdit()
            text_edit.setPlaceholderText(f"Wynik z {name} pojawi się tutaj...")
            text_edit.setMinimumHeight(80) # Dopasowane do stacka
            text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.api_edits.append(text_edit)
            text_edit_stack.addWidget(text_edit)

            # QLabel dla animacji GIF (drugi widget w stacku)
            loader_label_for_stack = QLabel()
            loader_label_for_stack.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Ustawienie stylu, aby tło i ramka pasowały do QTextEdit
            loader_label_for_stack.setStyleSheet("""
                background-color: #f3f3f3;  /* delikatnie szare */
                border: 1px solid #bababa; 
                border-radius: 4px;
            """)
            # Używamy paths.py do ścieżki GIFa
            gif_path = os.path.join(get_assets_dir_path(), "loader.gif")
            if os.path.exists(gif_path):
                movie = QMovie(gif_path)
                #movie.setScaledSize(QSize(96, 96))  # Ustaw rozmiar animacji
                loader_label_for_stack.setMovie(movie)
                self.api_movies[i] = movie 
            else:
                print(f"BŁĄD: Nie znaleziono pliku animacji: {gif_path}")
                loader_label_for_stack.setText("(loader.gif not found)")
            
            text_edit_stack.addWidget(loader_label_for_stack)
            self.api_loader_widgets.append(loader_label_for_stack) # Przechowujemy QLabel z GIFem
            
            self.api_text_edit_stacks.append(text_edit_stack) # Przechowujemy QStackedWidget
            panel_layout.addWidget(text_edit_stack) # Dodajemy QStackedWidget do panelu

            # Przyciski akcji (Wybierz) w układzie poziomym - usunięto Anuluj stąd
            action_buttons_layout = QHBoxLayout()
            action_buttons_layout.setContentsMargins(0, 0, 0, 0)
            action_buttons_layout.setSpacing(10)

            # Przycisk wyboru (pozostaje pod QStackedWidget)
            select_button = QPushButton(f"Wybierz i wklej ({name})")
            select_button.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            select_button.setEnabled(False)
            select_button.clicked.connect(lambda checked, idx=i: self._select_api_and_copy(idx))
            self.api_select_buttons.append(select_button)

            action_buttons_layout.addWidget(select_button)

            panel_layout.addLayout(action_buttons_layout) # Dodaj układ przycisków do panelu

            group_box.setLayout(panel_layout)
            self.api_grid_layout.addWidget(group_box, i // 2, i % 2)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(api_panel_container_widget)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded) 
        self.main_layout.addWidget(scroll_area)

    def _update_gui_after_settings_change(self):
        """Aktualizuje GUI, np. tytuły paneli, po zmianie ustawień."""
        # Odświeżenie konfiguracji, którą przechowuje MainWindow
        self.api_keys, self.current_models, self.settings, _ = config_manager.load_config()

        # Aktualizacja tytułów paneli API
        # Zakładamy, że self.api_grid_layout i groupboxy w nim istnieją
        # i są w tej samej kolejności co api_providers_config
        
        # Kolejność musi odpowiadać tej w _create_api_panels
        provider_names_ordered = ["OpenAI", "Anthropic", "Google Gemini", "DeepSeek"]

        for i in range(self.api_grid_layout.count()):
            widget = self.api_grid_layout.itemAt(i).widget()
            if isinstance(widget, QGroupBox):
                # Ustal, który to dostawca na podstawie kolejności lub przechowywanej nazwy
                # Tutaj uproszczenie - na podstawie kolejności i provider_names_ordered
                if i < len(provider_names_ordered):
                    provider_key_for_model = provider_names_ordered[i].split(" ")[0] # "OpenAI", "Anthropic", "Google", "DeepSeek"
                    # Dla "Google Gemini" potrzebujemy klucza "Gemini" w self.current_models
                    if provider_key_for_model == "Google":
                        provider_key_for_model = "Gemini"
                    
                    current_model_name = self.current_models.get(provider_key_for_model, "Nieznany model")
                    original_title_prefix = provider_names_ordered[i] # np. "OpenAI", "Google Gemini"
                    widget.setTitle(f"{original_title_prefix} ({current_model_name})")

        print("GUI zaktualizowane po zmianie ustawień (modele).")


    def open_settings(self):
        # Załaduj bieżącą konfigurację przed otwarciem dialogu
        # To zapewnia, że dialog zawsze startuje z najświeższymi danymi z pliku
        try:
            current_keys, current_models_conf, current_settings, _ = config_manager.load_config()
        except Exception as e:
            logger.error(f"Błąd ładowania konfiguracji przed otwarciem ustawień: {e}", exc_info=True)
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Błąd")
            msg.setText("Nie można załadować konfiguracji.")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.show()
            return # Nie otwieraj okna, jeśli nie można załadować configu
            
        dialog = SettingsDialog(current_keys, current_models_conf, self)
        if dialog.exec(): # exec() jest blokujące i zwraca True jeśli zaakceptowano (OK)
            logger.info("Ustawienia zaakceptowane i zapisane przez SettingsDialog.")
            self._update_gui_after_settings_change()
        else:
            logger.info("Okno ustawień anulowane.")

    def _style_changed(self):
        style_map = {
            "Normalny": "normal",
            "Profesjonalny": "professional",
            "Angielski": "translate_en",
            "Polski": "translate_pl",
            "Zmiana sensu": "change_meaning",
            "Podsumowanie": "summary",
            "Prompt AI": "prompt"
        }
        selected_display_style = self.style_combo.currentText()
        self.s_current_style = style_map.get(selected_display_style, "normal")
        print(f"Zmieniono styl na: {self.s_current_style} (Wyświetlany: {selected_display_style})")
        # ZAWSZE rozpocznij nowe przetwarzanie po zmianie stylu
        # Anuluj poprzednie i rozpocznij nowe
        logger.info("Rozpoczynam nowe przetwarzanie po zmianie stylu...")
        if self.s_original_text_content:
            self._start_api_requests(text_source="clipboard_content_already_fetched")
        else:
            # Jeśli brak tekstu bazowego, pobierz ze schowka
            self._start_api_requests(text_source="clipboard")

    def _copy_text_to_clipboard(self, text):
        if text:
            clipboard_manager.set_text(text)
            logger.info(f"Tekst skopiowany do schowka (przez manager): {text[:50]}...") # Używamy loggera
            self._update_status("Tekst skopiowany. Ukrywanie okna i próba wklejenia...")

            # Ukryj okno przed próbą wklejenia
            self.hide()
            QTimer.singleShot(150, lambda: self._paste_after_hide())
        else:
            logger.warning("Brak tekstu do skopiowania (funkcja _copy_text_to_clipboard).") # Używamy loggera
            self._update_status("Brak tekstu do skopiowania.")

    def _paste_after_hide(self):
        try:
            logger.info("Symulowanie Ctrl+V...")
            keyboard.press('ctrl')
            keyboard.press('v')
            keyboard.release('v')
            keyboard.release('ctrl')
            self._update_status("Tekst wklejony (Ctrl+V), okno ukryte.")
        except Exception as e:
            logger.error(f"Błąd podczas symulowania Ctrl+V: {e}", exc_info=True)
            self._update_status(f"Tekst skopiowany, błąd podczas Ctrl+V: {e}, okno ukryte.")

    def _select_api_and_copy(self, api_index):
        if 0 <= api_index < len(self.api_edits):
            text_to_copy = self.api_edits[api_index].toPlainText()
            self._copy_text_to_clipboard(text_to_copy)

    def _get_selected_text_from_clipboard(self):
        """Pobiera tekst ze schowka (używając clipboard_manager)."""
        text = clipboard_manager.get_text()
        if not text:
            logger.info("Schowek jest pusty podczas próby pobrania tekstu.") # Używamy loggera
            # Można by wyświetlić QMessageBox z informacją
            return None # lub self.s_original_text_content jako fallback
        # logger.debug(f"Pobrano ze schowka (przez manager): {text[:100]}...") # Linia debugująca
        return text

    def _get_instruction(self, style_key):
        return prompts.instructions.get(style_key, prompts.instructions["normal"])

    def _get_system_prompt(self):
        return prompts.system_prompt

    def _reset_api_states(self, processing_message="Przetwarzanie..."):
        """Resetuje stan kontrolek API przed nowym zapytaniem."""
        logger.info(f"GUI: Resetowanie stanów API. Wiadomość: '{processing_message}'") # Używamy loggera
        self.is_processing = True
        if hasattr(self, 'refresh_button'): # Sprawdzenie, czy przycisk istnieje
            self.refresh_button.setEnabled(False)
            self.refresh_button.setToolTip("Przetwarzanie w toku...")

        if hasattr(self, 'progress_bar'): # Sprawdzenie, czy progress_bar istnieje
            self.progress_bar.setVisible(True)

        for i, status_label in enumerate(self.api_status_labels):
            status_label.setText(processing_message) 
            self.api_edits[i].setPlainText("") # Czyścimy QTextEdit (nawet jeśli jest ukryty)
            self.api_edits[i].setPlaceholderText(f"Przetwarzanie dla {self.api_grid_layout.itemAt(i).widget().title().split('(')[0].strip()}...")
            self.api_select_buttons[i].setEnabled(False)
            self.api_select_buttons[i].setToolTip("Oczekiwanie na wynik API...")
            status_label.setToolTip("")

            # Przełączenie na QLabel z animacją i uruchomienie jej
            if i < len(self.api_text_edit_stacks) and i in self.api_movies:
                # Upewnij się, że loader_widget (QLabel z GIFem) istnieje dla tego indeksu
                if i < len(self.api_loader_widgets):
                    self.api_text_edit_stacks[i].setCurrentWidget(self.api_loader_widgets[i])
                    self.api_movies[i].start()
                else:
                    print(f"DEBUG: Brak api_loader_widgets[{i}] w _reset_api_states") 
            else:
                print(f"DEBUG: Brak QStackedWidget lub QMovie dla API index {i} w _reset_api_states")

        self._update_status(f"Rozpoczęto przetwarzanie: {self.s_original_text_content[:30]}...")

    def _start_api_requests(self, text_source="clipboard"):
        """
        Starts API requests for all configured providers in separate threads.
        Fetches text from clipboard unless text_source is "clipboard_content_already_fetched",
        in which case it uses self.s_original_text_content.
        """
        # USUŃ BLOKADĘ - pozwól na nowe zapytania nawet gdy inne trwają
        # if self.is_processing:
        #     logger.warning("Przetwarzanie już trwa, nowa prośba zignorowana.") # Logujemy ostrzeżenie
        #     self._update_status("Przetwarzanie już trwa.")
        #     return
        
        # Anuluj wszystkie poprzednie zapytania przed rozpoczęciem nowych
        if self.is_processing:
            logger.info("Anulowanie poprzednich zapytań przed rozpoczęciem nowych...")
            # Najpierw ustaw flagę anulowania w każdym wątku
            for api_index, worker in self.api_threads.items():
                if worker.isRunning():
                    logger.debug(f"Anulowanie wątku API ({api_index}) przed nowym zapytaniem.")
                    worker.cancel()
            
            # Wyczyść stare wątki - to KLUCZOWE!
            self.api_threads.clear()
            
            # Krótka pauza na anulowanie
            import time
            time.sleep(0.1)

        logger.info(f"Rozpoczynam przetwarzanie tekstu. Źródło: {text_source}") # Logujemy początek przetwarzania
        self._update_status("Rozpoczęto przetwarzanie...", "processing")

        # Resetowanie stanów GUI i flagi przetwarzania
        self.is_processing = True
        self._reset_api_states() # Resetuje GUI i aktywuje animacje ładowania

        text_to_process = ""
        if text_source == "clipboard":
            try:
                text_to_process = clipboard_manager.get_text()
                self.s_original_text_content = text_to_process # Zapisz oryginalny tekst ze schowka
                logger.info(f"Pobrano tekst ze schowka ({len(text_to_process)} znaków).") # Logujemy pobranie tekstu
            except Exception as e:
                error_message = f"Błąd podczas pobierania tekstu ze schowka: {e}"
                logger.error(error_message, exc_info=True) # Logujemy błąd z tracebackiem
                self._update_status(error_message, "error")
                self.is_processing = False # Resetujemy flagę
                self._reset_api_states(processing_message="Błąd pobierania schowka.") # Resetujemy GUI ze statusem błędu
                return # Przerywamy przetwarzanie

            if not text_to_process.strip():
                logger.info("Schowek jest pusty lub zawiera tylko białe znaki.") # Logujemy pusty schowek
                self._update_status("Schowek jest pusty. Brak tekstu do poprawy.", "warning")
                self.is_processing = False # Resetujemy flagę
                self._reset_api_states(processing_message="Brak tekstu do poprawy.") # Resetujemy GUI ze statusem błędu
                return # Przerywamy przetwarzanie

        elif text_source == "clipboard_content_already_fetched":
            text_to_process = self.s_original_text_content
            logger.info(f"Używam zapisanego tekstu schowka ({len(text_to_process)} znaków).") # Logujemy użycie zapisanego tekstu
            if not text_to_process.strip():
                 logger.warning("Używam zapisanego tekstu schowka, ale jest on pusty lub zawiera tylko białe znaki.")
                 self._update_status("Zapisany tekst schowka jest pusty.")
                 self.is_processing = False
                 self._reset_api_states(processing_message="Brak tekstu do poprawy.")
                 return

        else:
            # Nieznane źródło tekstu
            error_message = f"Nieznane źródło tekstu: {text_source}"
            logger.error(error_message)
            self._update_status(error_message)
            self.is_processing = False
            self._reset_api_states(processing_message="Wewnętrzny błąd źródła tekstu.")
            return


        self._update_status("Przetwarzam tekst...", "processing") # Aktualizujemy status po pobraniu tekstu

        # Ładujemy najnowsze klucze i modele przed każdym zapytaniem
        # aby uwzględnić zmiany dokonane w oknie ustawień bez restartu aplikacji
        try:
            self.api_keys, self.current_models, self.settings, _ = config_manager.load_config()
            logger.debug("Przeładowano konfigurację API przed rozpoczęciem zapytań.")
        except Exception as e:
            error_message = f"Błąd podczas przeładowania konfiguracji API: {e}"
            logger.error(error_message, exc_info=True)
            self._update_status(error_message)
            self.is_processing = False
            self._reset_api_states(processing_message="Błąd ładowania configu.")
            return # Przerywamy przetwarzanie jeśli nie można załadować configu

        # Włącz przycisk Anuluj w pasku narzędzi
        if hasattr(self, 'cancel_button'):
            self.cancel_button.setEnabled(True)
            self.cancel_button.setToolTip("Anuluj obecne żądania do API")

        selected_style = self.s_current_style
        system_prompt = self._get_system_prompt() # Pobierz globalny system prompt

        # Mapa indeksów API do funkcji klienckich i kluczy z configu
        api_dispatch = {
            API_OPENAI: (correct_text_openai, self.api_keys.get("OpenAI", "")),
            API_ANTHROPIC: (correct_text_anthropic, self.api_keys.get("Anthropic", "")),
            API_GEMINI: (correct_text_gemini, self.api_keys.get("Gemini", "")),
            API_DEEPSEEK: (correct_text_deepseek, self.api_keys.get("DeepSeek", ""))
        }

        # Zwiększ ID sesji dla nowej sesji zapytań
        self.current_session_id += 1
        logger.info(f"Rozpoczynam nową sesję zapytań ID: {self.current_session_id}")
        self._update_session_info(self.current_session_id)
        
        self.api_threads = {} # Resetujemy słownik wątków

        try:
            for i, (name, model_key, _, _) in enumerate(self.api_providers_config):
                api_index = self.api_clients_enum.get(name.replace("Google Gemini", "GEMINI").upper()) # Mapujemy nazwę na ENUM
                if api_index is None:
                    logger.warning(f"Nie znaleziono indeksu ENUM dla dostawcy API: {name}. Pomijam.")
                    continue

                api_function, api_key = api_dispatch.get(api_index, (None, None))
                model_name = model_key # Użyj bezpośrednio drugiego elementu tuple, który jest nazwą modelu

                if not api_function:
                     logger.warning(f"Brak funkcji API dla indeksu {api_index} ({name}). Pomijam.")
                     continue

                # Sprawdzamy, czy klucz API jest wymagany i czy jest dostępny
                # Dla OpenAI, Anthropic, Gemini i DeepSeek klucz jest wymagany
                if not api_key and api_index in [API_OPENAI, API_ANTHROPIC, API_GEMINI, API_DEEPSEEK]:
                    result_text = f"Błąd: Brak klucza API dla {name}."
                    logger.warning(result_text)
                    # Od razu aktualizujemy GUI o błąd braku klucza, bez uruchamiania wątku
                    self._update_api_result(i, result_text, True, self.current_session_id)
                    continue # Pomijamy uruchomienie wątku dla tego API

                worker = ApiWorker(i, api_function, api_key, model_name, text_to_process, selected_style, system_prompt, self.current_session_id)
                worker.finished_signal.connect(self._update_api_result)
                worker.cancelled_signal.connect(self._handle_api_cancelled)
                # Podłącz sygnał clicked przycisku anulowania do slotu _cancel_single_api_request
                if 0 <= i < len(self.api_cancel_single_buttons):
                    self.api_cancel_single_buttons[i].clicked.connect(lambda checked, idx=i: self._cancel_single_api_request(idx))
                    self.api_cancel_single_buttons[i].setEnabled(True) # Włącz przycisk anulowania dla tego API
                    self.api_cancel_single_buttons[i].setToolTip(f"Anuluj żądanie do {name}")
                else:
                    logger.warning(f"Brak przycisku anulowania dla API o indeksie {i}.")

                worker.start()
                self.api_threads[i] = worker # Przechowujemy referencję do wątku
                logger.debug(f"Uruchomiono wątek API dla {name} (indeks {i}).")

            logger.info("Wszystkie aktywne wątki API uruchomione.") # Logujemy zakończenie uruchamiania wątków
            # Aktualizuj licznik API
            self._update_api_counter(len(self.api_threads), len(self.api_providers_config))

        except Exception as e:
            # Ogólny wyjątek podczas tworzenia/uruchamiania wątków
            error_message = f"Krytyczny błąd podczas uruchamiania wątków API: {e}"
            logger.error(error_message, exc_info=True)
            self._update_status(error_message)
            self.is_processing = False
            self._reset_api_states(processing_message="Krytyczny błąd.")

        # is_processing zostanie ustawione na False w _update_api_result
        # gdy wszystkie wątki zakończą działanie (sprawdzane w tej metodzie)

    def _update_api_result(self, api_index, result_text, is_error, session_id):
        """Slot do odbierania wyników z wątków ApiWorker."""
        try:
            # BEZPIECZEŃSTWO: Sprawdź czy aplikacja nie jest zamykana
            if hasattr(self, '_is_closing') and self._is_closing:
                logger.info(f"Ignoruję wynik API {api_index} - aplikacja jest zamykana.")
                return
            
            # Sprawdź czy okno główne nadal istnieje
            if not self or self.isHidden():
                logger.info(f"Ignoruję wynik API {api_index} - okno główne nie istnieje lub jest ukryte.")
                return
                
            # KLUCZOWA POPRAWKA: Sprawdź czy wynik jest z aktualnej sesji
            if session_id != self.current_session_id:
                logger.info(f"Ignoruję wynik ze starej sesji {session_id} (aktualna: {self.current_session_id}) dla API {api_index}")
                return  # IGNORUJ wyniki ze starych sesji!
                
            api_name = self.api_providers_config[api_index][0]
            logger.info(f"Otrzymano wynik dla API {api_name} (indeks {api_index}). Błąd: {is_error}") # Logujemy otrzymanie wyniku

            # Zatrzymanie animacji QMovie i przełączenie QStackedWidget na QTextEdit
            if api_index in self.api_movies:
                self.api_movies[api_index].stop()
                # self.api_loader_labels[api_index].setVisible(False) # ZASTĄPIONE
                if api_index < len(self.api_text_edit_stacks):
                    self.api_text_edit_stacks[api_index].setCurrentIndex(0) # Przełącz na QTextEdit

            # Aktualizacja pola tekstowego wynikiem
            if 0 <= api_index < len(self.api_edits):
                self.api_edits[api_index].setText(result_text)

            # Aktualizacja statusu i przycisku
            if 0 <= api_index < len(self.api_status_labels):
                if is_error:
                    self.api_status_labels[api_index].setText(f"Status: Błąd - {result_text}")
                    self.api_status_labels[api_index].setStyleSheet("color: #e74c3c; font-style: normal;") # Ciemniejszy czerwony
                    logger.error(f"Błąd API {api_name}: {result_text}") # Logujemy błąd otrzymany z wątku
                    if api_index < len(self.api_select_buttons):
                        self.api_select_buttons[api_index].setEnabled(False) # Wyłącz przycisk wyboru
                else:
                    self.api_status_labels[api_index].setText("Status: Gotowy")
                    self.api_status_labels[api_index].setStyleSheet("color: #28a745; font-style: normal;") # Zielony
                    logger.info(f"API {api_name} zakończyło sukcesem.") # Logujemy sukces
                    if api_index < len(self.api_select_buttons):
                        self.api_select_buttons[api_index].setEnabled(True) # Włącz przycisk wyboru

            # Wyłącz przycisk anulowania pojedynczego API, gdy wątek zakończył działanie
            if 0 <= api_index < len(self.api_cancel_single_buttons):
                self.api_cancel_single_buttons[api_index].setEnabled(False)

            # KLUCZOWA POPRAWKA: Sprawdź, czy wątek nie został anulowany
            # Jeśli tak - IGNORUJ całkowicie wynik i nie aktualizuj GUI
            worker = self.api_threads.get(api_index)
            if worker and hasattr(worker, '_is_cancelled') and worker._is_cancelled:
                logger.info(f"Wątek API ({api_index}) zakończył działanie po anulowaniu. IGNORUJĘ całkowicie wynik.")
                # NIE aktualizuj pola tekstowego ani statusu - _handle_api_cancelled już to zrobiło
                # Jedyne co robimy to wyłączenie przycisku anulowania (już zrobione powyżej)
                return  # WYJDŹ Z FUNKCJI - nie rób nic więcej!

            # Sprawdzenie, czy wszystkie wątki zakończyły działanie
            all_finished = True
            finished_count = 0
            # Liczba wątków, które _zostały_ uruchomione
            total_expected_started = len(self.api_threads)

            # Iterujemy po wątkach, które faktycznie uruchomiliśmy w self.api_threads
            active_thread_indices = list(self.api_threads.keys())
            logger.debug(f"Sprawdzam status wątków. Aktywne indeksy: {active_thread_indices}.)")

            for idx in active_thread_indices:
                 worker = self.api_threads.get(idx)
                 if worker:
                     # Wątek zakończył działanie, jeśli nie jest uruchomiony.
                     # Traktujemy wątek jako 'zakończony' dla potrzeb licznika, jeśli nie isRunning().
                     # Status (sukces/błąd/anulowano) jest ustawiany przez sloty finished_signal lub cancelled_signal.
                     if worker.isRunning():
                         all_finished = False
                         logger.debug(f"Wątek dla API {self.api_providers_config[idx][0]} (indeks {idx}) nadal działa.")
                         break # Wystarczy jeden działający, żeby nie było all_finished
                     else:
                          # Wątek nie działa, ale mógł zakończyć się sukcesem lub błędem.
                          # Liczymy go jako zakończony.
                          finished_count += 1
                          logger.debug(f"Wątek dla API {self.api_providers_config[idx][0]} (indeks {idx}) zakończony.")
                 else:
                     logger.warning(f"Wątek dla indeksu {idx} nie znaleziony w self.api_threads. Możliwy błąd logiki.")
                     # Potraktuj brakujący wątek jako błąd, który uniemożliwia poprawne zakończenie
                     all_finished = False
                     break


            # Upewnij się, że sprawdzasz, czy liczba zakończonych wątków odpowiada liczbie uruchomionych.
            # To jest bardziej niezawodne niż isRunning()
            logger.debug(f"Zakończono {finished_count} z {total_expected_started} oczekiwanych wątków.")

            # Sprawdzenie, czy liczba zakończonych wątków odpowiada liczbie uruchomionych.
            if finished_count >= total_expected_started:
                 all_finished = True
                 logger.info("Wszystkie oczekiwane wątki API zakończyły działanie.")
            else:
                 all_finished = False
                 logger.debug("Nie wszystkie wątki zakończyły działanie.")


            if all_finished:
                logger.info("Przetwarzanie zakończone dla wszystkich API.") # Logujemy zakończenie
                self.is_processing = False # Reset flagi przetwarzania
                self._update_status("Gotowy", "ready")
                self._update_api_counter(0, len(self.api_providers_config))  # Resetuj licznik
                if hasattr(self, 'refresh_button'):
                     self.refresh_button.setEnabled(True) # Włącz przycisk odświeżania
                if hasattr(self, 'cancel_button'):
                    self.cancel_button.setEnabled(False) # Wyłącz przycisk Anuluj w pasku narzędzi
                if hasattr(self, 'progress_bar'):
                     self.progress_bar.setVisible(False) # Ukryj pasek postępu
                # Można by dodać tu jakieś podsumowanie lub dźwięk

        except Exception as e:
            logger.error(f"Błąd w _update_api_result dla API {api_index}: {e}", exc_info=True)
            # Nie przerywaj działania aplikacji z powodu błędu aktualizacji GUI

    def _handle_api_cancelled(self, api_index, session_id):
        """Slot do obsługi sygnału anulowania z wątku ApiWorker."""
        try:
            # BEZPIECZEŃSTWO: Sprawdź czy aplikacja nie jest zamykana
            if hasattr(self, '_is_closing') and self._is_closing:
                logger.info(f"Ignoruję anulowanie API {api_index} - aplikacja jest zamykana.")
                return
            
            # Sprawdź czy okno główne nadal istnieje
            if not self or self.isHidden():
                logger.info(f"Ignoruję anulowanie API {api_index} - okno główne nie istnieje lub jest ukryte.")
                return
                
            # Sprawdź czy anulowanie jest z aktualnej sesji
            if session_id != self.current_session_id:
                logger.info(f"Ignoruję anulowanie ze starej sesji {session_id} (aktualna: {self.current_session_id}) dla API {api_index}")
                return  # IGNORUJ anulowania ze starych sesji!
                
            api_name = self.api_providers_config[api_index][0]
            logger.info(f"Wątek API ({api_index}) ({api_name}) zgłosił anulowanie.")

            # Zatrzymaj animację i przełącz na pole tekstowe
            if api_index in self.api_movies:
                self.api_movies[api_index].stop()
                if api_index < len(self.api_text_edit_stacks):
                     self.api_text_edit_stacks[api_index].setCurrentIndex(0) # Przełącz na QTextEdit

            # Zaktualizuj status i pole tekstowe
            if 0 <= api_index < len(self.api_status_labels):
                self.api_status_labels[api_index].setText("Status: Anulowano")
                self.api_status_labels[api_index].setStyleSheet("color: #ff9800; font-style: normal;") # Pomarańczowy
                if api_index < len(self.api_edits):
                    self.api_edits[api_index].setPlainText("Żądanie anulowane przez użytkownika.")
                if api_index < len(self.api_select_buttons):
                    self.api_select_buttons[api_index].setEnabled(False) # Anulowane API nie można wybrać

            # Wyłącz przycisk anulowania pojedynczego API po anulowaniu
            if 0 <= api_index < len(self.api_cancel_single_buttons):
                self.api_cancel_single_buttons[api_index].setEnabled(False)

        except Exception as e:
            logger.error(f"Błąd w _handle_api_cancelled dla API {api_index}: {e}", exc_info=True)
            # Nie przerywaj działania aplikacji z powodu błędu anulowania

    def show_original_text_dialog(self):
        """Wyświetla dialog z oryginalnym tekstem."""
        if not self.s_original_text_content:
            logger.info("Próba wyświetlenia oryginalnego tekstu, ale s_original_text_content jest puste.") # Używamy loggera
            info_msg = QMessageBox(self)
            info_msg.setIcon(QMessageBox.Icon.Information)
            info_msg.setWindowTitle("Brak Tekstu")
            info_msg.setText("Brak oryginalnego tekstu do wyświetlenia.")
            info_msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            info_msg.show()
            return

        # Prosty dialog tylko do wyświetlania
        dialog = QDialog(self)
        dialog.setWindowTitle("Oryginalny Tekst")
        dialog.setMinimumSize(500, 350)
        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit(self.s_original_text_content)
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Segoe UI", 10))
        layout.addWidget(text_edit)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(dialog.reject) # Close to samo co reject dla tego dialogu
        layout.addWidget(button_box)
        
        dialog.show()

    # --- Monitorowanie schowka dla linków obrazków ---
    def _init_clipboard_monitoring(self):
        self.clipboard_timer = QTimer(self)
        self.clipboard_timer.timeout.connect(self._check_clipboard_for_image_link)
        self.clipboard_timer.start(700) # Sprawdzaj co 700 ms (częściej niż w AutoIt dla lepszej responsywności)

    def _check_clipboard_for_image_link(self):
        # logger.debug("SCHOWEK_DEBUG: Funkcja _check_clipboard_for_image_link została wywołana.") # Zakomentowano
        try:
            clipboard = QApplication.clipboard()
            if not clipboard:
                return
                
            raw_text_from_clipboard = clipboard.text() # Pobierz surowy tekst

            # Przetwarzany tekst (oczyszczony) będzie używany do porównania z poprzednim tekstem
            current_text_to_process = raw_text_from_clipboard.strip()

            # Sprawdź, czy tekst w schowku się zmienił
            if current_text_to_process == self.last_clipboard_text:
                return  # Tekst się nie zmienił, nie rób nic

            # Zaktualizuj ostatni tekst schowka
            self.last_clipboard_text = current_text_to_process

            # Sprawdź, czy to jest link do obrazka
            if re.match(r"^https?://.*\.(jpg|jpeg|png|gif|webp)$", current_text_to_process, re.IGNORECASE):
                # Sprawdź, czy to już nie jest markdown
                if not re.match(r"^\!\[.*\]\(.*\)$", current_text_to_process):
                    # Wyciągnij nazwę pliku z URL-a
                    file_name_match = re.search(r"/([^/]+)\.[^.]+$", current_text_to_process)
                    if file_name_match:
                        file_name_without_extension = file_name_match.group(1)
                        
                        # Stwórz format markdown z obsługą obrazka
                        markdown_text = f"![{file_name_without_extension}|600]({current_text_to_process} /raw =600x)"
                        
                        # Ustaw nowy tekst w schowku
                        clipboard.setText(markdown_text)
                        
                        # Pokaż notyfikację
                        if hasattr(self, 'tray_icon') and self.tray_icon:
                            self.tray_icon.showMessage(
                                "Link obrazka zamieniony",
                                f"Zamieniono na format markdown: {file_name_without_extension}",
                                QSystemTrayIcon.MessageIcon.Information,
                                3000
                            )

        except Exception as e:
            logger.error(f"Błąd podczas sprawdzania schowka dla linków obrazków: {e}")

    # Dodajemy QSystemTrayIcon (opcjonalnie, na razie tylko podstawy)
    # Będzie potrzebny import: from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
    # I ikona w assets
    def _create_tray_icon(self):
        # Ta funkcja powinna być wywołana w __init__
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
            # Używamy paths.py do ścieżki ikony
            icon_path = os.path.join(get_assets_dir_path(), "icon.ico")
            if os.path.exists(icon_path):
                self.tray_icon.setIcon(QIcon(icon_path))
                logger.debug(f"Załadowano ikonę zasobnika z: {icon_path}") # Dodano logowanie
            else:
                # Użyj domyślnej ikony, jeśli plik nie istnieje
                # Upewnij się, że QStyle jest zaimportowany
                self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
                logger.warning(f"Nie znaleziono ikony zasobnika pod ścieżką: {icon_path}. Użyto domyślnej.") # Dodano logowanie

            self.tray_icon.setToolTip("Poprawiacz Tekstu Multi-API")

            tray_menu = QMenu(self)
            
            # Stylizacja menu
            tray_menu.setStyleSheet("""
                QMenu {
                    background-color: #ffffff;
                    border: 1px solid #cccccc;
                    border-radius: 6px;
                    padding: 4px;
                    font-family: 'Segoe UI';
                    font-size: 9pt;
                }
                QMenu::item {
                    background-color: transparent;
                    padding: 6px 20px 6px 30px;
                    border-radius: 3px;
                    margin: 1px;
                }
                QMenu::item:selected {
                    background-color: #e3f2fd;
                    color: #1976d2;
                }
                QMenu::item:disabled {
                    color: #999999;
                }
                QMenu::separator {
                    height: 1px;
                    background-color: #e0e0e0;
                    margin: 4px 8px;
                }
                QMenu::icon {
                    width: 16px;
                    height: 16px;
                    left: 8px;
                }
            """)
            
            # Akcja pokazania okna
            show_action = QAction("🏠 Pokaż okno główne", self)
            show_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            show_action.setIcon(show_icon)
            show_action.triggered.connect(lambda: (self.showNormal(), self.activateWindow()))
            tray_menu.addAction(show_action)
            
            tray_menu.addSeparator()
            
            # Sekcja Operacje
            operations_title = QAction("📝 OPERACJE", self)
            operations_title.setEnabled(False)
            operations_title.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tray_menu.addAction(operations_title)
            
            # Akcja poprawy tekstu
            correct_action = QAction("✨ Popraw tekst ze schowka", self)
            correct_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
            correct_action.setIcon(correct_icon)
            correct_action.setToolTip("Hotkey: Ctrl+Shift+C")
            correct_action.triggered.connect(lambda: self._start_api_requests(text_source="clipboard"))
            tray_menu.addAction(correct_action)
            
            # Informacja o aktualnym stylu
            current_style = getattr(self, 'style_combo', None)
            if current_style:
                style_text = current_style.currentText()
                style_info = QAction(f"📋 Styl: {style_text}", self)
                style_info.setEnabled(False)
                style_info.setFont(QFont("Segoe UI", 8))
                tray_menu.addAction(style_info)
            
            tray_menu.addSeparator()
            
            # Sekcja Ustawienia
            settings_title = QAction("⚙️ USTAWIENIA", self)
            settings_title.setEnabled(False)
            settings_title.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tray_menu.addAction(settings_title)

            # Ustawienia aplikacji
            settings_action = QAction("🔧 Konfiguracja API", self)
            settings_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
            settings_action.setIcon(settings_icon)
            settings_action.triggered.connect(self.open_settings)
            tray_menu.addAction(settings_action)
            
            def toggle_autostart():
                if config_manager.is_in_startup():
                    if config_manager.remove_from_startup():
                        self.tray_icon.showMessage(
                            "Autostart", 
                            "Autostart został wyłączony", 
                            QSystemTrayIcon.MessageIcon.Information, 
                            2000
                        )
                    else:
                        self.tray_icon.showMessage(
                            "Błąd", 
                            "Nie udało się wyłączyć autostartu", 
                            QSystemTrayIcon.MessageIcon.Warning, 
                            2000
                        )
                else:
                    if config_manager.add_to_startup():
                        self.tray_icon.showMessage(
                            "Autostart", 
                            "Autostart został włączony", 
                            QSystemTrayIcon.MessageIcon.Information, 
                            2000
                        )
                    else:
                        self.tray_icon.showMessage(
                            "Błąd", 
                            "Nie udało się włączyć autostartu", 
                            QSystemTrayIcon.MessageIcon.Warning, 
                            2000
                        )
                # ZAWSZE odśwież tekst po zmianie
                refresh_autostart_text()

            # Funkcja do odświeżania tekstu autostart
            def refresh_autostart_text():
                if config_manager.is_in_startup():
                    autostart_action.setText("✅ Autostart systemu (WŁĄCZONY)")
                else:
                    autostart_action.setText("❌ Autostart systemu (WYŁĄCZONY)")

            autostart_action = QAction("", self)  # Tekst zostanie ustawiony przez refresh_autostart_text()
            autostart_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
            autostart_action.setIcon(autostart_icon)
            refresh_autostart_text()  # Ustaw początkowy tekst
            autostart_action.triggered.connect(toggle_autostart)
            tray_menu.addAction(autostart_action)
            
            tray_menu.addSeparator()
            
            # Sekcja System
            system_title = QAction("🔄 SYSTEM", self)
            system_title.setEnabled(False)
            system_title.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            tray_menu.addAction(system_title)
            
            # Restart aplikacji
            restart_action = QAction("🔄 Restart aplikacji", self)
            restart_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
            restart_action.setIcon(restart_icon)
            restart_action.triggered.connect(self._restart_application)
            tray_menu.addAction(restart_action)
            
            tray_menu.addSeparator()

            # Wyjście z aplikacji
            quit_action = QAction("❌ Zakończ aplikację", self)
            quit_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)
            quit_action.setIcon(quit_icon)
            quit_action.triggered.connect(self.quit_application)
            tray_menu.addAction(quit_action)
            
            tray_menu.addSeparator()
            
            # Informacja o wersji
            version_action = QAction("ℹ️ Poprawiacz Tekstu v2.0", self)
            version_action.setEnabled(False)
            version_action.setFont(QFont("Segoe UI", 8))
            tray_menu.addAction(version_action)

            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.show()

            # Dodatkowa obsługa kliknięcia na ikonę (np. pokaż/ukryj okno)
            self.tray_icon.activated.connect(self._tray_icon_activated)

            def refresh_menu_status():
                # Odśwież status autostartu
                refresh_autostart_text()
                
                # Zaktualizuj tekst akcji poprawy w zależności od stanu przetwarzania
                if hasattr(self, 'is_processing') and self.is_processing:
                    correct_action.setText("⏳ Przetwarzanie w toku...")
                    correct_action.setEnabled(False)
                else:
                    correct_action.setText("✨ Popraw tekst ze schowka")
                    correct_action.setEnabled(True)
                
                # Zaktualizuj informację o stylu
                if hasattr(self, 'style_combo') and self.style_combo:
                    current_style_text = self.style_combo.currentText()
                    style_info.setText(f"📋 Styl: {current_style_text}")

            tray_menu.aboutToShow.connect(refresh_menu_status)

        else:
            logger.warning("Zasobnik systemowy niedostępny. Ikona w zasobniku nie zostanie utworzona.") # Dodano logowanie
        # pass # Na razie pomijamy implementację tray icon dla uproszczenia -> Usunięto pass

    def _tray_icon_activated(self, reason):
        # Logujemy powód aktywacji ikony w zasobniku
        logger.debug(f"Ikona zasobnika aktywowana z powodu: {reason}")

        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
                if hasattr(self, 'clipboard_timer') and self.clipboard_timer:
                    self.clipboard_timer.stop()
            else:
                self.showNormal()
                if hasattr(self, 'clipboard_timer') and self.clipboard_timer:
                    self.clipboard_timer.start(700)
                self.activateWindow()

    # Ta metoda jest wywoływana z thread-safe hotkey manager (pynput)
    # Jej jedynym zadaniem jest bezpieczne wyemitowanie sygnału do wątku Qt.
    def handle_hotkey_event(self):
        logger.info("MainWindow: handle_hotkey_event wywołane (z hotkey manager), emitowanie sygnału...")
        self.hotkey_triggered_signal.emit()

    # Ten slot będzie wykonany w głównym wątku Qt po otrzymaniu sygnału
    def _process_hotkey_event_in_qt_thread(self):
        logger.info("MainWindow: _process_hotkey_event_in_qt_thread wywołane (wątek Qt).") # Używamy loggera

        # USUNIĘTO ograniczenie is_processing - teraz hotkey zawsze anuluje poprzednie i rozpoczyna nowe
        # if self.is_processing:
        #     logger.info("Już trwa przetwarzanie. Skrót pokazuje okno (jeśli ukryte) lub nic nie robi.") # Używamy loggera
        #     self._update_status("Już trwa przetwarzanie, proszę czekać...")
        #     if not self.isVisible() or self.isMinimized():
        #         self.showNormal()
        #         self.activateWindow()
        #         self.raise_()
        #     return # Zakończ, jeśli już przetwarza

        # Jeśli już trwa przetwarzanie, najpierw je anuluj
        if self.is_processing:
            logger.info("Hotkey: Anulowanie poprzedniego przetwarzania przed rozpoczęciem nowego...")
            self._cancel_api_requests()
        
        # Pobierz tekst ze schowka
        text_to_process_from_clipboard = self._get_selected_text_from_clipboard()

        if not text_to_process_from_clipboard:
            # Schowek pusty - pokaż tylko MessageBox
            logger.info("Schowek pusty. Pokazywanie QMessageBox z hotkeya.") # Używamy loggera
            self._update_status("Schowek jest pusty. Brak tekstu do przetworzenia.")
            
            # Tworzymy QMessageBox bez rodzica (parent=None)
            msg_box = QMessageBox(None) 
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setWindowTitle("Pusty schowek")
            msg_box.setText("Schowek nie zawiera tekstu do przetworzenia.")
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.setWindowModality(Qt.WindowModality.ApplicationModal) 
            
            # Ustawiamy flagę, aby okno było zawsze na wierzchu
            msg_box.setWindowFlags(msg_box.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            
            msg_box.activateWindow()
            msg_box.raise_()    
            msg_box.show()
            
        else:
            # Schowek zawiera tekst - pokaż okno (jeśli ukryte) i rozpocznij przetwarzanie
            if not self.isVisible() or self.isMinimized():
                logger.info("Okno było ukryte/zminimalizowane. Pokazywanie okna przed przetwarzaniem z hotkeya.") # Używamy loggera
                self.showNormal()
            
            self.activateWindow()
            self.raise_()

            logger.info("Rozpoczynanie przetwarzania tekstu (po sprawdzeniu schowka) po aktywacji skrótem.") # Używamy loggera
            # Użyj QTimer.singleShot, aby dać GUI chwilę na odświeżenie
            self.s_original_text_content = text_to_process_from_clipboard
            QTimer.singleShot(100, lambda: self._start_api_requests(text_source="clipboard_content_already_fetched"))  # Zwiększone na 100ms żeby dać czas na anulowanie

    def showEvent(self, event):
        super().showEvent(event)
        # Usunięto automatyczne wywołanie _style_changed() przy pierwszym pokazaniu
        # Przetwarzanie uruchamiaj tylko przez hotkey lub zmianę stylu
        if not getattr(self, '_style_changed_called', False):
            self._style_changed_called = True
            # NIE wywołuj _style_changed() automatycznie

    def _start_model_loading(self):
        self.loader_thread = ModelLoaderThread(self.model_loader)
        self.loader_thread.model_loaded.connect(self._update_model_status)
        self.loader_thread.loading_finished.connect(self._on_models_loaded)
        self.loader_thread.error_occurred.connect(self._on_model_loading_error)
        self.loader_thread.start()

    def _update_model_status(self, model_name, status):
        # Aktualizuj status modelu w UI
        for i, (name, _, _, _) in enumerate(self.api_providers_config):
            if name.split()[0] == model_name:  # Sprawdzamy tylko pierwszą część nazwy (np. "OpenAI" z "OpenAI (GPT-4)")
                self.api_status_labels[i].setText(f"Status: {status}")
                if status == "Gotowy":
                    self.api_status_labels[i].setStyleSheet("color: #008000;")  # Zielony kolor dla gotowego
                elif status == "Ładowanie...":
                    self.api_status_labels[i].setStyleSheet("color: #666666;")  # Szary kolor dla ładowania
                break

    def _on_models_loaded(self):
        # Włącz przyciski po załadowaniu modeli
        self.refresh_button.setEnabled(True)
        self._update_status("Wszystkie modele załadowane. Gotowy do pracy.", "ready")

    def _on_model_loading_error(self, error_msg):
        logger.error(f"Błąd ładowania modeli (z wątku ModelLoader): {error_msg}") # Używamy loggera
        self._update_status(f"Błąd ładowania modeli: {error_msg}", "error") # Nadal wyświetlamy w statusie dla użytkownika
        # Możesz tutaj dodać dodatkową obsługę błędów, np. wyłączenie przycisków API

    def _cancel_api_requests(self):
        """Anuluje wszystkie aktywne wątki API."""
        logger.info("Zażądano anulowania żądań API.")
        self._update_status("Anulowanie żądań...", "warning")
        if hasattr(self, 'cancel_button'):
            self.cancel_button.setEnabled(False)
            self.cancel_button.setToolTip("Anulowanie w toku...")

        # Ustaw flagę anulowania w każdym aktywnym wątku
        for api_index, worker in self.api_threads.items():
            if worker.isRunning(): # Sprawdź, czy wątek nadal działa
                logger.debug(f"Wysyłanie sygnału anulowania do wątku API ({api_index}).")
                worker.cancel() # Ustaw flagę anulowania w wątku
            else:
                logger.debug(f"Wątek API ({api_index}) już zakończył działanie lub nie był uruchomiony.")
        
        # Poczekaj krótko na zakończenie wątków, ale nie blokuj GUI
        QTimer.singleShot(100, self._finish_cancellation)  # 100ms na anulowanie

    def _finish_cancellation(self):
        """Kończy proces anulowania po krótkiej przerwie."""
        logger.info("Finalizacja anulowania żądań API.")
        self.is_processing = False
        self._update_status("Żądania anulowane. Gotowy do nowych zapytań.", "ready")
        
        # Resetuj przyciski
        if hasattr(self, 'refresh_button'):
            self.refresh_button.setEnabled(True)
            self.refresh_button.setToolTip("Odśwież (pobierz tekst ze schowka i przetwórz)")
        if hasattr(self, 'cancel_button'):
            self.cancel_button.setEnabled(False)
            self.cancel_button.setToolTip("Anuluj żądania do API")
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setVisible(False)

    def _cancel_single_api_request(self, api_index):
        """Anuluje pojedyncze żądanie API o podanym indeksie."""
        logger.info(f"Zażądano anulowania żądania API dla indeksu {api_index}.")
        if api_index in self.api_threads and self.api_threads[api_index].isRunning():
            logger.debug(f"Wysyłanie sygnału anulowania do wątku API ({api_index}).")
            self.api_threads[api_index].cancel()
            # Wyłącz przycisk anulowania dla tego API od razu
            if 0 <= api_index < len(self.api_cancel_single_buttons):
                 self.api_cancel_single_buttons[api_index].setEnabled(False)
                 # Od razu aktualizuj GUI, aby pokazać stan anulowania
                 if api_index in self.api_movies:
                     self.api_movies[api_index].stop() # Zatrzymaj animację
                 if api_index < len(self.api_text_edit_stacks):
                      self.api_text_edit_stacks[api_index].setCurrentIndex(0) # Przełącz na pole tekstowe

                 self.api_status_labels[api_index].setText("Status: Anulowanie...") # Tymczasowy status
                 self.api_edits[api_index].setPlainText("Trwa anulowanie...") # Wyczyść/ustaw tekst informacyjny

        elif 0 <= api_index < len(self.api_cancel_single_buttons):
             # Jeśli wątek już nie działa, tylko wyłącz przycisk
             self.api_cancel_single_buttons[api_index].setEnabled(False)
             logger.warning(f"Próba anulowania wątku API ({api_index}), który już nie działa lub nie istnieje.")

    def adjust_window_size(self):
        # logger.debug("adjust_window_size wywołane") # Opcjonalne logowanie debugujące
        screen = self.screen()
        if screen:
            # logger.debug(f"Ekran: {screen.name()}, Dostępna geometria: {screen.availableGeometry()}") # Opcjonalne logowanie
            available = screen.availableGeometry()
            width = int(available.width() * 0.6)
            height = int(available.height() * 0.85)
            # Użyj singleShot, aby dać GUI chwilę na przetworzenie
            QTimer.singleShot(50, lambda: self._apply_adjusted_size(width, height, available)) # Zwiększono opóźnienie do 50ms

    def _apply_adjusted_size(self, width, height, available_geometry):
         # logger.debug(f"_apply_adjusted_size wywołane: w={width}, h={height}") # Opcjonalne logowanie
         self.resize(width, height)
         self.move(
             available_geometry.left() + (available_geometry.width() - width) // 2,
             available_geometry.top() + (available_geometry.height() - height) // 2
         )

    def _restart_application(self):
        """Restart całej aplikacji."""
        try:
            logger.info("Rozpoczynam restart aplikacji...")
            
            # Zapisz aktualną ścieżkę wykonania
            if getattr(sys, 'frozen', False):
                # Jeśli uruchomiono z PyInstaller
                executable_path = sys.executable
                logger.info(f"Restart aplikacji PyInstaller: {executable_path}")
            else:
                # Jeśli uruchomiono jako skrypt Python
                executable_path = sys.executable
                script_path = os.path.abspath(sys.argv[0])
                logger.info(f"Restart skryptu Python: {executable_path} {script_path}")
            
            # Ustaw flagę zamykania
            self._is_closing = True
            
            # Wyczyść wszystkie wątki
            self._perform_full_cleanup()
            
            # Zamknij aplikację Qt
            QApplication.quit()
            
            # Uruchom nową instancję z opóźnieniem
            if getattr(sys, 'frozen', False):
                # PyInstaller - uruchom exe bezpośrednio
                subprocess.Popen([executable_path], 
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            else:
                # Skrypt Python
                subprocess.Popen([executable_path, script_path],
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
                
            logger.info("Restart zainicjowany pomyślnie")
            
        except Exception as e:
            error_msg = f"Błąd podczas restartu aplikacji: {e}"
            logger.error(error_msg, exc_info=True)
            
            # Fallback - po prostu zamknij aplikację
            self.quit_application()

    def closeEvent(self, event):
        logger.info("Otrzymano żądanie zamknięcia okna - minimalizuję do tray.")
        try:
            # Jeśli tray nie jest dostępny (np. WSL/Linux bez integracji traya), NIE chowaj okna
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logger.warning("System tray niedostępny – nie chowam do traya. Zamiast tego minimalizuję/utrzymuję okno.")
                try:
                    self.showMinimized()
                except Exception:
                    # Fallback: utrzymaj okno widoczne
                    self.show()
                event.ignore()
                return

            if hasattr(self, '_really_closing') and self._really_closing:
                self._perform_full_cleanup()
                event.accept()
                return
            if event.spontaneous() and (self.isMinimized() or not self.isVisible()):
                event.ignore()
                self.hide()
                if hasattr(self, 'clipboard_timer') and self.clipboard_timer:
                    self.clipboard_timer.stop()
                return
            self.hide()
            if hasattr(self, 'clipboard_timer') and self.clipboard_timer:
                self.clipboard_timer.stop()
            if hasattr(self, 'tray_icon') and self.tray_icon and not getattr(self, '_tray_message_shown', False):
                self.tray_icon.showMessage(
                    "Poprawiacz Tekstu",
                    "Aplikacja została zminimalizowana do zasobnika systemowego.\nGlobalny skrót Ctrl+Shift+C nadal działa.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )
                self._tray_message_shown = True
            logger.info("Okno ukryte do tray - aplikacja nadal działa.")
            event.ignore()
        except Exception as e:
            logger.error(f"Błąd podczas ukrywania do tray: {e}", exc_info=True)
            self.hide()
            event.ignore()

    def _perform_full_cleanup(self):
        """Wykonuje pełny cleanup przed zamknięciem aplikacji"""
        logger.info("Rozpoczynam pełny cleanup aplikacji.")
        
        try:
            # Ustaw flagę - aplikacja jest zamykana
            self._is_closing = True
            
            # Zatrzymaj wszystkie timery
            if hasattr(self, 'clipboard_timer') and self.clipboard_timer:
                self.clipboard_timer.stop()
                logger.info("Zatrzymano timer schowka.")
            
            # Anuluj wszystkie aktywne żądania API
            if self.is_processing and hasattr(self, 'api_threads'):
                logger.info("Anulowanie aktywnych wątków API przed zamknięciem...")
                for api_index, worker in self.api_threads.items():
                    if worker and worker.isRunning():
                        logger.info(f"Anulowanie wątku API {api_index}")
                        worker.cancel()
                
                # Poczekaj maksymalnie 2 sekundy na zakończenie thread'ów
                max_wait_time = 2.0
                start_time = time.time()
                while time.time() - start_time < max_wait_time:
                    all_finished = True
                    for worker in self.api_threads.values():
                        if worker and worker.isRunning():
                            all_finished = False
                            break
                    
                    if all_finished:
                        logger.info("Wszystkie wątki API zakończone przed zamknięciem.")
                        break
                    
                    # Pozwól na przetworzenie eventów
                    QApplication.processEvents()
                    time.sleep(0.1)
                
                # Force terminate jeśli nadal działają
                for api_index, worker in self.api_threads.items():
                    if worker and worker.isRunning():
                        logger.warning(f"Wymuszam zakończenie wątku API {api_index}")
                        worker.terminate()
                        worker.wait(1000)  # Czekaj max 1s
            
            # Wyłącz global hotkey - WYŁĄCZONO
            # UWAGA: Hotkey będzie usunięty w main.py podczas zamykania aplikacji
            # Nie usuwamy go tutaj, żeby uniknąć konfliktów i błędów krytycznych
            logger.info("Hotkey zostanie usunięty przez main.py podczas zamykania aplikacji.")

            # Ukryj ikonę tray
            if hasattr(self, 'tray_icon') and self.tray_icon:
                self.tray_icon.hide()
                logger.info("Ukryto ikonę tray.")
            
            # Zapisz konfigurację
            try:
                from utils import config_manager
                config_manager.save_config(self.api_keys, self.current_models, self.settings)
                logger.info("Konfiguracja zapisana przed zamknięciem.")
            except Exception as e:
                logger.warning(f"Nie udało się zapisać konfiguracji: {e}")
            
            logger.info("Pełny cleanup zakończony.")
            
        except Exception as e:
            logger.error(f"Błąd podczas pełnego cleanup: {e}", exc_info=True)

    def quit_application(self):
        """Prawdziwe zamknięcie aplikacji - wywołane z menu tray"""
        logger.info("Żądanie prawdziwego zamknięcia aplikacji z menu tray.")
        
        # Ustaw flagę prawdziwego zamknięcia
        self._really_closing = True
        
        # Zamknij aplikację
        self.close()
        QApplication.quit()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())