#!/usr/bin/env python3
"""
PoprawiaczTekstuPy - Nowoczesna wersja z CustomTkinter
Modern GUI dla Windows cross-compilation compatibility
"""

import sys
import os
import logging
from datetime import datetime
import customtkinter as ctk
import pystray
from PIL import Image
import threading
import time
from utils import config_manager
from utils.hotkey_manager import get_hotkey_processor, cleanup_global_hotkey
from api_clients import openai_client, anthropic_client, gemini_client, deepseek_client
import httpx
import tkinter.messagebox as msgbox
import tkinter.scrolledtext as scrolledtext
import pyperclip

# Globalne zmienne
main_app = None
tray_icon = None

class ModernTextCorrector(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Konfiguracja głównego okna
        self.title("PoprawiaczTekstuPy - Modern")
        self.geometry("800x600")
        
        # Ustaw theme
        ctk.set_appearance_mode("system")  # Modes: system (default), light, dark
        ctk.set_default_color_theme("blue")  # Themes: blue (default), dark-blue, green
        
        # Ikona
        try:
            self.iconbitmap("assets/icon.ico")
        except:
            logging.warning("Nie można załadować ikony aplikacji")
        
        # Konfiguracja API
        self.api_keys = {}
        self.models = {}
        self.settings = {}
        self.ai_settings = {}
        
        # Interfejs
        self.setup_ui()
        self.load_config()
        
        # Protocol dla zamykania okna
        self.protocol("WM_DELETE_WINDOW", self.hide_window)
        
    def setup_ui(self):
        """Konfiguruje nowoczesny interfejs użytkownika."""
        
        # Główny frame
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tytuł
        title_label = ctk.CTkLabel(
            self.main_frame, 
            text="PoprawiaczTekstuPy", 
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title_label.pack(pady=(10, 20))
        
        # Status label
        self.status_label = ctk.CTkLabel(
            self.main_frame,
            text="Status: Gotowy",
            font=ctk.CTkFont(size=12)
        )
        self.status_label.pack(pady=(0, 10))
        
        # Tekstowe pole do testowania
        text_frame = ctk.CTkFrame(self.main_frame)
        text_frame.pack(fill="both", expand=True, pady=10)
        
        text_label = ctk.CTkLabel(text_frame, text="Tekst do poprawy:")
        text_label.pack(anchor="w", padx=10, pady=(10, 5))
        
        self.text_input = ctk.CTkTextbox(text_frame, height=150)
        self.text_input.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Wynik
        result_label = ctk.CTkLabel(text_frame, text="Poprawiony tekst:")
        result_label.pack(anchor="w", padx=10, pady=(10, 5))
        
        self.text_output = ctk.CTkTextbox(text_frame, height=150)
        self.text_output.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Przyciski
        button_frame = ctk.CTkFrame(self.main_frame)
        button_frame.pack(fill="x", pady=10)
        
        self.process_button = ctk.CTkButton(
            button_frame,
            text="Popraw tekst",
            command=self.process_text_manual,
            height=40
        )
        self.process_button.pack(side="left", padx=5)
        
        self.clear_button = ctk.CTkButton(
            button_frame,
            text="Wyczyść",
            command=self.clear_text,
            height=40
        )
        self.clear_button.pack(side="left", padx=5)
        
        self.copy_button = ctk.CTkButton(
            button_frame,
            text="Kopiuj wynik",
            command=self.copy_result,
            height=40
        )
        self.copy_button.pack(side="left", padx=5)
        
        # Settings button
        self.settings_button = ctk.CTkButton(
            button_frame,
            text="Ustawienia",
            command=self.show_settings,
            height=40
        )
        self.settings_button.pack(side="right", padx=5)
        
        # Hotkey info
        hotkey_label = ctk.CTkLabel(
            self.main_frame,
            text="Globalny skrót: Ctrl+Shift+C (poprawia tekst ze schowka)",
            font=ctk.CTkFont(size=10)
        )
        hotkey_label.pack(pady=5)
        
    def load_config(self):
        """Ładuje konfigurację API."""
        try:
            (
                self.api_keys,
                self.models,
                self.settings,
                self.ai_settings,
                _,
            ) = config_manager.load_config()
            
            if not any(self.api_keys.values()):
                self.update_status("⚠️ Brak konfiguracji API - skonfiguruj w ustawieniach")
            else:
                configured_apis = [k for k, v in self.api_keys.items() if v]
                self.update_status(f"✅ API skonfigurowane: {', '.join(configured_apis)}")
                
        except Exception as e:
            logging.error(f"Błąd ładowania konfiguracji: {e}")
            self.update_status("❌ Błąd konfiguracji")
    
    def update_status(self, message):
        """Aktualizuje status aplikacji."""
        self.status_label.configure(text=f"Status: {message}")
        self.update_idletasks()
    
    def process_text_manual(self):
        """Przetwarza tekst z pola tekstowego."""
        text = self.text_input.get("1.0", "end-1c").strip()
        if not text:
            msgbox.showwarning("Uwaga", "Wprowadź tekst do poprawy")
            return
        
        self.process_text(text)
    
    def process_text(self, text):
        """Główna logika przetwarzania tekstu."""
        if not any(self.api_keys.values()):
            msgbox.showerror("Błąd", "Brak skonfigurowanych kluczy API")
            return
        
        self.update_status("🔄 Przetwarzanie...")
        self.process_button.configure(state="disabled")
        
        # Uruchom w osobnym wątku
        thread = threading.Thread(target=self._process_text_thread, args=(text,))
        thread.daemon = True
        thread.start()
    
    def _process_text_thread(self, text):
        """Przetwarzanie tekstu w osobnym wątku."""
        try:
            # Wybierz API (priorytet: OpenAI, Anthropic, Gemini, DeepSeek)
            if self.api_keys.get('openai'):
                result = openai_client.popraw_tekst(
                    text, self.api_keys['openai'], self.models.get('openai', 'gpt-3.5-turbo')
                )
            elif self.api_keys.get('anthropic'):
                result = anthropic_client.popraw_tekst(
                    text, self.api_keys['anthropic'], self.models.get('anthropic', 'claude-3-haiku-20240307')
                )
            elif self.api_keys.get('gemini'):
                result = gemini_client.popraw_tekst(
                    text, self.api_keys['gemini'], self.models.get('gemini', 'gemini-pro')
                )
            elif self.api_keys.get('deepseek'):
                result = deepseek_client.popraw_tekst(
                    text, self.api_keys['deepseek'], self.models.get('deepseek', 'deepseek-chat')
                )
            else:
                result = "Błąd: Brak skonfigurowanych kluczy API"
            
            # Aktualizuj GUI w głównym wątku
            self.after(0, self._update_result, result)
            
        except Exception as e:
            error_msg = f"Błąd przetwarzania: {str(e)}"
            logging.error(error_msg)
            self.after(0, self._update_result, error_msg)
    
    def _update_result(self, result):
        """Aktualizuje wynik w głównym wątku."""
        self.text_output.delete("1.0", "end")
        self.text_output.insert("1.0", result)
        
        self.process_button.configure(state="normal")
        self.update_status("✅ Gotowy")
    
    def clear_text(self):
        """Czyści pola tekstowe."""
        self.text_input.delete("1.0", "end")
        self.text_output.delete("1.0", "end")
        self.update_status("Pola wyczyszczone")
    
    def copy_result(self):
        """Kopiuje wynik do schowka."""
        result = self.text_output.get("1.0", "end-1c")
        if result.strip():
            pyperclip.copy(result)
            self.update_status("✅ Skopiowano do schowka")
        else:
            msgbox.showwarning("Uwaga", "Brak tekstu do skopiowania")
    
    def show_settings(self):
        """Pokazuje okno ustawień."""
        settings_window = SettingsWindow(self)
        settings_window.grab_set()  # Modal window
    
    def handle_hotkey_event(self):
        """Obsługuje zdarzenie hotkey (Ctrl+Shift+C)."""
        try:
            # Pobierz tekst ze schowka
            clipboard_text = pyperclip.paste()
            
            if not clipboard_text or not clipboard_text.strip():
                self.after(0, lambda: self.update_status("⚠️ Schowek jest pusty"))
                return
            
            # Pokaż okno jeśli ukryte
            self.after(0, self.show_window)
            
            # Wstaw tekst i przetwórz
            self.after(0, lambda: self.text_input.delete("1.0", "end"))
            self.after(0, lambda: self.text_input.insert("1.0", clipboard_text))
            self.after(0, lambda: self.process_text(clipboard_text))
            
        except Exception as e:
            logging.error(f"Błąd obsługi hotkey: {e}")
            self.after(0, lambda: self.update_status("❌ Błąd hotkey"))
    
    def hide_window(self):
        """Ukrywa okno do system tray."""
        self.withdraw()
    
    def show_window(self):
        """Pokazuje okno z system tray."""
        self.deiconify()
        self.lift()
        self.focus_force()

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        
        self.title("Ustawienia")
        self.geometry("500x400")
        self.resizable(False, False)
        
        # Center window
        self.transient(parent)
        
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        """Konfiguruje interfejs ustawień."""
        # Main frame
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title_label = ctk.CTkLabel(main_frame, text="Ustawienia API", font=ctk.CTkFont(size=18, weight="bold"))
        title_label.pack(pady=(0, 20))
        
        # OpenAI
        openai_frame = ctk.CTkFrame(main_frame)
        openai_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(openai_frame, text="OpenAI API Key:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        self.openai_entry = ctk.CTkEntry(openai_frame, placeholder_text="sk-...", show="*")
        self.openai_entry.pack(fill="x", padx=10, pady=5)
        
        # Anthropic
        anthropic_frame = ctk.CTkFrame(main_frame)
        anthropic_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(anthropic_frame, text="Anthropic API Key:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        self.anthropic_entry = ctk.CTkEntry(anthropic_frame, placeholder_text="sk-ant-...", show="*")
        self.anthropic_entry.pack(fill="x", padx=10, pady=5)
        
        # Gemini
        gemini_frame = ctk.CTkFrame(main_frame)
        gemini_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(gemini_frame, text="Gemini API Key:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        self.gemini_entry = ctk.CTkEntry(gemini_frame, placeholder_text="AIza...", show="*")
        self.gemini_entry.pack(fill="x", padx=10, pady=5)
        
        # DeepSeek
        deepseek_frame = ctk.CTkFrame(main_frame)
        deepseek_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(deepseek_frame, text="DeepSeek API Key:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        self.deepseek_entry = ctk.CTkEntry(deepseek_frame, placeholder_text="sk-...", show="*")
        self.deepseek_entry.pack(fill="x", padx=10, pady=5)
        
        # Buttons
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill="x", pady=20)
        
        save_button = ctk.CTkButton(button_frame, text="Zapisz", command=self.save_settings)
        save_button.pack(side="left", padx=5)
        
        cancel_button = ctk.CTkButton(button_frame, text="Anuluj", command=self.destroy)
        cancel_button.pack(side="right", padx=5)
    
    def load_settings(self):
        """Ładuje istniejące ustawienia."""
        if self.parent.api_keys.get('openai'):
            self.openai_entry.insert(0, self.parent.api_keys['openai'])
        if self.parent.api_keys.get('anthropic'):
            self.anthropic_entry.insert(0, self.parent.api_keys['anthropic'])
        if self.parent.api_keys.get('gemini'):
            self.gemini_entry.insert(0, self.parent.api_keys['gemini'])
        if self.parent.api_keys.get('deepseek'):
            self.deepseek_entry.insert(0, self.parent.api_keys['deepseek'])
    
    def save_settings(self):
        """Zapisuje ustawienia."""
        try:
            # Update parent's config
            self.parent.api_keys['openai'] = self.openai_entry.get().strip()
            self.parent.api_keys['anthropic'] = self.anthropic_entry.get().strip()
            self.parent.api_keys['gemini'] = self.gemini_entry.get().strip()
            self.parent.api_keys['deepseek'] = self.deepseek_entry.get().strip()
            
            # Save to file
            config_manager.save_config(self.parent.api_keys, self.parent.models, self.parent.settings)
            
            # Update parent status
            configured_apis = [k for k, v in self.parent.api_keys.items() if v]
            if configured_apis:
                self.parent.update_status(f"✅ API zaktualizowane: {', '.join(configured_apis)}")
            else:
                self.parent.update_status("⚠️ Brak skonfigurowanych API")
            
            msgbox.showinfo("Sukces", "Ustawienia zostały zapisane")
            self.destroy()
            
        except Exception as e:
            logging.error(f"Błąd zapisywania ustawień: {e}")
            msgbox.showerror("Błąd", f"Nie udało się zapisać ustawień: {e}")

def create_tray_icon(app):
    """Tworzy ikonę w system tray."""
    global tray_icon
    
    try:
        # Ładuj ikonę
        try:
            image = Image.open("assets/icon.ico")
        except:
            # Fallback - prosta ikona
            image = Image.new('RGB', (64, 64), color='blue')
        
        # Menu tray
        menu = pystray.Menu(
            pystray.MenuItem("Pokaż", lambda: app.after(0, app.show_window)),
            pystray.MenuItem("Ukryj", lambda: app.after(0, app.hide_window)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Zakończ", lambda: app.after(0, quit_app))
        )
        
        tray_icon = pystray.Icon("PoprawiaczTekstuPy", image, menu=menu)
        tray_icon.run()
        
    except Exception as e:
        logging.error(f"Błąd tworzenia tray icon: {e}")

def quit_app():
    """Zamyka aplikację."""
    global main_app, tray_icon
    
    try:
        cleanup_global_hotkey()
        
        if tray_icon:
            tray_icon.stop()
        
        if main_app:
            main_app.quit()
            
    except Exception as e:
        logging.error(f"Błąd podczas zamykania: {e}")
    
    sys.exit(0)

def setup_logging():
    """Konfiguruje logging."""
    try:
        log_dir = os.path.join(os.path.expanduser("~"), "PoprawiaczTekstu_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"app_modern_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        logging.info(f"Modern GUI logs: {log_file}")
    except Exception as e:
        print(f"Logging error: {e}")

def setup_global_hotkey(app):
    """Konfiguruje globalny hotkey."""
    logging.info("Konfiguracja globalnego skrótu Ctrl+Shift+C...")
    
    try:
        hotkey_processor = get_hotkey_processor()
        
        def hotkey_callback():
            app.handle_hotkey_event()
        
        success = hotkey_processor.setup_hotkey_with_fallback(hotkey_callback)
        
        if success:
            logging.info("Globalny skrót skonfigurowany pomyślnie")
            app.after(0, lambda: app.update_status("✅ Hotkey: Ctrl+Shift+C aktywny"))
        else:
            logging.warning("Nie udało się skonfigurować hotkey")
            app.after(0, lambda: app.update_status("⚠️ Hotkey niedostępny - tryb manualny"))
            
    except Exception as e:
        logging.error(f"Błąd konfiguracji hotkey: {e}")
        app.after(0, lambda: app.update_status("❌ Błąd hotkey"))

def main():
    global main_app
    
    setup_logging()
    logging.info("=== PoprawiaczTekstuPy Modern GUI Start ===")
    
    try:
        # Tworzenie aplikacji
        main_app = ModernTextCorrector()
        
        # Globalny hotkey w osobnym wątku
        hotkey_thread = threading.Thread(target=setup_global_hotkey, args=(main_app,))
        hotkey_thread.daemon = True
        hotkey_thread.start()
        
        # System tray w osobnym wątku
        tray_thread = threading.Thread(target=create_tray_icon, args=(main_app,))
        tray_thread.daemon = True
        tray_thread.start()
        
        # Start aplikacji
        main_app.mainloop()
        
    except KeyboardInterrupt:
        logging.info("Przerwano przez użytkownika")
        quit_app()
    except Exception as e:
        logging.error(f"Błąd aplikacji: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()