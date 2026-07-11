# Neural Extractor V3

Neural Extractor V3 is a clean rebuild of the app as a separate professional edition. It downloads single videos, full playlists, YouTube Mixes, batches of links, MP3/M4A audio, SRT subtitles, thumbnails, and optional metadata sidecars.

## What V3 Includes

- Video downloads as MP4 with selectable quality up to best available.
- Audio downloads as MP3 or M4A with bitrate presets.
- Full playlist and Mix support, plus current-video-only mode.
- Batch queue: paste one URL per line and process them in order.
- Subtitles saved as `.srt`, including auto-generated subtitles when needed.
- Thumbnail download as JPG, with optional embedding for audio files.
- Optional `cookies.txt` support for age-restricted or session-sensitive videos.
- Optional metadata JSON output.
- CLI mode for scripted downloads.
- PyQt6 desktop interface with progress, queue status, and logs.

## Start

From this folder:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\src"
python main.py
```

Or run:

```powershell
start.bat
```

## CLI Examples

Download a video with Dutch SRT subtitles and thumbnail:

```powershell
$env:PYTHONPATH = "$PWD\src"
python main.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --mode video --subs nl
```

Download a full playlist as MP3:

```powershell
$env:PYTHONPATH = "$PWD\src"
python main.py --url "https://www.youtube.com/playlist?list=PLAYLIST_ID" --mode audio_mp3 --playlist full
```

Download subtitles only:

```powershell
$env:PYTHONPATH = "$PWD\src"
python main.py --url "https://youtu.be/VIDEO_ID" --mode subtitles_only --subs nl
```

## Build Windows EXE

```powershell
pyinstaller NeuralExtractorV3.spec --clean --noconfirm
```

Or run:

```powershell
build.bat
```

The built executable is written to:

```text
dist\NeuralExtractorV3.exe
```

## GitHub Release Pipeline

V3 includes a GitHub Actions workflow at `.github/workflows/build-release.yml`.
The workflow will:

- require a numeric release version matching both source version files,
- install Python dependencies,
- run Ruff, compileall, and tests,
- build the Windows x64 `NeuralExtractorV3.exe` with PyInstaller,
- create the exact versioned Windows asset,
- generate its SHA-256 checksum and strict JSON manifest,
- publish the EXEs, checksum, and manifest to the GitHub Release.

It runs for tags matching `v*.*.*` and supports `workflow_dispatch` with an
explicit version. The manual action appears only after the workflow is on the
default branch. See [docs/UPDATE_ARCHITECTURE.md](docs/UPDATE_ARCHITECTURE.md)
for the GitHub Desktop and GitHub web release procedure.

## App Updates

On startup, the desktop app silently checks the latest stable GitHub Release. The
`Check Updates` button runs the same check manually. Packaged version 3.0.2 and
later can download the exact versioned EXE, validate its strict manifest and
SHA-256, install through a detached helper, restart, confirm startup, and roll
back to the verified backup when startup fails. Installation always requires a
clear user action.

Version 3.0.1 must be upgraded to 3.0.2 manually once. Source-mode or non-writable
installs retain the manual release-page fallback.

The default release repository is:

```text
AegisAI-Dev/NeuralExtractor
```

The automatic update source is intentionally pinned and is not configurable at
runtime. The EXE is SHA-256 verified but is not Authenticode publisher-signed.

## Notes

- FFmpeg is required for merging video/audio, MP3 conversion, thumbnail embedding, and SRT conversion. If a local `bin` folder exists, V3 will use it automatically.
- Use a Netscape-format `cookies.txt` file when YouTube blocks a download that works in your browser.
- Respect YouTube terms, creator rights, and local law.
