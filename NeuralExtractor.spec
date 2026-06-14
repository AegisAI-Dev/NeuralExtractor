# -*- mode: python ; coding: utf-8 -*-
# Neural Extractor – PyInstaller build spec
#
# Icon strategy
# ─────────────
# Windows : assets/NeuralExtractoricon.ico (multi-size ICO, 16-512 px)
#           The EXE icon field below embeds it into the .exe resource table so
#           Windows Explorer, the Taskbar, and the Alt-Tab switcher all display
#           the custom icon.  At runtime the GUI also calls
#           SetCurrentProcessExplicitAppUserModelID so the Taskbar groups the
#           window under the correct icon even when launched as a script.
#
# macOS   : assets/NeuralExtractorIcon.png (512 × 512, transparent bg)
#           Pass --icon assets/NeuralExtractorIcon.png on the CLI or set
#           icon='assets/NeuralExtractorIcon.png' in the EXE() call below when
#           building on macOS (PyInstaller converts it to .icns automatically).
#
# Linux   : No EXE icon field (not applicable). The PNG is loaded at runtime
#           via iconphoto(True, …) / QIcon(…).
#
# Adding the icon to a custom .spec or CLI build
# ──────────────────────────────────────────────
# CLI:   pyinstaller --onefile --windowed \
#                    --icon assets/NeuralExtractoricon.ico \
#                    --add-data "assets/NeuralExtractoricon.ico;assets" \
#                    --add-data "assets/NeuralExtractorIcon.png;assets" \
#                    main.py
#
# .spec: Set icon='assets/NeuralExtractoricon.ico' in EXE() (Windows) or
#        icon='assets/NeuralExtractorIcon.png' (macOS), and include both
#        files in the datas= list of Analysis() as shown below.

block_cipher = None

from PyInstaller.utils.hooks import collect_all

datas = [
    # Bundle both icon formats so the runtime path-resolution works on all
    # platforms without a network round-trip.
    ('assets/NeuralExtractorIcon.png', 'assets'),
    ('assets/NeuralExtractoricon.ico', 'assets'),
    ('assets/background.png', 'assets'),
    ('assets/backgroundrightpanel.png', 'assets'),
    ('bin/ffmpeg.exe', 'bin'),
    ('bin/ffprobe.exe', 'bin'),
]
binaries = []
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'youtube_transcript_api',
    'curl_cffi',
]

tmp_ret = collect_all('curl_cffi')
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    ['main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='NeuralExtractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # GUI-only; set True only for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows: embed icon into the .exe resource table
    # macOS  : change to 'assets/NeuralExtractorIcon.png' when building on Mac
    icon='assets/NeuralExtractoricon.ico',
)
