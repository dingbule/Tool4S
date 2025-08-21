"""
Dialog for merging seismic data files into longer segments.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QLineEdit, QPlainTextEdit, QListWidget,
                           QProgressBar, QPushButton, QCheckBox,
                           QListWidgetItem, QMessageBox, QTextEdit,
                           QGroupBox, QComboBox, QSpinBox, QFileDialog)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal
import json
import os
from pathlib import Path
import logging
import numpy as np
from obspy import Stream, UTCDateTime
from datetime import datetime

from core.plugin_manager import PluginManager
from utils.config import config
from utils.file_utils import get_file_format_and_reader
from utils.file_name_parser import FileNameParser
from gui.dialogs.base_tool_dialog import BaseToolDialog, BaseToolWorker
from utils.constants import DEFAULT_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

class FileMergeWorker(BaseToolWorker):
    """Worker for merging files in a separate thread."""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self):
        """Initialize worker."""
        super().__init__()
        self.file_list = []
        self.merged_length = 3600  # Default to 1 hour
        self.file_format = 'MSEED'  # Will be set from data.json
        self.start_on_hour = False  # Will be set from data.json
        self.zero_padded_percent = 50  # Default to 50%
        self.project_dir = None
        self.project_data = None
        self.plugin_manager = None
        self.parser = None
        self._is_cancelled = False
        self.trace_num = 1  # Default to single component
        self.components = []  # Component(channel) names from data.json or file's name

    def run(self):
        """Process all files in the list."""
        total_files = len(self.file_list)
        if total_files == 0:
            logger.warning("No files to process")
            self.finished.emit()
            return
            
        try:
            # Sort files by name
            sorted_files = sorted(self.file_list)
            
            # Check first 5 files for time order
            if not self._verify_time_order(sorted_files[:min(5, len(sorted_files))]):
                self.error.emit("Warning: File time order may not match filename order. Proceeding with filename order.")
            
            # Group files by NET.STATION.CHANNEL.COMPONENT
            file_groups = self._group_files(sorted_files)
            if not file_groups:
                raise ValueError("No valid file groups to process")
                
            # Process each group
            total_groups = len(file_groups)
            for group_index, (group_key, files) in enumerate(file_groups.items()):
                if self._is_cancelled:
                    break
                    
                try:
                    logger.info(f"Processing group {group_index + 1}/{total_groups}: {group_key}")
                    self.status_update.emit(f"Processing group: {group_key}")
                    self._process_group(group_key, files)
                    
                    # Update progress
                    progress = int((group_index + 1) / total_groups * 100)
                    self.progress.emit(progress)
                    
                except Exception as e:
                    logger.error(f"Error processing group {group_key}: {e}")
                    self.error.emit(f"Error processing group {group_key}: {str(e)}")
                    
            self.progress.emit(100)
            self.finished.emit()
            
        except Exception as e:
            logger.error(f"Error in merge processing: {e}")
            self.error.emit(str(e))
            self.finished.emit()

    def _verify_time_order(self, files):
        """Verify that file time order matches filename order."""
        if not files:
            return True
            
        try:
            # Get file format and reader
            file_format, reader = get_file_format_and_reader(files[0], self.project_data)
            if not reader:
                return True  # Skip verification if no reader
                
            # Read start times
            times = []
            for filename in files:
                try:
                    file_path = Path(self.project_dir) / filename
                    data = reader.read_header(str(file_path))
                    if data:
                        times.append(data[0].stats.starttime)
                except Exception:
                    continue
                    
            # Check if times are in ascending order
            if len(times) > 1:
                return all(times[i] <= times[i+1] for i in range(len(times)-1))
                
            return True
            
        except Exception as e:
            logger.error(f"Error verifying time order: {e}")
            return True  # Skip verification on error

    def _group_files(self, files):
        """Group files by NET.STATION.Location.CHANNEL"""
        groups = {}
        for filename in files:
            try:
                # Parse filename
                success, parsed_parts, _, error = self.parser.parse_filename(Path(filename).name)
                if not success:
                    logger.warning(f"Skipping file {filename}: {error}")
                    continue
                    
                # Create group key
                net = parsed_parts.get('Network', '')
                sta = parsed_parts.get('Station', '')
                loc = parsed_parts.get('Location', '')
                cha = parsed_parts.get('Channel', '')
                
                group_key = f"{net}.{sta}.{loc}.{cha}"
                
                if group_key not in groups:
                    groups[group_key] = []
                groups[group_key].append(filename)
                
            except Exception as e:
                logger.error(f"Error grouping file {filename}: {e}")
                continue
                
        return groups

    def _process_group(self, group_key, files):
        """Process a group of files."""
        if not files:
            return
            
        # Get file format and reader
        file_format, reader = get_file_format_and_reader(files[0], self.project_data)
        if not reader:
            raise ValueError(f"No suitable reader found for format: {file_format}")
            
        # Parse first file to get group info
        success, parsed_parts, _, error = self.parser.parse_filename(Path(files[0]).name)
        if not success:
            raise ValueError(f"Failed to parse filename: {error}")
            
        # Process files in group
        current_index = 0
        total_files = len(files)
        
        while current_index < len(files):
            try:
                # Read first file to get start time
                data = reader.read(str(Path(self.project_dir) / files[current_index]))
                if not data:
                    current_index += 1
                    self.progress.emit(int(current_index / total_files * 100))
                    continue
                    
                # Get start time
                start_time = data[0].stats.starttime
                
                # If start on hour is selected and current time is not on hour
                if self.start_on_hour:
                    if start_time.minute != 0 or start_time.second != 0:
                        # Add hours until we reach the next hour
                        start_time = start_time + (3600 - start_time.minute * 60 - start_time.second)
                        
                # Calculate end time
                sampling_interval = data[0].stats.delta
                end_time = start_time + self.merged_length - sampling_interval
                
                # Create output stream
                output_stream = Stream()
                
                # Read files until we have enough data
                total_gap_time = 0
                last_end_time = None
                current_start = start_time
                found_gap = False
                
                
                
                while current_index < len(files):
                    current_file = files[current_index]
                    print(current_file)
                    
                    # Read data
                    data = reader.read(str(Path(self.project_dir) / current_file))
                    if not data:
                        current_index += 1
                        continue
                        
                    # Check for time gaps
                    current_start = data[0].stats.starttime
                    if last_end_time is not None:
                        expected_start = last_end_time + sampling_interval
                        if current_start > expected_start:
                            gap_time = current_start - expected_start
                            total_gap_time += gap_time
                            
                            # Check if gap is too large
                            max_allowed_gap = self.merged_length * (self.zero_padded_percent / 100.0)
                            if total_gap_time > max_allowed_gap:
                                # Mark that we found a gap and break
                                found_gap = True
                                break
                                    
                    # Add data to output stream
                    output_stream += data
                    # Merge traces with same ID, fill empty gaps with zeros
                    output_stream.merge(0,0)
                    last_end_time = data[0].stats.endtime
                    # Move to next file
                    current_index += 1
                    
                    # Check if we have enough data
                    if output_stream[-1].stats.endtime >= end_time:
     
                        break
                        
                    
                    
                # If gap was found, skip saving and continue with new starting point
                if found_gap:
                    continue
                
                output_stream.trim(starttime=start_time, endtime=end_time, pad=True, fill_value=0)

                if len(output_stream) > 0:                   
                    if self.trace_num == 1 :
                        self.components = group_key.split(".")[-1]                   
                    # Create output directory based on components
                    if  self.components:
                        # Use components from data.json
                        for i, component in enumerate(self.components):
                            # Create parsed parts for folder architecture
                            folder_parts = parsed_parts.copy()
                            folder_parts['Channel']=component
                            
                            # Get folder architecture
                            folder_arch_path = Path(self.parser.get_folder_architecture(folder_parts))
                            
                            # Create output directory using output folder from project parameters
                            output_default = Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER  # Default value
                            if self.project_data and 'data_params' in self.project_data:
                                output_folder = self.project_data['data_params'].get('outputFolder', output_default)
                            out_dir = output_folder / folder_arch_path.relative_to(folder_arch_path.anchor)
                            
                            # Create output directory and emit signal
                            out_dir = self.create_output_directory(out_dir)
                            
                            # Create output filename
                            out_file = out_dir / f"{parsed_parts['Station']}.{component}.{start_time.strftime('%Y%m%d%H%M%S')}.{self.file_format.lower()}"
                            
                            # Write component data
                            writer_class = self.plugin_manager.get_reader(self.file_format)
                            if not writer_class:
                                raise ValueError(f"No writer found for format: {self.file_format}")
                            writer = writer_class()
                            writer.write(str(out_file), output_stream[i])
                        
                
                # Update progress
                self.progress.emit(int(current_index / total_files * 100))
                
            except Exception as e:
                logger.error(f"Error processing file {files[current_index]}: {e}")
                current_index += 1
                self.progress.emit(int(current_index / total_files * 100))

    def cancel(self):
        """Cancel the processing."""
        self._is_cancelled = True

class MergeFilesDialog(BaseToolDialog):
    """Dialog for merging seismic data files into longer segments."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog."""
        super().__init__(project_dir, "Merge Files", parent)
        
    def init_specific_ui(self):
        """Initialize UI components specific to file merging."""
        # Merged file length
        length_layout = QHBoxLayout()
        length_layout.addWidget(QLabel("Merged File Length (hours):"))
        self.merged_length = QSpinBox()
        self.merged_length.setRange(1, 24)
        self.merged_length.setValue(1)
        length_layout.addWidget(self.merged_length)
        self.params_layout.addLayout(length_layout)
        
        # Zero padded percent
        zero_padded_layout = QHBoxLayout()
        zero_padded_layout.addWidget(QLabel("Zero Padded Percent:"))
        self.zero_padded_percent = QSpinBox()
        self.zero_padded_percent.setRange(0, 100)
        self.zero_padded_percent.setValue(50)
        zero_padded_layout.addWidget(self.zero_padded_percent)
        self.params_layout.addLayout(zero_padded_layout)
        
    def start_processing(self):
        """Start processing files."""
        # Get selected files
        selected_files = self._get_selected_files()
                
        if not selected_files:
            QMessageBox.warning(
                self,
                "Warning",
                "Please select files to merge"
            )
            return
            
        # Create worker and thread
        self.thread = QThread()
        self.worker = FileMergeWorker()
        
        # Set worker parameters
        self.worker.file_list = selected_files
        self.worker.merged_length = self.merged_length.value() * 3600  # Convert hours to seconds
        self.worker.zero_padded_percent = self.zero_padded_percent.value()
        self.worker.project_dir = self.project_dir
        self.worker.project_data = self.project_data
        self.worker.plugin_manager = self.plugin_manager
        self.worker.parser = self.parser
        
        # Get format and start_on_hour from data.json
        if self.project_data and 'data_params' in self.project_data:
            params = self.project_data['data_params']
            self.worker.file_format = params.get('outputFormat', 'MSEED')
            self.worker.start_on_hour = params.get('startOnHour', False)
            self.worker.trace_num = params.get('traceNum', 1)
            if 'componentName' in params:
                self.worker.components = params['componentName'].split(',')

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
        QMessageBox.information(self, "Complete", "File merging complete")
        
    def _show_error(self, message):
        """Show error message from worker thread."""
        QMessageBox.critical(self, "Error", message) 

    # The closeEvent and reject methods can be removed since the base class implementation
    # now has improved thread handling and will be used instead