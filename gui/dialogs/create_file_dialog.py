"""
Dialog for creating overlapped files for seismic data processing.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QPushButton, QProgressBar, QMessageBox,
                           QTextEdit, QDoubleSpinBox, QListWidget,
                           QFileDialog, QGroupBox, QCheckBox, QSplitter,
                           QWidget, QTreeWidget, QTreeWidgetItem)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal
import os
from pathlib import Path
import logging
import numpy as np
from obspy import Stream, Trace, UTCDateTime
from datetime import datetime, timedelta
import json

from core.plugin_manager import PluginManager
from utils.config import config
from utils.file_utils import get_file_format_and_reader
from utils.file_name_parser import FileNameParser
from gui.dialogs.base_tool_dialog import BaseToolDialog, BaseToolWorker
from utils.constants import DEFAULT_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

class CreateFileWorker(QObject):
    """Worker for creating files with overlapping in a separate thread."""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self):
        """Initialize worker."""
        super().__init__()
        self.project_dir = None
        self.checked_paths = []
        self.overlap_percent = 50.0  # Changed default to 50%
        self.file_length_hours = 1.0  # Default 1 hour
        self.max_zero_padded_percent = 50.0  # Default max zero-padded percentage
        
        # Initialize plugin manager
        self.plugin_manager = PluginManager()
        
    def run(self):
        """Process all checked component directories."""
        if not self.checked_paths:
            logger.warning("No component directories to process")
            self.error.emit("No component directories to process")
            self.finished.emit()
            return
            
        try:
            # Calculate total work to be done
            total_work = len(self.checked_paths)
            
            # Process each checked component directory
            for i, component_path in enumerate(self.checked_paths):
                try:
                    # Get station and component from path
                    path_parts = Path(component_path).parts
                    if len(path_parts) < 2:
                        logger.warning(f"Invalid component path: {component_path}")
                        continue
                        
                    sta, nez = path_parts[-2], path_parts[-1]
                    component_dir = os.path.join(self.project_dir, component_path)
                    
                    if not os.path.isdir(component_dir):
                        logger.warning(f"Component directory does not exist: {component_dir}")
                        continue
                        
                    # Get all files in the component directory
                    files = sorted([f for f in os.listdir(component_dir) 
                                 if os.path.isfile(os.path.join(component_dir, f))])
                    
                    if len(files) < 2:
                        logger.warning(f"Not enough files in {component_dir} to create")
                        continue
                        
                    logger.info(f"Processing component directory: {component_dir}")
                    # Process files in this component directory
                    self._process_component_files(component_dir, files, sta, nez)
                    
                    # Update progress
                    progress = int(((i + 1) / total_work) * 100)
                    self.progress.emit(progress)
                    
                except Exception as e:
                    logger.error(f"Error processing directory {component_path}: {str(e)}")
                    continue
                
        except Exception as e:
            logger.error(f"Error in creating process: {str(e)}")
            self.error.emit(str(e))
            
        self.progress.emit(100)
        self.finished.emit()
        
    def _process_component_files(self, component_dir: str, files: list, sta: str, nez: str):
        """Process files in a component directory."""
        try:
            # Find a suitable first file that contains the component directory name
            first_file = None
            for file in files:
                if sta in file and nez in file:
                    first_file = file
                    break
                    
            if not first_file:
                logger.warning(f"No suitable first file found in {component_dir} that contains component name")
                return
                
            # Get reader for the format from the first file's extension
            format_ext = Path(first_file).suffix[1:].lower()  # Get format without dot
            reader_class = (self.plugin_manager.get_available_readers().get(f".{format_ext}") or 
                          self.plugin_manager.get_available_readers().get(format_ext))
            
            if not reader_class:
                raise ValueError(f"No reader found for format: {format_ext}")
                
            reader = reader_class()
            
            # Create a report file for missing data
            report_file = os.path.join(component_dir, f"Create_report.txt")
            missing_files = []
            zero_padded_files = []
            skipped_files = []
            skipped_zero_padded_files = []
            
            # Get first file's start time and set T0 to midnight of that date
            first_data = reader.read(str(os.path.join(component_dir, first_file)))
            if not isinstance(first_data, Stream):
                raise ValueError("Data is not in ObsPy Stream format")
                
            first_trace = first_data[0]
            first_start = first_trace.stats.starttime
            trace_delta = 1 / first_trace.stats.sampling_rate
            # Set T0 to midnight of the first file's date
            T0 = UTCDateTime(first_start.year, first_start.month, first_start.day)
            
            # Convert file length from hours to seconds
            L = self.file_length_hours * 3600
            
            # Calculate first createdd file's start time
            overlap_seconds = L * (self.overlap_percent / 100)
            step_seconds = L - overlap_seconds
            first_created_start = T0 + (1 - self.overlap_percent/100) * L
            
            # Create a dictionary of file times for easy lookup
            file_times = {}
            for file in files:
                file_path = os.path.join(component_dir, file)
                data = reader.read(str(file_path))
                if isinstance(data, Stream):
                    trace = data[0]
                    file_times[file] = {
                        'starttime': trace.stats.starttime,
                        'endtime': trace.stats.endtime,
                        'sampling_rate': trace.stats.sampling_rate,
                        'path': file_path
                    }
                    
            # Calculate all created file time ranges
            created_files = []
            current_start = first_created_start
            while True:
                # The endtime of obspy is starttime + (npts-1)*delta
                current_end = current_start +  L - 1 * trace_delta
                created_files.append({
                    'starttime': current_start,
                    'endtime': current_end,
                    'name': f"{sta}.{nez}.{current_start.strftime('%Y%m%d%H%M%S')}.{format_ext}"
                })
                current_start += step_seconds
                
                # Stop if we've gone past the last file's end time
                if current_start > max(info['endtime'] for info in file_times.values()):
                    break
            
            # Process each created file
            total_created_files = len(created_files)
            for i, created_file in enumerate(created_files):
                # Check if file already exists
                out_file = os.path.join(component_dir, created_file['name'])
                if os.path.exists(out_file):
                    logger.info(f"Skipping existing file: {created_file['name']}")
                    skipped_files.append(created_file['name'])
                    continue
                
                # Find source files
                source_files = []
                for file, info in file_times.items():
                    # Check if file overlaps with created file time range
                    if (info['starttime'] <= created_file['endtime'] and 
                        info['endtime'] >= created_file['starttime']):
                        source_files.append((file, info))
                
                if not source_files:
                    logger.warning(f"No source files found for {created_file['name']}")
                    missing_files.append(created_file['name'])
                    continue
                
                # Sort source files by start time
                source_files.sort(key=lambda x: x[1]['starttime'])
                
                # Create created data with proper data type
                created_data = np.zeros(int(L * source_files[0][1]['sampling_rate']), dtype=np.float32)
                total_samples = len(created_data)
                zero_samples = 0
                
                # Process each source file
                for file, info in source_files:
                    # Calculate overlap with created file
                    overlap_start = max(info['starttime'], created_file['starttime'])
                    overlap_end = min(info['endtime'], created_file['endtime'])
                    
                    if overlap_start >= overlap_end:
                        continue
                        
                    # Calculate sample indices
                    start_idx = int((overlap_start -created_file['starttime']) * info['sampling_rate'])
                    end_idx = int((overlap_end - created_file['starttime']) * info['sampling_rate'])
                    
                    # Read and copy data
                    data = reader.read(str(os.path.join(component_dir, file)))
                    if isinstance(data, Stream):
                        trace = data[0]
                        trace_start_idx = int((overlap_start - info['starttime']) * info['sampling_rate'])
                        trace_end_idx = int((overlap_end - info['starttime']) * info['sampling_rate'])
                        
                        # Ensure indices are within bounds
                        if trace_start_idx < len(trace.data):
                            if end_idx > len(created_data):
                                end_idx = len(created_data)
                            if trace_end_idx > len(trace.data):
                                trace_end_idx = len(trace.data)
                                
                            # Copy data with proper type conversion
                            created_data[start_idx:end_idx] = trace.data[trace_start_idx:trace_end_idx].astype(np.float32)
                
                # Count zero samples
                zero_samples = np.sum(created_data == 0)
                zero_percent = (zero_samples / total_samples) * 100
                
                # Check if zero padding exceeds the maximum allowed
                if zero_percent > self.max_zero_padded_percent:
                    logger.warning(f"Skipping {created_file['name']} - {zero_percent:.2f}% zero padding exceeds maximum of {self.max_zero_padded_percent}%")
                    skipped_zero_padded_files.append({
                        'name': created_file['name'],
                        'zero_percent': zero_percent
                    })
                    continue
                
                if zero_percent > 0:
                    zero_padded_files.append({
                        'name': created_file['name'],
                        'zero_percent': zero_percent
                    })
                
                # Create a new trace with created data
                created_trace = Trace(created_data.astype(np.float32))  # Ensure float32 type
                created_trace.stats = first_trace.stats.copy()
                created_trace.stats.starttime = created_file['starttime']
                
                # Create a new stream with the created trace
                created_stream = Stream([created_trace])
                
                # Write created data
                reader.write(str(out_file), created_stream)
                logger.info(f"Created created file: {out_file}")

                # Update progress after each created file is created
                # Calculate progress based on file progress only
                file_progress = (i + 1) / total_created_files
                self.progress.emit(int(file_progress * 100))
            
            # Write report
            with open(report_file, 'w') as f:
                f.write(f"create Report for {sta}.{nez}\n")
                f.write(f"File Length: {self.file_length_hours} hours\n")
                f.write(f"Overlap: {self.overlap_percent}%\n")
                f.write(f"Max Zero Padding: {self.max_zero_padded_percent}%\n")
                f.write(f"Totalcreated files created: {len(created_files) - len(missing_files) - len(skipped_files) - len(skipped_zero_padded_files)}\n")
                f.write(f"Files skipped (already exist): {len(skipped_files)}\n")
                f.write(f"Files skipped (too much zero padding): {len(skipped_zero_padded_files)}\n\n")
                
                if skipped_files:
                    f.write("Skipped Files (Already Exist):\n")
                    for name in skipped_files:
                        f.write(f"- {name}\n")
                    f.write("\n")
                
                if skipped_zero_padded_files:
                    f.write("Skipped Files (Too Much Zero Padding):\n")
                    for info in skipped_zero_padded_files:
                        f.write(f"- {info['name']}: {info['zero_percent']:.2f}% zeros\n")
                    f.write("\n")
                
                if missing_files:
                    f.write("Missing Files (Could not be created):\n")
                    for name in missing_files:
                        f.write(f"- {name}\n")
                    f.write("\n")
                
                if zero_padded_files:
                    f.write("Files with Zero Padding:\n")
                    for info in zero_padded_files:
                        f.write(f"- {info['name']}: {info['zero_percent']:.2f}% zeros\n")
                    
        except Exception as e:
            logger.error(f"Error processing component files: {str(e)}")
            raise

class CreateFileDialog(QDialog):
    """Dialog for creating files with overlapping."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog."""
        super().__init__(parent)
        
        # Ensure project_dir is a string path
        if isinstance(project_dir, str):
            self.project_dir = project_dir
        else:
            # If project_dir is not a string, try to get it from parent
            if parent and hasattr(parent, 'project_dir'):
                self.project_dir = parent.project_dir
            else:
                raise ValueError("Project directory must be provided as a string path")
            
        self.worker = None
        self.output_dir=None
        self.thread = None
        
        # Get plugin manager from parent window
        if parent and hasattr(parent, 'plugin_manager'):
            self.plugin_manager = parent.plugin_manager
        else:
            from core.plugin_manager import PluginManager
            self.plugin_manager = PluginManager()
            self.plugin_manager.reload_plugins()
        
        # Initialize UI
        self._init_ui()
        self.scan_stations()
        
    def _init_ui(self):
        """Initialize UI components."""
        self.setWindowTitle("Create Files")
        self.setMinimumWidth(500)
        
        main_layout = QVBoxLayout()
        
        # Create a splitter for the main sections
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel - Station and component selection
        left_panel = QVBoxLayout()
        
        # Station selection
        station_group = QGroupBox("Stations and Components")
        station_layout = QVBoxLayout()
        
        # Station tree widget
        self.station_tree = QTreeWidget()
        self.station_tree.setHeaderLabels(["Stations and Components"])
        self.station_tree.setColumnCount(1)
        self.station_tree.itemChanged.connect(self._on_tree_item_changed)
        
        # Component selection checkboxes
        self.component_group = QGroupBox("Select Component for All Stations")
        self.component_layout = QHBoxLayout()
        self.component_group.setLayout(self.component_layout)
        
        # Create empty dictionary for component checkboxes
        self.component_checkboxes = {}
        
        # Select all button
        select_all_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all_components)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all_components)
        select_all_layout.addWidget(self.select_all_btn)
        select_all_layout.addWidget(self.deselect_all_btn)
        
        station_layout.addWidget(self.station_tree)
        station_layout.addLayout(select_all_layout)
        station_group.setLayout(station_layout)
        left_panel.addWidget(station_group)
        left_panel.addWidget(self.component_group)
        
        # Right panel - Parameters and processing
        right_panel = QVBoxLayout()
        
        # Overlap settings
        overlap_group = QGroupBox("Overlap Settings")
        overlap_layout = QVBoxLayout()
        
        # Overlap percentage
        overlap_percent_layout = QHBoxLayout()
        overlap_percent_layout.addWidget(QLabel("Overlap Percentage:"))
        self.overlap_percent = QDoubleSpinBox()
        self.overlap_percent.setRange(0, 100)
        self.overlap_percent.setValue(50)  # Changed default to 50%
        self.overlap_percent.setSingleStep(10)  # Changed step to 10%
        self.overlap_percent.setSuffix("%")
        overlap_percent_layout.addWidget(self.overlap_percent)
        
        # File length
        file_length_layout = QHBoxLayout()
        file_length_layout.addWidget(QLabel("File Length (hours):"))
        self.file_length = QDoubleSpinBox()
        self.file_length.setRange(0.1, 24)
        self.file_length.setValue(1.0)
        self.file_length.setSingleStep(0.1)
        file_length_layout.addWidget(self.file_length)
        
        # Max zero-padded percentage
        max_zero_padded_layout = QHBoxLayout()
        max_zero_padded_layout.addWidget(QLabel("Max Zero-Padded Percentage:"))
        self.max_zero_padded = QDoubleSpinBox()
        self.max_zero_padded.setRange(0, 100)
        self.max_zero_padded.setValue(50)  # Default 50%
        self.max_zero_padded.setSingleStep(10)
        self.max_zero_padded.setSuffix("%")
        max_zero_padded_layout.addWidget(self.max_zero_padded)
        
        overlap_layout.addLayout(overlap_percent_layout)
        overlap_layout.addLayout(file_length_layout)
        overlap_layout.addLayout(max_zero_padded_layout)
        overlap_group.setLayout(overlap_layout)
        right_panel.addWidget(overlap_group)
        
        # Progress bar
        self.progress = QProgressBar()
        right_panel.addWidget(self.progress)
        
        # Start button
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.start_processing)
        self.start_button.setEnabled(False)
        right_panel.addWidget(self.start_button)
        
        # Add panels to splitter
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([300, 500])  # Set initial sizes
        
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
        
    def scan_stations(self):
        """Scan for stations and components in the project directory."""
        try:
            # Get project data to check which parts are available
            try:
                data_file = Path(self.project_dir) / 'data.json'
                with open(data_file, 'r', encoding='utf-8') as f:
                    self.project_data = json.load(f)
                
                # Get output folder from project data
                if self.project_data:
                    output_folder = self.project_data.get('data_params', {}).get('outputFolder', DEFAULT_OUTPUT_FOLDER)
                else:
                    output_folder = DEFAULT_OUTPUT_FOLDER  # Default value
                
            except Exception as e:
                logger.warning(f"Error reading data.json, using basic structure: {e}")
                output_folder = DEFAULT_OUTPUT_FOLDER  # Default value
                self.project_data = {'data_params': {'outputFolder': output_folder}}
            
            # Construct the output directory path

            output_dir = Path(self.project_dir) / output_folder
            
            if not output_dir.exists():
                logger.warning(f"Output directory {output_dir} does not exist")
                return
            self.output_dir=output_dir

            # Clear the tree widget
            self.station_tree.clear()
            
            # Create a dictionary to store the folder structure
            folder_structure = {}
            
            # First pass: build the folder structure by scanning directories only
            for root, dirs, _ in os.walk(output_dir):
                # Skip PSD folders
                if os.path.basename(root) == 'PSD':
                    continue
                    
                # Remove PSD directories from dirs to prevent them from being traversed
                if 'PSD' in dirs:
                    dirs.remove('PSD')
                    
                # Get relative path from output_dir
                rel_path = os.path.relpath(root, output_dir)
                if rel_path == '.':
                    continue
                    
                # Add this path to the folder structure
                path_parts = rel_path.split(os.sep)
                current_dict = folder_structure
                
                for part in path_parts:
                    if part not in current_dict:
                        current_dict[part] = {}
                    current_dict = current_dict[part]
            
            # Dictionary to track end nodes (components)
            self.end_nodes = {}
            
            # Build the tree widget from the folder structure
            self._build_tree_from_structure(folder_structure, None)
            
            # Identify end nodes (leaf nodes) as components
            self._identify_end_nodes()
            
            # Create component checkboxes based on end nodes
            self._create_component_checkboxes()
            
            # Expand all items
            self.station_tree.expandAll()
            
        except Exception as e:
            logger.error(f"Error scanning stations: {e}")
            QMessageBox.critical(self, "Error", f"Error scanning stations: {str(e)}")
    
    def _build_tree_from_structure(self, structure, parent_item):
        """Build tree widget items from folder structure dictionary."""
        for folder_name, subfolders in structure.items():
            # Create tree item
            item = QTreeWidgetItem()
            item.setText(0, folder_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            
            # Add to tree
            if parent_item is None:
                self.station_tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            
            # Process subfolders recursively
            self._build_tree_from_structure(subfolders, item)
    
    def _get_item_path(self, item):
        """Get the full path of an item in the tree."""
        path_parts = []
        current = item
        
        while current:
            path_parts.insert(0, current.text(0))
            current = current.parent()
            
        return os.path.join(*path_parts) if path_parts else ""
    
    def _identify_end_nodes(self):
        """Identify end nodes (leaf nodes) in the tree as components."""
        # Clear end nodes dictionary
        self.end_nodes = {}
        
        # Function to recursively find leaf nodes
        def find_leaf_nodes(item):
            if item.childCount() == 0:
                # This is a leaf node (end node)
                component = item.text(0)
                if component not in self.end_nodes:
                    self.end_nodes[component] = []
                self.end_nodes[component].append(item)
            else:
                # Process children
                for i in range(item.childCount()):
                    find_leaf_nodes(item.child(i))
        
        # Process all top-level items
        root = self.station_tree.invisibleRootItem()
        for i in range(root.childCount()):
            find_leaf_nodes(root.child(i))
    
    def _create_component_checkboxes(self):
        """Create checkboxes for each unique component."""
        # Clear existing checkboxes
        for i in reversed(range(self.component_layout.count())): 
            widget = self.component_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # Clear the dictionary
        self.component_checkboxes = {}
        
        # Create new checkboxes for each component
        for component in sorted(self.end_nodes.keys()):
            checkbox = QCheckBox(component)
            checkbox.stateChanged.connect(lambda state, comp=component: self._select_component_for_all(comp, state == Qt.Checked))
            self.component_checkboxes[component] = checkbox
            self.component_layout.addWidget(checkbox)
        
        # Update checkbox labels with counts
        self._update_component_checkbox_labels()
    
    def _update_component_checkbox_labels(self):
        """Update component checkbox labels based on available components."""
        # Count occurrences of each component
        component_counts = {}
        for component, items in self.end_nodes.items():
            component_counts[component] = len(items)
                
        # Update checkbox labels with component counts
        for comp, checkbox in self.component_checkboxes.items():
            count = component_counts.get(comp, 0)
            
            # Block signals temporarily
            checkbox.blockSignals(True)
            
            # Update label and enabled state
            checkbox.setText(f"{comp} ({count})")
            checkbox.setEnabled(count > 0)
            
            # Unblock signals
            checkbox.blockSignals(False)
    
    def _select_all_components(self):
        """Select all components."""
        # Get all top-level items
        root = self.station_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, Qt.Checked)
        
        # Update start button state
        self._update_start_button_state()
        
    def _deselect_all_components(self):
        """Deselect all components."""
        # Get all top-level items
        root = self.station_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, Qt.Unchecked)
        
        # Update start button state
        self._update_start_button_state()
        
    def _on_tree_item_changed(self, item, column):
        """Handle changes to tree item check state."""
        # Block signals to prevent recursive signal handling
        self.station_tree.blockSignals(True)
        
        # Propagate check state to children
        if item.checkState(column) == Qt.Checked:
            self._set_children_check_state(item, Qt.Checked)
        elif item.checkState(column) == Qt.Unchecked:
            self._set_children_check_state(item, Qt.Unchecked)
        
        # Update parent check state
        self._update_parent_check_state(item.parent())
        
        # Update component checkboxes based on tree selection
        self._sync_component_checkboxes()
        
        # Unblock signals
        self.station_tree.blockSignals(False)
        
        # Update start button state
        self._update_start_button_state()
    
    def _set_children_check_state(self, parent, state):
        """Set check state for all children of parent item."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setCheckState(0, state)
            self._set_children_check_state(child, state)
    
    def _update_parent_check_state(self, parent):
        """Update parent check state based on children."""
        if parent is None:
            return
            
        all_checked = True
        all_unchecked = True
        
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.checkState(0) == Qt.Checked:
                all_unchecked = False
            else:
                all_checked = False
        
        if all_checked:
            parent.setCheckState(0, Qt.Checked)
        elif all_unchecked:
            parent.setCheckState(0, Qt.Unchecked)
        else:
            parent.setCheckState(0, Qt.PartiallyChecked)
        
        # Recursively update parent's parent
        self._update_parent_check_state(parent.parent())
    
    def _sync_component_checkboxes(self):
        """Synchronize component checkboxes with the tree selection state."""
        # Block signals from component checkboxes
        for checkbox in self.component_checkboxes.values():
            checkbox.blockSignals(True)
        
        # Check each component
        for component, items in self.end_nodes.items():
            if component in self.component_checkboxes:
                # Determine checkbox state based on component items
                all_checked = all(item.checkState(0) == Qt.Checked for item in items) if items else False
                any_checked = any(item.checkState(0) == Qt.Checked for item in items) if items else False
                
                if all_checked:
                    self.component_checkboxes[component].setCheckState(Qt.Checked)
                elif any_checked:
                    self.component_checkboxes[component].setCheckState(Qt.PartiallyChecked)
                else:
                    self.component_checkboxes[component].setCheckState(Qt.Unchecked)
        
        # Unblock signals
        for checkbox in self.component_checkboxes.values():
            checkbox.blockSignals(False)
    
    def _get_checked_paths(self):
        """Get all checked paths from the tree."""
        checked_paths = []
        
        # Process all end nodes (components)
        for component, items in self.end_nodes.items():
            for item in items:
                # Only include checked or partially checked items
                check_state = item.checkState(0)
                if check_state != Qt.Unchecked:
                    # Build path by traversing backwards from leaf to root
                    path = self._build_path_from_item(item)

                    if path:
                        checked_paths.append(Path(self.output_dir) / path)
        
        return checked_paths
    
    def _build_path_from_item(self, item):
        """Build a path by traversing backwards from a tree item to the root."""
        path_parts = []
        current = item
        
        # Traverse up the tree, collecting path parts
        while current:
            path_parts.insert(0, current.text(0))
            current = current.parent()
        
        # Join path parts with OS-specific separator
        if path_parts:
            return os.path.join(*path_parts)
        return ""
    
    def _select_component_for_all(self, component, state):
        """Select all directories with the given component."""
        try:
            # Block signals to prevent recursive updates
            self.station_tree.blockSignals(True)
            
            # Update all tree items for this component
            if component in self.end_nodes:
                for item in self.end_nodes[component]:
                    item.setCheckState(0, Qt.Checked if state else Qt.Unchecked)
                    
                    # Update parent check states
                    parent = item.parent()
                    while parent:
                        self._update_parent_check_state(parent)
                        parent = parent.parent()
            
            # Unblock signals
            self.station_tree.blockSignals(False)
            
            # Update start button state
            self._update_start_button_state()
            
        except Exception as e:
            logger.error(f"Error selecting component {component}: {e}")
            QMessageBox.critical(self, "Error", f"Error selecting component {component}: {str(e)}")
    
    def _update_start_button_state(self):
        """Update the start button state based on checked items."""
        checked_paths = self._get_checked_paths()
        self.start_button.setEnabled(len(checked_paths) > 0)
    
    def start_processing(self):
        """Start processing files."""
        # Get checked paths
        checked_paths = self._get_checked_paths()
        if not checked_paths:
            logger.warning("No directories selected")
            QMessageBox.warning(
                self,
                "Warning",
                "No directories selected for processing"
            )
            return
            
        # Create worker and thread
        self.thread = QThread()
        self.worker = CreateFileWorker()
        
        # Set worker parameters
        self.worker.project_dir = self.project_dir
        self.worker.checked_paths = checked_paths
        self.worker.overlap_percent = self.overlap_percent.value()
        self.worker.file_length_hours = self.file_length.value()
        self.worker.max_zero_padded_percent = self.max_zero_padded.value()
        
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
        self.station_tree.setEnabled(False)
        self.overlap_percent.setEnabled(False)
        self.file_length.setEnabled(False)
        self.max_zero_padded.setEnabled(False)
            
        # Start processing
        self.thread.start()
        
    def _on_processing_finished(self):
        """Handle processing completion."""
        # Re-enable UI
        self.start_button.setEnabled(True)
        self.station_tree.setEnabled(True)
        self.overlap_percent.setEnabled(True)
        self.file_length.setEnabled(True)
        self.max_zero_padded.setEnabled(True)
        
        # Clean up thread and worker references
        self.thread = None
        self.worker = None
        
        # Show completion message
        QMessageBox.information(
            self,
            "Complete",
            "File creation complete"
        )
        
    def _show_error(self, message):
        """Show error message."""
        QMessageBox.critical(self, "Error", message) 

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
            
        super().closeEvent(event)
        
    def reject(self):
        """Handle dialog rejection (e.g., Escape key)."""
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
            
        super().reject() 