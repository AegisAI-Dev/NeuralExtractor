"""Auto-updater logic for checking and downloading background updates from GitHub."""

import json
import logging
import platform
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import QApplication

from neural_extractor.config import GITHUB_REPO, VERSION, get_data_dir

logger = logging.getLogger(__name__)


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string like 'v2.1.0' or '2.0' into a comparable tuple."""
    clean = version_str.lower().replace("v", "").replace("-", ".").split(".")
    parts = []
    for p in clean:
        try:
            parts.append(int(p))
        except ValueError:
            pass
    return tuple(parts)


class UpdaterSignals(QObject):
    """Signals for the Updater."""
    update_available = pyqtSignal(str)  # Emits the new version string
    download_progress = pyqtSignal(int) # Emits 0-100 progress
    update_ready = pyqtSignal(str, str) # Emits (version, temp_exe_path)
    error = pyqtSignal(str)


class UpdaterThread(QThread):
    """Background thread to check for and download updates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.signals = UpdaterSignals()
        self.temp_dir = get_data_dir() / "updates"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> None:
        """Run the update check."""
        try:
            # We only support auto-updating Windows EXEs right now
            if sys.platform != "win32" or not getattr(sys, "frozen", False):
                logger.info("Updater: Not running on Windows as a frozen EXE, skipping update check.")
                return

            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            
            # 1. Fetch latest release info
            req = urllib.request.Request(api_url, headers={"User-Agent": "NeuralExtractor-Updater"})
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode())
            except Exception as e:
                logger.warning(f"Updater: Could not check for updates: {e}")
                return

            latest_version_str = data.get("tag_name", "")
            if not latest_version_str:
                return

            latest_version = parse_version(latest_version_str)
            current_version = parse_version(VERSION)

            if latest_version <= current_version:
                logger.info(f"Updater: App is up to date (current: {VERSION}, latest: {latest_version_str})")
                return

            logger.info(f"Updater: Update found! Version {latest_version_str} is available.")
            self.signals.update_available.emit(latest_version_str)

            # 2. Find the Windows executable asset
            assets = data.get("assets", [])
            exe_asset = None
            for asset in assets:
                name = asset.get("name", "").lower()
                if name.endswith(".exe"):
                    exe_asset = asset
                    break
            
            if not exe_asset:
                logger.warning("Updater: No .exe asset found in the release.")
                return

            download_url = exe_asset.get("browser_download_url")
            asset_size = exe_asset.get("size", 1)

            # 3. Download the executable to a temporary file
            temp_exe = self.temp_dir / f"NeuralExtractor_{latest_version_str}.exe"
            
            # Clean up old updates if they exist
            for old_file in self.temp_dir.glob("*.exe"):
                if old_file.name != temp_exe.name:
                    try:
                        old_file.unlink()
                    except OSError:
                        pass

            # Download with progress
            req_dl = urllib.request.Request(download_url, headers={"User-Agent": "NeuralExtractor-Updater"})
            with urllib.request.urlopen(req_dl, timeout=30) as response:
                with open(temp_exe, "wb") as f:
                    downloaded = 0
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress = int((downloaded / asset_size) * 100)
                        self.signals.download_progress.emit(progress)

            logger.info(f"Updater: Download complete -> {temp_exe}")
            self.signals.update_ready.emit(latest_version_str, str(temp_exe))

        except Exception as e:
            logger.error(f"Updater error: {e}", exc_info=True)
            self.signals.error.emit(str(e))

def apply_update(temp_exe_path: str) -> None:
    """Creates a batch script to replace the running executable and restarts."""
    import os
    import subprocess
    import sys
    
    if not getattr(sys, "frozen", False):
        return  # Only works for frozen PyInstaller exes

    current_exe = sys.executable
    bat_path = get_data_dir() / "apply_update.bat"
    
    # Write the batch script
    bat_content = f"""@echo off
echo Installing Neural Extractor Update...
timeout /t 2 /nobreak > nul
copy /y "{temp_exe_path}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)
    
    # Launch the batch script detached without showing a window
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    
    # Exit the current app so the batch script can overwrite it
    QApplication.quit() if QApplication.instance() else sys.exit(0)
