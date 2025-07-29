"""
Base dialog and worker classes for seismic data processing tools.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QLineEdit, QProgressBar, QPushButton, QCheckBox,
                           QListWidget, QMessageBox, QTextEdit, QListWidgetItem,
                           QGroupBox, QFileDialog)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal
import os
from pathlib import Path
import logging
import json

from core.plugin_manager import PluginManager
from utils.file_name_parser import FileNameParser

logger = logging.getLogger(__name__)

class BaseToolWorker(QObject):
    """Base worker for processing files in a separate thread."""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    output_folder_created = pyqtSignal(str)  # New signal for output folder creation
    
    def __init__(self):
        """Initialize worker."""
        super().__init__()
        self.file_list = []
        self.file_format = 'MSEED'  # Will be set from data.json
        self.project_dir = None
        self.project_data = None
        self.plugin_manager = None
        self.parser = None
        self._is_cancelled = False
        self.trace_num = 1  # Default to single component
        self.components = []  # Component(channel) names from data.json or file's name
        
    def run(self):
        """Process all files in the list. 
        
        Should be overridden by subclasses to implement specific processing.
        """
        total_files = len(self.file_list)
        if total_files == 0:
            logger.warning("No files to process")
            self.finished.emit()
            return
            
        try:
            for i, filename in enumerate(self.file_list):
                if self._is_cancelled:
                    logger.info("Processing cancelled")
                    break
                    
                try:
                    self.process_file(filename)
                    if self._is_cancelled:  # Check after each file
                        break
                    progress = int((i + 1) / total_files * 100)
                    self.progress.emit(progress)
                except Exception as e:
                    logger.error(f"Error processing file {filename}: {e}")
                    self.error.emit(str(e))
                    
            self.progress.emit(100)
            self.finished.emit()
        except Exception as e:
            logger.error(f"Error in processing: {e}")
            self.error.emit(str(e))
            self.finished.emit()
            
    def process_file(self, filename):
        """Process a single file.
        
        Should be overridden by subclasses to implement specific processing.
        
        Args:
            filename: Path of file to process
        """
        raise NotImplementedError("Subclasses must implement process_file")
        
    def cancel(self):
        """Cancel the processing."""
        self._is_cancelled = True

    def create_output_directory(self, output_dir):
        """Create output directory and emit signal.
        
        Args:
            output_dir: Path to create
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created output directory: {output_dir}")
        self.output_folder_created.emit(str(output_dir))
        return output_dir

