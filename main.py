#!/usr/bin/env python3
import os
import sys
from dependencies import check_and_install_dependencies

# Check and install required dependencies
check_and_install_dependencies()

# After ensuring dependencies are installed, import the application
from youtube_downloader import YouTubeDownloaderApp

if __name__ == "__main__":
    app = YouTubeDownloaderApp()
    app.mainloop()
