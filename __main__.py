"""
Main entry point for Tool4S application.
"""

import sys
import logging
from PyQt5.QtWidgets import QApplication
from gui.main_window import MainWindow
from utils.config import config
from utils.logging import setup_logging
def main():
    """Main application entry point."""
    try:


        # Set up logging
        setup_logging()
        
        # Create Qt application
        app = QApplication(sys.argv)
        
        # Create and show main window
        window = MainWindow()
        window.show()
        
        # Start event loop
        sys.exit(app.exec_())
        
    except Exception as e:
        logging.error(f"Application error: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 