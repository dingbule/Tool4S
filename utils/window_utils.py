"""
Window management utilities for Tool4S application.
"""

from PyQt5.QtWidgets import QApplication, QMainWindow, QDialog
from PyQt5.QtCore import QSize
from utils.constants import APP_NAME, APP_VERSION

def get_screen_size():
    """Get the primary screen size."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    screen = app.primaryScreen().geometry()
    return screen.width(), screen.height()

def calculate_window_size(width_percent: float = 0.8, height_percent: float = 0.8) -> QSize:
    """
    Calculate window size based on screen dimensions and desired percentages.
    
    Args:
        width_percent (float): Desired width as percentage of screen width (0.0 to 1.0)
        height_percent (float): Desired height as percentage of screen height (0.0 to 1.0)
    
    Returns:
        QSize: Calculated window size
    """
    screen_width, screen_height = get_screen_size()
    width = int(screen_width * width_percent)
    height = int(screen_height * height_percent)
    return QSize(width, height)

def set_window_size(window: QMainWindow, width_percent: float = 0.8, height_percent: float = 0.8):
    """
    Set the size of a main window based on screen dimensions.
    
    Args:
        window (QMainWindow): The window to resize
        width_percent (float): Desired width as percentage of screen width (0.0 to 1.0)
        height_percent (float): Desired height as percentage of screen height (0.0 to 1.0)
    """
    size = calculate_window_size(width_percent, height_percent)
    window.resize(size)

def set_dialog_size(dialog: QDialog, width_percent: float = 0.5, height_percent: float = 0.5):
    """
    Set the size of a dialog based on screen dimensions.
    
    Args:
        dialog (QDialog): The dialog to resize
        width_percent (float): Desired width as percentage of screen width (0.0 to 1.0)
        height_percent (float): Desired height as percentage of screen height (0.0 to 1.0)
    """
    size = calculate_window_size(width_percent, height_percent)
    dialog.resize(size)

def center_window(window: QMainWindow):
    """
    Center a window on the screen.
    
    Args:
        window (QMainWindow): The window to center
    """
    screen_width, screen_height = get_screen_size()
    window_width = window.width()
    window_height = window.height()
    
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    
    window.move(x, y)

def center_dialog(dialog: QDialog):
    """
    Center a dialog on the screen.
    
    Args:
        dialog (QDialog): The dialog to center
    """
    screen_width, screen_height = get_screen_size()
    dialog_width = dialog.width()
    dialog_height = dialog.height()
    
    x = (screen_width - dialog_width) // 2
    y = (screen_height - dialog_height) // 2
    
    dialog.move(x, y)

def set_window_title(window, title=None, include_version=True):
    """
    Set window title with optional version information.
    
    Args:
        window: The window to set title for
        title: Custom title text (if None, uses APP_NAME)
        include_version: Whether to include version information
    """
    if title is None:
        title = APP_NAME
        
    if include_version:
        window.setWindowTitle(f"{title} v{APP_VERSION}")
    else:
        window.setWindowTitle(title) 