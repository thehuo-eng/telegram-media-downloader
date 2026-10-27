# -*- mode: python ; coding: utf-8 -*-
# Build from the repository root: python -m PyInstaller TelegramSmartDownloader.spec
from pathlib import Path
import os
import sys

if os.name == 'nt':
    # Build tools on PATH can carry an incompatible ICU with the same DLL name.
    # Qt uses Windows' system ICU; keep unrelated application runtimes out of discovery.
    windows = Path(os.environ.get('WINDIR', 'C:/Windows'))
    os.environ['PATH'] = os.pathsep.join([
        str(Path(sys.executable).parent), sys.base_prefix,
        str(Path(sys.base_prefix) / 'DLLs'), str(windows / 'System32'), str(windows),
    ])

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'src' / 'gui.py')],
    pathex=[str(root / 'src')],
    binaries=[],
    datas=[(str(root / 'src' / 'assets'), 'assets'), (str(root / 'LICENSE'), '.')],
    hiddenimports=['telethon', 'cryptg', 'python_socks.async_.asyncio', 'PySide6.QtSvg'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'pytest'],
    noarchive=False, optimize=0,
)
if os.name == 'nt':
    a.binaries = [entry for entry in a.binaries
                  if not Path(entry[0]).name.lower().startswith(('icuuc', 'icuin', 'icudt'))]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='TelegramSmartDownloader', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(root / 'src' / 'assets' / 'logo.ico'),
)
