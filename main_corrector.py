#!/usr/bin/env python3
"""
PoprawiaczTekstuPy - CustomTkinter version with ORIGINAL multi-API functionality
Pełna funkcjonalność: animacje, anulowanie, tray, kolory, auto-paste
"""

import sys
import os
import logging
from datetime import datetime
import difflib
import re
import customtkinter as ctk
import pystray
from PIL import Image, ImageTk
import threading
import time
import queue
import asyncio
import tkinter as tk
from tkinter import messagebox
from utils import config_manager
from utils.hotkey_manager import get_hotkey_processor, cleanup_global_hotkey
from api_clients import openai_client, anthropic_client, gemini_client, deepseek_client

# Import debug moved to main() after setup_logging()
import httpx
import pyperclip
import keyboard
from gui.prompts import get_system_prompt, get_instruction_prompt
from utils.model_fetcher import fetch_models_for_provider, get_default_model
from utils.build_info import get_app_version

# Globalne zmienne
main_app = None
tray_icon = None


def _safe_update_idletasks(widget):
    """Safely update idle tasks for a widget, ignoring errors."""
    if widget is None:
        return
    try:
        widget.update_idletasks()
    except Exception:
        pass


def _get_display_bounds(widget):
    """Return the usable display bounds (left, top, right, bottom) for a widget."""
    if widget is None:
        return 0, 0, 0, 0

    _safe_update_idletasks(widget)

    # Start with Tk's notion of the virtual root to cover multi-monitor setups
    try:
        left = int(widget.winfo_vrootx())
        top = int(widget.winfo_vrooty())
        width = int(widget.winfo_vrootwidth())
        height = int(widget.winfo_vrootheight())
        if width <= 0 or height <= 0:
            raise ValueError
        right = left + width
        bottom = top + height
    except Exception:
        screen_width = int(widget.winfo_screenwidth())
        screen_height = int(widget.winfo_screenheight())
        left, top = 0, 0
        right = left + max(1, screen_width)
        bottom = top + max(1, screen_height)

    # On Windows try to detect the monitor that hosts the widget and use its work area
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            MONITOR_DEFAULTTONEAREST = 2
            hwnd = widget.winfo_id()
            monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            def _detect_monitor_scale(monitor_handle):
                """Return the Windows scaling factor for the given monitor as a float."""
                try:
                    shcore = ctypes.windll.shcore
                except Exception:
                    shcore = None

                scale_value = None

                if shcore is not None:
                    try:
                        # GetScaleFactorForMonitor is available since Windows 8.1.
                        get_scale = getattr(shcore, "GetScaleFactorForMonitor", None)
                        if get_scale is not None:
                            scale = ctypes.c_uint()
                            # Returns 0 on success and the scale in percent (e.g. 150).
                            if get_scale(monitor_handle, ctypes.byref(scale)) == 0:
                                scale_value = max(1, int(scale.value)) / 100.0
                    except Exception:
                        scale_value = None

                if scale_value:
                    return scale_value

                try:
                    # Fallback to system DPI if per-monitor API is unavailable.
                    get_dpi_for_system = getattr(ctypes.windll.user32, "GetDpiForSystem", None)
                    if get_dpi_for_system is not None:
                        dpi = int(get_dpi_for_system())
                        if dpi > 0:
                            return dpi / 96.0
                except Exception:
                    pass

                try:
                    # Tk exposes its own scaling factor (pixels per point).
                    tk_scaling = float(widget.tk.call("tk", "scaling"))
                    if tk_scaling > 0:
                        # Convert pixels-per-point to the Windows notion of scale.
                        return tk_scaling / (96.0 / 72.0)
                except Exception:
                    pass

                return 1.0

            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
                scale_factor = _detect_monitor_scale(monitor)
                if not scale_factor or scale_factor <= 0:
                    scale_factor = 1.0

                left = int(round(work.left / scale_factor))
                top = int(round(work.top / scale_factor))
                right = int(round(work.right / scale_factor))
                bottom = int(round(work.bottom / scale_factor))
        except Exception:
            pass

    if right <= left:
        right = left + max(1, int(widget.winfo_screenwidth()))
    if bottom <= top:
        bottom = top + max(1, int(widget.winfo_screenheight()))

    return left, top, right, bottom


def _get_display_area(widget):
    """Return (width, height) for the usable display that hosts the widget."""
    left, top, right, bottom = _get_display_bounds(widget)
    return max(1, right - left), max(1, bottom - top)


def _get_widget_root_geometry(widget, fallback):
    """Return (x, y, width, height) for the widget or fall back to defaults."""
    if widget is None:
        return fallback

    _safe_update_idletasks(widget)
    try:
        width = int(widget.winfo_width())
        height = int(widget.winfo_height())
        x = int(widget.winfo_rootx())
        y = int(widget.winfo_rooty())
        if width <= 1 or height <= 1:
            raise ValueError
        return x, y, width, height
    except Exception:
        return fallback


def _compute_child_geometry(
    reference_widget,
    desired_width,
    desired_height,
    min_width=320,
    min_height=240,
    padding_x=0,
    padding_y=0,
):
    """Compute a geometry tuple constrained to the monitor of the reference widget."""
    if reference_widget is None:
        raise ValueError("reference_widget cannot be None")

    min_width = max(1, int(min_width))
    min_height = max(1, int(min_height))

    padding_x = max(0, int(padding_x))
    padding_y = max(0, int(padding_y))

    left, top, right, bottom = _get_display_bounds(reference_widget)
    area_width = max(1, right - left)
    area_height = max(1, bottom - top)

    usable_width = min(area_width, max(min_width, area_width - padding_x))
    usable_height = min(area_height, max(min_height, area_height - padding_y))

    desired_width = int(desired_width)
    desired_height = int(desired_height)

    width = int(min(usable_width, max(min_width, desired_width)))
    height = int(min(usable_height, max(min_height, desired_height)))

    fallback = (left, top, area_width, area_height)
    ref_x, ref_y, ref_width, ref_height = _get_widget_root_geometry(reference_widget, fallback)
    if ref_width <= 1 or ref_height <= 1:
        ref_width, ref_height = width, height

    x = ref_x + (ref_width - width) // 2
    y = ref_y + (ref_height - height) // 2

    x = max(left, min(x, right - width))
    y = max(top, min(y, bottom - height))

    return width, height, x, y, area_width, area_height


def _enforce_window_display_bounds(
    window,
    reference_widget,
    min_width=200,
    min_height=200,
    padding_x=0,
    padding_y=0,
):
    """Ensure the window stays fully visible within the reference widget's monitor."""
    if window is None or reference_widget is None:
        return
    try:
        if not window.winfo_exists():
            return
    except Exception:
        return

    _safe_update_idletasks(window)
    current_width = max(min_width, int(window.winfo_width()))
    current_height = max(min_height, int(window.winfo_height()))

    width, height, x, y, area_width, area_height = _compute_child_geometry(
        reference_widget,
        current_width,
        current_height,
        min_width,
        min_height,
        padding_x,
        padding_y,
    )

    geometry_changed = (
        int(window.winfo_width()) != width
        or int(window.winfo_height()) != height
        or int(window.winfo_rootx()) != x
        or int(window.winfo_rooty()) != y
    )

    if geometry_changed:
        window.geometry(f"{width}x{height}+{x}+{y}")

    usable_width = min(area_width, max(min_width, area_width - max(0, int(padding_x))))
    usable_height = min(area_height, max(min_height, area_height - max(0, int(padding_y))))

    window.minsize(int(min(min_width, usable_width)), int(min(min_height, usable_height)))
    window.maxsize(int(usable_width), int(usable_height))

    return area_width, area_height

def get_assets_dir_path():
    """Zwraca ścieżkę do katalogu assets."""
    if getattr(sys, 'frozen', False):
        # PyInstaller
        return os.path.join(sys._MEIPASS, 'assets')
    else:
        # Development
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')

class AnimatedGIF(tk.Label):
    """Widget dla animowanego GIF z lazy loading - oszczędza RAM."""
    def __init__(self, master, path, scale_factor=1.0):
        self.master = master
        self.path = path
        self.scale_factor = scale_factor
        self.frames = []
        self.current_frame = 0
        self.is_running = False
        self.frames_loaded = False  # Lazy loading flag
        
        # Create placeholder image instead of loading GIF immediately
        gif_size = max(120, int(200 * self.scale_factor))
        placeholder = Image.new('RGBA', (gif_size, gif_size), (245, 245, 245, 0))  # Transparent placeholder
        self.placeholder_photo = ImageTk.PhotoImage(placeholder)
        
        super().__init__(
            master, 
            image=self.placeholder_photo,
            borderwidth=0,           # Usuń ramkę
            highlightthickness=0,    # Usuń highlight ring
            relief='flat',           # Płaski relief
            bg='#f5f5f5'            # Dopasuj tło do aplikacji
        )
    
    def _load_frames_lazy(self):
        """Lazy loading GIF frames - ładuje tylko kiedy potrzeba."""
        if self.frames_loaded:
            return
            
        try:
            logging.debug(f"Lazy loading GIF frames: {self.path}")
            
            # Load GIF
            gif = Image.open(self.path)
            
            # Extract frames
            try:
                while True:
                    frame = gif.copy()
                    
                    # Convert to RGBA for transparency support
                    if frame.mode != 'RGBA':
                        frame = frame.convert('RGBA')
                    
                    # Composite na tło aplikacji (#f5f5f5) żeby pozbyć się szarego tła
                    app_bg_color = (245, 245, 245, 255)  # #f5f5f5 w RGBA
                    app_bg = Image.new('RGBA', frame.size, app_bg_color)
                    frame = Image.alpha_composite(app_bg, frame)
                    
                    # Resize with scale factor for different screen sizes
                    gif_size = max(120, int(200 * self.scale_factor))
                    try:
                        frame = frame.resize((gif_size, gif_size), Image.Resampling.LANCZOS)
                    except AttributeError:
                        # Fallback for older PIL versions
                        frame = frame.resize((gif_size, gif_size), Image.LANCZOS)
                    
                    self.frames.append(ImageTk.PhotoImage(frame))
                    gif.seek(len(self.frames))
            except EOFError:
                pass
            
            gif.close()  # Close to free memory
            self.frames_loaded = True
            logging.debug(f"🍾 Lazy loaded {len(self.frames)} GIF frames")
                
        except Exception as e:
            logging.error(f"Błąd lazy loading GIF {self.path}: {e}")
            # Create a simple colored square as fallback
            gif_size = max(120, int(200 * self.scale_factor))
            fallback_image = Image.new('RGB', (gif_size, gif_size), color='blue')
            self.frames = [ImageTk.PhotoImage(fallback_image)]
            self.frames_loaded = True

    def start(self):
        """Start animation - z lazy loading."""
        if not self.frames_loaded:
            self._load_frames_lazy()

        self.is_running = True
        self.animate()

    def stop(self):
        """Stop animation."""
        self.is_running = False

    def preload(self):
        """Wczytuje klatki bez rozpoczynania animacji."""
        if not self.frames_loaded:
            self._load_frames_lazy()

    def cleanup(self):
        """Cleanup frames to free RAM."""
        self.stop()
    
    def animate(self):
        """Animate frames."""
        if not self.is_running or not self.frames:
            return
        
        self.configure(image=self.frames[self.current_frame])
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        
        # Schedule next frame - zsynchronizowane z API polling (500ms / 5 = 100ms)
        self.after(100, self.animate)

