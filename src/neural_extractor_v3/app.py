"""Application bootstrap for Neural Extractor V3."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from neural_extractor_v3.config import APP_NAME
from neural_extractor_v3.core.downloader import DownloadEngine
from neural_extractor_v3.models import DownloadJob, DownloadOptions, MediaMode, PlaylistMode


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="NeuralExtractorV3")
    parser.add_argument("--url", action="append", help="YouTube URL. Can be passed more than once.")
    parser.add_argument("--output", default=None, help="Output directory.")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in MediaMode],
        default=MediaMode.VIDEO.value,
        help="Download mode.",
    )
    parser.add_argument(
        "--playlist",
        choices=[mode.value for mode in PlaylistMode],
        default=PlaylistMode.AUTO.value,
        help="Playlist handling mode.",
    )
    parser.add_argument("--quality", default="Best available", help="Video quality preset.")
    parser.add_argument("--audio-quality", default="320", help="Audio bitrate for MP3/M4A.")
    parser.add_argument("--subs", default="nl", help="Subtitle language code, for example nl or en.")
    parser.add_argument("--no-subs", action="store_true", help="Disable subtitle download.")
    parser.add_argument("--no-thumbnail", action="store_true", help="Disable thumbnail download.")
    parser.add_argument("--cookies", default=None, help="Path to cookies.txt.")
    return parser.parse_args(argv)


def run_cli(args: argparse.Namespace) -> int:
    output_dir = Path(args.output).expanduser() if args.output else Path.home() / "Downloads"
    options = DownloadOptions(
        output_dir=output_dir,
        media_mode=MediaMode(args.mode),
        playlist_mode=PlaylistMode(args.playlist),
        quality=args.quality,
        audio_quality=args.audio_quality,
        subtitle_language=args.subs,
        subtitles=not args.no_subs,
        thumbnail=not args.no_thumbnail,
        cookie_file=Path(args.cookies).expanduser() if args.cookies else None,
    )
    engine = DownloadEngine(
        options=options,
        progress_callback=lambda event: print(event.compact_status()),
        log_callback=print,
    )

    exit_code = 0
    for url in args.url:
        result = engine.download(DownloadJob(url=url))
        print(result.message)
        if not result.success:
            exit_code = 1
    return exit_code


def run_gui(argv: list[str]) -> int:
    from neural_extractor_v3.gui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Neuralshield")
    window = MainWindow()
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.url:
        return run_cli(args)
    return run_gui(sys.argv if argv is None else ["NeuralExtractorV3", *argv])
