import os
import sys

try:
    from pathlib import Path
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)).resolve()
    proj = base if (base / 'assets').exists() else Path(__file__).resolve().parent
    os.chdir(proj)
except Exception:
    pass
