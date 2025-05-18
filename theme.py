import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont

class HackerTheme:
    """Dark hacker-inspired theme for a Tkinter application."""
    
    # Color palette
    BACKGROUND_BLACK = "#0D0D0D"
    DARKER_BLACK = "#050505"
    LIGHTER_BLACK = "#1A1A1A"
    NEON_GREEN = "#00FF41"
    DARKER_GREEN = "#008F11"
    DANGER_RED = "#FF0000"
    WARNING_YELLOW = "#FFFF00"
    
    # Fonts
    FONT_FAMILY = "Courier"
    FONT_SIZE_SMALL = 9
    FONT_SIZE_NORMAL = 10
    FONT_SIZE_LARGE = 12
    FONT_SIZE_TITLE = 16
    
    @classmethod
    def configure_ttk_styles(cls):
        """Configure ttk styles for the application."""
        style = ttk.Style()
        
        # Configure the main theme
        style.theme_use('alt')  # Using 'alt' as base theme works better for customization
        
        # Configure TFrame
        style.configure("TFrame", background=cls.BACKGROUND_BLACK)
        
        # Configure TLabel
        style.configure("TLabel", 
                      background=cls.BACKGROUND_BLACK, 
                      foreground=cls.NEON_GREEN, 
                      font=(cls.FONT_FAMILY, cls.FONT_SIZE_NORMAL))
        
        # Configure TButton
        style.configure("TButton",
                      background=cls.DARKER_BLACK,
                      foreground=cls.NEON_GREEN,
                      borderwidth=1,
                      focusthickness=3,
                      focuscolor=cls.NEON_GREEN,
                      font=(cls.FONT_FAMILY, cls.FONT_SIZE_NORMAL))
        
        style.map("TButton",
                background=[('active', cls.LIGHTER_BLACK), ('pressed', cls.DARKER_BLACK)],
                foreground=[('active', cls.NEON_GREEN), ('pressed', cls.DARKER_GREEN)])
        
        # Download button with green glow
        style.configure("Glow.TButton",
                      background=cls.DARKER_BLACK,
                      foreground=cls.NEON_GREEN,
                      borderwidth=2,
                      focusthickness=3,
                      font=(cls.FONT_FAMILY, cls.FONT_SIZE_NORMAL, "bold"))
        
        # Configure TEntry
        style.configure("TEntry",
                      fieldbackground=cls.LIGHTER_BLACK,
                      foreground=cls.NEON_GREEN,
                      insertcolor=cls.NEON_GREEN,
                      borderwidth=1,
                      font=(cls.FONT_FAMILY, cls.FONT_SIZE_NORMAL))
        
        # Configure TCombobox
        style.configure("TCombobox",
                      fieldbackground=cls.LIGHTER_BLACK,
                      background=cls.DARKER_BLACK,
                      foreground=cls.NEON_GREEN,
                      arrowcolor=cls.NEON_GREEN,
                      font=(cls.FONT_FAMILY, cls.FONT_SIZE_NORMAL))
        
        style.map("TCombobox",
                fieldbackground=[('readonly', cls.LIGHTER_BLACK)],
                selectbackground=[('readonly', cls.DARKER_BLACK)],
                selectforeground=[('readonly', cls.NEON_GREEN)])
        
        # Configure TProgressbar
        style.configure("TProgressbar",
                      background=cls.NEON_GREEN,
                      troughcolor=cls.LIGHTER_BLACK,
                      borderwidth=0)
        
        # Configure Titlebar style
        style.configure("Title.TLabel",
                      background=cls.DARKER_BLACK,
                      foreground=cls.NEON_GREEN,
                      font=(cls.FONT_FAMILY, cls.FONT_SIZE_TITLE, "bold"))
        
    @classmethod
    def create_glow_effect(cls, widget):
        """Create a pulsating glow effect for a widget."""
        if not hasattr(cls, "_glow_intensity"):
            cls._glow_intensity = 0
            cls._glow_direction = 1
        
        def update_glow():
            # Update glow intensity
            cls._glow_intensity += cls._glow_direction * 0.05
            
            # Reverse direction at limits
            if cls._glow_intensity >= 1.0:
                cls._glow_intensity = 1.0
                cls._glow_direction = -1
            elif cls._glow_intensity <= 0.0:
                cls._glow_intensity = 0.0
                cls._glow_direction = 1
            
            # Calculate color based on intensity (make RGB values brighter)
            r = min(0, int(0 * cls._glow_intensity))  # Keep at 0
            g = min(255, int(255 * (0.7 + 0.3 * cls._glow_intensity)))  # Vary green intensity
            b = min(65, int(65 * cls._glow_intensity))  # Add a little blue for neon effect
            
            # Convert to hex color
            glow_color = f'#{r:02x}{g:02x}{b:02x}'
            
            # Apply to widget (only if widget still exists)
            try:
                widget.configure(foreground=glow_color)
                widget.after(50, update_glow)
            except:
                # Widget probably destroyed, stop the glow effect
                pass
        
        # Start the glow effect
        update_glow()
