#!/usr/bin/env python3
"""
PoprawiaczTekstuPy - CustomTkinter version with ORIGINAL multi-API functionality
Pełna funkcjonalność: animacje, anulowanie, tray, kolory, auto-paste
"""

import sys
import os
import logging
from datetime import datetime
import customtkinter as ctk
import pystray
from PIL import Image, ImageTk
import threading
import time
import queue
import tkinter as tk
from tkinter import messagebox
from utils import config_manager
from utils.hotkey_manager import get_hotkey_processor, cleanup_global_hotkey
from api_clients import openai_client, anthropic_client, gemini_client, deepseek_client
import httpx
import pyperclip
import keyboard

# Globalne zmienne
main_app = None
tray_icon = None

def get_assets_dir_path():
    """Zwraca ścieżkę do katalogu assets."""
    if getattr(sys, 'frozen', False):
        # PyInstaller
        return os.path.join(sys._MEIPASS, 'assets')
    else:
        # Development
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')

class AnimatedGIF(tk.Label):
    """Widget dla animowanego GIF w tkinter."""
    def __init__(self, master, path):
        self.master = master
        self.path = path
        self.frames = []
        self.current_frame = 0
        self.is_running = False
        
        # Load GIF
        self.gif = Image.open(path)
        
        # Extract frames
        try:
            while True:
                frame = self.gif.copy()
                frame = frame.resize((48, 48), Image.Resampling.LANCZOS)
                self.frames.append(ImageTk.PhotoImage(frame))
                self.gif.seek(len(self.frames))
        except EOFError:
            pass
        
        super().__init__(master, image=self.frames[0] if self.frames else None)
        
    def start(self):
        """Start animation."""
        self.is_running = True
        self.animate()
    
    def stop(self):
        """Stop animation."""
        self.is_running = False
    
    def animate(self):
        """Animate frames."""
        if not self.is_running or not self.frames:
            return
        
        self.configure(image=self.frames[self.current_frame])
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        
        # Schedule next frame
        self.after(50, self.animate)

