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
Use this folder as the repository root, then publish a release by pushing a tag:

```powershell
git tag v3.0.1
git push origin v3.0.1
```

The workflow will:

- install Python dependencies,
- run Ruff, compileall, and tests,
- build `NeuralExtractorV3.exe` with PyInstaller,
- create a versioned Windows asset,
- generate a SHA256 checksum,
- publish both files to the GitHub Release.

You can also run the workflow manually with `workflow_dispatch` and provide a release tag.

## App Updates

On startup, the desktop app silently checks the latest GitHub Release. The `Check Updates`
button runs the same check manually. When a newer release exists, V3 offers to open the
download URL for the newest `.exe` asset.

The default release repository is:

```text
AegisAI-Dev/NeuralExtractor
```

To use another repo, change `GITHUB_REPO` in `src/neural_extractor_v3/config.py`, or set
the `NEURAL_EXTRACTOR_GITHUB_REPO` environment variable before launching the app.

## Notes

- FFmpeg is required for merging video/audio, MP3 conversion, thumbnail embedding, and SRT conversion. If a local `bin` folder exists, V3 will use it automatically.
- Use a Netscape-format `cookies.txt` file when YouTube blocks a download that works in your browser.
- Respect YouTube terms, creator rights, and local law.
