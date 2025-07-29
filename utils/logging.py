"""
Logging configuration for Tool4S.
"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

def setup_logging(log_dir: Optional[str] = None,
                 log_level: int = logging.INFO,
                 max_bytes: int = 10485760,  # 10MB
                 backup_count: int = 5) -> None:
    """Set up logging configuration.
    
    Args:
        log_dir: Directory for log files (default: ./logs)
        log_level: Logging level (default: INFO)
        max_bytes: Maximum size of each log file
        backup_count: Number of backup files to keep
    """
    # Create logs directory if it doesn't exist
    if log_dir is None:
        log_dir = Path.cwd() / 'logs'
    else:
        log_dir = Path(log_dir)
    
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create formatters
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_formatter = logging.Formatter(
        '%(levelname)s: %(message)s'
    )
    
    # Create handlers
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'tool4s.log',
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    file_handler.setFormatter(file_formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Create error log handler
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / 'error.log',
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    error_handler.setFormatter(file_formatter)
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)
    
    logging.info("Logging system initialized") 