class MultiAPICorrector(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Konfiguracja głównego okna
        self.title("PoprawiaczTekstuPy - Multi-API")
        self.geometry("1400x850")
        
        # Ustaw theme
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        
        # Zmienne
        self.api_keys = {}
        self.models = {}
        self.settings = {}
        self.api_threads = {}
        self.api_results = {}
        self.original_text = ""
        self.processing = False
        self.current_session_id = 0
        self.cancel_flags = {}  # Flagi anulowania dla każdego API
        
        # UI
        self.setup_ui()
        self.load_config()
        
        # Protocol dla zamykania okna
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        
        # Start minimalized
        self.after(100, self.minimize_to_tray)
        
    def setup_ui(self):
        """Konfiguruje interfejs z 4 panelami API."""
        
        # Główny frame
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Top bar - status i info
        top_frame = ctk.CTkFrame(self.main_frame, height=80)
        top_frame.pack(fill="x", padx=5, pady=5)
        top_frame.pack_propagate(False)
        
        # Status label
        self.status_label = ctk.CTkLabel(
            top_frame,
            text="⌨️ Ctrl+Shift+C - zaznacz tekst i naciśnij aby poprawić",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.status_label.pack(pady=(10, 5))
        
        # Session and API counter
        info_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        info_frame.pack()
        
        self.session_label = ctk.CTkLabel(
            info_frame,
            text="📝 Sesja: 0",
            font=ctk.CTkFont(size=12)
        )
        self.session_label.pack(side="left", padx=10)
        
        self.api_counter_label = ctk.CTkLabel(
            info_frame,
            text="🤖 API: 0/4",
            font=ctk.CTkFont(size=12)
        )
        self.api_counter_label.pack(side="left", padx=10)
        
        self.progress_label = ctk.CTkLabel(
            info_frame,
            text="",
            font=ctk.CTkFont(size=12)
        )
        self.progress_label.pack(side="left", padx=10)
        
        # Container dla 4 API panels
        panels_container = ctk.CTkFrame(self.main_frame)
        panels_container.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Grid 2x2 dla 4 API
        self.api_frames = []
        self.api_text_widgets = []
        self.api_labels = []
        self.api_buttons = []
        self.api_cancel_buttons = []
        self.api_progress_bars = []
        self.api_loaders = []
        self.api_loader_frames = []
        
        # Oryginalne kolory z PyQt6 aplikacji
        api_names = ["OpenAI", "Anthropic", "Gemini", "DeepSeek"]
        api_colors = {
            "OpenAI": "#10a37f",     # Zielony OpenAI
            "Anthropic": "#d97706",   # Pomarańczowy Anthropic
            "Gemini": "#4285f4",      # Niebieski Google
            "DeepSeek": "#7c3aed"     # Fioletowy DeepSeek
        }
        
        for i, name in enumerate(api_names):
            row = i // 2
            col = i % 2
            color = api_colors[name]
            
            # Frame dla każdego API z kolorem tła
            api_frame = ctk.CTkFrame(panels_container, corner_radius=10)
            api_frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            self.api_frames.append(api_frame)
            
            # Konfiguracja grid
            panels_container.grid_rowconfigure(row, weight=1)
            panels_container.grid_columnconfigure(col, weight=1)
            
            # Colored header frame
            header_frame = ctk.CTkFrame(api_frame, fg_color=color, corner_radius=10, height=50)
            header_frame.pack(fill="x", padx=2, pady=(2, 0))
            header_frame.pack_propagate(False)
            
            # Header content frame
            header_content = ctk.CTkFrame(header_frame, fg_color="transparent")
            header_content.pack(fill="both", expand=True, padx=10, pady=5)
            
            # API name label
            api_label = ctk.CTkLabel(
                header_content,
                text=f"🤖 {name}",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="white"
            )
            api_label.pack(side="left")
            self.api_labels.append(api_label)
            
            # Cancel button for single API
            cancel_btn = ctk.CTkButton(
                header_content,
                text="✖",
                width=30,
                height=25,
                fg_color="transparent",
                hover_color="#ffffff33",
                text_color="white",
                command=lambda idx=i: self.cancel_single_api(idx)
            )
            cancel_btn.pack(side="right", padx=5)
            cancel_btn.configure(state="disabled")
            self.api_cancel_buttons.append(cancel_btn)
            
            # Progress bar
            progress_bar = ctk.CTkProgressBar(
                header_content,
                height=8,
                progress_color="white",
                fg_color="#ffffff33"
            )
            progress_bar.pack(side="right", padx=5, fill="x", expand=True)
            progress_bar.set(0)
            progress_bar.pack_forget()  # Ukryj na początku
            self.api_progress_bars.append(progress_bar)
            
            # Content frame
            content_frame = ctk.CTkFrame(api_frame, fg_color="#f5f5f5", corner_radius=5)
            content_frame.pack(fill="both", expand=True, padx=5, pady=5)
            
            # Loader frame (dla animacji GIF)
            loader_frame = tk.Frame(content_frame, bg="white")
            loader_frame.pack(fill="both", expand=True)
            loader_frame.pack_forget()  # Ukryj na początku
            self.api_loader_frames.append(loader_frame)
            
            # Animated GIF loader
            gif_path = os.path.join(get_assets_dir_path(), "loader.gif")
            if os.path.exists(gif_path):
                loader = AnimatedGIF(loader_frame, gif_path)
                loader.pack(expand=True)
                self.api_loaders.append(loader)
            else:
                # Fallback - zwykły label
                loader = tk.Label(loader_frame, text="⏳ Ładowanie...", bg="white")
                loader.pack(expand=True)
                self.api_loaders.append(loader)
            
            # Text widget dla wyniku
            text_widget = ctk.CTkTextbox(
                content_frame,
                wrap="word",
                font=ctk.CTkFont(size=12),
                fg_color="white",
                text_color="black"
            )
            text_widget.pack(fill="both", expand=True, padx=2, pady=2)
            text_widget.insert("1.0", f"Oczekiwanie na tekst...")
            text_widget.configure(state="disabled")
            self.api_text_widgets.append(text_widget)
            
            # Button "Użyj tego tekstu" z kolorem API
            use_button = ctk.CTkButton(
                api_frame,
                text=f"📋 Użyj {name}",
                command=lambda idx=i: self.use_api_result(idx),
                height=35,
                fg_color=color,
                text_color="white",
                hover_color=self.darken_color(color)
            )
            use_button.pack(fill="x", padx=5, pady=(0, 5))
            use_button.configure(state="disabled")
            self.api_buttons.append(use_button)
        
        # Bottom controls
        bottom_frame = ctk.CTkFrame(self.main_frame, height=60)
        bottom_frame.pack(fill="x", padx=5, pady=5)
        bottom_frame.pack_propagate(False)
        
        # Przyciski kontrolne
        control_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        control_frame.pack(expand=True)
        
        self.cancel_all_button = ctk.CTkButton(
            control_frame,
            text="❌ Anuluj wszystko",
            command=self.cancel_all_processing,
            width=140,
            height=40,
            fg_color="#ef4444",
            hover_color="#dc2626",
            state="disabled"
        )
        self.cancel_all_button.pack(side="left", padx=5)
        
        self.settings_button = ctk.CTkButton(
            control_frame,
            text="⚙️ Ustawienia",
            command=self.show_settings,
            width=140,
            height=40
        )
        self.settings_button.pack(side="left", padx=5)
        
        self.minimize_button = ctk.CTkButton(
            control_frame,
            text="🔽 Minimalizuj",
            command=self.minimize_to_tray,
            width=140,
            height=40
        )
        self.minimize_button.pack(side="left", padx=5)
    
    def darken_color(self, hex_color):
        """Przyciemnia kolor hex o 20%."""
        # Konwertuj hex na RGB
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        # Przyciemnij o 20%
        r = int(r * 0.8)
        g = int(g * 0.8)
        b = int(b * 0.8)
        
        # Konwertuj z powrotem na hex
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def load_config(self):
        """Ładuje konfigurację API."""
        try:
            self.api_keys, self.models, self.settings, _ = config_manager.load_config()
            
            # Sprawdź które API są skonfigurowane
            configured = []
            for api in ["OpenAI", "Anthropic", "Gemini", "DeepSeek"]:
                if self.api_keys.get(api, ""):
                    configured.append(api)
            
            if configured:
                self.update_status(f"✅ API gotowe: {', '.join(configured)}")
            else:
                self.update_status("⚠️ Brak API - skonfiguruj w ustawieniach")
                
        except Exception as e:
            logging.error(f"Błąd ładowania konfiguracji: {e}")
            self.update_status("❌ Błąd konfiguracji")
    
    def update_status(self, message):
        """Aktualizuje status."""
        self.status_label.configure(text=message)
        self.update_idletasks()
    
    def handle_hotkey_event(self):
        """Obsługuje Ctrl+Shift+C - pobiera zaznaczony tekst i przetwarza."""
        try:
            # Jeśli już przetwarza - anuluj poprzednie
            if self.processing:
                logging.info("Hotkey: Anulowanie poprzedniego przetwarzania...")
                self.cancel_all_processing()
                time.sleep(0.2)  # Daj czas na anulowanie
            
            # Symuluj Ctrl+C żeby skopiować zaznaczony tekst
            time.sleep(0.1)
            keyboard.send('ctrl+c')
            time.sleep(0.3)  # Czekaj na clipboard
            
            # Pobierz tekst ze schowka
            clipboard_text = pyperclip.paste()
            
            if not clipboard_text or not clipboard_text.strip():
                self.after(0, lambda: self.update_status("⚠️ Brak zaznaczonego tekstu"))
                # Pokaż message box
                self.after(0, lambda: messagebox.showinfo(
                    "Pusty schowek",
                    "Zaznacz tekst i spróbuj ponownie",
                    parent=None
                ))
                return
            
            self.original_text = clipboard_text
            
            # Pokaż okno i przetwórz
            self.after(0, self.show_window)
            self.after(100, lambda: self.process_text_multi_api(clipboard_text))
            
        except Exception as e:
            logging.error(f"Błąd obsługi hotkey: {e}")
            self.after(0, lambda: self.update_status("❌ Błąd hotkey"))
    
    def process_text_multi_api(self, text):
        """Przetwarza tekst używając wszystkich 4 API równocześnie."""
        if self.processing and not self.cancel_flags:
            # Jeśli już przetwarza ale nie anulowano
            self.update_status("⚠️ Już przetwarzam...")
            return
        
        self.processing = True
        self.api_results = {}
        self.cancel_flags = {}  # Reset flag anulowania
        self.current_session_id += 1  # Nowa sesja
        
        # Update session info
        self.session_label.configure(text=f"📝 Sesja: {self.current_session_id}")
        
        # Przygotuj panele
        for i in range(4):
            # Wyczyść tekst
            self.api_text_widgets[i].configure(state="normal")
            self.api_text_widgets[i].delete("1.0", "end")
            self.api_text_widgets[i].insert("1.0", "🔄 Przygotowanie...")
            self.api_text_widgets[i].configure(state="disabled")
            
            # Pokaż loader frame z animacją
            self.api_text_widgets[i].pack_forget()
            self.api_loader_frames[i].pack(fill="both", expand=True)
            
            # Start animation jeśli to AnimatedGIF
            if hasattr(self.api_loaders[i], 'start'):
                self.api_loaders[i].start()
            
            # Pokaż i uruchom progress bar
            self.api_progress_bars[i].pack(side="right", padx=5, fill="x", expand=True)
            self.api_progress_bars[i].set(0)
            self.api_progress_bars[i].start()
            
            # Enable cancel button
            self.api_cancel_buttons[i].configure(state="normal")
            
            # Disable use button
            self.api_buttons[i].configure(state="disabled")
            
            # Reset label
            api_name = ["OpenAI", "Anthropic", "Gemini", "DeepSeek"][i]
            self.api_labels[i].configure(text=f"🤖 {api_name}")
        
        # Enable cancel all button
        self.cancel_all_button.configure(state="normal")
        
        self.update_status("🔄 Wysyłanie do 4 API równocześnie...")
        self.progress_label.configure(text=f"Tekst: {len(text)} znaków")
        self.api_counter_label.configure(text="🤖 API: 0/4")
        
        # Uruchom wątki dla każdego API
        self.api_threads = {}
        session_id = self.current_session_id
        
        apis = [
            (0, "OpenAI", openai_client.popraw_tekst),
            (1, "Anthropic", anthropic_client.popraw_tekst),
            (2, "Gemini", gemini_client.popraw_tekst),
            (3, "DeepSeek", deepseek_client.popraw_tekst)
        ]
        
        for idx, api_name, api_func in apis:
            if self.api_keys.get(api_name):
                self.cancel_flags[idx] = False  # Flaga anulowania
                thread = threading.Thread(
                    target=self._process_single_api,
                    args=(idx, api_name, api_func, text, session_id),
                    daemon=True
                )
                thread.start()
                self.api_threads[idx] = thread
            else:
                self._update_api_result(idx, f"❌ Brak klucza API dla {api_name}", True, 0, session_id)
    
    def _process_single_api(self, idx, api_name, api_func, text, session_id):
        """Przetwarza tekst w pojedynczym API (w wątku)."""
        try:
            start_time = time.time()
            
            # Sprawdzaj co 0.5s czy anulowano
            def check_cancelled():
                return self.cancel_flags.get(idx, False)
            
            # Symuluj możliwość anulowania
            # W prawdziwej implementacji musisz sprawdzać cancel_flag w api_func
            result = None
            error = None
            
            # Uruchom API w osobnym wątku aby móc anulować
            api_thread_result = [None, None]  # [result, error]
            
            def run_api():
                try:
                    api_thread_result[0] = api_func(
                        text,
                        self.api_keys[api_name],
                        self.models.get(api_name, "")
                    )
                except Exception as e:
                    api_thread_result[1] = e
            
            api_thread = threading.Thread(target=run_api)
            api_thread.start()
            
            # Czekaj na wynik lub anulowanie
            while api_thread.is_alive():
                if check_cancelled():
                    logging.info(f"API {api_name} anulowane")
                    # Nie możemy przerwać wątku, ale przestajemy czekać
                    self.after(0, lambda: self._update_api_result(
                        idx, "❌ Anulowano", True, 0, session_id
                    ))
                    return
                time.sleep(0.1)
            
            # Sprawdź wynik
            if api_thread_result[1]:
                raise api_thread_result[1]
            
            result = api_thread_result[0]
            elapsed = time.time() - start_time
            
            # Sprawdź czy to nadal aktualna sesja
            if session_id != self.current_session_id:
                logging.info(f"Ignoruję wynik z nieaktualnej sesji {session_id}")
                return
            
            # Aktualizuj GUI w głównym wątku
            self.after(0, lambda: self._update_api_result(
                idx, result, False, elapsed, session_id
            ))
            
        except Exception as e:
            if session_id == self.current_session_id and not check_cancelled():
                error_msg = f"❌ Błąd: {str(e)}"
                logging.error(f"API {api_name} error: {e}")
                self.after(0, lambda: self._update_api_result(
                    idx, error_msg, True, 0, session_id
                ))
    
    def _update_api_result(self, idx, result, is_error, elapsed_time=0, session_id=0):
        """Aktualizuje wynik dla danego API."""
        # Sprawdź czy to aktualna sesja
        if session_id != 0 and session_id != self.current_session_id:
            logging.info(f"Ignoruję nieaktualny wynik z sesji {session_id}")
            return
        
        # Stop animation
        if hasattr(self.api_loaders[idx], 'stop'):
            self.api_loaders[idx].stop()
        
        # Hide loader, show text
        self.api_loader_frames[idx].pack_forget()
        self.api_text_widgets[idx].pack(fill="both", expand=True)
        
        # Stop progress bar
        self.api_progress_bars[idx].stop()
        self.api_progress_bars[idx].set(1.0 if not is_error else 0)
        
        # Update text
        self.api_text_widgets[idx].configure(state="normal")
        self.api_text_widgets[idx].delete("1.0", "end")
        self.api_text_widgets[idx].insert("1.0", result)
        self.api_text_widgets[idx].configure(state="disabled")
        
        # Disable cancel button
        self.api_cancel_buttons[idx].configure(state="disabled")
        
        # Store result and enable button if success
        api_name = ["OpenAI", "Anthropic", "Gemini", "DeepSeek"][idx]
        
        if not is_error:
            self.api_results[idx] = result
            self.api_buttons[idx].configure(state="normal")
            
            # Update label with time
            if elapsed_time > 0:
                self.api_labels[idx].configure(text=f"✅ {api_name} ({elapsed_time:.1f}s)")
            else:
                self.api_labels[idx].configure(text=f"✅ {api_name}")
        else:
            self.api_labels[idx].configure(text=f"❌ {api_name}")
        
        # Update API counter
        finished_count = len(self.api_results) + sum(
            1 for w in self.api_text_widgets 
            if "❌" in w.get("1.0", "end-1c")
        )
        self.api_counter_label.configure(text=f"🤖 API: {finished_count}/4")
        
        # Check if all APIs finished
        if finished_count >= 4:
            self.processing = False
            self.cancel_all_button.configure(state="disabled")
            
            # Hide all progress bars
            for pb in self.api_progress_bars:
                pb.stop()
                pb.pack_forget()
            
            if len(self.api_results) > 0:
                self.update_status(f"✅ Gotowe! Otrzymano {len(self.api_results)} wyników")
                self.progress_label.configure(text="Wybierz najlepszy wynik i kliknij 'Użyj'")
            else:
                self.update_status("❌ Nie otrzymano żadnych wyników")
                self.progress_label.configure(text="Sprawdź klucze API w ustawieniach")
    
    def cancel_single_api(self, idx):
        """Anuluje pojedyncze API."""
        if idx in self.api_threads and self.api_threads[idx].is_alive():
            self.cancel_flags[idx] = True
            logging.info(f"Anulowanie API {idx}")
    
    def cancel_all_processing(self):
        """Anuluje wszystkie przetwarzania."""
        logging.info("Anulowanie wszystkich API...")
        
        # Ustaw flagi anulowania
        for idx in range(4):
            self.cancel_flags[idx] = True
        
        # Czekaj chwilę na zakończenie
        time.sleep(0.1)
        
        # Reset UI
        for i in range(4):
            # Stop animations
            if hasattr(self.api_loaders[i], 'stop'):
                self.api_loaders[i].stop()
            
            # Hide loaders, show text
            self.api_loader_frames[i].pack_forget()
            self.api_text_widgets[i].pack(fill="both", expand=True)
            
            # Update text
            self.api_text_widgets[i].configure(state="normal")
            self.api_text_widgets[i].delete("1.0", "end")
            self.api_text_widgets[i].insert("1.0", "❌ Anulowano")
            self.api_text_widgets[i].configure(state="disabled")
            
            # Stop progress bars
            self.api_progress_bars[i].stop()
            self.api_progress_bars[i].pack_forget()
            
            # Disable buttons
            self.api_cancel_buttons[i].configure(state="disabled")
            self.api_buttons[i].configure(state="disabled")
            
            # Reset labels
            api_name = ["OpenAI", "Anthropic", "Gemini", "DeepSeek"][i]
            self.api_labels[i].configure(text=f"🤖 {api_name}")
        
        self.processing = False
        self.cancel_all_button.configure(state="disabled")
        self.update_status("❌ Anulowano przetwarzanie")
        self.progress_label.configure(text="")
        self.api_counter_label.configure(text="🤖 API: 0/4")
    
    def use_api_result(self, idx):
        """Używa wyniku z wybranego API - kopiuje do schowka i symuluje Ctrl+V."""
        if idx not in self.api_results:
            return
        
        selected_text = self.api_results[idx]
        
        # Kopiuj do schowka
        pyperclip.copy(selected_text)
        
        # Minimalizuj okno
        self.minimize_to_tray()
        
        # Poczekaj chwilę i symuluj Ctrl+V
        def paste_text():
            time.sleep(0.3)
            keyboard.send('ctrl+v')
        
        # Uruchom w osobnym wątku
        paste_thread = threading.Thread(target=paste_text)
        paste_thread.daemon = True
        paste_thread.start()
        
        # Update status
        api_name = ["OpenAI", "Anthropic", "Gemini", "DeepSeek"][idx]
        self.update_status(f"✅ Użyto tekstu z {api_name} i wklejono")
        
        logging.info(f"Użyto wyniku z {api_name}, wykonano auto-paste")
    
    def show_settings(self):
        """Pokazuje okno ustawień."""
        settings_window = SettingsWindow(self)
        settings_window.grab_set()
    
    def minimize_to_tray(self):
        """Minimalizuje do system tray."""
        self.withdraw()
        if tray_icon:
            # Pokaż notyfikację
            try:
                tray_icon.notify(
                    "PoprawiaczTekstuPy",
                    "Aplikacja działa w tle. Ctrl+Shift+C aby poprawić tekst."
                )
            except:
                pass
    
    def show_window(self):
        """Pokazuje okno z tray."""
        self.deiconify()
        self.lift()
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        
        self.title("Ustawienia API")
        self.geometry("500x500")
        self.resizable(False, False)
        
        self.transient(parent)
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        """Konfiguruje interfejs ustawień."""
        main_frame = ctk.CTkScrollableFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        title_label = ctk.CTkLabel(
            main_frame, 
            text="Konfiguracja kluczy API",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        title_label.pack(pady=(0, 20))
        
        # API configs with colors
        self.entries = {}
        
        apis = [
            ("OpenAI", "OpenAI API Key", "sk-...", "#10a37f"),
            ("Anthropic", "Anthropic API Key", "sk-ant-...", "#d97706"),
            ("Gemini", "Gemini API Key", "AIza...", "#4285f4"),
            ("DeepSeek", "DeepSeek API Key", "sk-...", "#7c3aed")
        ]
        
        for api_key, label, placeholder, color in apis:
            frame = ctk.CTkFrame(main_frame, fg_color=color, corner_radius=10)
            frame.pack(fill="x", pady=10)
            
            ctk.CTkLabel(
                frame,
                text=label,
                font=ctk.CTkFont(weight="bold"),
                text_color="white"
            ).pack(anchor="w", padx=15, pady=(10, 5))
            
            entry = ctk.CTkEntry(
                frame,
                placeholder_text=placeholder,
                show="*",
                height=35,
                fg_color="white",
                text_color="black"
            )
            entry.pack(fill="x", padx=15, pady=(0, 10))
            self.entries[api_key] = entry
        
        # Buttons
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill="x", pady=20)
        
        save_button = ctk.CTkButton(
            button_frame,
            text="💾 Zapisz",
            command=self.save_settings,
            height=40,
            fg_color="#10a37f",
            hover_color="#0e8968"
        )
        save_button.pack(side="left", padx=5)
        
        cancel_button = ctk.CTkButton(
            button_frame,
            text="❌ Anuluj",
            command=self.destroy,
            height=40,
            fg_color="#ef4444",
            hover_color="#dc2626"
        )
        cancel_button.pack(side="right", padx=5)
    
    def load_settings(self):
        """Ładuje istniejące ustawienia."""
        for api_key, entry in self.entries.items():
            if self.parent.api_keys.get(api_key):
                entry.insert(0, self.parent.api_keys[api_key])
    
    def save_settings(self):
        """Zapisuje ustawienia."""
        try:
            # Update API keys
            for api_key, entry in self.entries.items():
                self.parent.api_keys[api_key] = entry.get().strip()
            
            # Save to file
            config_manager.save_config(
                self.parent.api_keys,
                self.parent.models,
                self.parent.settings
            )
            
            # Reload config in parent
            self.parent.load_config()
            
            # Show success message
            messagebox.showinfo("Sukces", "Ustawienia zostały zapisane", parent=self)
            
            self.destroy()
            
        except Exception as e:
            logging.error(f"Błąd zapisywania ustawień: {e}")
            messagebox.showerror("Błąd", f"Nie udało się zapisać: {e}", parent=self)

def create_tray_icon(app):
    """Tworzy ikonę w system tray."""
    global tray_icon
    
    try:
        # Load icon
        icon_path = os.path.join(get_assets_dir_path(), "icon.ico")
        if os.path.exists(icon_path):
            image = Image.open(icon_path)
        else:
            # Fallback - create simple icon
            image = Image.new('RGB', (64, 64), color='#10a37f')
        
        # Tray menu
        menu = pystray.Menu(
            pystray.MenuItem("📱 Pokaż aplikację", lambda: app.after(0, app.show_window)),
            pystray.MenuItem("🔽 Minimalizuj", lambda: app.after(0, app.minimize_to_tray)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙️ Ustawienia", lambda: app.after(0, app.show_settings)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Zakończ", lambda: quit_app())
        )
        
        tray_icon = pystray.Icon(
            "PoprawiaczTekstuPy",
            image,
            "PoprawiaczTekstuPy\nCtrl+Shift+C - popraw tekst",
            menu=menu
        )
        
        # Start tray icon
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
        log_file = os.path.join(log_dir, f"app_corrector_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        logging.info(f"Multi-API Corrector logs: {log_file}")
    except Exception as e:
        print(f"Logging error: {e}")

def setup_global_hotkey(app):
    """Konfiguruje globalny hotkey Ctrl+Shift+C."""
    logging.info("Konfiguracja globalnego skrótu Ctrl+Shift+C...")
    
    try:
        hotkey_processor = get_hotkey_processor()
        
        def hotkey_callback():
            app.handle_hotkey_event()
        
        success = hotkey_processor.setup_hotkey_with_fallback(hotkey_callback)
        
        if success:
            logging.info("Globalny skrót skonfigurowany pomyślnie")
            app.after(0, lambda: app.update_status("✅ Ctrl+Shift+C aktywny - zaznacz tekst i naciśnij"))
        else:
            logging.warning("Nie udało się skonfigurować hotkey")
            app.after(0, lambda: app.update_status("⚠️ Hotkey niedostępny - skonfiguruj ręcznie"))
            
    except Exception as e:
        logging.error(f"Błąd konfiguracji hotkey: {e}")

def main():
    global main_app
    
    setup_logging()
    logging.info("=== PoprawiaczTekstuPy Multi-API Start ===")
    
    try:
        # Tworzenie aplikacji
        main_app = MultiAPICorrector()
        
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