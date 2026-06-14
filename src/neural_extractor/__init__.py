"""Neural Extractor - YouTube video downloader and extractor."""

__version__ = "2.0"

# Try to use PyQt6 GUI (v2), fall back to Tkinter GUI (v1)
try:
    from neural_extractor.gui.main_window_v2 import NeuralExtractorV2 as NeuralExtractor
except ImportError:
    from neural_extractor.gui.main_window import NeuralExtractor

__all__ = ["NeuralExtractor", "__version__"]

