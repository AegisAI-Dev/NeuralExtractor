"""Main GUI window for Neural Extractor."""

import math
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

import tkinter as tk
from PIL import Image, ImageTk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# Import auto_updater from parent directory (backward compatibility)
try:
    from auto_updater import create_updater_with_callback
except ImportError:
    # If auto_updater is not available, create a dummy
    def create_updater_with_callback(*args, **kwargs):
        class DummyUpdater:
            def run_auto_update(self, *args, **kwargs):
                return {"status": "skipped", "message": "Auto-updater not available"}
            def check_for_updates(self):
                return []
        return DummyUpdater()

from neural_extractor.config import (
    ACCENT_COLOR,
    ANIMATION_INTERVAL_MS,
    BG_COLOR,
    BUTTON_COLOR,
    BUTTON_FG,
    DEFAULT_OUTPUT,
    DEFAULT_QUALITY,
    DEFAULT_SUBTITLE_LANG,
    FG_COLOR,
    ICON_ICO,
    ICON_PNG,
    INPUT_BG_COLOR,
    PROGRESS_COLOR,
    QUALITY_OPTIONS,
    SUBTITLE_LANGUAGES,
    VERSION,
    WINDOW_GEOMETRY,
    WINDOW_MIN_SIZE,
    WINDOW_TITLE,
)
from neural_extractor.core.downloader import Downloader
from neural_extractor.logger import logger
from neural_extractor.thumbnail import download_thumbnail
from neural_extractor.validator import extract_video_id, validate_youtube_url


