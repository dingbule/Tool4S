"""
File cut dialog for splitting seismic data files into one-hour segments.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QLineEdit, QPlainTextEdit, QListWidget,
                           QProgressBar, QPushButton, QCheckBox,
                           QListWidgetItem, QMessageBox, QTextEdit,
                           QGroupBox, QComboBox, QFileDialog)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal, QDateTime
import json
import os
from pathlib import Path
import logging
import numpy as np
from obspy import Trace, UTCDateTime
from datetime import datetime

from core.plugin_manager import PluginManager
from utils.config import config
from utils.file_utils import get_file_format_and_reader
from utils.file_name_parser import FileNameParser
from gui.dialogs.base_tool_dialog import BaseToolDialog, BaseToolWorker
from utils.constants import DEFAULT_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

class FileProcessingWorker(BaseToolWorker):
    """Worker for processing files in a separate thread."""
    
    def __init__(self):
        """Initialize worker."""
        super().__init__()
        self.head_offset = 0
        self.tail_remove_length = 0
        self.first_file_offset = 0
        self.time_length = 3600  # Default to 1 hour
        self.file_format = 'MSEED'  # Will be set from data.json
        self.start_on_hour = False  # Will be set from data.json
        self.overlap_percent = 0  # Default to 0%
        self.start_time = None
        self.project_dir = None
        self.project_data = None
        self.plugin_manager = None
        self.parser = None
        self._is_cancelled = False
        self.trace_num = 1  # Default to single component
        self.components = []  # Component(channel) names from data.json or file's name

    def process_file(self, filename: str):
        """Process a single file."""
        if self._is_cancelled:
            return
            
        logger.info(f"Processing file: {filename}")
        
        try:
            # Parse filename using FileNameParser
            success, parsed_parts, _, error = self.parser.parse_filename(Path(filename).name)
            if not success:
                error_msg = f"Cannot process file {filename}: {error}"
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
            
            # Get file path
            file_path = Path(self.project_dir) / filename
            
            # Get file format and reader
            file_format, reader = get_file_format_and_reader(filename, self.project_data)
            if not reader:
                error_msg = f"No suitable reader found for format: {file_format}"
                logger.error(error_msg)
                self.error.emit(error_msg)
                return

            # Read data using the reader
            try:
                data = reader.read(str(file_path))
                if data is None:
                    error_msg = f"Failed to read data from file: {filename}"
                    logger.error(error_msg)
                    self.error.emit(error_msg)
                    return
                    
                # Get components from data.json for three traces
                if len(data) > 1:
                    if not self.project_data or 'data_params' not in self.project_data:
                        error_msg = "Cannot process three-trace file: data.json not properly configured"
                        logger.error(error_msg)
                        self.error.emit(error_msg)
                        return
                        
                    params = self.project_data['data_params']
                    if 'componentName' not in params:
                        error_msg = "Cannot process three-trace file: component names not found in data.json"
                        logger.error(error_msg)
                        self.error.emit(error_msg)
                        return
                        
                    self.components = params['componentName'].split(',')
                    if len(self.components) != len(data):
                        error_msg = f"Number of components ({len(self.components)}) does not match number of traces ({len(data)})"
                        logger.error(error_msg)
                        self.error.emit(error_msg)
                        return
                else:
                    # For single trace, use the channel name
                    self.components = [cha]
                    
                # Process each trace
                for i, trace in enumerate(data):
                    data_array = trace.data
                    sample_rate = trace.stats.sampling_rate
                    start_time = trace.stats.starttime
                    metadata = {
                        'network': net,
                        'station': sta,
                        'channel': self.components[i] if i < len(self.components) else cha
                    }
                    
                    if data_array is None or sample_rate is None:
                        logger.error(f"Missing required data fields in file: {filename}")
                        return

                    # Calculate start time based on parameters
                    # First, add the first_file_offset hours
                    new_start_time = start_time + (self.first_file_offset * 3600)
                    
                    # Then add the head_offset seconds and 1 minute
                    new_start_time = new_start_time + self.head_offset + 60
                    
                    # Replace seconds and microseconds with 0 using UTCDateTime methods
                    new_start_time = UTCDateTime(
                        year=new_start_time.year,
                        month=new_start_time.month,
                        day=new_start_time.day,
                        hour=new_start_time.hour,
                        minute=new_start_time.minute,
                        second=0,
                        microsecond=0
                    )
                    
                    # If start_on_hour is True, round up to the next hour
                    if self.start_on_hour:
                        # Round up to the next hour
                        if new_start_time.minute > 0:
                            new_start_time = new_start_time + 3600  # Add one hour
                            new_start_time = UTCDateTime(
                                year=new_start_time.year,
                                month=new_start_time.month,
                                day=new_start_time.day,
                                hour=new_start_time.hour,
                                minute=0,
                                second=0,
                                microsecond=0
                            )
                    
                    # Calculate the start_index based on the new start time
                    time_diff = new_start_time - start_time
                    start_index = int(time_diff * sample_rate)
                    
                    # Calculate end index
                    total_samples = len(data_array)
                    file_end_index = total_samples - int(self.tail_remove_length * sample_rate)
                    
                    logger.info(f"Original start time: {start_time}")
                    logger.info(f"New start time: {new_start_time}")
                    logger.info(f"Start index: {start_index}")
                    logger.info(f"File end index: {file_end_index}")

                    # Ensure indices are within bounds
                    if start_index < 0 or file_end_index > total_samples or start_index >= file_end_index:
                        logger.error(f"Invalid indices for file {filename}: start_index={start_index}, file_end_index={file_end_index}")
                        return

                    # Get reader for the specified format
                    reader_class = self.plugin_manager.get_reader(self.file_format)
                    if not reader_class:
                        msg = f"No suitable reader found for format: {self.file_format}"
                        logger.error(msg)
                        self.error.emit(msg)
                        return

                    # Create reader instance
                    reader = reader_class()

                    # Process and save data in time_length increments
                    current_start = start_index
                    segment_count = 0  # Add counter for segments
                    
                    while current_start < file_end_index:
                        if self._is_cancelled:  # Check before each segment
                            logger.info("Processing cancelled during segmentation")
                            return

                        # Calculate end index for this segment
                        current_end = min(current_start + int(self.time_length * sample_rate), file_end_index)
                        
                        # Skip if this segment is not a full time_length
                        if current_end - current_start < int(self.time_length * sample_rate):
                            logger.info(f"Skipping incomplete segment: {current_start} to {current_end}")
                            break
                        
                        # Slice data for this segment
                        segment_data = data_array[current_start:current_end]

                        # Calculate time for this segment based on new_start_time and segment count
                        current_time = new_start_time + (segment_count * self.time_length * (1 - self.overlap_percent/100))
                        current_time_str = current_time.strftime("%Y%m%d%H%M%S")
                        
                        # Create parsed parts dictionary for folder architecture
                        parsed_parts = {
                            'Network': net,
                            'Station': sta,
                            'Location': loc,
                            'Channel': metadata['channel']
                        }
                        
                        # Get folder architecture
                        folder_arch_path = Path(self.parser.get_folder_architecture(parsed_parts))
                            
                        # Create output directory using output folder from project parameters
                        output_default = Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER  # Default value
                        if self.project_data and 'data_params' in self.project_data:
                            output_folder = self.project_data['data_params'].get('outputFolder', output_default)
                        out_dir = output_folder / folder_arch_path.relative_to(folder_arch_path.anchor)
                        
                        # Create output directory and emit signal
                        out_dir = self.create_output_directory(out_dir)
                        
                        # Create output filename
                        out_file = out_dir / f"{sta}.{metadata['channel']}.{current_time_str}.{self.file_format.lower()}"
                        logger.info(f"Writing output to: {out_file}")

                        # Create new trace with segment data
                        tr_new = Trace(data=np.array(segment_data))
                        tr_new.stats.station = sta
                        tr_new.stats.starttime = current_time
                        tr_new.stats.sampling_rate = sample_rate
                        tr_new.stats.network = metadata.get('network', '')
                        tr_new.stats.channel = metadata['channel']
                        
                        # Save segment using the reader's write method
                        try:
                            reader.write(str(out_file), tr_new)
                            logger.info(f"Saved segment: {out_file}")
                        except Exception as e:
                            msg = f"Failed to write segment using {self.file_format} reader: {str(e)}"
                            logger.error(msg)
                            self.error.emit(msg)
                            return

                        # Update indices for the next segment
                        # If there's overlap, move forward by (1 - overlap_percent) of the time length
                        overlap_samples = int(self.time_length * sample_rate * (self.overlap_percent / 100))
                        current_start = current_end - overlap_samples
                        segment_count += 1  # Increment segment counter

                        # Emit progress update
                        progress = int((current_start / total_samples) * 100)
                        self.progress.emit(progress)

                        logger.info(f"Updated start time: {current_time}")
            except Exception as e:
                logger.error(f"Error reading file {filename}: {str(e)}")
                return

        except Exception as e:
            logger.error(f"Processing failed for {filename}: {str(e)}", exc_info=True)

class FileCutDialog(BaseToolDialog):
    """Dialog for cutting seismic data files into one-hour segments."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog."""
        super().__init__(project_dir, "Cut Files", parent)
        
    def _get_data_info(self):
        """Get formatted data information string."""
        if not self.project_data:
            return "No project data available"
            
        info = []
        
        # Add data parameters
        params = self.project_data.get('data_params', {})
        info.append(f"Sample Rate: {params.get('sampleRate', 'Unknown')}")
        info.append(f"Data Format: {params.get('dataFormat', 'Unknown')}")
        info.append(f"Output Format: {params.get('outputFormat', 'Unknown')}")
        info.append(f"Start on Hour: {params.get('startOnHour', False)}")
        
        # Add component names if available
        if 'componentName' in params:
            info.append(f"Component Names: {params['componentName']}")
            
        return "\n".join(info)
        
    def init_specific_ui(self):
        """Initialize UI components specific to file cutting."""
        # Head offset
        head_layout = QHBoxLayout()
        head_layout.addWidget(QLabel("Head Offset (seconds):"))
        self.head_offset = QLineEdit()
        self.head_offset.setText("3600")  # Default value
        head_layout.addWidget(self.head_offset)
        self.params_layout.addLayout(head_layout)
        
        # Tail remove length
        tail_layout = QHBoxLayout()
        tail_layout.addWidget(QLabel("Tail Remove Length (seconds):"))
        self.tail_remove = QLineEdit()
        self.tail_remove.setText("3600")  # Default value
        tail_layout.addWidget(self.tail_remove)
        self.params_layout.addLayout(tail_layout)
        
        # First file offset
        first_layout = QHBoxLayout()
        first_layout.addWidget(QLabel("First File Offset (hours):"))
        self.first_offset = QLineEdit()
        self.first_offset.setText("0")  # Default value
        first_layout.addWidget(self.first_offset)
        self.params_layout.addLayout(first_layout)
        
        # Overlapping percent
        overlap_layout = QHBoxLayout()
        overlap_layout.addWidget(QLabel("Overlapping Percent (%):"))
        self.overlap_percent = QLineEdit()
        self.overlap_percent.setText("0")  # Default value
        self.overlap_percent.setPlaceholderText("0-100")
        overlap_layout.addWidget(self.overlap_percent)
        self.params_layout.addLayout(overlap_layout)
        
        # New file time length
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("New File Time Length (seconds):"))
        self.time_length = QLineEdit()
        self.time_length.setText("3600")  # Default value
        time_layout.addWidget(self.time_length)
        self.params_layout.addLayout(time_layout)
        
    def start_processing(self):
        """Start cutting files."""
        # Get selected files
        files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                files.append(item.text())
                
        if not files:
            logger.warning("No files selected")
            return
            
        # Create worker and thread
        self.thread = QThread()
        self.worker = FileProcessingWorker()
        
        # Convert QLineEdit values to numbers
        try:
            head_offset = float(self.head_offset.text() or '0')
            tail_remove_length = float(self.tail_remove.text() or '0')
            first_file_offset = float(self.first_offset.text() or '0')
            time_length = float(self.time_length.text() or '3600')
            overlap_percent = int(self.overlap_percent.text() or '0')
        except ValueError as e:
            QMessageBox.critical(self, "Error", "Invalid numeric values in parameters. Please check your inputs.")
            logger.error(f"Invalid parameter values: {str(e)}")
            return
            
        # Set worker parameters with numerical values
        self.worker.file_list = files
        self.worker.head_offset = head_offset
        self.worker.tail_remove_length = tail_remove_length
        self.worker.first_file_offset = first_file_offset
        self.worker.time_length = time_length
        self.worker.overlap_percent = overlap_percent
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
        self.file_list.setEnabled(False)
        self.add_files.setEnabled(False)
        self.add_folders.setEnabled(False)
        self.reset_list.setEnabled(False)
        
        # Start processing
        self.thread.start()
        
    def _on_processing_finished(self):
        """Handle processing completion."""
        super()._on_processing_finished()
        QMessageBox.information(self, "Complete", "File cutting complete")

    