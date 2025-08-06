import queue
import threading
import time
from typing import Optional, Callable
from pynput import keyboard
from .logger import logger


class ThreadSafeHotkeyProcessor:
    """
    Thread-safe hotkey processor używający pynput z queue-based architecture.
    Rozwiązuje problemy threading i race conditions z poprzednią implementacją keyboard library.
    """
    
    def __init__(self):
        self.command_queue: queue.Queue = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.hotkeys: Optional[keyboard.GlobalHotKeys] = None
        self.main_window_callback: Optional[Callable] = None
        self.hotkey_registered = False
        self.running = False
        
    def start_worker(self):
        """Uruchamia worker thread dla przetwarzania queue."""
        if self.worker_thread and self.worker_thread.is_alive():
            return
            
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        logger.info("Hotkey worker thread started")
    
    def stop_worker(self):
        """Zatrzymuje worker thread."""
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)
        logger.info("Hotkey worker thread stopped")
    
    def _worker_loop(self):
        """Główna pętla worker thread - przetwarza komendy z queue."""
        while self.running:
            try:
                command, data = self.command_queue.get(timeout=1)
                
                if command == "simulate_copy":
                    self._safe_simulate_copy()
                elif command == "process_clipboard":
                    self._safe_process_clipboard()
                elif command == "stop":
                    break
                    
                self.command_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Hotkey worker thread error: {e}", exc_info=True)
    
    def _safe_simulate_copy(self):
        """
        Bezpieczna symulacja Ctrl+C z lepszym timing.
        Zwiększony czas oczekiwania z 0.1s na 0.3s dla pewności aktualizacji schowka.
        """
        try:
            logger.debug("Simulating Ctrl+C...")
            
            # Import keyboard dla symulacji (zachowujemy dla compatibility)
            import keyboard as kb
            
            kb.press('ctrl')
            kb.press('c')
            kb.release('c')
            kb.release('ctrl')
            
            # Zwiększony timing dla pewności kopiowania
            time.sleep(0.3)  # Zmienione z 0.1s na 0.3s
            
            logger.debug("Ctrl+C simulation completed")
            
        except Exception as e:
            logger.error(f"Copy simulation error: {e}", exc_info=True)
    
    def _safe_process_clipboard(self):
        """
        Bezpieczne przetworzenie schowka - wywołuje callback do main window.
        """
        try:
            if self.main_window_callback:
                logger.debug("Triggering main window clipboard processing")
                self.main_window_callback()
            else:
                logger.warning("No main window callback registered")
                
        except Exception as e:
            logger.error(f"Clipboard processing error: {e}", exc_info=True)
    
    def on_hotkey(self):
        """
        Callback wywołany przez pynput przy wykryciu hotkey.
        Non-blocking operation - dodaje komendy do queue.
        """
        try:
            logger.info("Global hotkey Ctrl+Shift+C detected (pynput)")
            
            # Dodaj komendy do queue (non-blocking)
            self.command_queue.put(("simulate_copy", None))
            
            # Zaplanuj przetwarzanie schowka z opóźnieniem
            # Używamy threading.Timer zamiast QTimer (bo jesteśmy poza Qt thread)
            clipboard_timer = threading.Timer(0.4, self._schedule_clipboard_processing)
            clipboard_timer.daemon = True
            clipboard_timer.start()
            
        except Exception as e:
            logger.error(f"Hotkey callback error: {e}", exc_info=True)
    
    def _schedule_clipboard_processing(self):
        """Planuje przetwarzanie schowka z opóźnieniem."""
        try:
            self.command_queue.put(("process_clipboard", None))
        except Exception as e:
            logger.error(f"Failed to schedule clipboard processing: {e}")
    
    def setup_hotkey_with_fallback(self, callback: Callable):
        """
        Konfiguruje global hotkey z fallback mechanisms.
        
        Args:
            callback: Funkcja wywoływana gdy hotkey zostanie wykryty
        """
        self.main_window_callback = callback
        
        # Uruchom worker thread
        self.start_worker()
        
        # Spróbuj zarejestrować primary hotkey
        if self._try_register_primary_hotkey():
            return True
        
        # Fallback na alternative hotkeys
        return self._try_alternative_hotkeys()
    
    def _try_register_primary_hotkey(self) -> bool:
        """
        Próbuje zarejestrować główny hotkey Ctrl+Shift+C.
        
        Returns:
            True jeśli sukces, False jeśli failure
        """
        try:
            self.hotkeys = keyboard.GlobalHotKeys({
                '<ctrl>+<shift>+c': self.on_hotkey
            })
            self.hotkeys.start()
            self.hotkey_registered = True
            logger.info("Global hotkey Ctrl+Shift+C registered successfully (pynput)")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to register Ctrl+Shift+C: {e}")
            return False
    
    def _try_alternative_hotkeys(self) -> bool:
        """
        Próbuje zarejestrować alternatywne hotkeys jeśli primary nie działa.
        
        Returns:
            True jeśli udało się zarejestrować jakiś hotkey
        """
        alternatives = [
            ('<ctrl>+<shift>+<alt>+c', "Ctrl+Shift+Alt+C"),
            ('<ctrl>+<alt>+c', "Ctrl+Alt+C"), 
            ('<shift>+<alt>+c', "Shift+Alt+C")
        ]
        
        for hotkey, description in alternatives:
            try:
                if self.hotkeys:
                    self.hotkeys.stop()
                    
                self.hotkeys = keyboard.GlobalHotKeys({hotkey: self.on_hotkey})
                self.hotkeys.start()
                self.hotkey_registered = True
                
                logger.info(f"Alternative hotkey {description} registered successfully")
                self._notify_hotkey_change(description)
                return True
                
            except Exception as e:
                logger.warning(f"Failed to register {description}: {e}")
                continue
        
        logger.error("Failed to register any hotkey - manual mode required")
        return False
    
    def _notify_hotkey_change(self, hotkey_combo: str):
        """
        Notyfikuje o zmianie hotkey (będzie implementowane w main_window).
        Na razie tylko log.
        """
        logger.info(f"Hotkey changed to: {hotkey_combo}")
        # TODO: Implement Qt notification in main window
    
    def cleanup(self):
        """Cleanup resources przy zamykaniu aplikacji."""
        try:
            logger.info("Cleaning up hotkey manager...")
            
            # Stop worker thread
            if self.running:
                self.command_queue.put(("stop", None))
                self.stop_worker()
            
            # Stop pynput hotkeys
            if self.hotkeys:
                self.hotkeys.stop()
                self.hotkeys = None
                
            self.hotkey_registered = False
            logger.info("Hotkey manager cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during hotkey manager cleanup: {e}", exc_info=True)
    
    def is_hotkey_active(self) -> bool:
        """Zwraca True jeśli hotkey jest aktywny."""
        return self.hotkey_registered and self.hotkeys is not None


# Global instance - będzie używany w main.py
hotkey_processor: Optional[ThreadSafeHotkeyProcessor] = None


def get_hotkey_processor() -> ThreadSafeHotkeyProcessor:
    """Singleton pattern dla hotkey processor."""
    global hotkey_processor
    if hotkey_processor is None:
        hotkey_processor = ThreadSafeHotkeyProcessor()
    return hotkey_processor


def cleanup_global_hotkey():
    """Cleanup global hotkey processor."""
    global hotkey_processor
    if hotkey_processor:
        hotkey_processor.cleanup()
        hotkey_processor = None