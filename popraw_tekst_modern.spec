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
    ],
    hiddenimports=[
        'customtkinter',
        'pystray',
        'PIL',
        'pyperclip',
        'pynput',
        'keyboard',
        'httpx',
        'openai',
        'anthropic',
        'google.generativeai',
        'certifi',
        'urllib3',
        'idna',
        'charset_normalizer',
        'sniffio',
        'h11',
        'anyio',
        'typing_extensions',
        'darkdetect',
        'python_xlib',
        'evdev'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PyQt6',
        'PyQt5',
        'tkinter.test',
        'test',
        'unittest',
        'pydoc',
        'doctest'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='popraw_tekst_modern',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico'
)