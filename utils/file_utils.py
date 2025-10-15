"""
Utility functions for file operations.
"""

from pathlib import Path
import logging
from core.plugin_manager import PluginManager

logger = logging.getLogger(__name__)

def get_file_format_and_reader( project_data: dict):
    """Determine file format and select the appropriate reader."""
    try:
        # Get file format from data.json
        if not project_data:
            logger.warning("No project data loaded")
            return None, None

        # Get format from data_params in project data
        data_params = project_data.get('data_params', {})
        file_format = data_params.get('dataFormat', '').lower()
        
        if not file_format:
            logger.warning("No data format found in project data")
            return None, None

        # Add dot prefix if not present
        if not file_format.startswith('.'):
            file_format = f".{file_format}"

        # Get reader from plugin manager
        plugin_manager = PluginManager()
        plugin_manager._load_plugins()
        readers = plugin_manager.get_available_readers()
        
        # Try both with and without dot, and both cases
        reader_class = (readers.get(file_format) or 
                       readers.get(file_format.lstrip('.')) or
                       readers.get(file_format.upper()) or
                       readers.get(file_format.lstrip('.').upper()))
        
        if not reader_class:
            logger.error(f"No suitable reader found for format: {file_format}")
            return file_format, None
            
        return file_format, reader_class

    except Exception as e:
        logger.error(f"Error determining file format: {e}")
        return None, None


def get_output_format_and_writer(project_data: dict):
    """Determine output file format and select the appropriate writer."""
    try:
        # Get output format from data.json
        if not project_data:
            logger.warning("No project data loaded")
            return None, None

        # Get format from data_params in project data
        data_params = project_data.get('data_params', {})
        output_format = data_params.get('outputFormat', '').lower()
        
        if not output_format:
            logger.warning("No output format found in project data")
            return None, None

        # Add dot prefix if not present
        if not output_format.startswith('.'):
            output_format = f".{output_format}"

        # Get writer from plugin manager (writers are the same as readers in this system)
        plugin_manager = PluginManager()
        plugin_manager._load_plugins()
        readers = plugin_manager.get_available_readers()
        
        # Try both with and without dot, and both cases
        writer_class = (readers.get(output_format) or 
                       readers.get(output_format.lstrip('.')) or
                       readers.get(output_format.upper()) or
                       readers.get(output_format.lstrip('.').upper()))
        
        if not writer_class:
            logger.error(f"No suitable writer found for format: {output_format}")
            return output_format, None
            
        return output_format, writer_class

    except Exception as e:
        logger.error(f"Error determining output format: {e}")
        return None, None