class MultiAPICorrector(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Ustaw ikonę okna
        try:
            icon_path = os.path.join(get_assets_dir_path(), "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
                logging.info(f"Ustawiono ikonę okna: {icon_path}")
            else:
                logging.warning(f"Ikona nie znaleziona: {icon_path}")
        except Exception as e:
            logging.error(f"Błąd ustawiania ikony okna: {e}")
        
        # Zmienne do trackingu monitora
        self.last_screen_width = 0
        self.last_screen_height = 0
        self.scale_factor = 1.0
        
        # Konfiguracja głównego okna
        self.app_version = get_app_version()
        self.title(f"PoprawiaczTekstuPy - Multi-API v{self.app_version}")
        self.setup_responsive_window()
        
        # Ustaw theme
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")
        
        # Zmienne
        self.api_keys = {}
        self.models = {}
        self.settings = {}
        self.ai_settings = {}
        self.api_threads = {}
        self.api_results = {}
        self.original_text = ""
        self.original_text_window = None
        self.original_text_textbox = None
        self.processing = False
        self.current_session_id = 0
        self.cancel_flags = {}  # Flagi anulowania dla każdego API
        self.api_cancel_events = {}
        # Guardy anty-duplikacji
        self.result_update_guard = {}  # klucz: (session_id, idx) -> bool
        self.paste_in_progress = False
        self._stream_started_indices = set()
        self.api_names = ["OpenAI", "Anthropic", "Gemini", "DeepSeek"]
        self._diff_word_pattern = re.compile(r"\S+")
        
        # UI - zbuduj cały interfejs
        self.setup_ui()
        self.load_config()
        
        # Protocol dla zamykania okna
        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        
        # PRE-RENDER wszystko w pamięci dla błyskawicznego pokazania
        self.update_idletasks()  # Wyrenderuj wszystkie widżety
        logging.info("🚀 Okno pre-rendered w pamięci - gotowe do natychmiastowego pokazania")
        
        # UKRYJ okno - będzie czekać w RAM!
        self.withdraw()  # Okno ukryte ale w pełni wyrenderowane w pamięci
        
        # Bind window configure events
        self.bind('<Configure>', self.on_window_configure)
    
    def get_screen_dimensions(self):
        """Pobiera wymiary aktualnego ekranu."""
        self.update_idletasks()  # Upewnij się że okno jest zaktualizowane
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        return screen_width, screen_height
    
    def calculate_optimal_size(self, screen_width, screen_height):
        """Oblicza optymalny rozmiar okna dla danej rozdzielczości - zoptymalizowane dla HiDPI."""
        # Wykryj skalowanie DPI dla lepszego dopasowania
        try:
            # Użyj prostej heurystyki - jeśli rozdzielczość > 1600px prawdopodobnie HiDPI
            is_hidpi = screen_width > 1600 or screen_height > 1000

            if is_hidpi:
                # Dla ekranów HiDPI - większy rozmiar ale rozumnie ograniczony
                width_percent = 0.70   # 70% szerokości dla HiDPI (przywrócone)
                height_percent = 0.75  # 75% wysokości dla HiDPI (przywrócone)
                min_width, min_height = 900, 600
            else:
                # Standardowe rozmiary dla normalnych ekranów
                width_percent = 0.75   # 75% szerokości
                height_percent = 0.80  # 80% wysokości
                min_width, min_height = 1000, 700
        except:
            # Fallback - konserwatywne rozmiary
            width_percent = 0.60
            height_percent = 0.70
            min_width, min_height = 800, 500

        optimal_width = int(screen_width * width_percent)
        optimal_height = int(screen_height * height_percent)

        # Maksymalne rozmiary - zmniejszone
        max_width, max_height = 1800, 1200

        # Ogranicz rozmiary
        optimal_width = max(min_width, min(optimal_width, max_width))
        optimal_height = max(min_height, min(optimal_height, max_height))
        
        return optimal_width, optimal_height
    
    def calculate_scale_factor(self, screen_width, screen_height):
        """Oblicza współczynnik skalowania na podstawie rozdzielczości."""
        # Bazowa rozdzielczość (1920x1080)
        base_width, base_height = 1920, 1080
        
        # Oblicz współczynnik skalowania
        width_scale = screen_width / base_width
        height_scale = screen_height / base_height
        
        # Użyj średniej, ale ogranicz zakres
        scale = (width_scale + height_scale) / 2
        scale = max(0.7, min(scale, 1.8))  # Ogranicz między 70% a 180%
        
        return scale
    
    def setup_responsive_window(self):
        """Konfiguruje responsywne okno."""
        screen_width, screen_height = self.get_screen_dimensions()
        optimal_width, optimal_height = self.calculate_optimal_size(screen_width, screen_height)
        self.scale_factor = self.calculate_scale_factor(screen_width, screen_height)
        
        # Ustaw rozmiar i wyśrodkuj okno
        x = (screen_width - optimal_width) // 2
        y = (screen_height - optimal_height) // 2
        
        self.geometry(f"{optimal_width}x{optimal_height}+{x}+{y}")

        # Dynamiczny minimalny rozmiar na podstawie wykrytego DPI
        is_hidpi = screen_width > 1600 or screen_height > 1000
        if is_hidpi:
            self.minsize(900, 600)  # Przywrócony większy minimalny rozmiar dla HiDPI
        else:
            self.minsize(1000, 700)  # Standardowy minimalny rozmiar
        
        # Zapisz aktualne wymiary ekranu
        self.last_screen_width = screen_width
        self.last_screen_height = screen_height
        
        logging.info(f"Window setup: {optimal_width}x{optimal_height}, scale: {self.scale_factor:.2f}")
    
    def on_window_configure(self, event):
        """Handler dla eventów zmiany okna."""
        # Sprawdź tylko dla głównego okna, nie dla sub-widgets
        if event.widget != self:
            return
        
        # Sprawdź czy zmienił się monitor/rozdzielczość
        current_screen_width, current_screen_height = self.get_screen_dimensions()
        
        if (current_screen_width != self.last_screen_width or
            current_screen_height != self.last_screen_height):

            logging.info(f"Monitor change detected: {current_screen_width}x{current_screen_height}")

            # Przeliczy skalowanie
            new_scale = self.calculate_scale_factor(current_screen_width, current_screen_height)

            if abs(new_scale - self.scale_factor) > 0.1:  # Jeśli znacząca zmiana
                self.scale_factor = new_scale
                self.rescale_ui_components()

            # Zaktualizuj zapisane wymiary
            self.last_screen_width = current_screen_width
            self.last_screen_height = current_screen_height

    def _set_original_text(self, text: str) -> None:
        """Aktualizuje przechowywany oryginalny tekst i widok podglądu."""
        self.original_text = text or ""
        self._update_original_text_view()
        if hasattr(self, "original_text_button"):
            try:
                if self.original_text.strip():
                    self.original_text_button.configure(state="normal")
                else:
                    self.original_text_button.configure(state="disabled")
            except Exception:
                pass

    def _update_original_text_view(self) -> None:
        """Odświeża zawartość okna z oryginalnym tekstem (jeśli jest otwarte)."""
        if not self.original_text_window or not self.original_text_textbox:
            return
        try:
            if not self.original_text_window.winfo_exists() or not self.original_text_textbox.winfo_exists():
                return
        except Exception:
            return

        textbox = self.original_text_textbox
        try:
            prev_state = textbox.cget("state")
        except Exception:
            prev_state = "normal"
        if prev_state != "normal":
            textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", self.original_text)
        textbox.yview_moveto(0.0)
        if prev_state != "normal":
            textbox.configure(state=prev_state)

    def _on_original_window_destroy(self, event) -> None:
        """Czyści referencje po zamknięciu okna podglądu oryginalnego tekstu."""
        if event.widget is self.original_text_window:
            self.original_text_window = None
            self.original_text_textbox = None

    def _close_original_text_window(self) -> None:
        """Zamyka okno z oryginalnym tekstem."""
        if self.original_text_window and self.original_text_window.winfo_exists():
            try:
                self.original_text_window.destroy()
            except Exception:
                pass
        self.original_text_window = None
        self.original_text_textbox = None

    def _copy_original_text_to_clipboard(self) -> None:
        """Kopiuje oryginalny tekst do schowka użytkownika."""
        if not self.original_text.strip():
            messagebox.showinfo(
                "Brak tekstu",
                "Brak oryginalnego tekstu do skopiowania.",
                parent=self
            )
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self.original_text)
            self.update()
            self.update_status("📋 Skopiowano oryginalny tekst do schowka")
        except Exception as exc:
            logging.error(f"Nie można skopiować oryginalnego tekstu: {exc}")
            messagebox.showerror(
                "Błąd",
                f"Nie można skopiować oryginalnego tekstu: {exc}",
                parent=self
            )

    def show_original_text_window(self) -> None:
        """Pokazuje okno z pełnym oryginalnym tekstem."""
        if not self.original_text.strip():
            messagebox.showinfo(
                "Brak tekstu",
                "Brak oryginalnego tekstu do wyświetlenia.",
                parent=self
            )
            return

        min_width = 360
        min_height = 280

        area_width, area_height = _get_display_area(self)
        padding_x = min(max(0, int(area_width * 0.08)), max(0, area_width - min_width))
        padding_y = min(max(0, int(area_height * 0.12)), max(0, area_height - min_height))

        max_width = min(area_width, max(min_width, area_width - padding_x))
        max_height = min(area_height, max(min_height, area_height - padding_y))

        # Zmniejszone proporcje dla dialogu "Oryginalny tekst" - lepsze dla HiDPI
        desired_width = min(max_width, max(min_width, int(area_width * 0.45)))  # 45% zamiast 55%
        desired_height = min(max_height, max(min_height, int(area_height * 0.55))) # 55% zamiast 70%

        if self.original_text_window and self.original_text_window.winfo_exists():
            try:
                self.original_text_window.deiconify()
                self.original_text_window.lift()
                self.original_text_window.focus_force()
                # Nie używamy _enforce_window_display_bounds - zapobiega automatycznemu powiększaniu
            except Exception:
                pass
            self._update_original_text_view()
            return

        window = ctk.CTkToplevel(self)
        window.title("Oryginalny tekst")
        window.transient(self)
        width, height, x, y, area_width, area_height = _compute_child_geometry(
            self,
            desired_width,
            desired_height,
            min_width,
            min_height,
            padding_x,
            padding_y,
        )
        window.geometry(f"{width}x{height}+{x}+{y}")
        usable_width = min(area_width, max(min_width, area_width - padding_x))
        usable_height = min(area_height, max(min_height, area_height - padding_y))
        window.minsize(int(min(min_width, usable_width)), int(min(min_height, usable_height)))
        window.maxsize(int(usable_width), int(usable_height))

        window.protocol("WM_DELETE_WINDOW", self._close_original_text_window)
        window.bind("<Destroy>", self._on_original_window_destroy)

        text_container = ctk.CTkFrame(window, fg_color="transparent")
        text_container.pack(fill="both", expand=True, padx=15, pady=(15, 10))

        textbox = ctk.CTkTextbox(
            text_container,
            wrap="word",
            font=ctk.CTkFont(size=13),
            fg_color="white",
            text_color="black"
        )
        textbox.pack(side="left", fill="both", expand=True)
        textbox.insert("1.0", self.original_text)
        textbox.configure(state="disabled")
        textbox.configure(cursor="xterm")

        scrollbar = ctk.CTkScrollbar(
            text_container,
            orientation="vertical",
            command=textbox.yview
        )
        scrollbar.pack(side="right", fill="y", padx=(5, 0))
        textbox.configure(yscrollcommand=scrollbar.set)

        button_frame = ctk.CTkFrame(window, fg_color="transparent")
        button_frame.pack(fill="x", padx=15, pady=(0, 15))

        copy_button = ctk.CTkButton(
            button_frame,
            text="📋 Kopiuj",
            command=self._copy_original_text_to_clipboard,
            width=130,
            height=36
        )
        copy_button.pack(side="right", padx=(10, 0))

        close_button = ctk.CTkButton(
            button_frame,
            text="Zamknij",
            command=self._close_original_text_window,
            width=130,
            height=36
        )
        close_button.pack(side="right")

        self.original_text_window = window
        self.original_text_textbox = textbox
        # NIE UŻYWAMY _enforce_window_display_bounds dla dialogu oryginalnego tekstu
        # aby zapobiec automatycznemu powiększaniu

    def rescale_ui_components(self):
        """Przeskalowuje komponenty UI na podstawie scale_factor."""
        # Przeskaluj czcionki
        base_font_size = 16
        scaled_font_size = max(12, int(base_font_size * self.scale_factor))
        
        if hasattr(self, 'status_label'):
            self.status_label.configure(font=ctk.CTkFont(size=scaled_font_size, weight="bold"))
        
        # Przeskaluj rozmiary animacji GIF
        if hasattr(self, 'api_loaders'):
            new_gif_size = max(120, int(200 * self.scale_factor))
            # Tutaj można by przeładować GIFy z nowym rozmiarem, ale to kosztowne
            # Zostawiamy to jako jest dla wydajności
        
        logging.info(f"UI rescaled with factor: {self.scale_factor:.2f}")

    def setup_ui(self):
        """Konfiguruje interfejs z 4 panelami API."""
        
        # Główny frame
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Top bar - status i info
        top_frame = ctk.CTkFrame(self.main_frame, height=80)
        top_frame.pack(fill="x", padx=5, pady=5)
        top_frame.pack_propagate(False)
        
        # Status label (skalowana czcionka)
        status_font_size = max(12, int(16 * self.scale_factor))
        self.status_label = ctk.CTkLabel(
            top_frame,
            text="⌨️ Ctrl+Shift+C - zaznacz tekst i od razu naciśnij (natychmiastowo!)",
            font=ctk.CTkFont(size=status_font_size, weight="bold")
        )
        self.status_label.pack(pady=(10, 5))
        
        # Session and API counter
        info_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        info_frame.pack()
        
        # Skalowane czcionki dla info labels
        info_font_size = max(10, int(12 * self.scale_factor))
        
        self.session_label = ctk.CTkLabel(
            info_frame,
            text="📝 Sesja: 0",
            font=ctk.CTkFont(size=info_font_size)
        )
        self.session_label.pack(side="left", padx=10)
        
        self.api_counter_label = ctk.CTkLabel(
            info_frame,
            text="🤖 API: 0/4",
            font=ctk.CTkFont(size=info_font_size)
        )
        self.api_counter_label.pack(side="left", padx=10)
        
        self.progress_label = ctk.CTkLabel(
            info_frame,
            text="",
            font=ctk.CTkFont(size=info_font_size)
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
        self.api_action_buttons = []  # Lista przycisków akcji
        self.api_progress_bars = []
        self.api_loaders = []
        self.api_loader_frames = []
        
        # Oryginalne kolory z PyQt6 aplikacji
        api_colors = {
            "OpenAI": "#10a37f",     # Zielony OpenAI
            "Anthropic": "#d97706",   # Pomarańczowy Anthropic
            "Gemini": "#4285f4",      # Niebieski Google
            "DeepSeek": "#7c3aed"     # Fioletowy DeepSeek
        }
        
        for i, name in enumerate(self.api_names):
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

            # Action button (dropdown menu)
            action_button = ctk.CTkOptionMenu(
                header_content,
                values=["⚙️ Akcje", "✨ Profesjonalizuj", "🇺🇸 Na angielski", "🇵🇱 Na polski"],
                width=120,
                height=25,
                fg_color="#ffffff20",
                button_color="#ffffff30",
                button_hover_color="#ffffff40",
                text_color="white",
                command=lambda value, idx=i: self.handle_action_menu(idx, value)
            )
            action_button.pack(side="right", padx=5)
            action_button.set("⚙️ Akcje")  # Default value
            self.api_action_buttons.append(action_button)

            # Cancel button for single API
            cancel_btn = ctk.CTkButton(
                header_content,
                text="✖",
                width=30,
                height=25,
                fg_color="transparent",
                hover_color="#f0f0f0",
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
                fg_color="#e0e0e0"
            )
            progress_bar.pack(side="right", padx=5, fill="x", expand=True)
            progress_bar.set(0)
            progress_bar.pack_forget()  # Ukryj na początku
            self.api_progress_bars.append(progress_bar)
            
            # Content frame - zawiera oba widoki
            content_frame = ctk.CTkFrame(api_frame, fg_color="#f5f5f5", corner_radius=5)
            content_frame.pack(fill="both", expand=True, padx=5, pady=5)
            
            # Loader frame (dla animacji GIF) - przezroczysty, ZAWSZE obecny, bez ramek
            loader_frame = ctk.CTkFrame(content_frame, fg_color="transparent", border_width=0)
            loader_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.api_loader_frames.append(loader_frame)
            
            # Animated GIF loader (skalowany)
            gif_path = os.path.join(get_assets_dir_path(), "loader.gif")
            if os.path.exists(gif_path):
                loader = AnimatedGIF(loader_frame, gif_path, self.scale_factor)
                loader.pack(expand=True)
                self.api_loaders.append(loader)
            else:
                # Fallback - zwykły label z przeskalowaną czcionką
                fallback_font_size = max(16, int(24 * self.scale_factor))
                loader = tk.Label(
                    loader_frame, 
                    text="⏳\nŁadowanie...", 
                    bg="white",
                    font=("Arial", fallback_font_size, "bold"),
                    fg="#666666",
                    justify="center"
                )
                loader.pack(expand=True, fill="both")
                
                # Add dummy cleanup method for compatibility
                loader.cleanup = lambda: None
                
                self.api_loaders.append(loader)
            
            # Text widget dla wyniku - ZAWSZE obecny
            text_widget = ctk.CTkTextbox(
                content_frame,
                wrap="word",
                font=ctk.CTkFont(size=12),
                fg_color="white",
                text_color="black"
            )
            text_widget.place(relx=0, rely=0, relwidth=1, relheight=1, in_=content_frame)
            text_widget.insert("1.0", f"Oczekiwanie na tekst...")
            text_widget.configure(state="disabled")
            self.api_text_widgets.append(text_widget)

            # Na początek pokaż text widget ponad loaderem
            text_widget.lift()
            
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

        self.original_text_button = ctk.CTkButton(
            control_frame,
            text="📄 Oryginalny tekst",
            command=self.show_original_text_window,
            width=160,
            height=40,
            state="disabled"
        )
        self.original_text_button.pack(side="left", padx=5)

        self.paste_button = ctk.CTkButton(
            control_frame,
            text="📋 Wklej tekst",
            command=self.paste_and_process,
            width=140,
            height=40,
            fg_color="#16a34a",
            hover_color="#15803d"
        )
        self.paste_button.pack(side="left", padx=5)
        
        self.minimize_button = ctk.CTkButton(
            control_frame,
            text="🔽 Minimalizuj",
            command=self.minimize_to_tray,
            width=140,
            height=40
        )
        self.minimize_button.pack(side="left", padx=5)

        self._preload_loader_gifs()
    
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

    def _preload_loader_gifs(self):
        """Preloads loader GIFs while okno jest jeszcze ukryte."""
        for loader in self.api_loaders:
            if hasattr(loader, 'preload'):
                try:
                    loader.preload()
                except Exception as exc:
                    logging.debug(f"Preload loader GIF failed: {exc}")
    
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
            
            # Sprawdź które API są skonfigurowane
            configured = []
            for api in self.api_names:
                if self.api_keys.get(api, ""):
                    configured.append(api)
            
            if configured:
                self.update_status(f"✅ API gotowe: {', '.join(configured)}")
                # Debug info o modelach
                logging.info(f"🔍 DEBUG: Configured models: {self.models}")
                for provider, model in self.models.items():
                    if self.api_keys.get(provider, '').strip():
                        logging.info(f"🔍 DEBUG: {provider} -> {model}")
            else:
                self.update_status("⚠️ Brak API - skonfiguruj w ustawieniach")

            self.refresh_diff_highlights()

        except Exception as e:
            logging.error(f"Błąd ładowania konfiguracji: {e}")
            self.update_status("❌ Błąd konfiguracji")
    
    def update_status(self, message):
        """Aktualizuje status."""
        self.status_label.configure(text=message)
        self.update_idletasks()
    
    def handle_hotkey_event(self):
        """Obsługuje Ctrl+Shift+C - NAJPIERW kopiuje tekst, POTEM pokazuje GUI."""
        try:
            logging.info("🚀 Hotkey detected - clipboard copy FIRST, GUI AFTER")
            
            # Jeśli już przetwarza - anuluj poprzednie
            if self.processing:
                logging.info("Hotkey: Quick cancel poprzedniego przetwarzania...")
                self.cancel_all_processing()
                time.sleep(0.1)  # Zmniejszony delay
            
            # KLUCZOWE: Szybkie kopiowanie W TLE - okno NADAL UKRYTE!
            # Oryginalna aplikacja ma focus, zaznaczenie nie zostanie utracone
            logging.info("🚀 Quick clipboard copy - okno ukryte, focus w oryginalnej app")
            clipboard_text = ""
            
            try:
                clipboard_text = self._robust_clipboard_copy()
                        
            except Exception as e:
                logging.warning(f"Background clipboard copy failed: {e}")
            
            # Uproszczone sprawdzenie - nie sprawdzamy czy ten sam tekst!
            if not clipboard_text or not clipboard_text.strip():
                logging.warning("Clipboard copy failed - pokażę GUI z błędem")
                
                # FAILURE: Pokaż GUI z komunikatem o błędzie
                self._show_gui_with_error()
                return
            
            # SUCCESS: Mamy tekst! Pokaż GUI i rozpocznij przetwarzanie
            logging.info(f"✅ Clipboard copy SUCCESS - {len(clipboard_text)} znaków")
            self._set_original_text(clipboard_text)
            
            # DOPIERO TERAZ pokaż GUI - po udanym kopiowaniu!
            self._show_gui_and_process(clipboard_text)
            
        except Exception as e:
            logging.error(f"Błąd obsługi hotkey: {e}")
            self.after(0, lambda: self.update_status("❌ Błąd hotkey"))
    
    def _show_gui_with_error(self):
        """Pokazuje GUI z komunikatem o błędzie kopiowania."""
        # Pokaż okno
        self.deiconify()
        self.lift()
        self.focus_force()
        
        self.after(0, lambda: self.update_status("⚠️ Brak zaznaczonego tekstu"))
        logging.warning("Kopiowanie w tle nie powiodło się")
        
        # Pokaż message box z instrukcjami
        self.after(100, lambda: messagebox.showinfo(
            "Nie skopiowano tekstu",
            "Nie udało się skopiować zaznaczonego tekstu w tle.\n\n"
            "💡 NOWA STRATEGIA: Clipboard copy PRZED pokazaniem GUI!\n\n"
            "🎯 Workflow:\n"
            "1. Zaznacz tekst myszką/klawiaturą\n"
            "2. Naciśnij Ctrl+Shift+C\n"
            "3. GUI pojawi się DOPIERO po kopiowaniu\n\n"
            "🔧 Alternatywne rozwiązanie:\n"
            "1. Zaznacz tekst i skopiuj ręcznie (Ctrl+C)\n"
            "2. Użyj przycisku '📋 Wklej tekst'\n\n"
            "Za chwilę okno zostanie ukryte.",
            parent=self
        ))
        
        # Okno pozostaje otwarte do momentu wyboru wyniku lub anulowania
    
    def _show_gui_and_process(self, clipboard_text):
        """Pokazuje GUI i rozpoczyna przetwarzanie po udanym kopiowaniu."""
        logging.info("🔧 Preparing loading state BEFORE showing GUI...")
        self.process_text_multi_api(clipboard_text, force_show=True)

    def _prepare_processing_session(self, text, status_message):
        """Resetuje UI i ustawia wszystkie panele w stan ładowania."""
        # Zatrzymaj ewentualne poprzednie strumienie
        for event in self.api_cancel_events.values():
            try:
                event.set()
            except Exception:
                pass

        self.processing = True
        self.api_results = {}
        self.cancel_flags = {}
        self.api_cancel_events = {}
        self.current_session_id += 1
        self._stream_started_indices.clear()
        self._set_original_text(text)

        self.update_status(status_message)
        self.session_label.configure(text=f"📝 Sesja: {self.current_session_id}")
        self.progress_label.configure(text=f"Tekst: {len(text)} znaków")
        self.api_counter_label.configure(text="🤖 API: 0/4")

        for i, api_name in enumerate(self.api_names):
            self.api_cancel_events[i] = threading.Event()
            text_widget = self.api_text_widgets[i]
            text_widget.configure(state="normal")
            text_widget.delete("1.0", "end")
            text_widget.insert("1.0", "🔄 Przygotowanie...")
            text_widget.configure(state="disabled")
            text_widget.tag_remove("diff_highlight", "1.0", "end")

            loader_frame = self.api_loader_frames[i]
            loader_frame.lift()

            loader = self.api_loaders[i]
            if hasattr(loader, 'start'):
                loader.start()

            progress_bar = self.api_progress_bars[i]
            progress_bar.pack(side="right", padx=5, fill="x", expand=True)
            progress_bar.set(0)

            self.api_cancel_buttons[i].configure(state="normal")
            self.api_buttons[i].configure(state="disabled")
            self.api_action_buttons[i].configure(state="disabled")
            self.api_labels[i].configure(text=f"🤖 {api_name}")

        self.cancel_all_button.configure(state="normal")

    def _append_partial(self, idx, chunk_text, session_id):
        """Bezpiecznie dokleja fragment strumienia do panelu API w aktualnej sesji."""
        if session_id != self.current_session_id:
            return
        if self.cancel_flags.get(idx, False):
            return

        # ASYNCHRONICZNY streaming - używam after() aby nie blokować wątku API
        def do_append():
            if session_id != self.current_session_id:
                return
            # Przełącz z loadera na textbox przy pierwszym fragmencie
            if idx not in self._stream_started_indices:
                # Ukryj loader i pokaż textbox
                try:
                    self.api_text_widgets[idx].lift()
                except Exception:
                    pass
                # Wyczyść placeholder
                try:
                    self.api_text_widgets[idx].configure(state="normal")
                    self.api_text_widgets[idx].delete("1.0", "end")
                    self.api_text_widgets[idx].configure(state="disabled")
                except Exception:
                    pass
                self._stream_started_indices.add(idx)

            # Doklej fragment
            try:
                self.api_text_widgets[idx].configure(state="normal")
                self.api_text_widgets[idx].insert("end", chunk_text)
                self.api_text_widgets[idx].see("end")
                self.api_text_widgets[idx].configure(state="disabled")
            except Exception:
                pass
        
        # ASYNCHRONICZNY UPDATE - nie blokuje wątku API
        self.after(0, do_append)

    def _is_diff_highlighting_enabled(self) -> bool:
        value = str(self.settings.get("HighlightDiffs", "0")).strip().lower()
        return value in {"1", "true", "yes", "on"}

    def _get_textbox_state(self, widget):
        """Zwraca aktualny stan CTkTextbox bez rzucania ValueError."""
        try:
            return widget.cget("state")
        except (ValueError, AttributeError):
            try:
                return widget._textbox.cget("state")
            except Exception:
                return "normal"

    def _highlight_diff(self, idx: int, original: str, corrected: str) -> None:
        widget = self.api_text_widgets[idx]
        prev_state = self._get_textbox_state(widget)
        if prev_state != "normal":
            widget.configure(state="normal")
        try:
            widget.tag_remove("diff_highlight", "1.0", "end")
            if not self._is_diff_highlighting_enabled():
                return
            if not original.strip() or not corrected.strip():
                return

            orig_tokens = [m.group() for m in self._diff_word_pattern.finditer(original)]
            corr_matches = list(self._diff_word_pattern.finditer(corrected))
            if not corr_matches:
                return
            corr_tokens = [m.group() for m in corr_matches]
            matcher = difflib.SequenceMatcher(None, orig_tokens, corr_tokens)
            widget.tag_config("diff_highlight", underline=1, foreground="#d93025")
            for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
                if tag not in ("replace", "insert"):
                    continue
                if j1 >= len(corr_matches) or j1 == j2:
                    continue
                end_index = min(j2 - 1, len(corr_matches) - 1)
                start = corr_matches[j1].start()
                end = corr_matches[end_index].end()
                widget.tag_add("diff_highlight", f"1.0+{start}c", f"1.0+{end}c")
        finally:
            if prev_state != "normal":
                widget.configure(state=prev_state)

    def refresh_diff_highlights(self):
        if not hasattr(self, "api_text_widgets"):
            return
        for idx, widget in enumerate(self.api_text_widgets):
            prev_state = self._get_textbox_state(widget)
            widget.configure(state="normal")
            text = widget.get("1.0", "end-1c")
            widget.tag_remove("diff_highlight", "1.0", "end")
            if self._is_diff_highlighting_enabled() and text.strip() and not text.startswith("❌") and not text.startswith("🔄"):
                try:
                    self._highlight_diff(idx, self.original_text or "", text)
                except Exception:
                    logging.debug("Highlight diff failed", exc_info=True)
            if prev_state != "normal":
                widget.configure(state=prev_state)

    def _start_api_threads(self, text):
        """Uruchamia API threads - UI już przygotowane!"""
        logging.info("🚀 Starting API threads with pre-rendered UI")
        
        # Uruchom wątki dla każdego API
        self.api_threads = {}
        session_id = self.current_session_id
        
        apis = [
            (0, "OpenAI", openai_client.correct_text_openai),
            (1, "Anthropic", anthropic_client.correct_text_anthropic),
            (2, "Gemini", gemini_client.correct_text_gemini),
            (3, "DeepSeek", deepseek_client.correct_text_deepseek)
        ]
        
        # Debug: podgląd przypisanych funkcji API
        for idx, api_name, api_func in apis:
            logging.debug(
                "API slot %s -> %s",
                idx,
                api_func.__name__ if hasattr(api_func, '__name__') else api_func,
            )
        
        for idx, api_name, api_func in apis:
            if self.api_keys.get(api_name):
                logging.info(f"🔍 DEBUG: Starting thread for {api_name} with model: {self.models.get(api_name, 'unknown')}")
                self.cancel_flags[idx] = False  # Flaga anulowania
                thread = threading.Thread(
                    target=self._process_single_api,
                    args=(idx, api_name, api_func, text, session_id),
                    daemon=True
                )
                thread.start()
                self.api_threads[idx] = thread
            else:
                logging.info(f"🔍 DEBUG: Skipping {api_name} - no API key")
                self._update_api_result(idx, f"❌ Brak klucza API dla {api_name}", True, 0, session_id)
    
    def _robust_clipboard_copy(self, max_retries=2):
        """Szybki clipboard copy - maksymalnie uproszczony."""
        
        for attempt in range(max_retries):
            try:
                logging.debug(f"Quick copy {attempt + 1}/{max_retries}")
                
                # Pynput z minimalnym delay
                from pynput.keyboard import Key, Controller
                kb_controller = Controller()
                
                kb_controller.press(Key.ctrl)
                kb_controller.press('c')
                time.sleep(0.02)  # Minimalny hold
                kb_controller.release('c')
                kb_controller.release(Key.ctrl)
                
                # Krótkie sprawdzenie - max 2 razy
                for check in range(2):  
                    time.sleep(0.02)  # Bardzo krótki delay
                    new_clipboard = pyperclip.paste()
                    
                    if new_clipboard and new_clipboard.strip():
                        logging.info(f"✅ Copy success {attempt + 1}.{check + 1}")
                        return new_clipboard
                
                # Jeśli pierwsze nie powiodło się, krótki retry
                if attempt < max_retries - 1:
                    logging.warning(f"Attempt {attempt + 1} failed - quick retry")
                    time.sleep(0.05)  # Minimalny delay przed retry
                
            except Exception as e:
                logging.warning(f"Copy attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.05)  # Minimalny delay
        
        logging.error("All clipboard copy attempts failed")
        return ""
    
    def process_text_multi_api(self, text, force_show=False):
        """Przetwarza tekst używając wszystkich 4 API równocześnie."""
        if self.processing and not self.cancel_flags:
            self.update_status("⚠️ Już przetwarzam...")
            return

        window_visible = bool(self.winfo_viewable())
        should_show = force_show or not window_visible
        status_message = "📝 Przetwarzanie tekstu..." if should_show else "🔄 Wysyłanie do 4 API równocześnie..."

        if should_show and window_visible:
            # Ukryj okno na czas przebudowy UI, żeby zapobiec migotaniu loaderów
            self.withdraw()
            self.update_idletasks()

        self._prepare_processing_session(text, status_message)

        if should_show:
            self.attributes('-alpha', 0.0)
            self.update_idletasks()
            self.deiconify()
            self.lift()
            self.focus_force()
            self.attributes('-topmost', True)
            self.after(50, lambda: self.attributes('-alpha', 1.0))
            self.after(120, lambda: self.attributes('-topmost', False))

        def launch_threads():
            if status_message != "🔄 Wysyłanie do 4 API równocześnie...":
                self.update_status("🔄 Wysyłanie do 4 API równocześnie...")
            self._start_api_threads(text)

        self.after(1, launch_threads)
    
    def _process_single_api(self, idx, api_name, api_func, text, session_id):
        """Przetwarza tekst w pojedynczym API (w wątku)."""
        try:
            start_time = time.time()
            logging.info(f"🔍 DEBUG: _process_single_api started for {api_name} (idx={idx})")
            
            cancel_event = self.api_cancel_events.get(idx)

            # Sprawdzaj co 0.5s czy anulowano
            def check_cancelled():
                if self.cancel_flags.get(idx, False):
                    return True
                return bool(cancel_event and cancel_event.is_set())
            
            # Symuluj możliwość anulowania
            # W prawdziwej implementacji musisz sprawdzać cancel_flag w api_func
            result = None
            error = None
            
            # Uruchom API w osobnym wątku aby móc anulować
            api_thread_result = [None, None]  # [result, error]
            
            def run_api():
                try:
                    # Get prompts
                    instruction_prompt = get_instruction_prompt("normal")
                    system_prompt = get_system_prompt("normal")
                    
                    logging.info(f"🔍 DEBUG: Calling {api_name} API function with model: {self.models.get(api_name, '')}")
                    logging.debug("Calling %s via %s", api_name, api_func)
                    logging.debug("api_func type: %s", type(api_func))
                    logging.debug(
                        "api_func.__name__: %s",
                        getattr(api_func, '__name__', 'NO_NAME'),
                    )
                    
                    # Call API with correct arguments: (api_key, model, text, instruction_prompt, system_prompt[, on_chunk])
                    logging.debug(
                        "Invoking %s with key=%s chars, model=%s, text_len=%s",
                        api_name,
                        len(self.api_keys[api_name]),
                        self.models.get(api_name, ''),
                        len(text),
                    )
                    
                    # DIRECT INSPECTION of the function being called
                    if api_name == "OpenAI":
                        logging.debug("OpenAI function memory address: %s", hex(id(api_func)))
                        logging.debug(
                            "OpenAI function source: %s",
                            getattr(api_func, '__code__', {}).co_filename
                            if hasattr(api_func, '__code__')
                            else 'NO_CODE',
                        )
                        logging.debug(
                            "OpenAI function first line: %s",
                            getattr(api_func, '__code__', {}).co_firstlineno
                            if hasattr(api_func, '__code__')
                            else 'NO_LINE',
                        )
                    
                    # Jeżeli klient wspiera streaming (on_chunk), przekaż callback
                    callback = (lambda ch, i=idx, s=session_id: self._append_partial(i, ch, s))
                    try:
                        if api_name == "Gemini":
                            api_thread_result[0] = api_func(
                                self.api_keys[api_name],
                                self.models.get(api_name, ""),
                                text,
                                instruction_prompt,
                                system_prompt,
                                on_chunk=callback,
                                cancel_event=cancel_event,
                            )
                        else:
                            api_thread_result[0] = api_func(
                                self.api_keys[api_name],
                                self.models.get(api_name, ""),
                                text,
                                instruction_prompt,
                                system_prompt,
                                on_chunk=callback
                            )
                    except TypeError:
                        # Starsza sygnatura bez on_chunk
                        api_thread_result[0] = api_func(
                            self.api_keys[api_name],
                            self.models.get(api_name, ""),
                            text,
                            instruction_prompt,
                            system_prompt
                        )

                    logging.info(f"🚨 CALL AFTER: {api_name} zwrócił: {type(api_thread_result[0])} - {str(api_thread_result[0])[:100]}...")
                    logging.info(f"🔍 DEBUG: {api_name} API call completed successfully")
                except Exception as e:
                    logging.error(f"🔍 DEBUG: {api_name} API call failed: {e}")
                    api_thread_result[1] = e

            api_thread = threading.Thread(target=run_api)
            api_thread.start()
            
            # Animuj progress bar i czekaj na wynik lub anulowanie
            
            while api_thread.is_alive():
                if check_cancelled():
                    logging.info(f"API {api_name} anulowane")
                    if cancel_event:
                        cancel_event.set()
                    def update_cancel_gui(i=idx, s=session_id):
                        self._update_api_result(i, "❌ Anulowano", True, 0, s)
                    self.after(0, update_cancel_gui)
                    return
                
                # Animuj progress bar 0->100% w ciągu 1s, potem resetuj
                for step in range(20):  # 20 kroków x 50ms = 1s
                    if not api_thread.is_alive():
                        break
                    progress = (step + 1) / 20.0  # 0.05, 0.10, ... 1.0
                    self.after(0, lambda i=idx, v=progress: 
                        self.api_progress_bars[i].set(v) if i < len(self.api_progress_bars) else None
                    )
                    time.sleep(0.05)  # 50ms między krokami
                
                # Reset progress bar na początek po 1s
                if api_thread.is_alive():
                    self.after(0, lambda i=idx: 
                        self.api_progress_bars[i].set(0) if i < len(self.api_progress_bars) else None
                    )
            
            # Sprawdź wynik
            if api_thread_result[1]:
                raise api_thread_result[1]

            result = api_thread_result[0]
            elapsed = time.time() - start_time

            # Sprawdź czy to nadal aktualna sesja
            if session_id != self.current_session_id:
                logging.info(f"Ignoruję wynik z nieaktualnej sesji {session_id}")
                return

            if check_cancelled():
                logging.info(f"API {api_name} zakończone po anulowaniu")
                return
            
            # Aktualizuj GUI w głównym wątku
            def update_gui(i=idx, r=result, e=elapsed, s=session_id):
                self._update_api_result(i, r, False, e, s)
            self.after(0, update_gui)
            
        except Exception as e:
            if session_id == self.current_session_id and not check_cancelled():
                error_msg = f"❌ Błąd: {str(e)}"
                logging.error(f"API {api_name} error: {e}")
                def update_error_gui(i=idx, msg=error_msg, s=session_id):
                    self._update_api_result(i, msg, True, 0, s)
                self.after(0, update_error_gui)
    
    def _update_api_result(self, idx, result, is_error, elapsed_time=0, session_id=0):
        """Aktualizuje wynik dla danego API z opóźnieniem dla płynności."""
        # Anti-dup: ignoruj powtórne aktualizacje tego samego API w tej samej sesji
        guard_key = (session_id or self.current_session_id, idx)
        if self.result_update_guard.get(guard_key):
            return
        self.result_update_guard[guard_key] = True
        # Sprawdź czy to aktualna sesja
        if session_id != 0 and session_id != self.current_session_id:
            logging.info(f"Ignoruję nieaktualny wynik z sesji {session_id}")
            return
        
        # Funkcja do aktualizacji panelu
        def update_panel():
            # Stop animation
            if hasattr(self.api_loaders[idx], 'stop'):
                self.api_loaders[idx].stop()
            
            # Przestaw kolejność widoków bez zmiany położenia
            try:
                self.api_text_widgets[idx].lift()
            except Exception:
                pass
            
            # Zakończ progress bar na 100% (lub 0% przy błędzie)
            self.api_progress_bars[idx].set(1.0 if not is_error else 0)
            
            # Update text
            self.api_text_widgets[idx].configure(state="normal")
            self.api_text_widgets[idx].delete("1.0", "end")
            self.api_text_widgets[idx].insert("1.0", result)
            if is_error:
                self.api_text_widgets[idx].tag_remove("diff_highlight", "1.0", "end")
            else:
                try:
                    self._highlight_diff(idx, self.original_text or "", result)
                except Exception:
                    logging.debug("Highlight diff failed", exc_info=True)
            self.api_text_widgets[idx].configure(state="disabled")
            
            # Disable cancel button
            self.api_cancel_buttons[idx].configure(state="disabled")
            
            # Force update dla płynności
            self.update_idletasks()
        
        # Rozłóż aktualizacje w czasie - każdy panel 30ms później
        self.after(idx * 30, update_panel)
        
        # Store result and enable button if success
        api_name = self.api_names[idx]
        
        if not is_error:
            self.api_results[idx] = result
            self.api_buttons[idx].configure(state="normal")
            self.api_action_buttons[idx].configure(state="normal")
            
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
            # Reset guard po ukończeniu sesji
            self.result_update_guard.clear()
            
            # Hide all progress bars
            for pb in self.api_progress_bars:
                pb.set(1.0)  # Ustaw na 100% przed ukryciem
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
            event = self.api_cancel_events.get(idx)
            if event:
                event.set()
    
    
    def cancel_all_processing(self):
        """Anuluje wszystkie przetwarzania."""
        logging.info("Anulowanie wszystkich API...")
        
        # Ustaw flagi anulowania
        for idx in range(4):
            self.cancel_flags[idx] = True
            event = self.api_cancel_events.get(idx)
            if event:
                event.set()
        
        # Czekaj chwilę na zakończenie
        time.sleep(0.1)
        
        # Reset UI
        for i in range(4):
            # Stop animations
            if hasattr(self.api_loaders[i], 'stop'):
                self.api_loaders[i].stop()
            
            # Przywróć widok tekstu ponad loaderem
            try:
                self.api_text_widgets[i].lift()
            except Exception:
                pass
            
            # Update text
            self.api_text_widgets[i].configure(state="normal")
            self.api_text_widgets[i].delete("1.0", "end")
            self.api_text_widgets[i].insert("1.0", "❌ Anulowano")
            self.api_text_widgets[i].configure(state="disabled")
            self.api_text_widgets[i].tag_remove("diff_highlight", "1.0", "end")
            
            # Zatrzymaj i ukryj progress bar
            self.api_progress_bars[i].set(0)  # Reset na 0% przy anulowaniu
            self.api_progress_bars[i].pack_forget()
            
            # Disable buttons
            self.api_cancel_buttons[i].configure(state="disabled")
            self.api_buttons[i].configure(state="disabled")
            self.api_action_buttons[i].configure(state="disabled")
            
            # Reset labels
            api_name = self.api_names[i]
            self.api_labels[i].configure(text=f"🤖 {api_name}")
        
        self.processing = False
        self.cancel_all_button.configure(state="disabled")
        self.update_status("❌ Anulowano przetwarzanie")
        self.progress_label.configure(text="")
        self.api_counter_label.configure(text="🤖 API: 0/4")

    def handle_action_menu(self, api_index, selected_value):
        """Obsługuje wybór akcji z menu dropdown dla danego panelu API"""
        try:
            # Walidacja indeksu
            if not (0 <= api_index < len(self.api_action_buttons)):
                self.log_message(f"Nieprawidłowy indeks API: {api_index}")
                return

            # Reset menu do domyślnej wartości
            self.api_action_buttons[api_index].set("⚙️ Akcje")

            # Sprawdź czy to pierwsza opcja (która jest tylko etykietą)
            if selected_value == "⚙️ Akcje":
                return

            # Sprawdź czy mamy wynik w tym panelu
            if api_index not in self.api_results:
                self.log_message(f"Brak wyniku w panelu {self.api_names[api_index]} do przetworzenia")
                return

            current_text = self.api_results[api_index].strip()
            if not current_text:
                self.log_message(f"Brak tekstu w panelu {self.api_names[api_index]} do przetworzenia")
                return

            # Określ typ akcji na podstawie wyboru
            if selected_value == "✨ Profesjonalizuj":
                action_type = "professionalize"
                system_prompt = "Zmień ton tego tekstu na profesjonalny, zachowując jego znaczenie i strukturę."
                action_name = "profesjonalizacji"
            elif selected_value == "🇺🇸 Na angielski":
                action_type = "translate_to_en"
                system_prompt = "Przetłumacz ten tekst na język angielski, zachowując jego znaczenie i ton."
                action_name = "tłumaczenia na angielski"
            elif selected_value == "🇵🇱 Na polski":
                action_type = "translate_to_pl"
                system_prompt = "Przetłumacz ten tekst na język polski, zachowując jego znaczenie i ton."
                action_name = "tłumaczenia na polski"
            else:
                return

            # Uruchom ponowne przetwarzanie dla danego panelu
            self.reprocess_single_panel(api_index, current_text, system_prompt, action_name)

        except Exception as e:
            error_context = f"api_index={api_index}, selected_value='{selected_value}'"
            self.log_message(f"Błąd podczas obsługi akcji menu ({error_context}): {e}")
            print(f"ERROR: handle_action_menu ({error_context}): {e}")

    def reprocess_single_panel(self, api_index, text, system_prompt, action_name):
        """Ponownie przetwarza tekst dla konkretnego panelu z niestandardowym promptem"""
        try:
            api_name = self.api_names[api_index]

            # Wyczyść poprzedni wynik
            if api_index in self.api_results:
                del self.api_results[api_index]

            # Wyłącz przyciski dla tego panelu
            self.api_buttons[api_index].configure(state="disabled")
            self.api_action_buttons[api_index].configure(state="disabled")
            self.api_cancel_buttons[api_index].configure(state="normal")

            # Pokaż loader
            self.api_loader_frames[api_index].lift()
            if hasattr(self.api_loaders[api_index], 'start'):
                self.api_loaders[api_index].start()

            # Aktualizuj status
            self.api_text_widgets[api_index].configure(state="normal")
            self.api_text_widgets[api_index].delete("1.0", "end")
            self.api_text_widgets[api_index].insert("1.0", f"Przetwarzanie {action_name}...")
            self.api_text_widgets[api_index].configure(state="disabled")

            self.log_message(f"Rozpoczęto {action_name} dla {api_name}")

            # Uruchom żądanie API w osobnym wątku
            def run_api_request():
                try:
                    # Sprawdź który API i uruchom odpowiednią funkcję
                    result = None
                    if api_name == "OpenAI":
                        result = openai_client.correct_text_openai(
                            self.api_keys.get("OpenAI", ""),
                            self.current_models.get("OpenAI", "gpt-4o-mini"),
                            text,
                            "custom",
                            system_prompt
                        )
                    elif api_name == "Anthropic":
                        result = anthropic_client.correct_text_anthropic(
                            self.api_keys.get("Anthropic", ""),
                            self.current_models.get("Anthropic", "claude-3-5-sonnet-20241022"),
                            text,
                            "custom",
                            system_prompt
                        )
                    elif api_name == "Gemini":
                        result = gemini_client.correct_text_gemini(
                            self.api_keys.get("Gemini", ""),
                            self.current_models.get("Gemini", "gemini-1.5-flash"),
                            text,
                            "custom",
                            system_prompt
                        )
                    elif api_name == "DeepSeek":
                        result = deepseek_client.correct_text_deepseek(
                            self.api_keys.get("DeepSeek", ""),
                            self.current_models.get("DeepSeek", "deepseek-chat"),
                            text,
                            "custom",
                            system_prompt
                        )

                    # Zaktualizuj GUI w głównym wątku
                    if result:
                        self.root.after(0, lambda: self.handle_single_api_result(api_index, result, action_name))
                    else:
                        self.root.after(0, lambda: self.handle_single_api_error(api_index, f"Brak odpowiedzi z {api_name}", action_name))

                except Exception as e:
                    self.root.after(0, lambda: self.handle_single_api_error(api_index, str(e), action_name))

            # Uruchom w osobnym wątku
            thread = threading.Thread(target=run_api_request, daemon=True)
            thread.start()

        except Exception as e:
            self.log_message(f"Błąd podczas ponownego przetwarzania: {e}")
            print(f"ERROR: reprocess_single_panel: {e}")

    def handle_single_api_result(self, api_index, result, action_name):
        """Obsługuje wynik z ponownego przetworzenia dla pojedynczego panelu"""
        try:
            # Zapisz wynik
            self.api_results[api_index] = result

            # Ukryj loader
            if hasattr(self.api_loaders[api_index], 'stop'):
                self.api_loaders[api_index].stop()
            self.api_text_widgets[api_index].lift()

            # Aktualizuj text widget
            self.api_text_widgets[api_index].configure(state="normal")
            self.api_text_widgets[api_index].delete("1.0", "end")
            self.api_text_widgets[api_index].insert("1.0", result)
            self.api_text_widgets[api_index].configure(state="disabled")

            # Włącz przyciski
            self.api_buttons[api_index].configure(state="normal")
            self.api_action_buttons[api_index].configure(state="normal")
            self.api_cancel_buttons[api_index].configure(state="disabled")

            self.log_message(f"Zakończono {action_name} dla {self.api_names[api_index]}")

        except Exception as e:
            self.log_message(f"Błąd podczas obsługi wyniku {action_name}: {e}")

    def handle_single_api_error(self, api_index, error_message, action_name):
        """Obsługuje błąd z ponownego przetworzenia dla pojedynczego panelu"""
        try:
            # Ukryj loader
            if hasattr(self.api_loaders[api_index], 'stop'):
                self.api_loaders[api_index].stop()
            self.api_text_widgets[api_index].lift()

            # Pokaż błąd
            self.api_text_widgets[api_index].configure(state="normal")
            self.api_text_widgets[api_index].delete("1.0", "end")
            self.api_text_widgets[api_index].insert("1.0", f"Błąd {action_name}: {error_message}")
            self.api_text_widgets[api_index].configure(state="disabled")

            # Włącz wszystkie przyciski po błędzie
            self.api_buttons[api_index].configure(state="normal")
            self.api_action_buttons[api_index].configure(state="normal")
            self.api_cancel_buttons[api_index].configure(state="disabled")

            self.log_message(f"Błąd {action_name} dla {self.api_names[api_index]}: {error_message}")

        except Exception as e:
            self.log_message(f"Błąd podczas obsługi błędu {action_name}: {e}")

    def use_api_result(self, idx):
        """Używa wyniku z wybranego API - kopiuje do schowka i symuluje Ctrl+V."""
        if idx not in self.api_results:
            return
        if self.paste_in_progress:
            return
        self.paste_in_progress = True
        
        selected_text = self.api_results[idx]
        
        # Kopiuj do schowka
        pyperclip.copy(selected_text)
        
        # Cleanup GIF-y żeby zwolnić RAM
        for loader in self.api_loaders:
            if hasattr(loader, 'cleanup'):
                loader.cleanup()
        
        # Ukryj okno z powrotem do pamięci
        self.withdraw()
        
        # Poczekaj chwilę i symuluj Ctrl+V
        def paste_text():
            time.sleep(0.3)
            keyboard.send('ctrl+v')
            # odblokuj po krótkim czasie, aby uniknąć podwójnych wklejeń
            time.sleep(0.2)
            self.paste_in_progress = False
        
        # Uruchom w osobnym wątku
        paste_thread = threading.Thread(target=paste_text)
        paste_thread.daemon = True
        paste_thread.start()
        
        # Update status
        api_name = self.api_names[idx]
        self.update_status(f"✅ Użyto tekstu z {api_name} i wklejono")
        
        logging.info(f"Użyto wyniku z {api_name}, wykonano auto-paste")
    
    def show_settings(self):
        """Pokazuje okno ustawień."""
        settings_window = SettingsWindow(self)
        settings_window.grab_set()
    
    def minimize_to_tray(self):
        """Minimalizuje do system tray - z anulowaniem API jeśli aktywne."""
        logging.info("🔄 Minimize to tray - sprawdzam aktywne API...")
        
        # KLUCZOWE: Anuluj API jeśli są aktywne przy zamykaniu okna!
        if self.processing:
            logging.info("❌ Anulowanie wszystkich API przed ukryciem okna")
            self.cancel_all_processing()
            
            # Daj UI czas na odświeżenie zanim schowamy okno
            self.after(200, self._complete_minimize_to_tray)
            return

        self._complete_minimize_to_tray()

    def _complete_minimize_to_tray(self):
        """Wykonuje właściwe ukrycie okna i sprzątanie zasobów."""
        # Cleanup GIF-y żeby zwolnić RAM
        for loader in self.api_loaders:
            if hasattr(loader, 'cleanup'):
                loader.cleanup()

        self.withdraw()

        if tray_icon:
            # Pokaż notyfikację
            try:
                tray_icon.notify(
                    "PoprawiaczTekstuPy",
                    "Aplikacja działa w tle. Ctrl+Shift+C aby poprawić tekst."
                )
            except Exception:
                pass
    
    def paste_and_process(self):
        """Wkleja tekst ze schowka i przetwarza bez hotkey."""
        try:
            clipboard_text = pyperclip.paste()
            if not clipboard_text or not clipboard_text.strip():
                messagebox.showinfo(
                    "Pusty schowek", 
                    "Skopiuj tekst do schowka (Ctrl+C) i spróbuj ponownie.",
                    parent=self
                )
                return
            
            logging.info(f"Przetwarzanie tekstu ze schowka: {len(clipboard_text)} znaków")
            self._set_original_text(clipboard_text)
            # Przygotuj stany loaderów zanim okno zostanie ponownie pokazane, aby uniknąć migotania.
            self._show_gui_and_process(clipboard_text)
            
        except Exception as e:
            logging.error(f"Błąd wklejania tekstu: {e}")
            messagebox.showerror(
                "Błąd", 
                f"Nie można pobrać tekstu ze schowka: {e}",
                parent=self
            )
    
    def show_window(self):
        """Pokazuje okno z tray z pre-renderowaniem."""
        # Pre-render wszystkich widgetów przed pokazaniem
        self.update_idletasks()
        
        # Teraz pokaż okno - będzie płynnie
        self.deiconify()
        self.lift()
        self.focus_force()
        
        # Topmost tylko na chwilę
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.api_names = parent.api_names
        
        # Ustaw ikonę okna Settings
        try:
            icon_path = os.path.join(get_assets_dir_path(), "icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception as e:
            logging.debug(f"Błąd ustawiania ikony okna Settings: {e}")
        
        self.title("Ustawienia API")

        self._reference_widget = parent if parent is not None else self
        if parent is not None:
            _safe_update_idletasks(parent)

        area_width, area_height = _get_display_area(self._reference_widget)
        scale = getattr(parent, "scale_factor", 1.0) or 1.0

        padding_x = min(max(0, int(area_width * 0.08)), max(0, area_width - 360))
        padding_y = min(max(0, int(area_height * 0.12)), max(0, area_height - 420))
        self._geometry_padding = (padding_x, padding_y)

        # Zmniejszone rozmiary bazowe dla okna ustawień, szczególnie dla HiDPI
        base_width_candidate = int(max(350, min(500, 380 * scale)))
        base_height_candidate = int(max(380, min(580, 450 * scale)))

        if area_width > 0:
            max_width_cap = min(area_width, max(360, area_width - padding_x))
        else:
            max_width_cap = base_width_candidate
        if area_height > 0:
            max_height_cap = min(area_height, max(420, area_height - padding_y))
        else:
            max_height_cap = base_height_candidate

        if max_width_cap >= 320:
            self._base_min_width = max(320, min(base_width_candidate, max_width_cap))
        else:
            self._base_min_width = max_width_cap if max_width_cap > 0 else base_width_candidate

        if max_height_cap >= 400:
            self._base_min_height = max(400, min(base_height_candidate, max_height_cap))
        else:
            self._base_min_height = max_height_cap if max_height_cap > 0 else base_height_candidate

        self._max_width_cap = max_width_cap if max_width_cap > 0 else self._base_min_width
        self._max_height_cap = max_height_cap if max_height_cap > 0 else self._base_min_height

        if area_width > 0:
            desired_width = max(self._base_min_width, int(area_width * 0.62))
        else:
            desired_width = self._base_min_width
        if area_height > 0:
            desired_height = max(self._base_min_height, int(area_height * 0.75))
        else:
            desired_height = self._base_min_height

        desired_width = min(self._max_width_cap, desired_width)
        desired_height = min(self._max_height_cap, desired_height)

        self._current_width = desired_width
        self._current_height = desired_height
        self._display_area = (0, 0)
        self._min_width = self._base_min_width
        self._min_height = self._base_min_height

        self._apply_geometry(desired_width, desired_height)
        enforced_area = _enforce_window_display_bounds(
            self,
            self._reference_widget,
            self._min_width,
            self._min_height,
            padding_x,
            padding_y,
        )
        if enforced_area:
            self._display_area = enforced_area
        self.resizable(True, True)

        self.transient(parent)
        self.setup_ui()
        self.load_settings()
        self._resize_to_fit_content()

    def _apply_geometry(self, width, height, min_width=None, min_height=None):
        """Ustawia geometrię okna w granicach ekranu i zapamiętuje bieżący rozmiar."""
        effective_min_width = int(min_width) if min_width is not None else self._base_min_width
        effective_min_height = int(min_height) if min_height is not None else self._base_min_height

        padding_x, padding_y = getattr(self, "_geometry_padding", (0, 0))
        width, height, x, y, area_width, area_height = _compute_child_geometry(
            self._reference_widget,
            width,
            height,
            effective_min_width,
            effective_min_height,
            padding_x,
            padding_y,
        )

        self.geometry(f"{width}x{height}+{x}+{y}")
        self._current_width = width
        self._current_height = height
        self._display_area = (area_width, area_height)
        self._min_width = effective_min_width
        self._min_height = effective_min_height
        usable_width = min(area_width, max(effective_min_width, area_width - max(0, int(padding_x))))
        usable_height = min(area_height, max(effective_min_height, area_height - max(0, int(padding_y))))
        self._usable_width = usable_width
        self._usable_height = usable_height
        self.minsize(int(min(effective_min_width, usable_width)), int(min(effective_min_height, usable_height)))
        self.maxsize(int(usable_width), int(usable_height))

    def _resize_to_fit_content(self):
        """Rozszerza okno tak, aby cała zawartość mieściła się bez przewijania, jeśli pozwala na to ekran."""
        if not hasattr(self, "main_frame"):
            return

        try:
            content_widget = self.main_frame._scrollable_frame
        except AttributeError:
            content_widget = self.main_frame

        self.update_idletasks()
        content_width = content_widget.winfo_reqwidth()
        content_height = content_widget.winfo_reqheight()

        padding_x, padding_y = getattr(self, "_geometry_padding", (0, 0))
        content_padding_x = max(40, padding_x // 2)
        content_padding_y = max(60, padding_y // 2)

        area_width, area_height = self._display_area if any(self._display_area) else _get_display_area(self._reference_widget)
        usable_width = getattr(self, "_usable_width", None)
        usable_height = getattr(self, "_usable_height", None)

        if not usable_width:
            usable_width = min(area_width, max(self._min_width, area_width - max(0, int(padding_x))))
        if not usable_height:
            usable_height = min(area_height, max(self._min_height, area_height - max(0, int(padding_y))))

        effective_min_width = max(self._base_min_width, content_width + content_padding_x)
        effective_min_height = max(self._base_min_height, content_height + content_padding_y)

        desired_width = min(usable_width, max(self._current_width, effective_min_width))
        desired_height = min(usable_height, max(self._current_height, effective_min_height))

        self._apply_geometry(desired_width, desired_height, effective_min_width, effective_min_height)

    def setup_ui(self):
        """Konfiguruje interfejs ustawień."""
        self.main_frame = ctk.CTkScrollableFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Skalowana czcionka tytułu
        title_font_size = max(16, int(18 * self.parent.scale_factor))
        title_label = ctk.CTkLabel(
            self.main_frame,
            text="Konfiguracja kluczy API",
            font=ctk.CTkFont(size=title_font_size, weight="bold")
        )
        title_label.pack(pady=(0, 20))
        
        # API configs with colors and model selection
        self.entries = {}
        self.model_combos = {}
        self.model_inputs = {}
        self.refresh_buttons = {}
        self.highlight_var = ctk.BooleanVar(value=False)

        apis = [
            ("OpenAI", "OpenAI API Key", "sk-...", "#10a37f"),
            ("Anthropic", "Anthropic API Key", "sk-ant-...", "#d97706"),
            ("Gemini", "Gemini API Key", "AIza...", "#4285f4"),
            ("DeepSeek", "DeepSeek API Key", "sk-...", "#7c3aed")
        ]
        
        for api_key, label, placeholder, color in apis:
            frame = ctk.CTkFrame(self.main_frame, fg_color=color, corner_radius=10)
            frame.pack(fill="x", pady=10)
            
            # Skalowana czcionka dla label
            label_font_size = max(12, int(14 * self.parent.scale_factor))
            ctk.CTkLabel(
                frame,
                text=label,
                font=ctk.CTkFont(size=label_font_size, weight="bold"),
                text_color="white"
            ).pack(anchor="w", padx=15, pady=(10, 5))
            
            # API Key entry
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
            
            # Model selection section
            model_frame = ctk.CTkFrame(frame, fg_color="transparent")
            model_frame.pack(fill="x", padx=15, pady=(0, 10))
            
            ctk.CTkLabel(
                model_frame,
                text=f"Model {api_key}:",
                font=ctk.CTkFont(size=label_font_size-2, weight="bold"),
                text_color="white"
            ).pack(anchor="w", pady=(5, 5))
            
            # Row z ComboBox i przyciskiem refresh
            combo_row = ctk.CTkFrame(model_frame, fg_color="transparent")
            combo_row.pack(fill="x")
            
            # ComboBox dla modeli
            model_combo = ctk.CTkComboBox(
                combo_row,
                values=["Ładowanie modeli..."],
                height=30,
                fg_color="white",
                button_color=color,
                text_color="black",
                dropdown_fg_color="white"
            )
            model_combo.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self.model_combos[api_key] = model_combo
            
            # Przycisk refresh modeli
            refresh_btn = ctk.CTkButton(
                combo_row,
                text="🔄",
                width=30,
                height=30,
                fg_color="white",
                text_color=color,
                hover_color="#f0f0f0",
                command=lambda provider=api_key: self.refresh_models(provider)
            )
            refresh_btn.pack(side="right")
            self.refresh_buttons[api_key] = refresh_btn
            
            # Input fallback dla custom modelu
            model_input = ctk.CTkEntry(
                model_frame,
                placeholder_text="lub wpisz model manualnie",
                height=25,
                fg_color="white",
                text_color="black",
                font=ctk.CTkFont(size=label_font_size-4)
            )
            model_input.pack(fill="x", pady=(5, 0))
            self.model_inputs[api_key] = model_input

        general_frame = ctk.CTkFrame(self.main_frame, fg_color="#1f2937", corner_radius=10)
        general_frame.pack(fill="x", pady=(10, 10))

        ctk.CTkLabel(
            general_frame,
            text="Widok wyników",
            font=ctk.CTkFont(size=max(12, int(14 * self.parent.scale_factor)), weight="bold"),
            text_color="white"
        ).pack(anchor="w", padx=15, pady=(12, 6))

        self.highlight_checkbox = ctk.CTkCheckBox(
            general_frame,
            text="Podkreślaj zmiany względem oryginału (czerwone podkreślenie)",
            variable=self.highlight_var,
            onvalue=True,
            offvalue=False
        )
        self.highlight_checkbox.pack(anchor="w", padx=15, pady=(0, 12))

        # AI Settings section for GPT-5 models
        ai_settings_frame = ctk.CTkFrame(self.main_frame, fg_color="#6366f1", corner_radius=10)
        ai_settings_frame.pack(fill="x", pady=(20, 10))
        
        # Title for AI settings
        label_font_size = max(12, int(14 * self.parent.scale_factor))
        ctk.CTkLabel(
            ai_settings_frame,
            text="Ustawienia AI dla modeli GPT-5",
            font=ctk.CTkFont(size=label_font_size, weight="bold"),
            text_color="white"
        ).pack(anchor="w", padx=15, pady=(10, 5))
        
        ctk.CTkLabel(
            ai_settings_frame,
            text="Dotyczy modeli: gpt-5, gpt-5-mini, gpt-5-nano, o4, o3, o1",
            font=ctk.CTkFont(size=label_font_size-2),
            text_color="white"
        ).pack(anchor="w", padx=15, pady=(0, 10))
        
        # Settings grid
        settings_grid = ctk.CTkFrame(ai_settings_frame, fg_color="transparent")
        settings_grid.pack(fill="x", padx=15, pady=(0, 15))
        
        # Reasoning Effort
        reasoning_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        reasoning_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(
            reasoning_frame,
            text="Poziom reasoning:",
            font=ctk.CTkFont(size=label_font_size-2, weight="bold"),
            text_color="white"
        ).pack(side="left", padx=(0, 10))
        
        self.reasoning_combo = ctk.CTkComboBox(
            reasoning_frame,
            values=["minimal", "low", "medium", "high"],
            width=120,
            height=30,
            fg_color="white",
            button_color="#6366f1",
            text_color="black",
            dropdown_fg_color="white"
        )
        self.reasoning_combo.pack(side="left", padx=(0, 10))
        
        # Reasoning explanation
        reasoning_help = ctk.CTkLabel(
            reasoning_frame,
            text="high = najlepsza jakość (wolniej), minimal = szybko (mniej dokładne)",
            font=ctk.CTkFont(size=label_font_size-4),
            text_color="white"
        )
        reasoning_help.pack(side="left")
        
        # Verbosity
        verbosity_frame = ctk.CTkFrame(settings_grid, fg_color="transparent")
        verbosity_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(
            verbosity_frame,
            text="Szczegółowość:",
            font=ctk.CTkFont(size=label_font_size-2, weight="bold"),
            text_color="white"
        ).pack(side="left", padx=(0, 10))
        
        self.verbosity_combo = ctk.CTkComboBox(
            verbosity_frame,
            values=["low", "medium", "high"],
            width=120,
            height=30,
            fg_color="white",
            button_color="#6366f1",
            text_color="black",
            dropdown_fg_color="white"
        )
        self.verbosity_combo.pack(side="left", padx=(0, 10))
        
        # Verbosity explanation  
        verbosity_help = ctk.CTkLabel(
            verbosity_frame,
            text="medium = optymalne dla korekty, high = więcej wyjaśnień",
            font=ctk.CTkFont(size=label_font_size-4),
            text_color="white"
        )
        verbosity_help.pack(side="left")
        
        # Buttons
        button_frame = ctk.CTkFrame(self.main_frame)
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
        
        # Load model settings
        for api_key, model_combo in self.model_combos.items():
            current_model = self.parent.models.get(api_key, get_default_model(api_key))
            if current_model:
                # Try to set in combo, otherwise use input
                try:
                    model_combo.set(current_model)
                except:
                    self.model_inputs[api_key].insert(0, current_model)
        
        ai_settings = getattr(self.parent, "ai_settings", {}) or {}
        reasoning_effort = ai_settings.get("ReasoningEffort", "high") or "high"
        verbosity = ai_settings.get("Verbosity", "medium") or "medium"

        if reasoning_effort not in {"minimal", "low", "medium", "high"}:
            logging.debug(
                "Nieznana wartość ReasoningEffort w konfiguracji: %s", reasoning_effort
            )
            reasoning_effort = "high"
        if verbosity not in {"low", "medium", "high"}:
            logging.debug("Nieznana wartość Verbosity w konfiguracji: %s", verbosity)
            verbosity = "medium"

        self.reasoning_combo.set(reasoning_effort)
        self.verbosity_combo.set(verbosity)

        highlight_enabled = str(self.parent.settings.get("HighlightDiffs", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self.highlight_var.set(highlight_enabled)

        # Load models asynchronously
        self.after(100, self.load_all_models_async)
    
    def load_all_models_async(self):
        """Ładuje modele dla wszystkich API asynchronicznie."""
        async def load_models():
            for provider in self.api_names:
                api_key = self.entries[provider].get().strip()
                if api_key:
                    await self.refresh_models_async(provider, api_key)
                else:
                    # Load fallback models
                    from utils.model_fetcher import FALLBACK_MODELS
                    models = FALLBACK_MODELS.get(provider, [])
                    self.after(0, lambda p=provider, m=models: self.update_model_combo(p, m))
        
        # Run in thread to avoid blocking UI
        def run_async():
            loop = None
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(load_models())
            except Exception as e:
                logging.error(f"Error loading models: {e}")
            finally:
                # Clean up event loop properly
                if loop and not loop.is_closed():
                    try:
                        # Cancel pending tasks
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        # Wait for cancelled tasks if any
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        loop.close()
                    except Exception as e:
                        logging.debug(f"Error cleaning up event loop: {e}")
                # Clear the event loop from thread
                try:
                    asyncio.set_event_loop(None)
                except Exception:
                    pass
        
        threading.Thread(target=run_async, daemon=True).start()
    
    def refresh_models(self, provider):
        """Odświeża modele dla konkretnego providera."""
        api_key = self.entries[provider].get().strip()
        if not api_key:
            messagebox.showwarning("Brak API Key", f"Wpisz {provider} API key przed odświeżaniem modeli", parent=self)
            return
        
        # Disable button during refresh
        self.refresh_buttons[provider].configure(text="⏳", state="disabled")
        
        # Run async
        def run_refresh():
            async def refresh():
                await self.refresh_models_async(provider, api_key)
                # Re-enable button
                self.after(0, lambda: self.refresh_buttons[provider].configure(text="🔄", state="normal"))
            
            loop = None
            try:
                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(refresh())
            except Exception as e:
                logging.error(f"Error refreshing models for {provider}: {e}")
                self.after(0, lambda: self.refresh_buttons[provider].configure(text="❌", state="normal"))
            finally:
                # Clean up event loop properly
                if loop and not loop.is_closed():
                    try:
                        # Cancel pending tasks
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        # Wait for cancelled tasks if any
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        loop.close()
                    except Exception as e:
                        logging.debug(f"Error cleaning up event loop: {e}")
                # Clear the event loop from thread
                try:
                    asyncio.set_event_loop(None)
                except Exception:
                    pass
        
        threading.Thread(target=run_refresh, daemon=True).start()
    
    async def refresh_models_async(self, provider, api_key):
        """Asynchronicznie pobiera modele dla providera."""
        try:
            models = await fetch_models_for_provider(provider, api_key)
            self.after(0, lambda: self.update_model_combo(provider, models))
        except Exception as e:
            logging.error(f"Failed to fetch models for {provider}: {e}")
            from utils.model_fetcher import FALLBACK_MODELS
            models = FALLBACK_MODELS.get(provider, [])
            self.after(0, lambda: self.update_model_combo(provider, models))
    
    def update_model_combo(self, provider, models):
        """Aktualizuje ComboBox z modelami."""
        if not models:
            models = [get_default_model(provider)]
        
        # Update combo values
        combo = self.model_combos[provider]
        combo.configure(values=models)
        
        # Set current selection if not set
        current = combo.get()
        if current == "Ładowanie modeli..." or current not in models:
            # Try to keep current model from parent
            parent_model = self.parent.models.get(provider, get_default_model(provider))
            if parent_model in models:
                combo.set(parent_model)
            else:
                combo.set(models[0])
        
        logging.info(f"Updated {provider} with {len(models)} models")

    def save_settings(self):
        """Zapisuje ustawienia."""
        try:
            # Update API keys
            for api_key, entry in self.entries.items():
                self.parent.api_keys[api_key] = entry.get().strip()
            
            # Update models - prefer combo selection over manual input
            for api_key, combo in self.model_combos.items():
                selected_model = combo.get()
                manual_model = self.model_inputs[api_key].get().strip()
                
                # Use manual input if provided, otherwise combo selection
                if manual_model:
                    self.parent.models[api_key] = manual_model
                elif selected_model and selected_model != "Ładowanie modeli...":
                    self.parent.models[api_key] = selected_model
                else:
                    # Fallback to default
                    self.parent.models[api_key] = get_default_model(api_key)
            
            ai_settings = {
                "ReasoningEffort": (self.reasoning_combo.get() or "high").strip().lower(),
                "Verbosity": (self.verbosity_combo.get() or "medium").strip().lower()
            }

            base_settings = dict(self.parent.settings)
            base_settings.setdefault("AutoStartup", '0')
            base_settings.setdefault("DefaultStyle", 'normal')
            base_settings["HighlightDiffs"] = '1' if self.highlight_var.get() else '0'
            settings_payload = {k: str(v) for k, v in base_settings.items()}

            config_manager.save_config(
                self.parent.api_keys,
                self.parent.models,
                settings_payload,
                ai_settings
            )

            self.parent.settings = settings_payload
            self.parent.ai_settings = ai_settings
            self.parent.refresh_diff_highlights()
            self.parent.update_status("✅ Ustawienia zapisane")
            
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
        # Load icon with better error handling
        icon_path = os.path.join(get_assets_dir_path(), "icon.ico")
        logging.info(f"Próba załadowania ikony tray z: {icon_path}")
        
        if os.path.exists(icon_path):
            try:
                image = Image.open(icon_path)
                # Convert to appropriate size for tray (typically 16x16 or 32x32)
                image = image.resize((32, 32), Image.Resampling.LANCZOS)
                logging.info("Pomyślnie załadowano ikonę tray z pliku")
            except Exception as icon_error:
                logging.error(f"Błąd ładowania ikony {icon_path}: {icon_error}")
                # Fallback - create simple icon with app-like appearance
                image = Image.new('RGBA', (32, 32), color=(16, 163, 127, 255))  # Green with alpha
        else:
            logging.warning(f"Plik ikony nie istnieje: {icon_path}")
            # Fallback - create simple icon with app-like appearance
            image = Image.new('RGBA', (32, 32), color=(16, 163, 127, 255))  # Green with alpha
        
        # Check autostart status
        def toggle_autostart():
            try:
                if config_manager.is_in_startup():
                    config_manager.remove_from_startup()
                    tray_icon.notify("PoprawiaczTekstuPy", "Autostart wyłączony")
                else:
                    if config_manager.add_to_startup():
                        tray_icon.notify("PoprawiaczTekstuPy", "Autostart włączony")
                    else:
                        tray_icon.notify("PoprawiaczTekstuPy", "Błąd włączania autostartu")
            except Exception as e:
                logging.error(f"Błąd toggle autostart: {e}")
                tray_icon.notify("PoprawiaczTekstuPy", "Błąd konfiguracji autostartu")

        def get_autostart_text():
            try:
                return "⏹️ Wyłącz autostart" if config_manager.is_in_startup() else "🚀 Włącz autostart"
            except:
                return "🚀 Autostart"

        # Tray menu
        menu = pystray.Menu(
            pystray.MenuItem("📱 Pokaż aplikację", lambda: app.after(0, app.show_window), default=True),  # default=True dla lewego kliku
            pystray.MenuItem("🔽 Minimalizuj", lambda: app.after(0, app.minimize_to_tray)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙️ Ustawienia", lambda: app.after(0, app.show_settings)),
            pystray.MenuItem(get_autostart_text(), toggle_autostart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Zakończ", lambda: quit_app())
        )
        
        tray_icon = pystray.Icon(
            "PoprawiaczTekstuPy",
            image,
            "PoprawiaczTekstuPy\nZaznacz tekst → OD RAZU Ctrl+Shift+C",
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

def cleanup_old_logs(log_dir, max_files=10):
    """Usuwa stare pliki logów, zachowując tylko najnowsze max_files plików."""
    try:
        if not os.path.exists(log_dir):
            return
            
        # Znajdź wszystkie pliki logów
        log_files = []
        for file in os.listdir(log_dir):
            if file.startswith("app_corrector_") and file.endswith(".log"):
                file_path = os.path.join(log_dir, file)
                try:
                    mtime = os.path.getmtime(file_path)
                    log_files.append((file_path, mtime))
                except OSError:
                    continue
        
        # Sortuj według czasu modyfikacji (najnowsze pierwsze)
        log_files.sort(key=lambda x: x[1], reverse=True)
        
        # Usuń stare pliki jeśli jest ich więcej niż max_files
        if len(log_files) > max_files:
            for file_path, _ in log_files[max_files:]:
                try:
                    os.remove(file_path)
                    print(f"Usunięto stary log: {file_path}")
                except OSError:
                    pass
                    
    except Exception as e:
        print(f"Błąd czyszczenia logów: {e}")

def setup_logging():
    """Konfiguruje logging z automatycznym czyszczeniem starych logów."""
    try:
        # Try home directory first
        try:
            log_dir = os.path.join(os.path.expanduser("~"), "PoprawiaczTekstu_logs")
            os.makedirs(log_dir, exist_ok=True)
        except (OSError, PermissionError):
            # Fallback to temp directory
            import tempfile
            log_dir = os.path.join(tempfile.gettempdir(), "PoprawiaczTekstu_logs")
            os.makedirs(log_dir, exist_ok=True)
        
        # Wyczyść stare logi (zachowaj 7 najnowszych)
        cleanup_old_logs(log_dir, max_files=7)
            
        log_file = os.path.join(log_dir, f"app_corrector_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        # Console only logging as fallback
        handlers = [logging.StreamHandler()]
        
        # Add file handler if possible
        try:
            handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
        except (OSError, PermissionError):
            print(f"Warning: Cannot create log file, using console only")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
        
        if len(handlers) > 1:
            logging.info(f"Multi-API Corrector logs: {log_file}")
            logging.info(f"Automatyczne czyszczenie logów - zachowywane 7 najnowszych plików")
        else:
            logging.info("Multi-API Corrector - console logging only")
            
    except Exception as e:
        print(f"Logging setup failed: {e}")
        # Minimal console logging as last resort
        logging.basicConfig(level=logging.INFO, format='%(message)s')

def setup_global_hotkey(app):
    """Konfiguruje globalny hotkey Ctrl+Shift+C."""
    logging.info("Konfiguracja globalnego skrótu Ctrl+Shift+C...")
    
    try:
        hotkey_processor = get_hotkey_processor()

        # Konfiguracja opóźnienia przetwarzania schowka (ms w config)
        delay_setting = None
        if hasattr(app, 'settings'):
            delay_setting = app.settings.get('ClipboardProcessingDelayMs')

        if isinstance(delay_setting, str):
            normalized = delay_setting.strip().lower()
            if normalized in {"off", "disabled", "none"}:
                hotkey_processor.set_clipboard_delay(None)
            else:
                try:
                    hotkey_processor.set_clipboard_delay(float(delay_setting) / 1000.0)
                except ValueError:
                    logging.warning(
                        "Invalid ClipboardProcessingDelayMs value '%s' - using default",
                        delay_setting,
                    )
                    hotkey_processor.set_clipboard_delay(0.4)
        elif isinstance(delay_setting, (int, float)):
            hotkey_processor.set_clipboard_delay(float(delay_setting) / 1000.0)
        else:
            hotkey_processor.set_clipboard_delay(0.4)

        def hotkey_callback():
            app.handle_hotkey_event()
        
        success = hotkey_processor.setup_hotkey_with_fallback(hotkey_callback)
        
        if success:
            logging.info("Globalny skrót skonfigurowany pomyślnie")
            app.after(0, lambda: app.update_status("✅ Ctrl+Shift+C aktywny - zaznacz tekst i OD RAZU naciśnij!"))
        else:
            logging.warning("Nie udało się skonfigurować hotkey")
            app.after(0, lambda: app.update_status("⚠️ Hotkey niedostępny - skonfiguruj ręcznie"))
            
    except Exception as e:
        logging.error(f"Błąd konfiguracji hotkey: {e}")

def main():
    global main_app
    
    setup_logging()
    app_version = get_app_version()
    logging.info("=== PoprawiaczTekstuPy Multi-API Start ===")
    logging.info("🔍 Build version: %s", app_version)
    
    # Sprawdź sygnaturę funkcji OpenAI
    import inspect
    try:
        sig = inspect.signature(openai_client.correct_text_openai)
        logging.debug("OpenAI corrector signature: %s", sig)
        logging.debug("OpenAI module: %s", openai_client.correct_text_openai.__module__)
        logging.debug("OpenAI source file: %s", inspect.getfile(openai_client.correct_text_openai))
    except Exception as e:
        logging.error(f"🚨 SIGNATURE ERROR: {e}")
    
    logging.debug(
        "openai_client.correct_text_openai exists: %s",
        hasattr(openai_client, 'correct_text_openai'),
    )
    if hasattr(openai_client, 'correct_text_openai'):
        logging.debug(
            "openai_client.correct_text_openai ref: %s", openai_client.correct_text_openai
        )
    else:
        logging.error(
            "openai_client attributes (missing correct_text_openai): %s",
            dir(openai_client),
        )
    
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
