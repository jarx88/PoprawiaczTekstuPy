import os
import sys
from PyQt6.QtWidgets import QApplication

def get_text():
    """Pobiera tekst ze schowka, zwraca None jeśli pusty lub błąd."""
    try:
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if not text:
            print("Schowek jest pusty.") # Można by logować zamiast printować
            return None
        # print(f"Pobrano ze schowka: {text[:100]}...") # Linia debugująca
        return text.strip()
    except Exception as e:
        print(f"Błąd podczas pobierania tekstu ze schowka: {e}") # Można by logować
        return None

def set_text(text):
    """Ustawia tekst w schowku."""
    if text is not None:
        try:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            # print(f"Tekst ustawiony w schowku: {text[:100]}...") # Linia debugująca
        except Exception as e:
            print(f"Błąd podczas ustawiania tekstu w schowku: {e}") # Można by logować

# Funkcje do monitorowania i symulacji Ctrl+V pozostawiamy na razie w main_window ze względu na integrację z GUI.
# Można je refaktorować później, np. przekazując referencję do MainWindow lub używając sygnałów. 