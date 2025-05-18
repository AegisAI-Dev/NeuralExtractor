import os
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import re
from urllib.parse import urlparse, parse_qs
import traceback
import time
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
        # Main frame
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Title banner
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill=tk.X, pady=(0, 15))
        
        title_label = ttk.Label(
            title_frame, 
            text="0xRootNull - Neural Extraction Terminal",
            style="Title.TLabel",
            anchor="center"
        )
        title_label.pack(fill=tk.X, pady=10)
        
        # Input section
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=10)
        
        url_label = ttk.Label(input_frame, text="YouTube URL:")
        url_label.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        
        self.url_entry = ttk.Entry(input_frame, width=60)
        self.url_entry.grid(row=0, column=1, sticky="ew", pady=5)
        
        quality_label = ttk.Label(input_frame, text="Quality:")
        quality_label.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        
        self.quality_var = tk.StringVar()
        self.quality_combo = ttk.Combobox(
            input_frame, 
            textvariable=self.quality_var,
            values=["Highest Resolution", "720p", "480p", "360p", "240p", "144p", "Audio Only (MP3)"],
            state="readonly",
            width=20
        )
        self.quality_combo.current(0)
        self.quality_combo.grid(row=1, column=1, sticky="w", pady=5)
        
        # Make the entry column expandable
        input_frame.columnconfigure(1, weight=1)
        
        # Download button with glow effect
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        self.download_button = tk.Button(
            button_frame,
            text="DOWNLOAD",
            bg=HackerTheme.DARKER_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL, "bold"),
            borderwidth=2,
            relief=tk.RAISED,
            padx=20,
            pady=5,
            command=self.start_download
        )
        self.download_button.pack(pady=10)
        HackerTheme.create_glow_effect(self.download_button)
        
        # Status section
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=10)
        
        status_label = ttk.Label(status_frame, text="Status:")
        status_label.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        
        self.status_var = tk.StringVar(value="Ready")
        status_value = ttk.Label(status_frame, textvariable=self.status_var)
        status_value.grid(row=0, column=1, sticky="w", pady=5)
        
        filename_label = ttk.Label(status_frame, text="File Name:")
        filename_label.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        
        self.filename_var = tk.StringVar(value="No file selected")
        filename_value = ttk.Label(status_frame, textvariable=self.filename_var)
        filename_value.grid(row=1, column=1, sticky="w", pady=5)
        
        # Progress bar
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=10)
        
        self.progress = ttk.Progressbar(
            progress_frame, 
            orient=tk.HORIZONTAL,
            length=100, 
            mode='determinate'
        )
        self.progress.pack(fill=tk.X, pady=5)
        
        # Log section
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        log_label = ttk.Label(log_frame, text="Log:")
        log_label.pack(anchor="w", pady=(0, 5))
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            bg=HackerTheme.LIGHTER_BLACK,
            fg=HackerTheme.NEON_GREEN,
            font=(HackerTheme.FONT_FAMILY, HackerTheme.FONT_SIZE_NORMAL),
            wrap=tk.WORD,
            height=10
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
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
            self.download_button.configure(text="DOWNLOAD", bg=HackerTheme.DARKER_BLACK)
            self.log("Download cancelled")
            return
        
        # Update UI for downloading state
        self.status_var.set("Initializing...")
        self.filename_var.set("Fetching...")
        self.progress['value'] = 0
        self.download_button.configure(text="CANCEL", bg="#500000")  # Red for cancel
        
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
            
            if quality == "Audio Only (MP3)":
                self.log("Selected audio only (MP3)")
                stream = yt.streams.filter(only_audio=True).first()
                output_file = stream.download(output_path)
                
                # Convert to MP3
                base, _ = os.path.splitext(output_file)
                mp3_file = base + '.mp3'
                os.rename(output_file, mp3_file)
                final_file = mp3_file
                
            else:
                if quality == "Highest Resolution":
                    self.log("Selected highest resolution")
                    stream = yt.streams.filter(progressive=True).get_highest_resolution()
                else:
                    # Extract numeric resolution
                    resolution = quality.replace("p", "")
                    self.log(f"Selected {quality} resolution")
                    stream = yt.streams.filter(progressive=True, resolution=quality).first()
                    
                    # If not found, get the closest resolution
                    if not stream:
                        self.log(f"Resolution {quality} not available, selecting best match")
                        stream = yt.streams.filter(progressive=True).get_highest_resolution()
                
                # Download the video
                final_file = stream.download(output_path)
            
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
            self.download_button.configure(text="DOWNLOAD", bg=HackerTheme.DARKER_BLACK)
    
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
        self.update_status_ui("Completed", os.path.basename(file_path))
        self.progress['value'] = 100
        self.log(f"Download completed: {file_path}")
        self.download_button.configure(text="DOWNLOAD", bg=HackerTheme.DARKER_BLACK)
    
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
