"""Application bootstrap for Neural Extractor V3."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from neural_extractor_v3.config import APP_NAME, VERSION
from neural_extractor_v3.core.diagnostics import run_support_diagnostics
from neural_extractor_v3.core.downloader import DownloadEngine
from neural_extractor_v3.core.update_installer import (
    cleanup_stale_update_state,
    read_update_recovery_message,
    run_update_helper,
    write_startup_confirmation,
)
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
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print environment diagnostics for support and exit without downloading.",
    )
    parser.add_argument(
        "--diagnostics-probe-url",
        default=None,
        help="YouTube URL for the safe format probe. Defaults to the first --url or a public test video.",
    )
    parser.add_argument("--apply-update", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--post-update-token", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--post-update-marker", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--update-rollback-status", default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _options_from_args(args: argparse.Namespace) -> DownloadOptions:
    output_dir = Path(args.output).expanduser() if args.output else Path.home() / "Downloads"
    return DownloadOptions(
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


def run_diagnostics_cli(args: argparse.Namespace) -> int:
    options = _options_from_args(args)
    probe_url = args.diagnostics_probe_url or (args.url[0] if args.url else None)
    report = run_support_diagnostics(options, probe_url)
    print(report.text())
    return 0


def run_cli(args: argparse.Namespace) -> int:
    options = _options_from_args(args)
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


def run_gui(argv: list[str], args: argparse.Namespace) -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from neural_extractor_v3.gui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Neuralshield")
    window = MainWindow()
    window.show()

    if args.post_update_token and args.post_update_marker:
        def confirm_startup() -> None:
            try:
                write_startup_confirmation(
                    args.post_update_token,
                    Path(args.post_update_marker),
                    version=VERSION,
                )
                window.log(f"Update startup confirmed for version {VERSION}")
            except Exception:
                window.log("Update startup confirmation failed; the updater will restore the previous version")
                QTimer.singleShot(0, app.quit)

        QTimer.singleShot(1200, confirm_startup)

    if args.update_rollback_status:
        def show_recovery_status() -> None:
            message = read_update_recovery_message(Path(args.update_rollback_status))
            window.log(message)
            QMessageBox.warning(window, "Update Recovery", message)

        QTimer.singleShot(800, show_recovery_status)

    QTimer.singleShot(10_000, cleanup_stale_update_state)
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.apply_update:
        return run_update_helper(Path(args.apply_update))
    if bool(args.post_update_token) != bool(args.post_update_marker):
        return 2
    if args.diagnostics:
        return run_diagnostics_cli(args)
    if args.url:
        return run_cli(args)
    return run_gui(
        sys.argv if argv is None else ["NeuralExtractorV3", *argv],
        args,
    )
