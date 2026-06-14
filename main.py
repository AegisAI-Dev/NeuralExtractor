#!/usr/bin/env python3
"""Main entry point for Neural Extractor."""

import argparse
import sys
from pathlib import Path

# Add src to path so 'neural_extractor' package is importable in development.
# PyInstaller bundles handle this automatically via sys._MEIPASS.
script_dir = Path(__file__).parent.resolve()
src_path = script_dir / "src"
if src_path.exists():
    src_path_str = str(src_path)
    if src_path_str not in sys.path:
        sys.path.insert(0, src_path_str)

try:
    from neural_extractor import NeuralExtractor
except ImportError as e:
    print(f"Error: Could not import NeuralExtractor – {e}")
    print(f"Expected package at: {src_path / 'neural_extractor'}")
    sys.exit(1)

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Neural Extractor - YouTube video downloader with Dutch subtitles")
    parser.add_argument('--url', type=str, help='YouTube video URL to download')
    parser.add_argument('--subs', type=str, default='nl', choices=['nl', 'nl_auto', 'nl_whisper', 'none'],
                        help='Subtitle mode: nl (native), nl_auto (API), nl_whisper (local), none')
    parser.add_argument('--output', type=str, help='Output directory for downloads')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    app = NeuralExtractor()

    # Handle CLI arguments – pre-populate URL in the appropriate GUI backend
    if args.url:
        print(f"Downloading: {args.url}")
        print(f"Subtitle mode: {args.subs}")

        # Try to inject URL into the GUI for automatic download
        try:
            # PyQt6 v2 backend uses add_to_queue(url)
            if hasattr(app, 'add_to_queue'):
                app.add_to_queue(args.url)  # type: ignore[union-attr]
            # Tkinter v1 backend: set the URL entry, then call start_download()
            elif hasattr(app, 'url_entry'):
                app.url_entry.insert(0, args.url)  # type: ignore[union-attr]
                app.start_download()  # type: ignore[union-attr]
        except Exception as exc:
            print(f"Warning: could not inject CLI URL – {exc}")

    # Start the event loop – compatible with both Tkinter and PyQt6
    if hasattr(app, 'mainloop'):
        # Tkinter backend (tk.Tk has .mainloop)
        app.mainloop()
    else:
        # PyQt6 backend – QMainWindow needs .show(), then QApplication.exec()
        app.show()  # type: ignore[union-attr]
        from PyQt6.QtWidgets import QApplication as _QApp
        qapp = _QApp.instance()
        sys.exit(qapp.exec() if qapp else 1)

