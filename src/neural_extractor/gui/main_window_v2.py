"""Neural Extractor v2 - Premium Glass-Morphism GUI."""

import sys
import threading
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QSettings,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# PyQt6 has built-in high-DPI support, no need for manual attribute setting
from neural_extractor.config import (
    DEFAULT_OUTPUT,
    DEFAULT_QUALITY,
    DEFAULT_SUBTITLE_LANG,
    QUALITY_OPTIONS,
    SUBTITLE_LANGUAGES,
    VERSION,
    get_base_dir,
)
from neural_extractor.core.downloader import Downloader
from neural_extractor.core.subtitle_manager import SubtitleManager
from neural_extractor.core.updater import UpdaterThread, apply_update
from neural_extractor.logger import logger
from neural_extractor.validator import validate_youtube_url

# Color Tokens
COLORS = {
    "primary_bg": "#0E1A2B",
    "accent": "#00BDB0",
    "cta": "#FF7E31",
    "surface": "#F7F8FA",
    "text_high": "#1C1E22",
    "text_low": "rgba(28, 30, 34, 150)",
    "glass_bg": "rgba(14, 26, 43, 180)",
    "glass_border": "rgba(255, 255, 255, 26)",
}


class ElectricLabel(QLabel):
    """A QLabel that draws a flowing, glowing electric border around its bounding box."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.offset = 0.0
        self.animations_enabled = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_electricity)
        self.timer.start(30)

    def set_animations_enabled(self, enabled: bool):
        self.animations_enabled = enabled
        if enabled:
            if not self.timer.isActive():
                self.timer.start(30)
        else:
            self.timer.stop()
            self.update()

    def update_electricity(self):
        self.offset -= 2.0  # Speed of the electricity flow
        if self.offset < -1000:
            self.offset = 0.0
        self.update()

    def paintEvent(self, event):  # noqa: N802
        # Draw the text and style first
        super().paintEvent(event)

        if not self.animations_enabled:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Border box slightly inside the widget to prevent clipping
        rect = self.rect().adjusted(2, 2, -2, -2)

        # Draw three layers of electric current (glow -> core -> bright center)
        layers = [
            (6, 60, QColor(0, 189, 176)),  # Outer blue glow
            (3, 150, QColor(0, 189, 176)),  # Inner blue core
            (1, 255, QColor(255, 255, 255)),  # Bright white hot center
        ]

        for width, alpha, base_color in layers:
            color = QColor(base_color)
            color.setAlpha(alpha)
            pen = QPen(color)
            pen.setWidth(width)

            # Create a broken/dashed line that looks like energy arcs
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([15, 10, 5, 20, 25, 10])
            pen.setDashOffset(self.offset)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

            painter.setPen(pen)
            painter.drawRoundedRect(rect, 6, 6)

        painter.end()


class SignalEmitter(QObject):
    """Emitter for thread-safe signals."""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(dict)
    status_signal = pyqtSignal(str, str)
    # Per-queue-item signals: (progress_value, speed_text, progress_bar_ref, speed_label_ref)
    queue_update_signal = pyqtSignal(int, str, object, object)
    # Title update: (title_text, url_label_ref)
    queue_title_signal = pyqtSignal(str, object)


class NeuralExtractorV2(QMainWindow):
    """Premium glass-morphism GUI for Neural Extractor v2."""

    def __init__(self) -> None:
        """Initialize the main window."""
        # Ensure QApplication exists
        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()

        super().__init__()

        # Window setup
        self.setWindowTitle(f"Neural Extractor v{VERSION}")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        # Set window icon
        self.set_app_icon()

        # Apply dark theme
        self.apply_theme()

        # Download state
        self.download_thread: threading.Thread | None = None
        self.stop_download: bool = False
        self.downloader: Downloader | None = None

        # Initialize settings storage
        self.settings = QSettings("Neuralshield", "NeuralExtractor")

        # Output directory (user-configurable, saved)
        saved_output = self.settings.value("output_dir", str(DEFAULT_OUTPUT))
        self.output_dir: Path = Path(saved_output)

        # Optional cookies.txt file (saved)
        saved_cookie = self.settings.value("cookie_file", "")
        self.cookie_file: Path | None = Path(saved_cookie) if saved_cookie else None

        # Subtitle manager
        self.subtitle_manager = SubtitleManager(
            output_dir=self.output_dir, cookie_file=self.cookie_file
        )
        self.subtitle_manager.set_status_callback(self.update_subtitle_status)

        # Signal emitter for thread-safe updates
        self.emitter = SignalEmitter()
        self.emitter.log_signal.connect(self.log)
        self.emitter.progress_signal.connect(self.on_progress)
        self.emitter.status_signal.connect(self.update_status_ui)
        self.emitter.queue_update_signal.connect(self._on_queue_update)
        self.emitter.queue_title_signal.connect(self._on_queue_title)

        # Create UI
        self.create_widgets()

        # Apply fade-in animation to headings
        QTimer.singleShot(100, self.fade_in_headings)

        # Log initialization
        self.log(f"Neural Extractor v{VERSION} initialized")
        self.log("Ready to download videos")

        # Start background updater check
        self.check_for_updates()

    def fade_in_headings(self) -> None:
        """Apply fade-in animation to headings."""
        # Create fade-in effect using opacity animation
        self.header_animation = QPropertyAnimation(self, b"windowOpacity")
        self.header_animation.setDuration(300)
        self.header_animation.setStartValue(0.0)
        self.header_animation.setEndValue(1.0)
        self.header_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.header_animation.start()

    def check_for_updates(self) -> None:
        """Start the background updater thread."""
        self.updater_thread = UpdaterThread(self)
        self.updater_thread.signals.update_available.connect(self.on_update_available)
        self.updater_thread.signals.update_ready.connect(self.on_update_ready)
        self.updater_thread.signals.error.connect(self.on_update_error)
        self.updater_thread.start()

    def on_update_available(self, version: str) -> None:
        """Called when a new version is detected."""
        self.log(f"⭐ Nieuwe update beschikbaar: {version}. Downloaden op de achtergrond...")

    def on_update_ready(self, version: str, temp_exe_path: str) -> None:
        """Called when the new version has finished downloading."""
        self.log(f"✅ Update {version} is gedownload en klaar voor installatie!")
        reply = QMessageBox.question(
            self,
            "Update Beschikbaar!",
            f"Versie {version} is op de achtergrond gedownload.\n\nWil je Neural Extractor nu herstarten om de update te installeren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            apply_update(temp_exe_path)

    def on_update_error(self, error: str) -> None:
        """Called if the updater encounters an error."""
        logger.warning(f"Updater fout: {error}")

    def toggle_animations(self) -> None:
        """Start or stop animations based on the checkbox state."""
        is_enabled = self.animations_check.isChecked()
        self.settings.setValue("animations_enabled", is_enabled)
        for label in self.electric_labels:
            if hasattr(label, "set_animations_enabled"):
                label.set_animations_enabled(is_enabled)

    def set_app_icon(self) -> None:
        """Set the application icon for window title bar and taskbar/dock.

        Works in both development (relative path) and PyInstaller bundle
        (sys._MEIPASS). On Windows we also set a unique AppUserModelID so
        the OS taskbar shows our custom icon instead of the generic Python
        icon.
        """
        try:
            # Resolve the assets directory
            if getattr(sys, "frozen", False):
                # Running as PyInstaller bundle — assets are unpacked next to
                # the executable inside sys._MEIPASS
                base_path = Path(sys._MEIPASS)  # type: ignore[attr-defined]
            else:
                # Development: navigate from this file up to the project root
                # gui/main_window_v2.py -> gui -> neural_extractor -> src -> project
                base_path = Path(__file__).resolve().parent.parent.parent.parent

            # Platform-specific icon: .ico on Windows, .png everywhere else
            if sys.platform == "win32":
                icon_path = base_path / "assets" / "NeuralExtractoricon.ico"
            else:
                icon_path = base_path / "assets" / "NeuralExtractorIcon.png"

            if icon_path.exists():
                icon = QIcon(str(icon_path))
                # Set on both window and application (covers title bar + dock)
                self.setWindowIcon(icon)
                self.app.setWindowIcon(icon)

                # Windows: register a unique AppUserModelID so the taskbar
                # groups the window under our icon, not the Python launcher icon
                if sys.platform == "win32":
                    try:
                        import ctypes

                        app_id = "Neuralshield.NeuralExtractor.v2"
                        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
                    except Exception:
                        pass  # Non-fatal: icon still shows in title bar
            else:
                logger.warning(f"Icon file not found at: {icon_path}")
        except Exception as e:
            logger.warning(f"Could not set application icon: {e}")

    def add_background_to_widget(
        self, widget: QWidget, image_filename: str, centered: bool = False
    ) -> None:
        """
        Add a background image to a widget with proper scaling and positioning.

        Args:
            widget: The widget to apply the background to
            image_filename: Name of the image file in assets folder
            centered: If True, center the image; if False, position top-right
        """
        try:
            # Get the path to the background image
            background_path = get_base_dir() / "assets" / image_filename

            if background_path.exists():
                # Load the pixmap
                pixmap = QPixmap(str(background_path))
                if not pixmap.isNull():
                    # Create a label for the background
                    background_label = QLabel(widget)
                    background_label.setObjectName(f"background_{image_filename}")

                    # Scale image to fill widget dimensions without distortion (like CSS background-size: cover)
                    scaled_pixmap = pixmap.scaled(
                        widget.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    background_label.setPixmap(scaled_pixmap)

                    # Position the background
                    if centered:
                        # Center the image
                        x = (widget.width() - scaled_pixmap.width()) // 2
                        y = (widget.height() - scaled_pixmap.height()) // 2
                    else:
                        # Position top-right
                        x = widget.width() - scaled_pixmap.width()
                        y = 0

                    background_label.setGeometry(
                        x, y, scaled_pixmap.width(), scaled_pixmap.height()
                    )
                    background_label.lower()  # Send to back so widgets remain visible

                    # Store reference for resize handling
                    widget.setProperty("background_label", background_label)
                    widget.setProperty("background_filename", image_filename)
                    widget.setProperty("background_centered", centered)

                    # Connect resize event to update background
                    widget.resizeEvent = lambda event: self.update_widget_background(widget, event)
        except Exception as e:
            logger.warning(f"Could not load background image {image_filename}: {e}")

    def update_widget_background(self, widget: QWidget, event) -> None:
        """Update background image when widget is resized."""
        # Call original resize event if exists
        if hasattr(widget, "_original_resizeEvent"):
            widget._original_resizeEvent(event)

        # Get background properties
        background_label = widget.property("background_label")
        image_filename = widget.property("background_filename")
        centered = widget.property("background_centered")

        if background_label and image_filename:
            try:
                background_path = get_base_dir() / "assets" / image_filename

                if background_path.exists():
                    pixmap = QPixmap(str(background_path))
                    if not pixmap.isNull():
                        # Rescale to new dimensions (fill widget like CSS background-size: cover)
                        scaled_pixmap = pixmap.scaled(
                            widget.size(),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        background_label.setPixmap(scaled_pixmap)

                        # Reposition
                        if centered:
                            x = (widget.width() - scaled_pixmap.width()) // 2
                            y = (widget.height() - scaled_pixmap.height()) // 2
                        else:
                            x = widget.width() - scaled_pixmap.width()
                            y = 0

                        background_label.setGeometry(
                            x, y, scaled_pixmap.width(), scaled_pixmap.height()
                        )
            except Exception as e:
                logger.warning(f"Could not update background image: {e}")

    def apply_theme(self) -> None:
        """Apply premium dark theme with glass-morphism."""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["primary_bg"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["surface"]))
        palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["primary_bg"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["primary_bg"]))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["surface"]))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text_high"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["surface"]))
        palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["glass_bg"]))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["surface"]))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(COLORS["accent"]))
        palette.setColor(QPalette.ColorRole.Link, QColor(COLORS["accent"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["primary_bg"]))
        QApplication.setPalette(palette)

        # Set font
        font = QFont("Inter", 10)
        QApplication.setFont(font)

    def create_widgets(self) -> None:
        """Create and arrange UI widgets."""
        self.electric_labels = []  # Initialize before any labels are created

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Main layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Create main content area
        self.create_main_content(main_layout)

        # Create queue panel
        self.create_queue_panel(main_layout)

    def create_main_content(self, parent_layout: QHBoxLayout) -> None:
        """Create central canvas with drag-drop zone and background image."""
        content = QFrame()
        content.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS["primary_bg"]};
            }}
        """
        )

        # Add background image to Main Frame (centered)
        self.add_background_to_widget(content, "background.png", centered=True)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 40, 40, 40)
        content_layout.setSpacing(32)

        # Header with gradient styling
        header_container = QFrame()
        header_container.setStyleSheet(
            """
            QFrame {
                background-color: rgba(14, 26, 43, 64);
                border-radius: 12px;
                padding: 12px 16px;
            }
        """
        )

        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Single unified header
        header = ElectricLabel("Neural Extractor v2")
        header.setStyleSheet(
            """
            QLabel {
                color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #00BDB0, stop:1 #FF7E31);
                font-size: 32px;
                font-weight: 800;
                letter-spacing: -0.5px;
                font-family: "Inter", "SF Pro Display", "Poppins", Arial;
                padding: 12px 12px;
            }
        """
        )
        self.electric_labels.append(header)

        header_layout.addWidget(header)
        content_layout.addWidget(header_container)

        # Canvas card with glass effect
        canvas_card = QFrame()
        canvas_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS["glass_bg"]};
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 12px;
            }}
        """
        )

        card_layout = QVBoxLayout(canvas_card)
        card_layout.setContentsMargins(48, 48, 48, 48)
        card_layout.setSpacing(24)

        # Drag-drop zone
        self.drag_drop_zone = QFrame()
        self.drag_drop_zone.setMinimumHeight(120)
        self.drag_drop_zone.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(0, 189, 176, 13);
                border: 2px dashed {COLORS["glass_border"]};
                border-radius: 12px;
            }}
            QFrame:hover {{
                border-color: {COLORS["accent"]};
                background-color: rgba(0, 189, 176, 26);
            }}
        """
        )
        self.drag_drop_zone.setAcceptDrops(True)

        zone_layout = QVBoxLayout(self.drag_drop_zone)
        zone_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_label = QLabel("Drag & drop video URL here")
        drop_label.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["surface"]};
                font-size: 16px;
                font-weight: 500;
            }}
        """
        )
        drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Add subtle shadow for better readability
        drop_shadow = QGraphicsDropShadowEffect()
        drop_shadow.setBlurRadius(10)
        drop_shadow.setColor(QColor(0, 0, 0, 120))
        drop_shadow.setOffset(0, 1)
        drop_label.setGraphicsEffect(drop_shadow)
        zone_layout.addWidget(drop_label)

        sub_label = QLabel("or paste from clipboard")
        sub_label.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["text_low"]};
                font-size: 14px;
            }}
        """
        )
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone_layout.addWidget(sub_label)

        card_layout.addWidget(self.drag_drop_zone)

        # URL Input Row
        url_layout = QHBoxLayout()
        url_layout.setSpacing(12)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_input.setFixedHeight(50)
        self.url_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: {COLORS["glass_bg"]};
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 12px;
                color: {COLORS["surface"]};
                font-size: 15px;
                padding: 0 16px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS["accent"]};
            }}
        """
        )
        url_layout.addWidget(self.url_input, stretch=1)

        # Paste button
        self.paste_button = QPushButton("Paste")
        self.paste_button.setFixedHeight(50)
        self.paste_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 10);
                color: {COLORS["surface"]};
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 12px;
                font-size: 15px;
                font-weight: 600;
                padding: 0 24px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 20);
                border-color: {COLORS["surface"]};
            }}
        """
        )
        self.paste_button.clicked.connect(self.paste_url)
        url_layout.addWidget(self.paste_button)

        # Download button
        self.download_button = QPushButton("Start Download")
        self.download_button.setFixedHeight(50)
        self.download_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS["cta"]};
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 600;
                padding: 0 32px;
            }}
            QPushButton:hover {{
                background-color: #ff8f4a;
            }}
            QPushButton:pressed {{
                background-color: {COLORS["cta"]};
            }}
        """
        )
        self.download_button.clicked.connect(self._start_download_from_input)
        url_layout.addWidget(self.download_button)

        card_layout.addLayout(url_layout)

        # Options section
        options_layout = QHBoxLayout()
        options_layout.setSpacing(24)

        # Quality dropdown
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITY_OPTIONS)
        self.quality_combo.setCurrentIndex(0)
        self.quality_combo.setStyleSheet(
            f"""
            QComboBox {{
                background-color: {COLORS["glass_bg"]};
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 12px;
                color: {COLORS["surface"]};
                font-size: 14px;
                font-weight: 500;
                padding: 12px 20px;
                min-width: 150px;
            }}
            QComboBox:hover {{
                border-color: {COLORS["accent"]};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {COLORS["surface"]};
            }}
        """
        )
        options_layout.addWidget(self.quality_combo)

        # Subtitle pills (checkboxes styled as pills)
        self.subtitle_check = QCheckBox("Download subtitles")
        self.subtitle_check.setStyleSheet(
            f"""
            QCheckBox {{
                color: {COLORS["surface"]};
                font-size: 14px;
                font-weight: 500;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid {COLORS["accent"]};
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS["accent"]};
            }}
        """
        )
        options_layout.addWidget(self.subtitle_check)

        # Subtitle language combo
        self.subtitle_lang_combo = QComboBox()
        self.subtitle_lang_combo.addItems(SUBTITLE_LANGUAGES)
        self.subtitle_lang_combo.setCurrentText(DEFAULT_SUBTITLE_LANG)
        self.subtitle_lang_combo.setFixedHeight(28)
        self.subtitle_lang_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subtitle_lang_combo.setStyleSheet(
            f"""
            QComboBox {{
                background-color: rgba(255, 255, 255, 10);
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 4px;
                color: {COLORS["surface"]};
                padding: 0 10px;
                font-size: 13px;
                font-family: "Inter", "SF Pro Display", "Poppins", Arial;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {COLORS["surface"]};
                margin-right: 8px;
            }}
        """
        )
        options_layout.addWidget(self.subtitle_lang_combo)

        # Auto-thumbnail checkbox
        self.thumbnail_check = QCheckBox("Auto-thumbnail")
        self.thumbnail_check.setChecked(True)
        self.thumbnail_check.setStyleSheet(
            f"""
            QCheckBox {{
                color: {COLORS["surface"]};
                font-size: 14px;
                font-weight: 500;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid {COLORS["accent"]};
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS["accent"]};
            }}
        """
        )
        options_layout.addWidget(self.thumbnail_check)

        # Animations toggle
        saved_animations = self.settings.value("animations_enabled", True, type=bool)
        self.animations_check = QCheckBox("Animations")
        self.animations_check.setChecked(saved_animations)
        self.animations_check.stateChanged.connect(self.toggle_animations)
        self.animations_check.setStyleSheet(
            f"""
            QCheckBox {{
                color: {COLORS["surface"]};
                font-size: 14px;
                font-weight: 500;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid {COLORS["accent"]};
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS["accent"]};
            }}
        """
        )
        options_layout.addWidget(self.animations_check)

        options_layout.addStretch()
        card_layout.addLayout(options_layout)

        # ── Output folder row ───────────────────────────────────────────────
        output_row = QHBoxLayout()
        output_row.setSpacing(12)

        output_icon = QLabel("📁 Output folder:")
        output_icon.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["surface"]};
                font-size: 13px;
                font-weight: 500;
                min-width: 110px;
            }}
        """
        )
        output_row.addWidget(output_icon)

        self.output_path_edit = QLineEdit(str(self.output_dir))
        self.output_path_edit.setReadOnly(True)
        self.output_path_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 8);
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 8px;
                color: {COLORS["surface"]};
                font-size: 13px;
                padding: 6px 12px;
            }}
        """
        )
        output_row.addWidget(self.output_path_edit, stretch=1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedHeight(34)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(0, 189, 176, 25);
                border: 1px solid {COLORS["accent"]};
                border-radius: 8px;
                color: {COLORS["accent"]};
                font-size: 13px;
                font-weight: 600;
                padding: 0 18px;
            }}
            QPushButton:hover {{
                background-color: rgba(0, 189, 176, 55);
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 189, 176, 80);
            }}
        """
        )
        browse_btn.clicked.connect(self.browse_output_folder)
        output_row.addWidget(browse_btn)

        card_layout.addLayout(output_row)
        # ────────────────────────────────────────────────────────────────────

        # ── Cookies.txt row ────────────────────────────────────────────────
        cookies_row = QHBoxLayout()
        cookies_row.setSpacing(12)

        cookies_icon = QLabel("🍪 Cookies.txt:")
        cookies_icon.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["surface"]};
                font-size: 13px;
                font-weight: 500;
                min-width: 110px;
            }}
        """
        )
        cookies_row.addWidget(cookies_icon)

        initial_cookie_text = (
            str(self.cookie_file) if self.cookie_file else "Not set – browser cookies or no cookies"
        )
        self.cookie_path_edit = QLineEdit(initial_cookie_text)
        self.cookie_path_edit.setReadOnly(True)

        # Style based on whether a cookie is loaded
        color_val = COLORS["accent"] if self.cookie_file else "rgba(247, 248, 250, 140)"
        font_style = "normal" if self.cookie_file else "italic"

        self.cookie_path_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 8);
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 8px;
                color: {color_val};
                font-size: 12px;
                padding: 6px 12px;
                font-style: {font_style};
            }}
        """
        )
        cookies_row.addWidget(self.cookie_path_edit, stretch=1)

        browse_cookie_btn = QPushButton("Load")
        browse_cookie_btn.setFixedHeight(34)
        browse_cookie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_cookie_btn.setToolTip(
            "Select a cookies.txt file exported from your browser.\n"
            "Chrome/Edge: install 'Get cookies.txt LOCALLY' extension.\n"
            "Firefox: install 'cookies.txt' extension.\n"
            "This lets you download with the browser open."
        )
        browse_cookie_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(255, 126, 49, 20);
                border: 1px solid {COLORS["cta"]};
                border-radius: 8px;
                color: {COLORS["cta"]};
                font-size: 13px;
                font-weight: 600;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 126, 49, 50);
            }}
        """
        )
        browse_cookie_btn.clicked.connect(self.browse_cookie_file)
        cookies_row.addWidget(browse_cookie_btn)

        clear_cookie_btn = QPushButton("×")
        clear_cookie_btn.setFixedSize(34, 34)
        clear_cookie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_cookie_btn.setToolTip("Remove cookies.txt (fall back to browser cookies)")
        clear_cookie_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 10);
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 8px;
                color: {COLORS["surface"]};
                font-size: 16px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 80, 80, 60);
                border-color: #ff5050;
            }}
        """
        )
        clear_cookie_btn.clicked.connect(self.clear_cookie_file)
        cookies_row.addWidget(clear_cookie_btn)

        card_layout.addLayout(cookies_row)
        # ────────────────────────────────────────────────────────────────────

        content_layout.addWidget(canvas_card)
        content_layout.addStretch()

        # Professional Credits
        credits_label = QLabel("Published by NeuralShield • Created by 0xRootNull")
        credits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits_label.setStyleSheet(
            """
            QLabel {
                color: rgba(255, 255, 255, 90);
                font-size: 12px;
                font-weight: 500;
                letter-spacing: 0.5px;
                padding-bottom: 8px;
                font-family: "Inter", "SF Pro Display", "Poppins", Arial;
            }
        """
        )
        content_layout.addWidget(credits_label)

        parent_layout.addWidget(content, stretch=1)

    def create_queue_panel(self, parent_layout: QHBoxLayout) -> None:
        """Create right queue panel with download items and background image."""
        queue_panel = QFrame()
        queue_panel.setFixedWidth(320)
        queue_panel.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS["glass_bg"]};
                border-left: 1px solid {COLORS["glass_border"]};
            }}
        """
        )

        # Add background image to Right Panel (top-right positioning)
        self.add_background_to_widget(queue_panel, "backgroundrightpanel.png", centered=False)

        queue_layout = QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(24, 24, 24, 24)
        queue_layout.setSpacing(16)

        # Header with gradient styling
        queue_header = ElectricLabel("Download Queue")
        queue_header.setStyleSheet(
            """
            QLabel {
                color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #00BDB0, stop:1 #FF7E31);
                font-size: 18px;
                font-weight: 700;
                font-family: "Inter", "SF Pro Display", "Poppins", Arial;
                padding: 12px 12px;
            }
        """
        )
        self.electric_labels.append(queue_header)

        queue_layout.addWidget(queue_header)

        # Queue items container
        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.setSpacing(12)
        queue_layout.addWidget(self.queue_container)

        queue_layout.addStretch()

        # Log console
        log_label = QLabel("Log Console")
        log_label.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["surface"]};
                font-size: 14px;
                font-weight: 600;
                padding: 4px 0px;
            }}
        """
        )
        # Add shadow for better readability
        log_shadow = QGraphicsDropShadowEffect()
        log_shadow.setBlurRadius(12)
        log_shadow.setColor(QColor(0, 0, 0, 140))
        log_shadow.setOffset(0, 1)
        log_label.setGraphicsEffect(log_shadow)
        queue_layout.addWidget(log_label)

        # Subtitle status label
        self.subtitle_status_label = QLabel("Ondertitels: Niet actief")
        self.subtitle_status_label.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["text_low"]};
                font-size: 12px;
                font-weight: 500;
                padding: 4px 0px;
                font-style: italic;
            }}
        """
        )
        queue_layout.addWidget(self.subtitle_status_label)

        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(120)
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            f"""
            QTextEdit {{
                background-color: rgba(0, 0, 0, 77);
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 8px;
                color: {COLORS["accent"]};
                font-family: "JetBrains Mono", "Consolas", monospace;
                font-size: 13px;
                padding: 12px;
            }}
        """
        )
        queue_layout.addWidget(self.log_text)

        parent_layout.addWidget(queue_panel)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        """Handle drag enter event."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """Handle drop event."""
        urls = [url.toLocalFile() for url in event.mimeData().urls()]
        for url in urls:
            if validate_youtube_url(url):
                self.url_input.setText(url)
                self.log(f"URL loaded from drag-drop: {url}")
                return  # Only take the first valid one

    def paste_url(self) -> None:
        """Paste URL from clipboard."""
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            self.url_input.setText(text)
            self.log("Pasted from clipboard.")

    def _start_download_from_input(self) -> None:
        """Triggered by the Start Download button."""
        url = self.url_input.text().strip()
        if url and validate_youtube_url(url):
            self.add_to_queue(url)
            self.url_input.clear()  # clear after starting
        else:
            self.log("❌ Invalid YouTube URL")

    def add_to_queue(self, url: str) -> None:
        """Add URL to download queue and immediately start the download."""
        # ── Build queue item widget ──────────────────────────────────────────
        queue_item = QFrame()
        queue_item.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(255, 255, 255, 13);
                border: 1px solid {COLORS["glass_border"]};
                border-radius: 12px;
            }}
            QFrame:hover {{
                background-color: rgba(255, 255, 255, 20);
            }}
        """
        )

        item_layout = QHBoxLayout(queue_item)
        item_layout.setContentsMargins(16, 16, 16, 16)
        item_layout.setSpacing(12)

        # Thumbnail placeholder
        thumbnail = QLabel("YT")
        thumbnail.setFixedSize(60, 60)
        thumbnail.setStyleSheet(
            f"""
            QLabel {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {COLORS["accent"]}, stop:1 {COLORS["cta"]});
                color: white;
                font-weight: 600;
                font-size: 12px;
                border-radius: 8px;
            }}
        """
        )
        thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        item_layout.addWidget(thumbnail)

        # Info column
        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        # Show a placeholder until the real title is fetched
        short_label = "⏳ Ophalen…"
        url_label = QLabel(short_label)
        url_label.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["surface"]};
                font-size: 13px;
                font-weight: 500;
            }}
        """
        )
        info_layout.addWidget(url_label)

        speed_label = QLabel("⏳ Starting…")
        speed_label.setStyleSheet(
            f"""
            QLabel {{
                color: {COLORS["accent"]};
                font-family: "JetBrains Mono", "Consolas", monospace;
                font-size: 12px;
            }}
        """
        )
        info_layout.addWidget(speed_label)

        # Progress bar
        progress_bar = QProgressBar()
        progress_bar.setFixedHeight(8)
        progress_bar.setTextVisible(False)
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                background-color: rgba(255, 255, 255, 10);
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {COLORS["accent"]}, stop:1 {COLORS["cta"]});
                border-radius: 2px;
            }}
        """
        )
        info_layout.addWidget(progress_bar)

        item_layout.addLayout(info_layout)
        self.queue_layout.addWidget(queue_item)
        # ────────────────────────────────────────────────────────────────────

        # ── Start real download thread ───────────────────────────────────────
        t = threading.Thread(
            target=self._run_download,
            args=(url, progress_bar, speed_label, url_label),
            daemon=True,
        )
        t.start()

    def _run_download(
        self,
        url: str,
        progress_bar: QProgressBar,
        speed_label: QLabel,
        url_label: QLabel,
    ) -> None:
        """Download worker – runs in a background thread.

        All UI mutations are dispatched back to the main thread via
        Qt signals, which are the only thread-safe way to update widgets.
        """

        def progress_hook(data: dict) -> None:
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes", 0) or data.get("total_bytes_estimate", 0)
                downloaded = data.get("downloaded_bytes", 0)
                pct = int(downloaded / total * 100) if total > 0 else 0
                spd = data.get("speed") or 0
                if spd:
                    spd_mb = spd / 1_048_576
                    eta = int((total - downloaded) / spd) if spd and total else 0
                    spd_text = f"⬇ {spd_mb:.1f} MB/s  ETA {eta}s"
                else:
                    spd_text = "⬇ Downloading…"
                self.emitter.queue_update_signal.emit(pct, spd_text, progress_bar, speed_label)
            elif status == "finished":
                self.emitter.queue_update_signal.emit(100, "🔄 Merging…", progress_bar, speed_label)

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            downloader = Downloader(
                output_dir=self.output_dir,
                quality=self.quality_combo.currentText() or DEFAULT_QUALITY,
                download_subtitles=self.subtitle_check.isChecked(),
                subtitle_lang=self.subtitle_lang_combo.currentText(),
                download_thumbnail=self.thumbnail_check.isChecked(),
                progress_callback=progress_hook,
                cookie_file=self.cookie_file,
            )

            # ── Fetch title BEFORE downloading so the queue shows it ────
            try:
                import yt_dlp

                probe_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
                if self.cookie_file and self.cookie_file.exists():
                    probe_opts["cookiefile"] = str(self.cookie_file)
                with yt_dlp.YoutubeDL(probe_opts) as probe:
                    info = probe.extract_info(url, download=False)
                    video_title = (info or {}).get("title", "")
                    if video_title:
                        self.emitter.queue_title_signal.emit(video_title[:50], url_label)
            except Exception:
                pass  # title stays as placeholder, download continues
            # ────────────────────────────────────────────────────────────

            result = downloader.download(url)
            if result.get("status") == "success":
                title = result.get("title", url)
                self.emitter.queue_title_signal.emit(title[:50], url_label)
                self.emitter.queue_update_signal.emit(100, "✅ Klaar!", progress_bar, speed_label)
                self.emitter.log_signal.emit(f"✅ Downloaded: {title}")
                # Subtitles handling
                if self.subtitle_check.isChecked():
                    lang = self.subtitle_lang_combo.currentText()
                    subtitle_paths = result.get("subtitle_paths")

                    if subtitle_paths and any(subtitle_paths.values()):
                        # Downloader (yt-dlp or transcript API) succeeded
                        srt_path = list(subtitle_paths.values())[0]
                        self.emitter.log_signal.emit(f"🗒 Subtitles: {srt_path.name}")
                    else:
                        # Fallback to local Whisper AI
                        self.emitter.log_signal.emit(
                            f"Downloading {lang} subtitles via local Whisper AI fallback…"
                        )
                        srt = self.subtitle_manager._try_whisper_transcription(url, title, lang)
                        if srt:
                            self.emitter.log_signal.emit(f"🗒 Subtitles (Whisper): {srt.name}")
                        else:
                            self.emitter.log_signal.emit(f"⚠ Could not get {lang} subtitles")
            else:
                msg = result.get("message", "Unknown error")
                self.emitter.queue_update_signal.emit(0, "❌ Mislukt", progress_bar, speed_label)
                self.emitter.log_signal.emit(f"❌ Download failed: {msg}")
        except Exception as exc:
            self.emitter.queue_update_signal.emit(0, "❌ Fout", progress_bar, speed_label)
            self.emitter.log_signal.emit(f"❌ Error: {exc}")
            logger.error(f"Download thread error: {exc}")

    def browse_output_folder(self) -> None:
        """Open a folder-chooser dialog and update the output directory."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose output folder",
            str(self.output_dir),
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self.output_dir = Path(folder)
            self.settings.setValue("output_dir", folder)
            self.output_path_edit.setText(folder)
            self.subtitle_manager = SubtitleManager(
                output_dir=self.output_dir, cookie_file=self.cookie_file
            )
            self.subtitle_manager.set_status_callback(self.update_subtitle_status)
            self.log(f"📁 Output folder: {folder}")

    def browse_cookie_file(self) -> None:
        """Open a file picker to select a Netscape cookies.txt file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select cookies.txt file",
            str(Path.home()),
            "Cookies file (*.txt);;All files (*)",
        )
        if path:
            self.cookie_file = Path(path)
            self.settings.setValue("cookie_file", path)
            self.subtitle_manager.cookie_file = self.cookie_file
            self.cookie_path_edit.setText(path)
            self.cookie_path_edit.setStyleSheet(
                self.cookie_path_edit.styleSheet()
                .replace("rgba(247, 248, 250, 140)", COLORS["accent"])
                .replace("italic", "normal")
            )
            self.log(f"🍪 Cookies loaded: {path}")

    def clear_cookie_file(self) -> None:
        """Remove the cookies.txt file selection."""
        self.cookie_file = None
        self.settings.remove("cookie_file")
        self.subtitle_manager.cookie_file = None
        self.cookie_path_edit.setText("Not set – browser cookies or no cookies")
        self.cookie_path_edit.setStyleSheet(
            self.cookie_path_edit.styleSheet()
            .replace(COLORS["accent"], "rgba(247, 248, 250, 140)")
            .replace("normal", "italic")
        )
        self.log("🍪 Cookies.txt cleared")

    def log(self, message: str) -> None:
        """Add message to log console."""
        import time

        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_text.append(f"[{timestamp}] {message}")

    def _on_queue_update(
        self, bar_val: int, speed_text: str, bar: QProgressBar, label: QLabel
    ) -> None:
        """Update a queue item's progress bar and speed label (main thread)."""
        bar.setValue(bar_val)
        label.setText(speed_text)

    def _on_queue_title(self, title: str, label: QLabel) -> None:
        """Update a queue item's title label (main thread)."""
        label.setText(title)

    def on_progress(self, data: dict) -> None:
        """Handle download progress updates."""
        if data.get("status") == "downloading":
            total_size = data.get("total_bytes", 0) or data.get("total_bytes_estimate", 0)
            downloaded = data.get("downloaded_bytes", 0)

            if total_size > 0:
                percentage = (downloaded / total_size) * 100
                speed = data.get("speed", 0)
                if speed:
                    speed_mb = speed / (1024 * 1024)
                    eta = (total_size - downloaded) / speed if speed > 0 else 0
                    eta_str = f"{int(eta)}s"
                else:
                    speed_mb = 0
                    eta_str = "N/A"
            else:
                percentage = 0
                speed_mb = 0
                eta_str = "N/A"

            self.emitter.status_signal.emit(
                f"Downloading ({int(percentage)}%) - {speed_mb:.1f} MB/s - ETA: {eta_str}",
                data.get("filename", "N/A"),
            )

    def update_status_ui(self, status: str, filename: str) -> None:
        """Update status UI elements."""
        self.log(f"Status: {status} - {filename}")

    def update_subtitle_status(self, status: str) -> None:
        """Update subtitle status label."""
        if hasattr(self, "subtitle_status_label"):
            self.subtitle_status_label.setText(f"Ondertitels: {status}")

    def start_download(self, url: str) -> None:
        """Start a download (used by CLI --url argument).

        Delegates to add_to_queue so the queue widget is also updated.
        """
        if validate_youtube_url(url):
            self.add_to_queue(url)
            self.log(f"CLI download queued: {url}")
        else:
            self.log(f"Invalid URL passed via CLI: {url}")

    def mainloop(self) -> None:
        """Start the main event loop (compatibility with Tkinter interface)."""
        self.show()
        sys.exit(self.app.exec())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NeuralExtractorV2()
    window.show()
    sys.exit(app.exec())
