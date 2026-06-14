"""GUI components for Neural Extractor."""

# Prefer the PyQt6 v2 GUI; fall back to Tkinter v1 if PyQt6 is unavailable.
try:
    from neural_extractor.gui.main_window_v2 import NeuralExtractorV2 as NeuralExtractor
except ImportError:
    from neural_extractor.gui.main_window import NeuralExtractor  # type: ignore[assignment]

__all__ = ["NeuralExtractor"]
