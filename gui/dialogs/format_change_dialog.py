"""
Dialog for changing file formats.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QComboBox, QPushButton, QProgressBar, QMessageBox,
                           QGroupBox, QTextEdit, QCheckBox, QLineEdit, QListWidget,
                           QFileDialog, QListWidgetItem)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal
import os
from pathlib import Path
import logging
import shutil
import json
from obspy import Stream

from core.plugin_manager import PluginManager
from utils.config import config
from utils.file_name_parser import FileNameParser
from gui.dialogs.base_tool_dialog import BaseToolDialog, BaseToolWorker
from utils.constants import DEFAULT_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

class FormatChangeWorker(BaseToolWorker):
    """Worker for changing file formats in a separate thread."""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self):
        """Initialize worker."""
        super().__init__()
        self.orig_format = None  # Will be set from data.json
        self.final_format = None  # Will be set from data.json
        self.file_list = []
        
        self.start_datetime = None
        self.split_components = False  # Will be set from data.json
        self.components = []  # Will be set from data.json
        self.parser = None
        self.project_data = None
        
        # Initialize plugin manager
        self.plugin_manager = PluginManager()
        self.readers = self.plugin_manager.get_available_readers()
        
        # Add cancellation flag
        self._is_cancelled = False
        
    def cancel(self):
        """Cancel the processing."""
        self._is_cancelled = True
        
    def process_file(self, filepath: str):
        """Process a single file.
        
        Args:
            filepath: Path of file to process
        """
        logger.info(f"Processing file: {filepath}")
        
        try:
            # Parse filename using FileNameParser
            success, parsed_parts, _, error = self.parse_filename(Path(filepath).name)
            if not success:
                error_msg = f"Cannot process file {filepath}: {error}"
                logger.error(error_msg)
                self.error.emit(error_msg)
                return
                
            # Get file info from parsed parts
            net = parsed_parts.get('Network', '')
            sta = parsed_parts.get('Station', '')
            loc = parsed_parts.get('Location', '')
            cha = parsed_parts.get('Channel', '')
            
            # Log the parts we're using
            logger.info(f"Using parts for file: Net={net}, STA={sta}, LOC={loc}, NEZ={cha}")
            
            # Get appropriate reader - try both with and without dot, and both cases
            orig_format = self.orig_format.lower()  # Convert to lowercase
            reader_class = (self.plugin_manager.get_available_readers().get(f".{orig_format}") or 
                          self.plugin_manager.get_available_readers().get(orig_format) or
                          self.plugin_manager.get_available_readers().get(f".{orig_format.upper()}") or
                          self.plugin_manager.get_available_readers().get(orig_format.upper()))
            
            if not reader_class:
                error_msg = f"No reader found for format: {self.orig_format}"
                logger.error(error_msg)
                self.error.emit(error_msg)
                return
                
            reader = reader_class()
            
            # Read data
            file_path = Path(self.project_dir) / filepath
            data = reader.read(str(file_path))
            if data is None:
                error_msg = f"Failed to read data from {filepath}"
                logger.error(error_msg)
                self.error.emit(error_msg)
                return
                
            # Get number of traces
            trace_num = len(data)
            
            # Get component names from project data
            components = []
            if(trace_num == 1):
                components = [cha]
            else:
                if self.project_data and 'data_params' in self.project_data:
                    components = self.project_data['data_params'].get('componentName', '').split(',')
            
            # If no components defined or number doesn't match, use default names
            if not components or len(components) != trace_num:
                if trace_num == 1:
                    components = [cha] if cha else ['CH1']
                else:
                    components = ['N', 'E', 'Z']
            
            # Process each component
            for i, (component, trace) in enumerate(zip(components, data)):
                try:
                    # Create parsed parts dictionary for folder architecture
                    folder_parts = parsed_parts.copy()
                    folder_parts['Channel'] = component
                    
                    # Get folder architecture
                    folder_arch_path = Path(self.parser.get_folder_architecture(folder_parts))
                    
                    # Create output directory using output folder from project parameters
                    output_default = Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER  # Default value
                    if self.project_data and 'data_params' in self.project_data:
                        output_folder = self.project_data['data_params'].get('outputFolder', output_default)
                    out_dir = output_folder / folder_arch_path.relative_to(folder_arch_path.anchor)
                    
                    # Create output directory and emit signal
                    out_dir = self.create_output_directory(out_dir)
                    
                    # Get start time from data
                    start_time = trace.stats.starttime.strftime("%Y%m%d%H%M%S")
                    
                    # Create output filename
                    out_file = out_dir / f"{sta}.{component}.{start_time}.{self.final_format.lower()}"
                    logger.info(f"Writing component {i} ({component}) to: {out_file}")
                    
                    # Get writer for final format
                    final_format = self.final_format.lower()
                    writer_class = (self.plugin_manager.get_available_readers().get(f".{final_format}") or 
                                  self.plugin_manager.get_available_readers().get(final_format) or
                                  self.plugin_manager.get_available_readers().get(f".{final_format.upper()}") or
                                  self.plugin_manager.get_available_readers().get(final_format.upper()))
                    
                    if not writer_class:
                        raise ValueError(f"No writer found for format: {self.final_format}")
                        
                    writer = writer_class()
                    writer.write(str(out_file), Stream([trace]))
                    
                    if not out_file.exists():
                        logger.error(f"Failed to create output file: {out_file}")
                    else:
                        logger.info(f"Successfully wrote output file: {out_file}")
                        
                except Exception as e:
                    logger.error(f"Error processing component {component}: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error processing file {filepath}: {str(e)}")
            raise
        
    def parse_filename(self, filename: str) -> tuple:
        """Parse filename using FileNameParser.
        
        Args:
            filename: Name of file to parse
            
        Returns:
            Tuple containing:
            - Success flag (bool)
            - Dictionary of parsed parts (Dict[str, str])
            - Channel flag (bool)
            - Error message if any (str)
        """
        try:
            # Parse filename using the parser
            return self.parser.parse_filename(filename)
            
        except Exception as e:
            logger.error(f"Error parsing filename '{filename}': {str(e)}")
            return False, {}, False, str(e)
        
    def run(self):
        """Process all files in the list."""
        total_files = len(self.file_list)
        if total_files == 0:
            logger.warning("No files to process")
            self.finished.emit()
            return
            
        for i, filename in enumerate(self.file_list):
            if self._is_cancelled:
                logger.info("Processing cancelled by user")
                break
                
            try:
                self.process_file(filename)
                progress = int((i + 1) / total_files * 100)
                self.progress.emit(progress)
            except Exception as e:
                logger.error(f"Error processing file {filename}: {e}")
                self.error.emit(str(e))
                
        self.progress.emit(100)
        self.finished.emit()

class FormatChangeDialog(BaseToolDialog):
    """Dialog for changing file formats."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog.
        
        Args:
            project_dir: Project directory path
            parent: Parent widget
        """
        super().__init__(project_dir, "Change Format", parent)
        
    def init_specific_ui(self):
        """Initialize UI components specific to file format change."""
        self.params_group.setVisible(False)

    def _get_data_info(self):
        """Get formatted data information string."""
        if not self.project_data:
            return "No project data available"
            
        info = []
        
        # Add data parameters
        params = self.project_data.get('data_params', {})
        info.append(f"Original Format: {params.get('dataFormat', 'Unknown')}")
        info.append(f"Output Format: {params.get('outputFormat', 'Unknown')}")
        info.append(f"Number of Components: {params.get('traceNum', 1)}")
        
        component_info = params.get('componentName', 'Unknown')
        trace_num = params.get('traceNum', 1)
        info.append(f"Component Names: {component_info if trace_num > 1 else 'Use channel ID in file name'}")
        info.append(f"Test Result: {'Passed' if self.project_data.get('test_result', False) else 'Not Tested'}")
        
        return "\n".join(info)
        
    def start_processing(self):
        """Start processing files."""
        # Get selected files
        selected_files = self._get_selected_files()
                
        if not selected_files:
            QMessageBox.warning(
                self,
                "Warning",
                "Please select files to process"
            )
            return
            
        # Create worker and thread
        self.thread = QThread()
        self.worker = FormatChangeWorker()
        
        # Set worker parameters
        self.worker.file_list = selected_files
        self.worker.project_dir = self.project_dir
        self.worker.project_data = self.project_data
        self.worker.plugin_manager = self.plugin_manager
        self.worker.parser = self.parser
        
        # Get format and component settings from data.json
        if self.project_data and 'data_params' in self.project_data:
            params = self.project_data['data_params']
            self.worker.orig_format = params.get('dataFormat', 'MSEED')
            self.worker.final_format = params.get('outputFormat', 'MSEED')
        
        # Connect worker signals
        self.connect_worker_signals()
        
        # Set up thread
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._on_processing_finished)
        self.worker.error.connect(self._show_error)
        
        # Disable UI
        self.start_button.setEnabled(False)
        self.select_all.setEnabled(False)
        self.file_list.setEnabled(True)
        self.add_files.setEnabled(False)
        self.add_folders.setEnabled(False)
        self.reset_list.setEnabled(False)
        
        # Start processing
        self.thread.start()

    def _on_processing_finished(self):
        """Handle processing completion."""
        super()._on_processing_finished()
        QMessageBox.information(self, "Complete", "Format conversion complete")

    def _show_error(self, message):
        """Show error message dialog."""
        QMessageBox.critical(self, "Error", message)