class NeuralExtractor(tk.Tk):
    """Main application window for Neural Extractor."""
    
    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()
        
        # Set window icon for cross-platform compatibility
        self._setup_icon()
        
        # App configuration
        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_GEOMETRY)
        self.minsize(*WINDOW_MIN_SIZE)
        self.configure(bg=BG_COLOR)
        
        # Animation variables
        self.animation_running: bool = True
        self.animation_frame: int = 0
        self.pulse_phase: int = 0
        
        # Download state
        self.download_thread: Optional[threading.Thread] = None
        self.stop_download: bool = False
        self.downloader: Optional[Downloader] = None
        
        # Apply theme
        self.apply_theme()
        
        # Create the UI
        self.create_widgets()
        
        # Start animations
        self.animate()
        
        # Initialize auto-updater
        self.updater = create_updater_with_callback(
            task_in_progress_callback=self.is_download_in_progress
        )
        
        # Run auto-update on startup (in background)
        self.run_auto_update_on_startup()
    
    def _setup_icon(self) -> None:
        """Set up the window icon for title bar, taskbar and dock.

        - Windows  : .ico via iconbitmap + SetCurrentProcessExplicitAppUserModelID
                     (the ctypes call is required for the taskbar to show the
                      custom icon instead of the generic Python launcher icon)
        - macOS / Linux: 512 × 512 .png via iconphoto(True, …)
        """
        try:
            if sys.platform.startswith("win"):
                # Register a unique AppUserModelID so Windows Taskbar groups
                # this window under our custom icon, not python.exe
                try:
                    import ctypes
                    app_id = "Neuralshield.NeuralExtractor.v2"
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
                except Exception:
                    pass  # Non-fatal

                # Apply the .ico to the title bar (and bundled .exe icon)
                if ICON_ICO.exists():
                    self.iconbitmap(default=str(ICON_ICO))
            else:
                # Linux / macOS: use the high-res PNG via iconphoto
                if ICON_PNG.exists():
                    img = Image.open(ICON_PNG)
                    self.icon_imgtk = ImageTk.PhotoImage(img)
                    self.iconphoto(True, self.icon_imgtk)
        except Exception as e:
            logger.warning(f"Could not set icon: {e}")
    
    def is_download_in_progress(self) -> bool:
        """Check if a download is currently in progress."""
        return (
            self.download_thread is not None
            and self.download_thread.is_alive()
        )
    
    def run_auto_update_on_startup(self) -> None:
        """Run auto-update on startup in a separate thread."""
        def update_thread() -> None:
            try:
                self.log("Checking for updates...")
                result = self.updater.run_auto_update(update_file=True)
                
                if result.get("status") == "completed":
                    self.log(f"✓ Updated {result.get('packages_updated', 0)} packages")
                elif result.get("status") == "up_to_date":
                    self.log("✓ All packages are up to date")
                elif result.get("status") == "skipped":
                    self.log("Update skipped: task in progress")
                elif result.get("status") == "error":
                    self.log(f"Update error: {result.get('message', 'Unknown error')}")
            except Exception as e:
                self.log(f"Update check failed: {str(e)}")
                logger.exception("Update check failed")
        
        # Start update thread
        update_thread_obj = threading.Thread(target=update_thread)
        update_thread_obj.daemon = True
        update_thread_obj.start()
    
    def check_for_updates_manual(self) -> None:
        """Manually check for updates and show results."""
        try:
            self.log("Checking for updates...")
            outdated = self.updater.check_for_updates()
            
            if not outdated:
                messagebox.showinfo("Updates", "All packages are up to date!")
                self.log("All packages are up to date")
            else:
                # Show outdated packages
                packages_info = "\n".join(
                    [f"{name}: {current} → {latest}" for name, current, latest in outdated]
                )
                
                response = messagebox.askyesno(
                    "Updates Available",
                    f"Found {len(outdated)} outdated packages:\n\n{packages_info}\n\n"
                    "Would you like to update them now?",
                )
                
                if response:
                    self.log("Starting manual update...")
                    result = self.updater.run_auto_update(update_file=True)
                    
                    if result.get("status") == "completed":
                        messagebox.showinfo(
                            "Update Complete",
                            f"Successfully updated {result.get('packages_updated', 0)} packages",
                        )
                        self.log(f"✓ Updated {result.get('packages_updated', 0)} packages")
                    elif result.get("status") == "error":
                        messagebox.showerror(
                            "Update Error",
                            f"Error during update: {result.get('message', 'Unknown error')}",
                        )
                        self.log(f"✗ Update error: {result.get('message')}")
                else:
                    self.log("Update cancelled by user")
                    
        except Exception as e:
            error_msg = f"Failed to check for updates: {str(e)}"
            self.log(error_msg)
            logger.exception("Failed to check for updates")
            messagebox.showerror("Error", error_msg)
    
    def apply_theme(self) -> None:
        """Apply the application theme."""
        # Configure ttk styles
        style = ttk.Style()
        style.configure("TFrame", background=BG_COLOR)
        style.configure("TLabel", background=BG_COLOR, foreground=FG_COLOR)
        style.configure("TButton", background=BUTTON_COLOR, foreground=BUTTON_FG)
        style.configure(
            "TProgressbar",
            background=PROGRESS_COLOR,
            troughcolor=BG_COLOR,
            bordercolor=ACCENT_COLOR,
            lightcolor=PROGRESS_COLOR,
            darkcolor=PROGRESS_COLOR,
        )
    
    def create_widgets(self) -> None:
        """Create all UI widgets."""
        # Main frame
        self.main_frame = tk.Frame(self, bg=BG_COLOR)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Title banner
        self.title_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        self.title_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Animated title
        self.title_label = tk.Label(
            self.title_frame,
            text=WINDOW_TITLE,
            bg=BG_COLOR,
            fg=PROGRESS_COLOR,
            font=("Arial", 24, "bold"),
            pady=10,
        )
        self.title_label.pack(fill=tk.X, pady=5)
        
        # Animated subtitle
        self.subtitle_label = tk.Label(
            self.title_frame,
            text="Advanced Media Extraction System",
            bg=BG_COLOR,
            fg=ACCENT_COLOR,
            font=("Arial", 12),
            pady=5,
        )
        self.subtitle_label.pack(fill=tk.X)
        
        # Input section
        input_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        input_frame.pack(fill=tk.X, pady=15)
        
        # URL entry
        url_label = tk.Label(
            input_frame,
            text="YouTube URL:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12, "bold"),
        )
        url_label.pack(anchor="w", pady=(5, 0))
        
        self.url_entry = tk.Entry(
            input_frame,
            bg=INPUT_BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12),
            insertbackground=FG_COLOR,
            borderwidth=1,
            relief=tk.SOLID,
        )
        self.url_entry.pack(fill=tk.X, padx=5, pady=5)
        
        # Batch URLs section
        batch_frame = tk.Frame(input_frame, bg=BG_COLOR)
        batch_frame.pack(fill=tk.X, pady=5)
        batch_label = tk.Label(
            batch_frame,
            text="Batch URLs (one per line):",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12, "bold"),
        )
        batch_label.pack(anchor="w", pady=(5, 0))
        self.batch_text = scrolledtext.ScrolledText(
            batch_frame,
            bg=INPUT_BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12),
            height=3,
            insertbackground=FG_COLOR,
            selectbackground=ACCENT_COLOR,
            selectforeground=FG_COLOR,
            borderwidth=1,
            relief=tk.SOLID,
        )
        self.batch_text.pack(fill=tk.X, padx=5, pady=5)
        
        # Output folder selection
        output_frame = tk.Frame(input_frame, bg=BG_COLOR)
        output_frame.pack(fill=tk.X, pady=5)
        output_label = tk.Label(
            output_frame,
            text="Output Folder:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12, "bold"),
        )
        output_label.pack(anchor="w", pady=(5, 0))
        self.output_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        output_entry = tk.Entry(
            output_frame,
            textvariable=self.output_var,
            bg=INPUT_BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12),
            insertbackground=FG_COLOR,
            borderwidth=1,
            relief=tk.SOLID,
        )
        output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        browse_button = tk.Button(
            output_frame,
            text="Browse",
            bg=BUTTON_COLOR,
            fg=BUTTON_FG,
            font=("Arial", 12),
            command=self.browse_output_folder,
        )
        browse_button.pack(side=tk.RIGHT, padx=5, pady=5)
        
        # Quality selection
        quality_frame = tk.Frame(input_frame, bg=BG_COLOR)
        quality_frame.pack(fill=tk.X, pady=5)
        quality_label = tk.Label(
            quality_frame,
            text="Quality Selection:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12, "bold"),
        )
        quality_label.pack(anchor="w", pady=(5, 0))
        self.quality_var = tk.StringVar()
        self.quality_combo = ttk.Combobox(
            quality_frame,
            textvariable=self.quality_var,
            values=QUALITY_OPTIONS,
            state="readonly",
            width=25,
            font=("Arial", 12),
        )
        self.quality_combo.current(0)
        self.quality_combo.pack(anchor="w", padx=5, pady=5)
        
        # Thumbnail download checkbox
        self.download_thumbnail_var = tk.BooleanVar(value=False)
        self.thumbnail_checkbox = tk.Checkbutton(
            input_frame,
            text="Download thumbnail (YouTube image)",
            variable=self.download_thumbnail_var,
            bg=BG_COLOR,
            fg=FG_COLOR,
            selectcolor=ACCENT_COLOR,
            font=("Arial", 12),
            activebackground=BG_COLOR,
            activeforeground=ACCENT_COLOR,
        )
        self.thumbnail_checkbox.pack(anchor="w", padx=5, pady=(0, 10))
        
        # Subtitles download checkbox
        self.download_subtitles_var = tk.BooleanVar(value=False)
        self.subtitles_checkbox = tk.Checkbutton(
            input_frame,
            text="Download subtitles (WebVTT & SRT)",
            variable=self.download_subtitles_var,
            bg=BG_COLOR,
            fg=FG_COLOR,
            selectcolor=ACCENT_COLOR,
            font=("Arial", 12),
            activebackground=BG_COLOR,
            activeforeground=ACCENT_COLOR,
            command=self.toggle_subtitle_language,
        )
        self.subtitles_checkbox.pack(anchor="w", padx=5, pady=(0, 2))
        
        # Subtitle language dropdown
        self.subtitle_language_var = tk.StringVar(value=DEFAULT_SUBTITLE_LANG)
        self.subtitle_language_combo = ttk.Combobox(
            input_frame,
            textvariable=self.subtitle_language_var,
            values=SUBTITLE_LANGUAGES,
            state="readonly",
            width=10,
            font=("Arial", 12),
        )
        self.subtitle_language_combo.pack(anchor="w", padx=30, pady=(0, 10))
        self.subtitle_language_combo.configure(state="disabled")
        
        # Download button
        button_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        button_frame.pack(fill=tk.X, pady=20)
        self.download_button = tk.Button(
            button_frame,
            text="Download",
            bg=BUTTON_COLOR,
            fg=BUTTON_FG,
            font=("Arial", 14, "bold"),
            command=self.start_download,
        )
        self.download_button.pack(fill=tk.X, pady=10)
        
        # Check for Updates button
        self.update_button = tk.Button(
            button_frame,
            text="Check for Updates",
            bg="#4CAF50",  # Green color for updates
            fg=FG_COLOR,
            font=("Arial", 10),
            command=self.check_for_updates_manual,
            cursor="hand2",
        )
        self.update_button.pack(fill=tk.X, pady=(5, 0))
        
        # Status section
        status_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        status_frame.pack(fill=tk.X, pady=15)
        status_label = tk.Label(
            status_frame,
            text="Status:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12, "bold"),
        )
        status_label.pack(anchor="w", pady=(5, 0))
        self.status_var = tk.StringVar(value="Ready")
        self.status_value = tk.Label(
            status_frame,
            textvariable=self.status_var,
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12),
        )
        self.status_value.pack(anchor="w", pady=2)
        
        # Progress bar
        progress_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        progress_frame.pack(fill=tk.X, pady=15)
        self.progress = ttk.Progressbar(
            progress_frame,
            orient=tk.HORIZONTAL,
            length=100,
            mode="determinate",
        )
        self.progress.pack(fill=tk.X, pady=5)
        
        # Log section
        log_frame = tk.Frame(self.main_frame, bg=BG_COLOR)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=15)
        log_label = tk.Label(
            log_frame,
            text="Log:",
            bg=BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 12, "bold"),
        )
        log_label.pack(anchor="w", pady=(5, 0))
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            bg=INPUT_BG_COLOR,
            fg=FG_COLOR,
            font=("Arial", 10),
            wrap=tk.WORD,
            height=8,
            insertbackground=FG_COLOR,
            selectbackground=ACCENT_COLOR,
            selectforeground=FG_COLOR,
            borderwidth=1,
            relief=tk.SOLID,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Add initial log messages
        self.log_text.insert(tk.END, f"Neural Extractor {VERSION}\n")
        self.log_text.insert(tk.END, "Ready to download videos.\n")
        self.log_text.config(state="disabled")
    
    def animate(self) -> None:
        """Handle all animations."""
        if not self.animation_running:
            return
        
        # Update animation frame
        self.animation_frame = (self.animation_frame + 1) % 360
        
        # Title glow effect
        glow_intensity = abs(math.sin(math.radians(self.animation_frame * 2))) * 0.5 + 0.5
        glow_color = self.adjust_color(PROGRESS_COLOR, glow_intensity)
        self.title_label.configure(fg=glow_color)
        
        # Progress bar pulse
        self.pulse_phase = (self.pulse_phase + 1) % 360
        pulse_intensity = abs(math.sin(math.radians(self.pulse_phase))) * 0.3 + 0.7
        pulse_color = self.adjust_color(PROGRESS_COLOR, pulse_intensity)
        self.progress.configure(style="TProgressbar")
        
        # Schedule next animation frame
        self.after(ANIMATION_INTERVAL_MS, self.animate)
    
    def adjust_color(self, hex_color: str, intensity: float) -> str:
        """Adjust color intensity for glow effects."""
        # Convert hex to RGB
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        
        # Adjust intensity
        r = int(r * intensity)
        g = int(g * intensity)
        b = int(b * intensity)
        
        # Convert back to hex
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def pulse_button(self, button: tk.Button) -> None:
        """Pulse animation for buttons."""
        original_color = button.cget("bg")
        
        def pulse(phase: int) -> None:
            if phase < 360:
                intensity = abs(math.sin(math.radians(phase))) * 0.3 + 0.7
                new_color = self.adjust_color(original_color, intensity)
                button.configure(bg=new_color)
                button.after(16, lambda: pulse(phase + 10))
            else:
                button.configure(bg=original_color)
        
        pulse(0)
    
    def log(self, message: str) -> None:
        """Add a message to the log with timestamp."""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")
        logger.info(message)
    
    def start_download(self) -> None:
        """Start the download process."""
        # Pulse the download button
        self.pulse_button(self.download_button)
        
        # Collect URLs
        urls: list[str] = []
        single_url = self.url_entry.get().strip()
        if single_url:
            self.log(f"Processing single URL: {single_url}")
            urls.append(single_url)
        batch_text = self.batch_text.get("1.0", tk.END).strip()
        if batch_text:
            self.log("Processing batch URLs")
            urls.extend([url.strip() for url in batch_text.split("\n") if url.strip()])
        
        if not urls:
            messagebox.showerror("Error", "Please enter at least one YouTube URL")
            return
        
        # Validate URLs
        valid_urls: list[str] = []
        for url in urls:
            if validate_youtube_url(url):
                self.log(f"Valid YouTube URL: {url}")
                valid_urls.append(url)
            else:
                self.log(f"Invalid YouTube URL: {url}")
        
        if not valid_urls:
            self.log("No valid URLs to process")
            messagebox.showerror("Error", "No valid URLs to process")
            return
        
        self.log(f"Starting download of {len(valid_urls)} video(s)/playlist(s)/mix(es)")
        
        # Check if download is already in progress
        if self.download_thread and self.download_thread.is_alive():
            self.stop_download = True
            if self.downloader:
                self.downloader.cancel()
            self.download_button.configure(text="Download", bg=BUTTON_COLOR)
            self.log("💀 Extraction aborted by user")
            return
        
        # Update UI for downloading state
        self.status_var.set("🔄 INITIALIZING EXTRACTION...")
        self.progress["value"] = 0
        self.download_button.configure(text="❌ ABORT EXTRACTION", bg=BUTTON_COLOR)
        
        # Clear stop flag
        self.stop_download = False
        
        # Start download thread
        self.download_thread = threading.Thread(
            target=self.download_video, args=(valid_urls,)
        )
        self.download_thread.daemon = True
        self.download_thread.start()
    
    def download_video(self, urls: list[str]) -> None:
        """Download videos in a separate thread."""
        self.log("Starting download_video thread...")
        
        output_dir = Path(self.output_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for url in urls:
            if self.stop_download:
                self.log("Download stopped by user.")
                break
            
            try:
                self.log(f"Fetching metadata: {url}")
                
                # Create downloader instance
                self.downloader = Downloader(
                    output_dir=output_dir,
                    quality=self.quality_var.get() or DEFAULT_QUALITY,
                    download_subtitles=self.download_subtitles_var.get(),
                    subtitle_lang=self.subtitle_language_var.get(),
                    download_thumbnail=self.download_thumbnail_var.get(),
                    progress_callback=self.on_progress,
                )
                
                # Download
                result = self.downloader.download(url)
                
                if result.get("status") == "success":
                    self.log(f"Successfully downloaded: {url}")
                    
                    # Download thumbnail if requested
                    if self.download_thumbnail_var.get():
                        video_id = result.get("video_id") or extract_video_id(url)
                        if video_id:
                            title = result.get("title")
                            download_thumbnail(video_id, output_dir, title)
                    
                    # Log subtitle download results
                    subtitle_paths = result.get("subtitle_paths")
                    if subtitle_paths:
                        for fmt, path in subtitle_paths.items():
                            if path:
                                self.log(f"Downloaded {fmt.upper()} subtitles: {path}")
                else:
                    self.log(f"Download failed: {result.get('message', 'Unknown error')}")
                    self.update_status_ui("Failed", result.get("message", "Unknown error"))
                    
            except Exception as e:
                self.update_status_ui("Failed", "Error occurred")
                self.log(f"Error: {str(e)}")
                logger.exception("Download error")
                messagebox.showerror("Error", f"An unexpected error occurred: {str(e)}")
            finally:
                # Reset download button
                self.download_button.configure(text="Download", bg=BUTTON_COLOR)
        
        self.log("Exiting download_video thread.")
    
    def on_progress(self, d: dict[str, Any]) -> None:
        """Callback for download progress."""
        if self.stop_download:
            raise Exception("Download cancelled by user")
        
        if d.get("status") == "downloading":
            # Calculate progress percentage
            total_size = d.get("total_bytes", 0) or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            
            if total_size > 0:
                percentage = (downloaded / total_size) * 100
                speed = d.get("speed", 0)
                if speed:
                    speed_mb = speed / (1024 * 1024)
                    eta = (total_size - downloaded) / speed if speed > 0 else 0
                    eta_str = f"{int(eta)}s"
                else:
                    speed_mb = 0
                    eta_str = "N/A"
                size_mb = downloaded / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
            else:
                percentage = 0
                speed_mb = 0
                eta_str = "N/A"
                size_mb = downloaded / (1024 * 1024) if downloaded else 0
                total_mb = 0
            
            # Update progress bar
            self.progress["value"] = percentage
            
            # Update status with speed and ETA
            if "playlist_index" in d:
                playlist_index = d["playlist_index"]
                playlist_count = d.get("playlist_count", "?")
                status_text = (
                    f"Downloading video {playlist_index}/{playlist_count} "
                    f"({int(percentage)}%) - {speed_mb:.1f} MB/s - ETA: {eta_str}"
                )
            else:
                status_text = (
                    f"Downloading ({int(percentage)}%) - {speed_mb:.1f} MB/s - ETA: {eta_str}"
                )
            
            self.update_status_ui(
                status_text,
                f"{d.get('filename', 'N/A')} - {size_mb:.1f}MB of {total_mb:.1f}MB",
            )
        
        elif d.get("status") == "finished":
            self.log(f"Download completed: {d.get('filename', 'N/A')}")
            self.on_complete(d)
    
    def on_complete(self, info: dict[str, Any]) -> None:
        """Callback when download is complete."""
        filename = info.get("filename", "Unknown")
        self.update_status_ui(
            "✅ EXTRACTION COMPLETE",
            f"Downloaded {Path(filename).name if filename else 'Unknown'}",
        )
        self.progress["value"] = 100
        self.log(f"🚀 Neural extraction completed: {filename}")
        self.download_button.configure(text="Download", bg=BUTTON_COLOR)
    
    def update_status_ui(self, status: str, filename: str) -> None:
        """Update status UI elements safely from any thread."""
        def update() -> None:
            self.status_var.set(status)
            self.log(f"Status: {status} - {filename}")
        
        # Schedule the update on the main thread
        self.after(0, update)
    
    def browse_output_folder(self) -> None:
        """Open a dialog to select the output folder."""
        folder = filedialog.askdirectory()
        if folder:
            self.output_var.set(folder)
    
    def toggle_subtitle_language(self) -> None:
        """Toggle subtitle language dropdown state."""
        if self.download_subtitles_var.get():
            self.subtitle_language_combo.configure(state="readonly")
        else:
            self.subtitle_language_combo.configure(state="disabled")


if __name__ == "__main__":
    app = NeuralExtractor()
    app.mainloop()

