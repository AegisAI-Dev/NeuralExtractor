import os
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import re
from urllib.parse import urlparse, parse_qs
import traceback
import time
import random
from pytube import YouTube
from pytube.exceptions import PytubeError
from theme import HackerTheme

class YouTubeDownloaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # App configuration
        self.title("0xRootNull - YouTube Downloader")
        self.geometry("800x600")
        self.minsize(700, 500)
        self.configure(bg=HackerTheme.BACKGROUND_BLACK)
        
        # Apply theme
        HackerTheme.configure_ttk_styles()
        
        # Create the UI
        self.create_widgets()
        
        # Variables for download state
        self.download_thread = None
        self.stop_download = False
        
    def create_widgets(self):
        # Background canvas for Matrix rain effect
        self.bg_canvas = tk.Canvas(
            self, 
            bg=HackerTheme.BACKGROUND_BLACK,
            highlightthickness=0
        )
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        
        # Start Matrix rain effect
        self.after(100, lambda: HackerTheme.create_matrix_rain_effect(
            self.bg_canvas, 800, 600
        ))
        
        # Main frame with transparent background
        main_frame = tk.Frame(self, bg=HackerTheme.BACKGROUND_BLACK)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Title banner with enhanced styling
        title_frame = tk.Frame(main_frame, bg=HackerTheme.BACKGROUND_BLACK)
        title_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Animated title with neon border
        title_border = tk.Frame(
            title_frame,
            bg=HackerTheme.NEON_GREEN,
            height=3
        )
        title_border.pack(fill=tk.X, pady=(0, 5))
        
        self.title_label = tk.Label(
            title_frame,
            text="",
            bg=HackerTheme.DARKER_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_TITLE, "bold"),
            relief=tk.RAISED,
            borderwidth=2,
            pady=10
        )
        self.title_label.pack(fill=tk.X, pady=5)
        
        # Start typing effect for title
        HackerTheme.create_typing_effect(
            self.title_label, 
            "0xRootNull - Neural Extraction Terminal", 
            delay=100
        )
        
        # Add scanning line effect to title
        HackerTheme.create_scanning_line(self.title_label)
        
        # Input section with enhanced styling
        input_frame = tk.Frame(main_frame, bg=HackerTheme.BACKGROUND_BLACK)
        input_frame.pack(fill=tk.X, pady=15)
        
        # URL input with glow border
        url_container = tk.Frame(input_frame, bg=HackerTheme.NEON_GREEN, height=2)
        url_container.pack(fill=tk.X, pady=(0, 10))
        
        url_inner = tk.Frame(url_container, bg=HackerTheme.BACKGROUND_BLACK)
        url_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        url_label = tk.Label(
            url_inner, 
            text="► YouTube URL:",
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold")
        )
        url_label.pack(anchor="w", pady=(5, 0))
        
        self.url_entry = tk.Entry(
            url_inner,
            bg=HackerTheme.LIGHTER_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL),
            insertbackground=HackerTheme.NEON_GREEN,
            borderwidth=1,
            relief=tk.SOLID
        )
        self.url_entry.pack(fill=tk.X, padx=5, pady=5)
        
        # Add pulse effect to URL entry
        HackerTheme.create_pulse_effect(self.url_entry)
        
        # Quality selection with cyber styling
        quality_container = tk.Frame(input_frame, bg=HackerTheme.ELECTRIC_BLUE, height=2)
        quality_container.pack(fill=tk.X, pady=(10, 0))
        
        quality_inner = tk.Frame(quality_container, bg=HackerTheme.BACKGROUND_BLACK)
        quality_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        quality_label = tk.Label(
            quality_inner,
            text="► Quality Selection:",
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.ELECTRIC_BLUE,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold")
        )
        quality_label.pack(anchor="w", pady=(5, 0))
        
        self.quality_var = tk.StringVar()
        self.quality_combo = ttk.Combobox(
            quality_inner,
            textvariable=self.quality_var,
            values=["🔥 Highest Resolution", "📺 720p HD", "📱 480p", "💾 360p", "⚡ 240p", "📻 144p", "🎵 Audio Only (MP3)"],
            state="readonly",
            width=25,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL)
        )
        self.quality_combo.current(0)
        self.quality_combo.pack(anchor="w", padx=5, pady=5)
        
        # Enhanced download button with cyber effects
        button_frame = tk.Frame(main_frame, bg=HackerTheme.BACKGROUND_BLACK)
        button_frame.pack(fill=tk.X, pady=20)
        
        # Create button with multiple glow layers
        button_glow_outer = tk.Frame(button_frame, bg=HackerTheme.NEON_GREEN, height=60)
        button_glow_outer.pack(pady=10)
        
        button_glow_inner = tk.Frame(button_glow_outer, bg=HackerTheme.BACKGROUND_BLACK)
        button_glow_inner.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        
        self.download_button = tk.Button(
            button_glow_inner,
            text="▶ INITIATE NEURAL EXTRACTION ◀",
            bg=HackerTheme.DARKER_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, 14, "bold"),
            borderwidth=0,
            relief=tk.FLAT,
            padx=30,
            pady=15,
            command=self.start_download,
            cursor="hand2"
        )
        self.download_button.pack(fill=tk.BOTH, expand=True)
        
        # Add multiple visual effects
        HackerTheme.create_glow_effect(self.download_button)
        HackerTheme.create_pulse_effect(button_glow_outer)
        
        # Enhanced status section with cyber styling
        status_frame = tk.Frame(main_frame, bg=HackerTheme.BACKGROUND_BLACK)
        status_frame.pack(fill=tk.X, pady=15)
        
        # Status display with neon border
        status_container = tk.Frame(status_frame, bg=HackerTheme.CYBER_PURPLE, height=2)
        status_container.pack(fill=tk.X, pady=(0, 10))
        
        status_inner = tk.Frame(status_container, bg=HackerTheme.BACKGROUND_BLACK)
        status_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        status_header = tk.Label(
            status_inner,
            text="● SYSTEM STATUS ●",
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.CYBER_PURPLE,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold")
        )
        status_header.pack(pady=(5, 0))
        
        # Status and filename in grid
        info_frame = tk.Frame(status_inner, bg=HackerTheme.BACKGROUND_BLACK)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        status_label = tk.Label(
            info_frame, 
            text="► Status:",
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold")
        )
        status_label.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=2)
        
        self.status_var = tk.StringVar(value="⚡ READY FOR EXTRACTION")
        self.status_value = tk.Label(
            info_frame, 
            textvariable=self.status_var,
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.NEON_CYAN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL)
        )
        self.status_value.grid(row=0, column=1, sticky="w", pady=2)
        
        filename_label = tk.Label(
            info_frame,
            text="► Target:",
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold")
        )
        filename_label.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=2)
        
        self.filename_var = tk.StringVar(value="🎯 No target selected")
        self.filename_value = tk.Label(
            info_frame,
            textvariable=self.filename_var,
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.WARNING_YELLOW,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL)
        )
        self.filename_value.grid(row=1, column=1, sticky="w", pady=2)
        
        # Enhanced progress bar with custom styling
        progress_frame = tk.Frame(main_frame, bg=HackerTheme.BACKGROUND_BLACK)
        progress_frame.pack(fill=tk.X, pady=15)
        
        progress_label = tk.Label(
            progress_frame,
            text="▼ EXTRACTION PROGRESS ▼",
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.ELECTRIC_BLUE,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold")
        )
        progress_label.pack(pady=(0, 5))
        
        # Progress bar container with glow effect
        progress_container = tk.Frame(progress_frame, bg=HackerTheme.NEON_GREEN, height=25)
        progress_container.pack(fill=tk.X, pady=5)
        
        progress_inner = tk.Frame(progress_container, bg=HackerTheme.LIGHTER_BLACK)
        progress_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        self.progress = ttk.Progressbar(
            progress_inner,
            orient=tk.HORIZONTAL,
            length=100,
            mode='determinate'
        )
        self.progress.pack(fill=tk.X, pady=3)
        
        # Enhanced log section with terminal styling
        log_frame = tk.Frame(main_frame, bg=HackerTheme.BACKGROUND_BLACK)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=15)
        
        # Log header with animated effect
        log_header = tk.Label(
            log_frame,
            text="◆ NEURAL ACTIVITY LOG ◆",
            bg=HackerTheme.BACKGROUND_BLACK,
            fg=HackerTheme.MATRIX_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold")
        )
        log_header.pack(anchor="w", pady=(0, 5))
        
        # Terminal-style log container
        log_container = tk.Frame(log_frame, bg=HackerTheme.MATRIX_GREEN, height=2)
        log_container.pack(fill=tk.BOTH, expand=True)
        
        log_inner = tk.Frame(log_container, bg=HackerTheme.DARKER_BLACK)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        self.log_text = scrolledtext.ScrolledText(
            log_inner,
            bg=HackerTheme.DARKER_BLACK,
            fg=HackerTheme.MATRIX_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_SMALL),
            wrap=tk.WORD,
            height=8,
            insertbackground=HackerTheme.MATRIX_GREEN,
            selectbackground=HackerTheme.LIGHTER_BLACK,
            selectforeground=HackerTheme.NEON_GREEN,
            borderwidth=0,
            highlightthickness=0
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Add some initial boot-up messages
        self.log_text.insert(tk.END, ">>> Neural Extraction Terminal v2.1 ONLINE\n")
        self.log_text.insert(tk.END, ">>> Quantum encryption layers: ACTIVE\n")
        self.log_text.insert(tk.END, ">>> Awaiting extraction coordinates...\n")
        self.log_text.config(state='disabled')
        
        # Add glow effect to log header
        HackerTheme.create_glow_effect(log_header)
        
    def log(self, message):
        """Add a message to the log with timestamp."""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state='disabled')
        
    def validate_youtube_url(self, url):
        """Validate if the URL is a valid YouTube URL."""
        # Basic pattern for YouTube URLs
        youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$'
        match = re.match(youtube_regex, url)
        return match is not None
    
    def extract_video_id(self, url):
        """Extract video ID from YouTube URL."""
        if 'youtu.be' in url:
            return urlparse(url).path.strip('/')
        else:
            parsed_url = urlparse(url)
            return parse_qs(parsed_url.query).get('v', [None])[0]
    
    def start_download(self):
        """Start the download process in a separate thread."""
        url = self.url_entry.get().strip()
        
        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
            return
        
        if not self.validate_youtube_url(url):
            messagebox.showerror("Error", "Invalid YouTube URL")
            return
        
        # Check if download is already in progress
        if self.download_thread and self.download_thread.is_alive():
            self.stop_download = True
            self.download_button.configure(text="▶ INITIATE NEURAL EXTRACTION ◀", bg=HackerTheme.DARKER_BLACK)
            self.log("💀 Extraction aborted by user")
            return
        
        # Update UI for downloading state
        self.status_var.set("🔄 INITIALIZING EXTRACTION...")
        self.filename_var.set("🔍 Scanning target...")
        self.progress['value'] = 0
        self.download_button.configure(text="❌ ABORT EXTRACTION", bg="#500000")  # Red for cancel
        
        # Clear stop flag
        self.stop_download = False
        
        # Start download thread
        self.download_thread = threading.Thread(target=self.download_video, args=(url,))
        self.download_thread.daemon = True
        self.download_thread.start()
    
    def download_video(self, url):
        """Download video in a separate thread."""
        try:
            self.log(f"Fetching video metadata: {url}")
            
            # Create a YouTube object and fetch video info
            yt = YouTube(
                url,
                on_progress_callback=self.on_progress,
                on_complete_callback=self.on_complete
            )
            
            # Update UI with video title
            self.update_status_ui("Preparing download", yt.title)
            self.log(f"Title: {yt.title}")
            self.log(f"Duration: {yt.length} seconds")
            
            # Determine output path
            output_path = os.path.expanduser("~/Downloads")
            if not os.path.exists(output_path):
                output_path = os.getcwd()
            
            # Select stream based on quality
            quality = self.quality_var.get()
            
            if "Audio Only" in quality:
                self.log("🎵 Selected audio only (MP3)")
                stream = yt.streams.filter(only_audio=True).first()
                if stream:
                    output_file = stream.download(output_path)
                    
                    # Convert to MP3
                    base, _ = os.path.splitext(output_file)
                    mp3_file = base + '.mp3'
                    os.rename(output_file, mp3_file)
                    final_file = mp3_file
                else:
                    raise Exception("No audio stream available")
                
            else:
                if "Highest Resolution" in quality:
                    self.log("🔥 Selected highest resolution")
                    stream = yt.streams.filter(progressive=True).get_highest_resolution()
                else:
                    # Extract numeric resolution from emoji options
                    if "720p" in quality:
                        resolution = "720p"
                    elif "480p" in quality:
                        resolution = "480p"
                    elif "360p" in quality:
                        resolution = "360p"
                    elif "240p" in quality:
                        resolution = "240p"
                    elif "144p" in quality:
                        resolution = "144p"
                    else:
                        resolution = "720p"  # Default
                    
                    self.log(f"📺 Selected {resolution} resolution")
                    stream = yt.streams.filter(progressive=True, resolution=resolution).first()
                    
                    # If not found, get the closest resolution
                    if not stream:
                        self.log(f"Resolution {resolution} not available, selecting best match")
                        stream = yt.streams.filter(progressive=True).get_highest_resolution()
                
                # Download the video
                if stream:
                    final_file = stream.download(output_path)
                else:
                    raise Exception("No suitable video stream found")
            
            # Final message will be shown by on_complete callback
            
        except PytubeError as e:
            self.update_status_ui("Failed", "Error occurred")
            self.log(f"PyTube Error: {str(e)}")
            messagebox.showerror("Download Error", f"Error downloading video: {str(e)}")
        except Exception as e:
            self.update_status_ui("Failed", "Error occurred")
            self.log(f"Error: {str(e)}")
            self.log(traceback.format_exc())
            messagebox.showerror("Error", f"An unexpected error occurred: {str(e)}")
        finally:
            # Reset download button
            self.download_button.configure(text="▶ INITIATE NEURAL EXTRACTION ◀", bg=HackerTheme.DARKER_BLACK)
    
    def on_progress(self, stream, chunk, bytes_remaining):
        """Callback for download progress."""
        if self.stop_download:
            raise Exception("Download cancelled by user")
        
        # Calculate progress percentage
        total_size = stream.filesize
        bytes_downloaded = total_size - bytes_remaining
        percentage = (bytes_downloaded / total_size) * 100
        
        # Update progress bar
        self.progress['value'] = percentage
        
        # Update status every 5%
        if int(percentage) % 5 == 0:
            size_mb = bytes_downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            self.update_status_ui(f"Downloading ({int(percentage)}%)", 
                                  f"{stream.default_filename} - {size_mb:.1f}MB of {total_mb:.1f}MB")
    
    def on_complete(self, stream, file_path):
        """Callback when download is complete."""
        self.update_status_ui("✅ EXTRACTION COMPLETE", f"🎯 {os.path.basename(file_path)}")
        self.progress['value'] = 100
        self.log(f"🚀 Neural extraction completed: {file_path}")
        self.download_button.configure(text="▶ INITIATE NEURAL EXTRACTION ◀", bg=HackerTheme.DARKER_BLACK)
    
    def update_status_ui(self, status, filename):
        """Update status UI elements safely from any thread."""
        def update():
            self.status_var.set(status)
            self.filename_var.set(filename)
            self.log(f"Status: {status} - {filename}")
        
        # Schedule the update on the main thread
        self.after(0, update)

if __name__ == "__main__":
    app = YouTubeDownloaderApp()
    app.mainloop()
