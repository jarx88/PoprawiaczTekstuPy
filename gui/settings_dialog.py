from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QDialogButtonBox, QTabWidget, QWidget, QGroupBox,
    QSizePolicy, QGridLayout
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt

# Próba importu config_manager - podobnie jak w main_window
import os
import sys
# Używamy paths.py zamiast ręcznego obliczania ścieżki
# current_file_path_for_utils = os.path.abspath(__file__)
# gui_dir_for_utils = os.path.dirname(current_file_path_for_utils)
# project_dir_for_utils = os.path.dirname(gui_dir_for_utils)
# if project_dir_for_utils not in sys.path:
#     sys.path.insert(0, project_dir_for_utils)
from utils import config_manager


class SettingsDialog(QDialog):
    def __init__(self, current_api_keys, current_models, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ustawienia API i Modeli")
        self.setMinimumSize(600, 400) # Rozsądny minimalny rozmiar
        self.setMaximumSize(900, 700) # Maksymalny rozmiar dla wygody
        self.resize(650, 500) # Domyślny rozmiar startowy
        self.setModal(True)

        self.api_keys = dict(current_api_keys) # Kopia, aby można było anulować
        self.models = dict(current_models)

        # Definicje domyślnych/przykładowych modeli, jeśli nie ma ich w config_manager
        # Można by je przenieść do config_manager lub trzymać tutaj dla UI
        self.OPENAI_MODELS_EXAMPLES = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4"]
        self.ANTHROPIC_MODELS_EXAMPLES = ["claude-3-5-sonnet-latest", "claude-3-opus-latest", "claude-3-haiku-latest", "claude-2.1"]
        self.GEMINI_MODELS_EXAMPLES = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.0-pro"]
        self.DEEPSEEK_MODELS_EXAMPLES = ["deepseek-chat", "deepseek-coder", "deepseek-v2"]


        main_layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        self._create_api_keys_tab()
        self._create_ai_models_tab()

        # Przyciski OK i Anuluj
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

        # Podstawowa stylizacja dla czytelności
        self.setStyleSheet("""
            QDialog {
                background-color: #f8f9fa;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 10pt;
                background-color: #f0f4f8;
                border: 1px solid #d1d8e0;
                border-radius: 5px;
                margin-top: 0.7em;
                padding: 1em; 
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                left: 10px;
                top: -2px;
            }
            QLabel {
                font-size: 9pt;
                padding-top: 5px; /* Dodatkowy padding dla etykiet w QFormLayout */
            }
            QLineEdit {
                font-size: 9pt;
                padding: 4px;
                border: 1px solid #ced4da;
                border-radius: 3px;
                background-color: #ffffff;
            }
            QPushButton { /* Styl dla przycisków OK/Anuluj */
                font-size: 9pt;
                padding: 6px 12px;
                background-color: #e9ecef;
                border: 1px solid #adb5bd;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #dee2e6;
            }
            QTabWidget::pane { /* Ramka wokół zawartości zakładek */
                border-top: 1px solid #ced4da;
                margin-top: -1px; /* Aby zakładka "siedziała" na ramce */
            }
            QTabBar::tab { /* Styl dla samych zakładek */
                background: #e9ecef;
                border: 1px solid #ced4da;
                border-bottom-color: #ced4da; /* Dolna ramka zakładki */
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 8ex;
                padding: 5px 10px;
                margin-right: 2px; /* Odstęp między zakładkami */
            }
            QTabBar::tab:selected {
                background: #f8f9fa; /* Tło aktywnej zakładki */
                border-color: #ced4da;
                border-bottom-color: #f8f9fa; /* Aby "połączyć" z panelem */
                margin-bottom: -1px; /* Aby "siedziała" na ramce panelu */
            }
            QTabBar::tab:!selected:hover {
                background: #dee2e6;
            }
        """)


    def _create_api_keys_tab(self):
        api_keys_widget = QWidget()
        layout = QFormLayout(api_keys_widget)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows) # Lepsze zawijanie
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft) # Wyrównanie etykiet

        self.openai_key_input = QLineEdit(self.api_keys.get("OpenAI", ""))
        layout.addRow(QLabel("Klucz OpenAI:"), self.openai_key_input)

        self.anthropic_key_input = QLineEdit(self.api_keys.get("Anthropic", ""))
        layout.addRow(QLabel("Klucz Anthropic:"), self.anthropic_key_input)

        self.gemini_key_input = QLineEdit(self.api_keys.get("Gemini", ""))
        layout.addRow(QLabel("Klucz Gemini:"), self.gemini_key_input)

        self.deepseek_key_input = QLineEdit(self.api_keys.get("DeepSeek", ""))
        layout.addRow(QLabel("Klucz DeepSeek:"), self.deepseek_key_input)

        self.tab_widget.addTab(api_keys_widget, "Klucze API")

    def _create_ai_models_tab(self):
        ai_models_widget = QWidget()
        main_models_layout = QVBoxLayout(ai_models_widget) # Główny layout dla tej zakładki

        # Użyjemy siatki dla lepszego rozmieszczenia modeli
        grid_layout = QGridLayout()
        grid_layout.setSpacing(15)

        # OpenAI
        self.openai_model_input, openai_group = self._create_model_group(
            "OpenAI", self.models.get("OpenAI", ""), self.OPENAI_MODELS_EXAMPLES
        )
        grid_layout.addWidget(openai_group, 0, 0)

        # Anthropic
        self.anthropic_model_input, anthropic_group = self._create_model_group(
            "Anthropic", self.models.get("Anthropic", ""), self.ANTHROPIC_MODELS_EXAMPLES
        )
        grid_layout.addWidget(anthropic_group, 0, 1)

        # Gemini
        self.gemini_model_input, gemini_group = self._create_model_group(
            "Gemini", self.models.get("Gemini", ""), self.GEMINI_MODELS_EXAMPLES
        )
        grid_layout.addWidget(gemini_group, 1, 0)

        # DeepSeek
        self.deepseek_model_input, deepseek_group = self._create_model_group(
            "DeepSeek", self.models.get("DeepSeek", ""), self.DEEPSEEK_MODELS_EXAMPLES
        )
        grid_layout.addWidget(deepseek_group, 1, 1)
        
        main_models_layout.addLayout(grid_layout)
        main_models_layout.addStretch(1) # Dodaje rozciągliwą przestrzeń na dole, jeśli jest miejsce

        self.tab_widget.addTab(ai_models_widget, "Modele AI")

    def _create_model_group(self, title, current_model_value, examples_list):
        group_box = QGroupBox(title)
        group_layout = QVBoxLayout(group_box)
        group_layout.setSpacing(8)

        label_model = QLabel("Wpisz model:")
        model_input = QLineEdit(current_model_value)
        model_input.setFont(QFont("Segoe UI", 10))
        
        group_layout.addWidget(label_model)
        group_layout.addWidget(model_input)

        if examples_list:
            label_examples_title = QLabel("Przykłady:")
            label_examples_title.setStyleSheet("font-weight: normal; margin-top: 5px;") # Zmniejszenie wagi i margines
            group_layout.addWidget(label_examples_title)
            
            # Tworzymy etykiety dla przykładów, dzieląc je na linie, jeśli jest ich dużo
            examples_per_line = 2 # Ile przykładów w jednej linii
            current_line_examples = []
            for i, example in enumerate(examples_list):
                current_line_examples.append(example)
                if len(current_line_examples) == examples_per_line or i == len(examples_list) - 1:
                    example_label = QLabel(", ".join(current_line_examples))
                    example_label.setStyleSheet("font-weight: normal; font-size: 8pt; color: #505050;")
                    group_layout.addWidget(example_label)
                    current_line_examples = []
        
        group_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred) # Aby grupy się rozciągały
        return model_input, group_box

    def get_updated_config(self):
        # Zbieranie danych z pól przed zapisem
        self.api_keys["OpenAI"] = self.openai_key_input.text()
        self.api_keys["Anthropic"] = self.anthropic_key_input.text()
        self.api_keys["Gemini"] = self.gemini_key_input.text()
        self.api_keys["DeepSeek"] = self.deepseek_key_input.text()

        self.models["OpenAI"] = self.openai_model_input.text()
        self.models["Anthropic"] = self.anthropic_model_input.text()
        self.models["Gemini"] = self.gemini_model_input.text()
        self.models["DeepSeek"] = self.deepseek_model_input.text()
        
        return self.api_keys, self.models

    def accept(self):
        # Zapisz konfigurację przy akceptacji
        updated_keys, updated_models = self.get_updated_config()
        config_manager.save_config(updated_keys, updated_models)
        super().accept()

# Przykładowe użycie (do testowania samego dialogu)
if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Załaduj przykładową lub pustą konfigurację do testów
    # W rzeczywistej aplikacji te dane przyszłyby z MainWindow
    try:
        keys, models_conf, settings_conf, ai_settings, _ = config_manager.load_config()
    except Exception as e:
        print(f"Błąd ładowania configu: {e}, używam domyślnych.")
        keys = {"OpenAI": "", "Anthropic": "", "Gemini": "", "DeepSeek": ""}
        models_conf = {"OpenAI": "gpt-4o-mini", "Anthropic": "claude-3-5-sonnet-latest", "Gemini": "gemini-1.5-flash", "DeepSeek": "deepseek-chat"}

    dialog = SettingsDialog(keys, models_conf)
    if dialog.exec():
        print("Ustawienia zapisane.")
        new_keys, new_models = dialog.get_updated_config() # Po zamknięciu przez OK, config jest już zapisany
        print("Nowe klucze:", new_keys)
        print("Nowe modele:", new_models)
    else:
        print("Anulowano ustawienia.")
    sys.exit(app.exec())
