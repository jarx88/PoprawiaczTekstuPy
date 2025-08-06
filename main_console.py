#!/usr/bin/env python3
"""
Console-only version of PoprawiaczTekstuPy for Wine compatibility.
This version works without Qt GUI - uses command line interface.
"""

import sys
import os
import logging
from datetime import datetime
import keyboard
import time
from utils import config_manager
from utils.hotkey_manager import get_hotkey_processor, cleanup_global_hotkey
from api_clients import openai_client, anthropic_client, gemini_client, deepseek_client
import httpx

def setup_logging():
    try:
        log_dir = os.path.join(os.path.expanduser("~"), "PoprawiaczTekstu_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"app_console_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        print(f"Logs: {log_file}")
    except Exception as e:
        print(f"Logging error: {e}")

def main():
    setup_logging()
    print("=== PoprawiaczTekstuPy Console Version ===")
    print("Console-only version for Wine compatibility")
    print("Press Ctrl+Shift+C to process clipboard text")
    print("Press Ctrl+C to exit")
    
    try:
        # Load config
        api_keys, models, settings, new_config = config_manager.load_config()
        
        if not api_keys or not any(api_keys.values()):
            print("ERROR: No API keys configured")
            print("Please configure API keys in config.ini")
            return 1
        
        print("Available APIs:", [k for k, v in api_keys.items() if v])
        
        # Setup hotkey
        hotkey_processor = get_hotkey_processor()
        
        def process_clipboard():
            print("\n🔄 Processing clipboard...")
            # Here you would add the actual text processing logic
            # For now, just simulate
            print("✅ Text processed!")
        
        success = hotkey_processor.setup_hotkey_with_fallback(process_clipboard)
        
        if success:
            print("✅ Hotkey registered: Ctrl+Shift+C")
        else:
            print("⚠️  Hotkey registration failed, manual mode only")
        
        # Keep running
        print("\nApplication running... Press Ctrl+C to exit")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nExiting...")
        
        cleanup_global_hotkey()
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        logging.error(f"Main error: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())