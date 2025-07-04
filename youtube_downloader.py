import os
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import re
from urllib.parse import urlparse, parse_qs
import traceback
import time
import random
from pytube import YouTube, Playlist
from pytube.exceptions import PytubeError
from theme import HackerTheme
import yt_dlp
from PIL import Image, ImageTk
import math
import requests
import sys

class NeuralExtractor(tk.Tk):
    def __init__(self):
        super().__init__()
        
        # Set window icon for cross-platform compatibility
        try:
            if sys.platform.startswith('win'):
                # Use .ico for Windows
                ico_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", "NeuralExtractorIcon.ico"))
                self.iconbitmap(default=ico_path)
            else:
                # Use .png for Linux/Mac
                png_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", "NeuralExtractorIcon.png"))
                img = Image.open(png_path)
                self.icon_imgtk = ImageTk.PhotoImage(img)
                self.iconphoto(True, self.icon_imgtk)
        except Exception as e:
            print(f"Could not set icon: {e}")
        
        # App configuration
        self.title("Neural Extractor")
        self.geometry("800x600")
        self.minsize(700, 500)
        self.configure(bg="#1a2233")  # Navy blue background
        
        # Animation variables
        self.animation_running = True
        self.animation_frame = 0
        self.pulse_phase = 0
        
        # Apply theme
        self.apply_theme()
        
        # Create the UI
        self.create_widgets()
        
        # Start animations
        self.animate()
        
        # Variables for download state
        self.download_thread = None
        self.stop_download = False
        
    def apply_theme(self):
        # Define navy blue theme colors
        self.bg_color = "#1a2233"  # Navy blue
        self.fg_color = "#ffffff"  # White for text
        self.accent_color = "#1abc9c"  # Teal accent
        self.button_color = "#ff9900"  # Orange for buttons
        self.button_fg = "#000000"  # Black for button text
        self.progress_color = "#1abc9c"  # Teal for progress bar
        self.neon_blue = "#1abc9c"  # Use teal for animations
        
        # Configure ttk styles
        style = ttk.Style()
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabel", background=self.bg_color, foreground=self.fg_color)
        style.configure("TButton", background=self.button_color, foreground=self.button_fg)
        style.configure("TProgressbar", 
                       background=self.progress_color,
                       troughcolor=self.bg_color,
                       bordercolor=self.accent_color,
                       lightcolor=self.progress_color,
                       darkcolor=self.progress_color)
        
    def create_widgets(self):
        # Main frame with navy blue background
        self.main_frame = tk.Frame(self, bg=self.bg_color)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Title banner with professional styling and animation
        self.title_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        self.title_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Animated title
        self.title_label = tk.Label(
            self.title_frame,
            text="Neural Extractor",
            bg=self.bg_color,
            fg=self.neon_blue,
            font=("Arial", 24, "bold"),
            pady=10
        )
        self.title_label.pack(fill=tk.X, pady=5)
        
        # Animated subtitle
        self.subtitle_label = tk.Label(
            self.title_frame,
            text="Advanced Media Extraction System",
            bg=self.bg_color,
            fg=self.accent_color,
            font=("Arial", 12),
            pady=5
        )
        self.subtitle_label.pack(fill=tk.X)
        
        # Input section with professional styling
        input_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        input_frame.pack(fill=tk.X, pady=15)
        
        url_label = tk.Label(
            input_frame, 
            text="YouTube URL:",
            bg=self.bg_color,
            fg=self.fg_color,
            font=("Arial", 12, "bold")
        )
        url_label.pack(anchor="w", pady=(5, 0))
        
        self.url_entry = tk.Entry(
            input_frame,
            bg="#2c3e50",  # Darker blue for input
            fg=self.fg_color,
            font=("Arial", 12),
            insertbackground=self.fg_color,
            borderwidth=1,
            relief=tk.SOLID
        )
        self.url_entry.pack(fill=tk.X, padx=5, pady=5)
        
        # Batch URLs section
        batch_frame = tk.Frame(input_frame, bg=self.bg_color)
        batch_frame.pack(fill=tk.X, pady=5)
        batch_label = tk.Label(
            batch_frame, 
            text="Batch URLs (one per line):", 
            bg=self.bg_color, 
            fg=self.fg_color, 
            font=("Arial", 12, "bold")
        )
        batch_label.pack(anchor="w", pady=(5, 0))
        self.batch_text = scrolledtext.ScrolledText(
            batch_frame, 
            bg="#2c3e50", 
            fg=self.fg_color, 
            font=("Arial", 12), 
            height=3, 
            insertbackground=self.fg_color, 
            selectbackground=self.accent_color, 
            selectforeground=self.fg_color, 
            borderwidth=1, 
            relief=tk.SOLID
        )
        self.batch_text.pack(fill=tk.X, padx=5, pady=5)

        # Output folder selection
        output_frame = tk.Frame(input_frame, bg=self.bg_color)
        output_frame.pack(fill=tk.X, pady=5)
        output_label = tk.Label(
            output_frame, 
            text="Output Folder:", 
            bg=self.bg_color, 
            fg=self.fg_color, 
            font=("Arial", 12, "bold")
        )
        output_label.pack(anchor="w", pady=(5, 0))
        self.output_var = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        output_entry = tk.Entry(
            output_frame, 
            textvariable=self.output_var, 
            bg="#2c3e50", 
            fg=self.fg_color, 
            font=("Arial", 12), 
            insertbackground=self.fg_color, 
            borderwidth=1, 
            relief=tk.SOLID
        )
        output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        browse_button = tk.Button(
            output_frame, 
            text="Browse", 
            bg=self.button_color, 
            fg=self.button_fg, 
            font=("Arial", 12), 
            command=self.browse_output_folder
        )
        browse_button.pack(side=tk.RIGHT, padx=5, pady=5)
        
        # Quality selection
        quality_frame = tk.Frame(input_frame, bg=self.bg_color)
        quality_frame.pack(fill=tk.X, pady=5)
        quality_label = tk.Label(
            quality_frame, 
            text="Quality Selection:", 
            bg=self.bg_color, 
            fg=self.fg_color, 
            font=("Arial", 12, "bold")
        )
        quality_label.pack(anchor="w", pady=(5, 0))
        self.quality_var = tk.StringVar()
        self.quality_combo = ttk.Combobox(
            quality_frame, 
            textvariable=self.quality_var,
            values=["Highest Resolution", "720p HD", "480p", "360p", "240p", "144p", "Audio Only (MP3)"], 
            state="readonly",
            width=25,
            font=("Arial", 12)
        )
        self.quality_combo.current(0)
        self.quality_combo.pack(anchor="w", padx=5, pady=5)
        
        # Thumbnail download checkbox
        self.download_thumbnail_var = tk.BooleanVar(value=False)
        self.thumbnail_checkbox = tk.Checkbutton(
            input_frame,
            text="Download thumbnail (YouTube image)",
            variable=self.download_thumbnail_var,
            bg=self.bg_color,
            fg=self.fg_color,
            selectcolor=self.accent_color,
            font=("Arial", 12),
            activebackground=self.bg_color,
            activeforeground=self.accent_color
        )
        self.thumbnail_checkbox.pack(anchor="w", padx=5, pady=(0, 10))

        # Subtitles download checkbox
        self.download_subtitles_var = tk.BooleanVar(value=False)
        self.subtitles_checkbox = tk.Checkbutton(
            input_frame,
            text="Download subtitles (SRT)",
            variable=self.download_subtitles_var,
            bg=self.bg_color,
            fg=self.fg_color,
            selectcolor=self.accent_color,
            font=("Arial", 12),
            activebackground=self.bg_color,
            activeforeground=self.accent_color,
            command=self.toggle_subtitle_language
        )
        self.subtitles_checkbox.pack(anchor="w", padx=5, pady=(0, 2))

        # Subtitle language dropdown
        self.subtitle_language_var = tk.StringVar(value="en")
        self.subtitle_language_combo = ttk.Combobox(
            input_frame,
            textvariable=self.subtitle_language_var,
            values=["en", "nl", "de", "fr", "es", "it", "tr", "ru", "ar", "zh-Hans", "ja", "ko"],
            state="readonly",
            width=10,
            font=("Arial", 12)
        )
        self.subtitle_language_combo.pack(anchor="w", padx=30, pady=(0, 10))
        self.subtitle_language_combo.configure(state="disabled")
        
        # Download button
        button_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        button_frame.pack(fill=tk.X, pady=20)
        self.download_button = tk.Button(
            button_frame, 
            text="Download", 
            bg=self.button_color, 
            fg=self.button_fg, 
            font=("Arial", 14, "bold"), 
            command=self.start_download
        )
        self.download_button.pack(fill=tk.X, pady=10)
        
        # Status section
        status_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        status_frame.pack(fill=tk.X, pady=15)
        status_label = tk.Label(
            status_frame, 
            text="Status:", 
            bg=self.bg_color, 
            fg=self.fg_color, 
            font=("Arial", 12, "bold")
        )
        status_label.pack(anchor="w", pady=(5, 0))
        self.status_var = tk.StringVar(value="Ready")
        self.status_value = tk.Label(
            status_frame, 
            textvariable=self.status_var,
            bg=self.bg_color, 
            fg=self.fg_color, 
            font=("Arial", 12)
        )
        self.status_value.pack(anchor="w", pady=2)
        
        # Progress bar
        progress_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        progress_frame.pack(fill=tk.X, pady=15)
        self.progress = ttk.Progressbar(
            progress_frame, 
            orient=tk.HORIZONTAL,
            length=100,
            mode='determinate'
        )
        self.progress.pack(fill=tk.X, pady=5)
        
        # Log section
        log_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=15)
        log_label = tk.Label(
            log_frame,
            text="Log:", 
            bg=self.bg_color, 
            fg=self.fg_color, 
            font=("Arial", 12, "bold")
        )
        log_label.pack(anchor="w", pady=(5, 0))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            bg="#2c3e50", 
            fg=self.fg_color, 
            font=("Arial", 10), 
            wrap=tk.WORD,
            height=8,
            insertbackground=self.fg_color, 
            selectbackground=self.accent_color, 
            selectforeground=self.fg_color, 
            borderwidth=1, 
            relief=tk.SOLID
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Add some initial log messages
        self.log_text.insert(tk.END, "Neural Extractor v0.1\n")
        self.log_text.insert(tk.END, "Ready to download videos.\n")
        self.log_text.config(state='disabled')
        
    def animate(self):
        """Handle all animations"""
        if not self.animation_running:
            return
            
        # Update animation frame
        self.animation_frame = (self.animation_frame + 1) % 360
        
        # Title glow effect
        glow_intensity = abs(math.sin(math.radians(self.animation_frame * 2))) * 0.5 + 0.5
        glow_color = self.adjust_color(self.neon_blue, glow_intensity)
        self.title_label.configure(fg=glow_color)
        
        # Progress bar pulse
        self.pulse_phase = (self.pulse_phase + 1) % 360
        pulse_intensity = abs(math.sin(math.radians(self.pulse_phase))) * 0.3 + 0.7
        pulse_color = self.adjust_color(self.progress_color, pulse_intensity)
        self.progress.configure(style='TProgressbar')
        
        # Schedule next animation frame
        self.after(16, self.animate)  # ~60 FPS
        
    def adjust_color(self, hex_color, intensity):
        """Adjust color intensity for glow effects"""
        # Convert hex to RGB
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        
        # Adjust intensity
        r = int(r * intensity)
        g = int(g * intensity)
        b = int(b * intensity)
        
        # Convert back to hex
        return f'#{r:02x}{g:02x}{b:02x}'
        
    def fade_in(self, widget, duration=500):
        """Fade in animation for widgets"""
        widget.attributes('-alpha', 0)
        widget.update()
        
        def fade(alpha):
            if alpha < 1:
                widget.attributes('-alpha', alpha)
                widget.after(16, lambda: fade(alpha + 0.1))
                
        fade(0)
        
    def pulse_button(self, button):
        """Pulse animation for buttons"""
        original_color = button.cget('bg')
        
        def pulse(phase):
            if phase < 360:
                intensity = abs(math.sin(math.radians(phase))) * 0.3 + 0.7
                new_color = self.adjust_color(original_color, intensity)
                button.configure(bg=new_color)
                button.after(16, lambda: pulse(phase + 10))
            else:
                button.configure(bg=original_color)
                
        pulse(0)
        
    def log(self, message):
        """Add a message to the log with timestamp."""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        self.log_text.configure(state='normal')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state='disabled')
        
    def validate_youtube_url(self, url):
        """Validate if the URL is a valid YouTube URL."""
        # Basic pattern for YouTube URLs including Mixes and specific indices
        youtube_regex = r'^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/(watch\?v=|playlist\?list=|mix\/|watch\?v=.*&list=).*$'
        match = re.match(youtube_regex, url)
        return match is not None
    
    def extract_video_id(self, url):
        """Extract video ID from YouTube URL."""
        if 'youtu.be' in url:
            return urlparse(url).path.strip('/')
        else:
            parsed_url = urlparse(url)
            return parse_qs(parsed_url.query).get('v', [None])[0]
    
    def extract_playlist_videos(self, playlist_url):
        try:
            # Handle both regular playlists and Mixes
            if "mix" in playlist_url or "list=" in playlist_url:
                self.log(f"Processing URL: {playlist_url}")
                
                # Extract the starting index if present
                start_index = 1
                if "index=" in playlist_url:
                    try:
                        start_index = int(playlist_url.split("index=")[1].split("&")[0])
                        self.log(f"Detected starting index: {start_index}")
                    except (ValueError, IndexError):
                        self.log("Could not parse index, defaulting to 1")

                # Extract the list ID
                list_id = None
                if "list=" in playlist_url:
                    list_id = playlist_url.split("list=")[1].split("&")[0]
                    self.log(f"Detected list ID: {list_id}")

                try:
                    playlist = Playlist(playlist_url)
                    self.log("Successfully created playlist object")
                    
                    # For Mixes, we'll limit to 100 videos to avoid infinite loops
                    max_videos = 100 if "mix" in playlist_url or "RD" in playlist_url else None
                    video_urls = []
                    
                    # Log the starting point
                    if start_index > 1:
                        self.log(f"Starting from video #{start_index} in the Mix")
                    
                    # Skip to the starting index
                    current_index = 1
                    for video_url in playlist.video_urls:
                        if current_index >= start_index:
                            video_urls.append(video_url)
                            self.log(f"Added video {current_index}: {video_url}")
                            if max_videos and len(video_urls) >= max_videos:
                                self.log(f"Reached maximum video limit of {max_videos}")
                                break
                        current_index += 1
                    
                    # Sort videos by their playlist index to maintain proper order
                    video_urls.sort(key=lambda x: int(x.split('index=')[1].split('&')[0]) if 'index=' in x else 1)
                    
                    if video_urls:
                        self.log(f"Successfully extracted {len(video_urls)} videos starting from index {start_index}")
                        return video_urls
                    else:
                        self.log("No videos were extracted from the playlist")
                        return []
                        
                except Exception as e:
                    self.log(f"Error processing playlist: {str(e)}")
                    self.log(traceback.format_exc())
                    raise
                    
                return []
                
            return []
        except Exception as e:
            self.log(f"Error extracting playlist/mix: {str(e)}")
            self.log(traceback.format_exc())
            messagebox.showerror("Playlist/Mix Error", f"Could not extract playlist/mix: {str(e)}")
            return []
    
    def start_download(self):
        """Start the download process with animation"""
        # Pulse the download button
        self.pulse_button(self.download_button)
        
        # Collect URLs
        urls = []
        single_url = self.url_entry.get().strip()
        if single_url:
            self.log(f"Processing single URL: {single_url}")
            urls.append(single_url)
        batch_text = self.batch_text.get("1.0", tk.END).strip()
        if batch_text:
            self.log("Processing batch URLs")
            urls.extend([url.strip() for url in batch_text.split('\n') if url.strip()])
        
        if not urls:
            messagebox.showerror("Error", "Please enter at least one YouTube URL")
            return
        
        # Only validate and pass URLs to yt-dlp, do not expand playlists/mixes
        valid_urls = []
        for url in urls:
            if self.validate_youtube_url(url):
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
            self.download_button.configure(text="Download", bg=self.button_color)
            self.log("💀 Extraction aborted by user")
            return
        
        # Update UI for downloading state
        self.status_var.set("🔄 INITIALIZING EXTRACTION...")
        self.progress['value'] = 0
        self.download_button.configure(text="❌ ABORT EXTRACTION", bg=self.button_color)  # Teal for cancel
        
        # Clear stop flag
        self.stop_download = False
        
        # Start download thread
        self.download_thread = threading.Thread(target=self.download_video, args=(valid_urls,))
        self.download_thread.daemon = True
        self.download_thread.start()
    
    def download_thumbnail(self, video_id, title=None):
        """Download YouTube thumbnail for a video ID."""
        # Probeer eerst maxresdefault, anders hqdefault
        base_url = f"https://img.youtube.com/vi/{video_id}/"
        for thumb in ["maxresdefault.jpg", "hqdefault.jpg"]:
            url = base_url + thumb
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200 and response.content:
                    # Determine filename
                    safe_title = title or video_id
                    safe_title = re.sub(r'[^\w\-_\. ]', '_', safe_title)
                    filename = f"{safe_title}_thumbnail.jpg"
                    output_path = os.path.join(self.output_var.get(), filename)
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    self.log(f"Thumbnail saved as: {output_path}")
                    return output_path
            except Exception as e:
                self.log(f"Error downloading thumbnail: {e}")
        self.log(f"Thumbnail not found for video {video_id}")
        return None
    
    def download_video(self, urls):
        """Download videos in a separate thread, supporting batch downloads and playlists."""
        self.log("Starting download_video thread...")
        for url in urls:
            try:
                self.log(f"Fetching metadata: {url}")
                
                # Detect playlist/mix
                is_mix = ("mix" in url or "RD" in url)
                is_playlist = ("playlist" in url or "list=" in url or is_mix)
                
                # Configure yt-dlp options
                if is_playlist:
                    outtmpl = os.path.join(self.output_var.get(), '%(playlist)s/%(playlist_index)s-%(title)s.%(ext)s')
                else:
                    outtmpl = os.path.join(self.output_var.get(), '%(title)s.%(ext)s')
                ydl_opts = {
                    'format': 'best',  # Default to best quality
                    'outtmpl': outtmpl,
                    'progress_hooks': [self.on_progress],
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }] if "Audio Only" in self.quality_var.get() else [],
                    'ignoreerrors': True,  # Skip videos that can't be downloaded
                    'no_warnings': True,
                    'quiet': True,
                }
                # Subtitle opties toevoegen indien aangevinkt
                if self.download_subtitles_var.get():
                    ydl_opts.update({
                        'writesubtitles': True,
                        'subtitleslangs': [self.subtitle_language_var.get()],
                        'subtitlesformat': 'srt',
                        'writeautomaticsub': True,  # Probeer ook automatische subs
                    })
                
                # Add playlist-specific options if it's a playlist or mix
                if is_playlist:
                    self.log("Playlist or Mix detected! Downloading all videos...")
                    ydl_opts.update({
                        'playlist': True,
                        'playlistreverse': False,
                        'playlistrandom': False
                    })
                
                self.log(f"Creating yt_dlp.YoutubeDL object with options: {ydl_opts}")
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    self.log("Calling ydl.extract_info...")
                    info = ydl.extract_info(url, download=False)  # Get info first
                    self.log(f"yt-dlp extract_info returned: {type(info)}")
                    if not info:
                        self.log("yt-dlp could not extract info for this URL.")
                        self.update_status_ui("Failed", "yt-dlp could not extract info.")
                        continue
                    # Handle playlist/mix
                    if 'entries' in info:
                        self.log("'entries' found in info, processing as playlist/mix.")
                        entries = list(info['entries'])
                        seen_ids = set()
                        filtered_entries = []
                        for entry in entries:
                            if not entry:
                                continue
                            vid = entry.get('id')
                            if vid and vid not in seen_ids:
                                filtered_entries.append(entry)
                                seen_ids.add(vid)
                            if is_mix and len(filtered_entries) >= 20:
                                break
                        total_videos = len(filtered_entries)
                        self.log(f"Processing {total_videos} unique videos from playlist/mix.")
                        for idx, entry in enumerate(filtered_entries, 1):
                            if self.stop_download:
                                self.log("Download stopped by user.")
                                break
                            video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                            self.update_status_ui(f"Downloading {entry.get('title', 'Unknown')} ({idx}/{total_videos})", video_url)
                            self.progress['value'] = 0
                            self.log(f"Calling ydl.download for {video_url}")
                            # Actually download the video
                            try:
                                ydl.download([video_url])
                                self.log(f"Finished downloading {video_url}")
                                # Download thumbnail if checked
                                if self.download_thumbnail_var.get():
                                    self.download_thumbnail(entry['id'], entry.get('title'))
                            except Exception as e:
                                self.log(f"Error downloading {video_url}: {e}")
                        self.log(f"Completed downloading {idx if not self.stop_download else idx-1} videos from playlist/mix.")
                    else:
                        # Single video
                        self.progress['value'] = 0
                        self.log(f"Title: {info['title']}")
                        self.log(f"Duration: {info['duration']} seconds")
                        self.update_status_ui("Preparing download", info['title'])
                        self.log(f"Calling ydl.download for {url}")
                        ydl.download([url])
                        self.log(f"Finished downloading {url}")
                        # Download thumbnail if checked
                        if self.download_thumbnail_var.get():
                            video_id = info.get('id') or self.extract_video_id(url)
                            self.download_thumbnail(video_id, info.get('title'))
            except Exception as e:
                self.update_status_ui("Failed", "Error occurred")
                self.log(f"Error: {str(e)}")
                self.log(traceback.format_exc())
                messagebox.showerror("Error", f"An unexpected error occurred: {str(e)}")
            finally:
                # Reset download button
                self.download_button.configure(text="Download", bg=self.button_color)
        self.log("Exiting download_video thread.")
    
    def on_progress(self, d):
        """Callback for download progress with speed and ETA display."""
        if self.stop_download:
            raise Exception("Download cancelled by user")
        
        if d['status'] == 'downloading':
            # Calculate progress percentage
            total_size = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            
            if total_size > 0:
                percentage = (downloaded / total_size) * 100
                speed = d.get('speed', 0)
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
            self.progress['value'] = percentage
            
            # Update status with speed and ETA
            if 'playlist_index' in d:
                playlist_index = d['playlist_index']
                playlist_count = d.get('playlist_count', '?')
                status_text = f"Downloading video {playlist_index}/{playlist_count} ({int(percentage)}%) - {speed_mb:.1f} MB/s - ETA: {eta_str}"
            else:
                status_text = f"Downloading ({int(percentage)}%) - {speed_mb:.1f} MB/s - ETA: {eta_str}"
            
            self.update_status_ui(status_text, f"{d.get('filename', 'N/A')} - {size_mb:.1f}MB of {total_mb:.1f}MB")
        
        elif d['status'] == 'finished':
            self.log(f"Download completed: {d.get('filename', 'N/A')}")
            self.on_complete(d)
    
    def on_complete(self, info):
        """Callback when download is complete."""
        self.update_status_ui("✅ EXTRACTION COMPLETE", f"Downloaded {os.path.basename(info['filename'])}")
        self.progress['value'] = 100
        self.log(f"🚀 Neural extraction completed: {info['filename']}")
        self.download_button.configure(text="Download", bg=self.button_color)
    
    def update_status_ui(self, status, filename):
        """Update status UI elements safely from any thread."""
        def update():
            self.status_var.set(status)
            self.log(f"Status: {status} - {filename}")
        
        # Schedule the update on the main thread
        self.after(0, update)

    def browse_output_folder(self):
        """Open a dialog to select the output folder."""
        folder = filedialog.askdirectory()
        if folder:
            self.output_var.set(folder)

    def toggle_subtitle_language(self):
        if self.download_subtitles_var.get():
            self.subtitle_language_combo.configure(state="readonly")
        else:
            self.subtitle_language_combo.configure(state="disabled")

if __name__ == "__main__":
    app = NeuralExtractor()
    app.mainloop()
