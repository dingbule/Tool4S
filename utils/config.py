"""
Configuration handler for Tool4S
"""

import os
import configparser
from typing import Tuple, Any, Optional
from pathlib import Path
import logging
import sys

logger = logging.getLogger(__name__)

class Config:
    """Configuration manager for Tool4S application."""
    
    DEFAULT_CONFIG = {
        'Project': {
            'ProDir': '',
            'CurrentFile': '',
            'LastDirectory': str(Path.home())
        }
    }

    def __init__(self):
        """Initialize configuration."""
        self.config = configparser.ConfigParser()
        
        # First, try to find config.ini in the application directory (where the executable is)
        if getattr(sys, 'frozen', False):
            # If running as a bundled executable
            self.config_file = Path(sys.executable).parent / 'config.ini'
        else:
            # If running in development mode
            self.config_file = Path(__file__).parent.parent / 'config.ini'
        
        # Load existing config or create new one
        if self.config_file.exists():
            try:
                self.config.read(self.config_file)
                logger.info(f"Loaded configuration from {self.config_file}")
            except Exception as e:
                logger.error(f"Error loading config file: {e}")
        else:
            self._create_default_config()
            logger.info(f"Created new configuration file at {self.config_file}")

    def _create_default_config(self) -> None:
        """Create default configuration file."""
        for section, options in self.DEFAULT_CONFIG.items():
            if not self.config.has_section(section):
                self.config.add_section(section)
            for key, value in options.items():
                self.config.set(section, key, value)
        self.save()

    def save(self) -> None:
        """Save current configuration to file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                self.config.write(f)
            logger.info(f"Saved configuration to {self.config_file}")
        except Exception as e:
            logger.error(f"Error saving config file: {e}")

    def get(self, section: str, option: str, fallback: Any = None) -> str:
        """Get configuration value."""
        try:
            return self.config.get(section, option, fallback=fallback)
        except Exception as e:
            logger.error(f"Error getting config value {section}.{option}: {e}")
            return fallback

    def set(self, section: str, option: str, value: str) -> None:
        """Set configuration value."""
        try:
            if not self.config.has_section(section):
                self.config.add_section(section)
            self.config.set(section, option, value)
            self.save()
            logger.info(f"Set config value {section}.{option} = {value}")
        except Exception as e:
            logger.error(f"Error setting config value {section}.{option}: {e}")

    def get_project_paths(self) -> Tuple[str, str]:
        """Get project directory and current file."""
        return (
            self.get('Project', 'ProDir', ''),
            self.get('Project', 'CurrentFile', '')
        )

    def set_project_paths(self, pro_dir: str, current_file: Optional[str] = None) -> None:
        """Set project directory and optionally current file."""
        self.set('Project', 'ProDir', pro_dir)
        if current_file is not None:
            self.set('Project', 'CurrentFile', current_file)

# Global configuration instance
config = Config() 