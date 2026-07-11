# -*- mode: python ; coding: utf-8 -*-

import os
import shutil
from pathlib import Path

project_root = Path.cwd()
assets = project_root / "assets"
node_candidates = [
    project_root / "bin" / "node.exe",
]
node_from_path = shutil.which("node")
if node_from_path:
    node_candidates.append(Path(node_from_path))
for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
    root = os.environ.get(env_name)
    if root:
        node_candidates.append(Path(root) / "nodejs" / "node.exe")
node_runtime = next((path for path in node_candidates if path.exists()), None)

ffmpeg_bin_candidates = [
    project_root / "bin",
    project_root.parent
    / "NeuralYouTubeExtractor v0.1.1"
    / "NeuralYouTubeExtractor v0.1"
    / "NeuralExtractor"
    / "bin",
]
ffmpeg_bin = next((path for path in ffmpeg_bin_candidates if (path / "ffmpeg.exe").exists()), None)

datas = [
    (str(assets / "NeuralExtractoricon.ico"), "assets"),
    (str(assets / "NeuralExtractorIcon.png"), "assets"),
    (str(assets / "background.png"), "assets"),
    (str(assets / "backgroundrightpanel.png"), "assets"),
    (str(assets / "chevron-down.png"), "assets"),
    (str(assets / "chevron-down-disabled.png"), "assets"),
]

if ffmpeg_bin:
    datas += [
        (str(ffmpeg_bin / "ffmpeg.exe"), "bin"),
        (str(ffmpeg_bin / "ffprobe.exe"), "bin"),
    ]

binaries = []
if node_runtime:
    binaries.append((str(node_runtime), "bin"))

a = Analysis(
    ["main.py"],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="NeuralExtractorV3",
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
    icon=str(assets / "NeuralExtractoricon.ico"),
)
