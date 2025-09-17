# -*- mode: python ; coding: utf-8 -*-
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(SPECPATH[0]))
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, 'main.py')
ASSETS_DIR = os.path.join(PROJECT_ROOT, 'assets')


from PyInstaller.utils.hooks import collect_all

# Collect all PyQt6 data
pyqt6_datas, pyqt6_binaries, pyqt6_hiddenimports = collect_all('PyQt6')

a = Analysis(
    ['main.py'],
    pathex=[PROJECT_ROOT],
    binaries=pyqt6_binaries,
    datas=[('assets', 'assets'), ('VERSION', '.')] + pyqt6_datas,
    hiddenimports=[
        'PyQt6.QtCore',
        'PyQt6.QtGui', 
        'PyQt6.QtWidgets',
        'PyQt6.QtCore.QCoreApplication',
        'PyQt6.QtWidgets.QApplication',
        'PyQt6.sip',
        'keyboard',
        'pynput',
        'pynput.keyboard',
        'pynput.mouse',
        'httpx',
        'openai',
        'anthropic',
        'google.generativeai',
        'google.genai',
        'google.genai.types',
        'utils.hotkey_manager',
        'utils.config_manager',
        'utils.clipboard_manager',
        'utils.logger',
        'utils.model_loader',
        'utils.paths'
    ] + pyqt6_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PySide6', 'PySide6.QtCore', 'PySide6.QtWidgets', 'PySide6.QtGui'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='popraw_tekst',
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
    icon=[os.path.join(PROJECT_ROOT, 'assets', 'icon.ico')],
)
