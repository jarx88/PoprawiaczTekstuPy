# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main_modern.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('utils', 'utils'),
        ('api_clients', 'api_clients'),
        ('VERSION', '.'),
    ],
    hiddenimports=[
        'customtkinter',
        'pystray',
        'PIL',
        'pyperclip',
        'pynput',
        'httpx',
        'openai',
        'anthropic',
        'google.generativeai',
        'google.genai',
        'google.genai.types',
        'darkdetect',
        'python_xlib'
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'PyQt6',
        'PyQt5',
        'test',
        'unittest'
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='popraw_tekst_modern_linux',
    debug=False,
    strip=False,
    console=False,
    icon='assets/icon.ico'
)
