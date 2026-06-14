# Neural Extractor v2.0.0

Neural Extractor is a modern, user-friendly application for Windows, Linux, and Mac that lets you easily download YouTube videos, thumbnails, and subtitles (SRT, WebVTT). The app supports single videos, playlists, batches, and Mixes, and offers a professional, colorful interface with a clear logo and icon.

## Why no .exe?
- You can inspect all code for safety and transparency.
- No hidden binaries or malware risk.
- Works on Windows, Linux, and Mac with Python 3.11+.

## Installation & Usage
1. **Install Python 3.11+**
   - [Download Python](https://www.python.org/downloads/)
2. **Open a terminal in this folder**
3. **Install the required packages:**
   ```bash
   pip install -r requirements.txt
   ```
   *(Optional)* You can also use `uv` for faster installation, as an `uv.lock` file is provided:
   ```bash
   uv sync
   ```
4. **Start the app:**
   ```bash
   python main.py
   ```

## Development & Testing

Neural Extractor v2.0.0 uses a highly modular structure (`src/neural_extractor/`) with strict type hinting, automated linting, and comprehensive test coverage.

- **Run tests locally:** `pytest`
- **Run linting:** `ruff check .`
- **Run type checking:** `mypy src/`

## Features
- Download YouTube videos in various qualities
- Download thumbnails (YouTube images) automatically
- Download subtitles in WebVTT and SRT formats, with language selection
  - Native/auto subtitle download via yt-dlp
  - Fallback to youtube-transcript-api for AI-translated subtitles
  - Automatic ASR (auto-generated) translation support
- **Dutch subtitle workflow with three-level fallback:**
  - Level 1: Native NL-track from YouTube (yt-dlp)
  - Level 2: YouTube-Transcript-API with auto-translation to Dutch
  - Level 3: Local Whisper transcription (requires Whisper installation)
  - Real-time status updates in GUI
  - Async processing to prevent GUI blocking
- Batch download: multiple links at once
- Playlist and Mix support
- Modern, colorful GUI (navy, teal, orange)
- Professional icon and logo
- Log and progress bar

## Visual Effects
The GUI features a pulsing neon glow effect on the main headers, implemented using `QGraphicsDropShadowEffect` and `QPropertyAnimation`. The glow tweens its blur radius seamlessly to create a subtle breathing effect. This can be toggled on/off via the "Animations" checkbox in the options panel.

## Subtitles & Translations
The app includes a robust subtitle workflow that guarantees an `.srt` or `.vtt` file in your preferred language (with dedicated handling for Dutch):

### GUI Usage
- Check "Download subtitles (WebVTT & SRT)"
- Select desired language from the dropdown (or use "Altijd NL-ondertitels" for Dutch)
- Subtitles are saved alongside the video file

### CLI Usage
```bash
python main.py --url "https://youtube.com/watch?v=VIDEO_ID" --subs nl
```

Subtitle modes:
- `nl` (default): Try native NL-track, then API, then Whisper
- `nl_auto`: Force API fallback
- `nl_whisper`: Force local Whisper transcription
- `none`: Disable subtitles

### Requirements for Whisper Fallback
- Install Whisper: `pip install openai-whisper`
- FFmpeg must be installed and in PATH
- First run downloads the Whisper model (~150MB for base model)

## Icons & Platforms

| Platform | Icon file | Shown in title bar | Shown in taskbar/dock |
|---|---|---|---|
| **Windows 11** | `assets/NeuralExtractoricon.ico` (multi-size 16–512 px) | ✅ | ✅ (script + .exe) |
| **macOS Sonoma** | `assets/NeuralExtractorIcon.png` (512 × 512, transparent) | ✅ | ✅ |
| **Ubuntu 24.04** | `assets/NeuralExtractorIcon.png` | ✅ | ✅ |

### How it works

**PyQt6 GUI (v2 – default)** – `src/neural_extractor/gui/main_window_v2.py`
```python
# set_app_icon() called in __init__:
icon = QIcon("assets/NeuralExtractoricon.ico")   # Windows
icon = QIcon("assets/NeuralExtractorIcon.png")   # macOS / Linux
self.setWindowIcon(icon)   # title bar
self.app.setWindowIcon(icon)  # dock / taskbar

# Windows taskbar fix (prevents grouping under python.exe):
import ctypes
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
    "Neuralshield.NeuralExtractor.v2"
)
```

**Tkinter GUI (v1 – fallback)** – `src/neural_extractor/gui/main_window.py`
```python
# Windows
self.iconbitmap(default="assets/NeuralExtractoricon.ico")

# macOS / Linux
img = Image.open("assets/NeuralExtractorIcon.png")
self.iconphoto(True, ImageTk.PhotoImage(img))
```

### High-DPI & dark-mode notes
- PyQt6 has **built-in high-DPI support** (no manual attribute flags needed on Qt 6).
- The `.ico` file contains sizes from **16 px to 512 px** so Windows auto-selects the right size at any DPI scale (100 %–200 %+).
- The PNG has a **transparent background** so it composites correctly on any dock/panel colour.

## Build & Distribution (PyInstaller)

### Quick CLI build (Windows)
```powershell
pyinstaller --onefile --windowed `
    --name NeuralExtractor `
    --icon assets/NeuralExtractoricon.ico `
    --add-data "assets/NeuralExtractoricon.ico;assets" `
    --add-data "assets/NeuralExtractorIcon.png;assets" `
    --add-data "assets/background.png;assets" `
    --add-data "assets/backgroundrightpanel.png;assets" `
    main.py
```

### Quick CLI build (macOS / Linux)
```bash
pyinstaller --onefile --windowed \
    --name NeuralExtractor \
    --icon assets/NeuralExtractorIcon.png \
    --add-data "assets/NeuralExtractorIcon.png:assets" \
    --add-data "assets/background.png:assets" \
    --add-data "assets/backgroundrightpanel.png:assets" \
    main.py
```
> **Note:** On macOS, PyInstaller automatically converts the `.png` to `.icns`.  
> On Linux the `--icon` flag is ignored at build time; the icon is set at runtime via `QIcon`.

### Using the included .spec file
```powershell
pyinstaller NeuralExtractor.spec
```
The `NeuralExtractor.spec` file already includes:
- `datas` entries for both `NeuralExtractoricon.ico` and `NeuralExtractorIcon.png`
- `icon='assets/NeuralExtractoricon.ico'` embedded into the `.exe` resource table

To build for **macOS** from the spec, change the `icon=` line in `EXE()`:
```python
icon='assets/NeuralExtractorIcon.png',  # PyInstaller converts to .icns
```

### Runtime path resolution in the bundle
`sys._MEIPASS` points to the temporary folder where PyInstaller unpacks assets.
Both GUI modules detect this automatically:
```python
if getattr(sys, 'frozen', False):
    base_path = Path(sys._MEIPASS)   # bundled
else:
    base_path = Path(__file__).resolve().parent.parent.parent.parent  # dev
icon_path = base_path / "assets" / "NeuralExtractoricon.ico"
```

## Frequently Asked Questions
- **Why no .exe?**
  - For maximum transparency and trust. You can inspect the code yourself.
- **How do I get the icon in the Windows taskbar when running as a script?**
  - The app uses `SetCurrentProcessExplicitAppUserModelID` via `ctypes` to force
    Windows to display the custom icon in the taskbar even when running as a Python
    script. No .exe required.
- **Python not found?**
  - Add Python to your PATH or install Python 3.11+.

## Support
For questions or issues, email AegisAI@duck.com or visit https://www.Neuralshield.dev.

---

Made with ❤️ by Neuralshield & 0xRootNull.