class BaseToolDialog(QDialog):
    """Base dialog for processing seismic data files."""
    
    # Signal to notify main window of output folder creation
    output_folder_created = pyqtSignal(str)
    
    def __init__(self, project_dir: str, title: str = "Tool Dialog", parent=None):
        """Initialize dialog.
        
        Args:
            project_dir: Project directory path
            title: Dialog title
            parent: Parent widget
        """
        super().__init__(parent)
        self.project_dir = project_dir
        self.worker = None
        self.thread = None
        self.title = title
        
        # Get plugin manager from parent window
        if parent and hasattr(parent, 'plugin_manager'):
            self.plugin_manager = parent.plugin_manager
        else:
            from core.plugin_manager import PluginManager
            self.plugin_manager = PluginManager()
            self.plugin_manager.reload_plugins()
        
        # Initialize data attributes
        self.project_data = None
        self.project_format = None
        self.test_result = False
        
        # Initialize file name parser
        self.parser = FileNameParser(project_dir=self.project_dir)
        
        # Initialize UI first
        self._init_base_ui()
        
        # Initialize subclass UI
        self.init_specific_ui()
        
        # Load data after UI is initialized
        self.load_data_info()
        
    def _init_base_ui(self):
        """Initialize base UI components common to all tool dialogs."""
        self.setWindowTitle(self.title)
        self.setMinimumWidth(800)
        self.setMinimumHeight(500)
        
        self.main_layout = QVBoxLayout()
        
        # Data info section
        info_group = QGroupBox("Data Information")
        info_layout = QVBoxLayout()
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        info_layout.addWidget(self.info_text)
        info_group.setLayout(info_layout)
        self.main_layout.addWidget(info_group)
        
        # Parameters section (will be filled by subclasses)
        self.params_group = QGroupBox("Parameters")
        self.params_layout = QVBoxLayout()
        self.params_group.setLayout(self.params_layout)
        self.main_layout.addWidget(self.params_group)
        
        # Files section
        files_group = QGroupBox("Files")
        files_layout = QVBoxLayout()
        
        # Select all checkbox
        self.select_all = QCheckBox("Select All")
        self.select_all.stateChanged.connect(self._on_select_all)
        files_layout.addWidget(self.select_all)
        
        # File list
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.file_list.itemChanged.connect(self._on_item_changed)
        files_layout.addWidget(self.file_list)
        
        # Add file and folder buttons
        button_layout = QHBoxLayout()
        self.add_files = QPushButton("Add Files")
        self.add_files.clicked.connect(self._on_add_files)
        self.add_folders = QPushButton("Add Folders")
        self.add_folders.clicked.connect(self._on_add_folders)
        self.reset_list = QPushButton("Reset List")
        self.reset_list.clicked.connect(self._on_reset_list)
        
        button_layout.addWidget(self.add_files)
        button_layout.addWidget(self.add_folders)
        button_layout.addWidget(self.reset_list)
        files_layout.addLayout(button_layout)
        
        files_group.setLayout(files_layout)
        self.main_layout.addWidget(files_group)
        
        # Progress bar
        self.progress = QProgressBar()
        self.main_layout.addWidget(self.progress)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_processing)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._on_cancel)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(button_layout)
        
        self.setLayout(self.main_layout)
        
    def init_specific_ui(self):
        """Initialize UI components specific to subclass.
        
        Should be overridden by subclasses to add specific UI elements.
        """
        pass
        
    def _get_data_info(self):
        """Get formatted data information string.
        
        May be overridden by subclasses to add specific data info.
        """
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
        
    def _on_select_all(self, state):
        """Handle select all checkbox state change."""
        check_state = Qt.Checked if state == Qt.Checked else Qt.Unchecked
        for i in range(self.file_list.count()):
            self.file_list.item(i).setCheckState(check_state)
            
    def _on_item_changed(self, item):
        """Handle item change (including checkbox state change)."""
        self._update_start_button()
        
    def _update_start_button(self):
        """Update start button state based on file selection."""
        selected = False
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                selected = True
                break
                
        self.start_button.setEnabled(selected)
        
    def _on_add_files(self):
        """Handle add files button click."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Files",
            str(Path(self.project_dir)),
            "All Files (*.*)"
        )
        first_file = True
        first_file_path = ""
        file_num = 0
        
        if files:
            for file in files:
                # Check if file matches pattern
                success, _, _, _ = self.parser.parse_filename(Path(file).name)
                if success:
                    if first_file:
                        first_file_path = file
                        first_file = False
                    file_num = file_num + 1
                    item = QListWidgetItem(file)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    self.file_list.addItem(item)
                else:
                    logger.warning(f"Skipping file {file}: Does not match pattern")
                    
            if first_file_path:
                _, parsed_parts, _, _ = self.parser.parse_filename(Path(first_file_path).name)
                current_text = self.info_text.toPlainText()
                file_info = (f"File Information:\n"
                            f"Files Added: {file_num}\n"
                            f"Last Parsed File: {os.path.basename(first_file_path)}\n"
                            f"Parsed Parts: {parsed_parts}")
                self.info_text.setPlainText(current_text.split("File Information:")[0] + file_info)
            
    def _on_add_folders(self):
        """Handle add folders button click."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder",
            str(Path(self.project_dir))
        )
        first_file = True
        first_file_path = ""
        file_num = 0
        
        if folder:
            # Walk through folder and add files
            for root, _, files in os.walk(folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Check if file matches pattern
                    success, _, _, _ = self.parser.parse_filename(file)
                    if success:
                        if first_file:
                            first_file_path = file_path
                            first_file = False
                        file_num = file_num + 1
                        item = QListWidgetItem(file_path)
                        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                        item.setCheckState(Qt.Unchecked)
                        self.file_list.addItem(item)
                    else:
                        logger.warning(f"Skipping file {file}: Does not match pattern")
                        
            if first_file_path:
                _, parsed_parts, _, _ = self.parser.parse_filename(Path(first_file_path).name)
                current_text = self.info_text.toPlainText()
                file_info = (f"File Information:\n"
                           f"Files Added: {file_num}\n"
                           f"Last Parsed File: {os.path.basename(first_file_path)}\n"
                           f"Parsed Parts: {parsed_parts}")
                self.info_text.setPlainText(current_text.split("File Information:")[0] + file_info)
                
    def _on_reset_list(self):
        """Handle reset list button click."""
        self.file_list.clear()
        self.start_button.setEnabled(False)
        
        # Update info text
        current_text = self.info_text.toPlainText()
        file_info = (f"File Information:\n"
                   f"Files Added: 0\n"
                   f"Last Added: None")
        
        # Replace the File Information section
        new_text = current_text.split("File Information:")[0] + file_info
        self.info_text.setPlainText(new_text)
        
    def _on_cancel(self):
        """Handle cancel button click."""
        try:
            if hasattr(self, 'thread') and self.thread:
                try:
                    is_running = self.thread.isRunning()
                except RuntimeError:
                    is_running = False
                    
                if is_running and hasattr(self, 'worker') and self.worker:
                    # Disable the cancel button to prevent multiple clicks
                    self.cancel_button.setEnabled(False)
                    
                    # Request cancellation through the worker's slot
                    logger.info("Requesting cancellation")
                    self.worker.cancel()
                    
                    # Wait a bit for the worker to finish its current operation
                    self.thread.quit()
                    if not self.thread.wait(1000):  # Wait up to 1 second
                        logger.warning("Worker thread did not respond to quit request")
        except Exception as e:
            logger.debug(f"Error during cancel operation: {e}")
            
        self.reject()
        
    def start_processing(self):
        """Start processing files.
        
        Should be overridden by subclasses to implement specific processing start.
        """
        pass
        
    def _on_processing_finished(self):
        """Handle processing completion."""
        # Re-enable UI
        self.start_button.setEnabled(True)
        self.select_all.setEnabled(True)
        self.file_list.setEnabled(True)
        self.add_files.setEnabled(True)
        self.add_folders.setEnabled(True)
        self.reset_list.setEnabled(True)
        
        # Clear thread and worker
        self.thread = None
        self.worker = None
        
        # Show completion message
        #QMessageBox.information(self, "Complete", "Processing complete")
        
    def _show_error(self, message):
        """Show error message from worker thread."""
        QMessageBox.critical(self, "Error", message)
        
    def load_data_info(self):
        """Load data information from config."""
        try:
            data_file = Path(self.project_dir) / 'data.json'
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Store project data
            self.project_data = data
            # Get parameters
            params = data.get('data_params', {})
            self.project_format = params.get('dataFormat', 'Unknown')
            self.test_result = data.get('test_result', False)
            
            # Get format and component info
            orig_format = params.get('dataFormat', 'Unknown')
            output_format = params.get('outputFormat', 'Unknown')
            components = params.get('componentName', 'Unknown')
            trace_num = params.get('traceNum', 1)
            
            # Update info text
            info = (f"Project Information:\n"
                   f"Original Format: {orig_format}\n"
                   f"Output Format: {output_format}\n"
                   f"Number of Components: {trace_num}\n"
                   f"Component Names: {components if trace_num > 1 else 'Use channel ID in file name'}\n"
                   f"Test Result: {'Passed' if self.test_result else 'Not Tested'}\n\n"
                   f"File Information:\n"
                   f"Files Added: 0\n"
                   f"Last Parsed File: None")
            self.info_text.setPlainText(info)
                
            logger.info("Successfully loaded project data")
            
        except FileNotFoundError:
            logger.error(f"Data file not found: {data_file}")
            self.project_data = None
            self.info_text.setPlainText("No data.json file found.")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in data file: {data_file}")
            self.project_data = None
            self.info_text.setPlainText("Invalid data.json format.")
        except Exception as e:
            logger.error(f"Error loading data info: {e}")
            self.project_data = None
            self.info_text.setPlainText(f"Error loading data info: {str(e)}")
            
    def connect_worker_signals(self):
        """Connect worker signals to dialog slots.
        
        This method should be called after creating the worker in subclasses.
        """
        if self.worker:
            self.worker.output_folder_created.connect(self._on_output_folder_created)
            
    def _on_output_folder_created(self, folder_path):
        """Handle output folder creation.
        
        Args:
            folder_path: Path of created folder
        """
        # Forward signal to main window
        self.output_folder_created.emit(folder_path)
            
    def reject(self):
        """Handle dialog rejection (cancel button)."""
        try:
            if hasattr(self, 'thread') and self.thread:
                # Try to check if thread is running, but handle case where C++ object is deleted
                try:
                    is_running = self.thread.isRunning()
                except RuntimeError:
                    is_running = False
                    
                if is_running:
                    # Stop the worker first
                    if hasattr(self, 'worker') and self.worker:
                        self.worker.cancel()
                    
                    # Wait for the thread to finish
                    self.thread.quit()
                    if not self.thread.wait(3000):  # Wait up to 3 seconds
                        self.thread.terminate()  # Force quit if thread doesn't respond
                        self.thread.wait()
        except Exception as e:
            logger.error(f"Error during thread cleanup: {e}")
            
        # Reset thread and worker
        self.thread = None
        self.worker = None
        
        # Re-enable UI elements
        self.start_button.setEnabled(True)
        self.select_all.setEnabled(True)
        self.file_list.setEnabled(True)
        self.add_files.setEnabled(True)
        self.add_folders.setEnabled(True)
        self.reset_list.setEnabled(True)
        self.cancel_button.setEnabled(True)
        
        super().reject()

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Stop any running worker thread
        try:
            if hasattr(self, 'thread') and self.thread:
                # Try to check if thread is running, but handle case where C++ object is deleted
                try:
                    is_running = self.thread.isRunning()
                except RuntimeError:
                    is_running = False
                    
                if is_running:
                    if hasattr(self, 'worker') and self.worker:
                        self.worker.cancel()
                    self.thread.quit()
                    self.thread.wait(1000)  # Wait up to 1 second for thread to finish
        except Exception as e:
            logger.debug(f"Error during thread cleanup: {e}")
            self.thread = None
            self.worker = None
            
        # Clean up resources
        if hasattr(self, 'file_list'):
            self.file_list.clear()
        
        super().closeEvent(event) 

    