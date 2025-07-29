"""
Dialog for calculating Power Spectral Density (PSD) from seismic data.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QPlainTextEdit, QListWidget, QProgressBar,
                           QPushButton, QListWidgetItem, QMessageBox,
                           QDateTimeEdit, QTreeWidget, QTreeWidgetItem,
                           QGroupBox, QCheckBox, QSplitter, QComboBox,
                           QWidget, QLineEdit, QFileDialog, QSpinBox,
                           QDoubleSpinBox, QFileSystemModel, QTreeView)
from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal, QDateTime, QTimer, QDir, QItemSelectionModel, QModelIndex
import os
from pathlib import Path
import logging
from datetime import datetime
import numpy as np
import configparser
import json

from core.psd import PSDCalculator
from core.plugin_manager import PluginManager
from utils.config import config
from utils.window_utils import set_dialog_size, center_dialog
from utils.constants import DEFAULT_OUTPUT_FOLDER, PSD_FILE_SUFFIX, PSD_FOLDER_NAME

logger = logging.getLogger(__name__)

class PSDProcessingWorker(QObject):
    """Worker for processing files in a separate thread."""
    
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self):
        """Initialize worker."""
        super().__init__()
        self.file_list = []
        self.sampling_rate = 0
        self.filter_enabled = False
        self.filter_type = "High Pass"
        self.filter_freq = 0.1
        self.low_freq = 1
        self.high_freq = 20
        self.response_enabled = False
        self.natural_period = 10
        self.damping = 0
        self.sensitivity = 0
        self.window_size = 1000
        self.overlap = 0.8
        self.window_type = "hann"
        self.psd_freq_min = 0.001
        self.psd_freq_max = 100
        self.project_dir = None
        self.instrument_type = 0
        
        # Initialize plugin manager
        self.plugin_manager = PluginManager()
        self.readers = self.plugin_manager.get_available_readers()
        
    def run(self):
        """Process all files in the list."""
        total_files = len(self.file_list)
        if total_files == 0:
            logger.warning("No files to process")
            self.error.emit("No files to process")
            self.finished.emit()
            return
            
        try:
            for i, filename in enumerate(self.file_list):
                try:
                    self.process_file(filename)
                    progress = int((i + 1) / total_files * 100)
                    self.progress.emit(progress)
                except Exception as e:
                    logger.error(f"Error processing file {filename}: {e}")
                        # Continue with next file instead of stopping
                
            self.progress.emit(100)
            self.finished.emit()
        except Exception as e:
            logger.error(f"Error in PSD processing: {e}")
            self.error.emit(str(e))
        self.finished.emit()
        
    def process_file(self, file_name):
        """Process a single file."""
        logger.info(f"Processing file: {file_name}")
        
        try:
            # Get file extension and reader
            ext = Path(file_name).suffix.lower()
            reader_class = self.readers.get(ext)
            if not reader_class:
                raise ValueError(f"Unsupported file format: {ext}")
                
            reader = reader_class()
            data = reader.read(file_name)
            
            # Check if data is an ObsPy Stream
            if hasattr(data, 'traces') and len(data) > 0:
                # Get the first trace's data
                trace = data[0]
                data_array = trace.data
                sample_rate = trace.stats.sampling_rate
            else:
                raise ValueError("Invalid data format: expected ObsPy Stream with at least one trace")
            
            # Calculate PSD
            calculator = PSDCalculator(
                sample_rate=float(sample_rate),
                sensitivity=float(self.sensitivity),
                instrument_type=self.instrument_type,
                damping_ratio=float(self.damping),
                natural_period=float(self.natural_period)
            )
            
            # Configure calculator
            calculator.filter_enabled = self.filter_enabled
            calculator.response_removal_enabled = self.response_enabled
            
            if calculator.filter_enabled:
                calculator.filter_type = self.filter_type
                if calculator.filter_type == "High Pass":
                    calculator.cutoff_freq = self.filter_freq
                else:  # Band Pass
                    calculator.cutoff_freq = (self.low_freq, self.high_freq)
                    
            # Configure window parameters
            calculator.window_size = self.window_size
            calculator.overlap = self.overlap
            calculator.window_type = self.window_type
            
            # Configure PSD frequency range
            calculator.psd_freq_min = self.psd_freq_min
            calculator.psd_freq_max = self.psd_freq_max
            
            # Calculate PSD and smoothed PSD
            calculator.calculate_psd(data_array)
            
            # Create output directory
            out_dir = Path(file_name).parent / PSD_FOLDER_NAME
            out_dir.mkdir(parents=True, exist_ok=True)
            
            # Save PSD data to file
            out_file = out_dir / f"{Path(file_name).stem}{PSD_FILE_SUFFIX}"
            
            # Save PSD data to file
            np.savez(
                out_file,
                frequencies=calculator.frequencies,
                psd=calculator.psd,
                f_smoothed=calculator.smoothed_frequencies,
                smoothed_psd=calculator.smoothed_psd,
                psd_distribution=calculator.psd_distribution,
                psd_db_range=calculator.PSD_DB_RANGE[:-1],  # Save the bin centers
                metadata={
                    'filter_enabled': calculator.filter_enabled,
                    'filter_type': calculator.filter_type,
                    'cutoff_freq': calculator.cutoff_freq,
                    'response_removal_enabled': calculator.response_removal_enabled,
                    'window_size': calculator.window_size,
                    'overlap': calculator.overlap,
                    'window_type': calculator.window_type,
                    'psd_freq_min': calculator.psd_freq_min,
                    'psd_freq_max': calculator.psd_freq_max
                }
            )
            
            logger.info(f"Saved PSD data to {out_file}")
            
        except Exception as e:
            logger.error(f"Error processing file {file_name}: {e}")
            raise

class PSDCalculationDialog(QDialog):
    """Dialog for calculating Power Spectral Density."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog."""
        super().__init__(parent)
       
        self.project_dir = project_dir
            
        self.worker = None
        self.thread = None
        
        # instrument info
        self.instrument_info = None
        # Initialize data attributes
        self.sampling_rate = None
        # filter
        self.filter_enabled = False
        self.filter_type = "High Pass"
        self.filter_freq = 0.1
        self.low_freq = 0.1 
        self.high_freq = 40

        # instrument response
        self.response_enabled = False

        # instrument 
        self.natural_period = 1.0
        self.damping = 0.707
        self.sensitivity = 2000.0

        # welch
        self.window_size = 1000
        self.window_type = 'hann'
        self.overlap = 0.8

        # psd range
        self.psd_freq_min = 0.01
        self.psd_freq_max = 40
        
        # Store station and component data
        self.stations = {}
        self.selected_files = []
        
        self._init_ui()
        self.load_psd_info()
        self._load_config_path()
        self.scan_stations()
        
    def _init_ui(self):
        """Initialize UI components."""
        self.setWindowTitle("Calculate PSD")
        
        # Set dialog size to 70% of screen size
        set_dialog_size(self, 0.7, 0.7)
        center_dialog(self)
        
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
        
        # Time range selection
        time_group = QGroupBox("Time Range")
        time_layout = QVBoxLayout()
        
        # Global time range
        global_time_layout = QHBoxLayout()
        global_time_layout.addWidget(QLabel("Global Time Range:"))
            
            # Start time
        self.start_time = QDateTimeEdit()
        self.start_time.setCalendarPopup(True)
        self.start_time.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_time.setDateTime(QDateTime.currentDateTime().addDays(-7))
        global_time_layout.addWidget(self.start_time)
            
            # End time
        self.end_time = QDateTimeEdit()
        self.end_time.setCalendarPopup(True)
        self.end_time.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_time.setDateTime(QDateTime.currentDateTime())
        global_time_layout.addWidget(self.end_time)
        
        time_layout.addLayout(global_time_layout)
        
        # Scan files button (replacing Apply Time button)
        self.scan_button = QPushButton("Scan Files")
        self.scan_button.clicked.connect(self.scan_files)
        time_layout.addWidget(self.scan_button)
        
        time_group.setLayout(time_layout)
        left_panel.addWidget(time_group)
        
        # Right panel - PSD parameters and processing
        right_panel = QVBoxLayout()
        
        # PSD parameters
        params_group = QGroupBox("PSD Parameters")
        params_layout = QVBoxLayout()
        
        # Parameters info
        self.info_text = QPlainTextEdit()
        self.info_text.setReadOnly(True)
        params_layout.addWidget(self.info_text)
        
        params_group.setLayout(params_layout)
        right_panel.addWidget(params_group)
        
        # File count
        self.file_count_label = QLabel("Selected Files: 0")
        right_panel.addWidget(self.file_count_label)
        
        # Progress bar
        self.progress = QProgressBar()
        right_panel.addWidget(self.progress)
        
        # Start button
        self.start_button = QPushButton("Start Processing")
        self.start_button.clicked.connect(self.start_processing)
        self.start_button.setEnabled(False)
        right_panel.addWidget(self.start_button)
        
        # Config file selection
        config_group = QGroupBox("Configuration")
        config_layout = QHBoxLayout()
        
        self.config_path = QLineEdit()
        self.config_path.setReadOnly(True)
        self.config_path.setPlaceholderText("Select PSD configuration file...")
        
        select_config_btn = QPushButton("Select Config")
        select_config_btn.clicked.connect(self._select_config)
        
        config_layout.addWidget(self.config_path)
        config_layout.addWidget(select_config_btn)
        config_group.setLayout(config_layout)
        right_panel.addWidget(config_group)
        
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
                
                # Get output folder from project parameters
                output_folder = self.project_data.get('data_params', {}).get('outputFolder', DEFAULT_OUTPUT_FOLDER)
                
            except Exception as e:
                logger.warning(f"Error reading data.json, using basic structure: {e}")
                output_folder = DEFAULT_OUTPUT_FOLDER  # Default value
                self.project_data = {'data_params': {'outputFolder': output_folder}}
            
            # Construct the output directory path
            output_dir = Path(self.project_dir) / output_folder
            
            if not output_dir.exists():
                logger.warning(f"Output directory {output_dir} does not exist")
                return

            # Clear the tree widget
            self.station_tree.clear()
            
            # Create a dictionary to store the folder structure
            folder_structure = {}
            
            # First pass: build the folder structure by scanning directories only
            for root, dirs, _ in os.walk(output_dir):
                # Skip PSD folders
                if os.path.basename(root) == PSD_FOLDER_NAME:
                    continue
                    
                # Remove PSD directories from dirs to prevent them from being traversed
                if PSD_FOLDER_NAME in dirs:
                    dirs.remove(PSD_FOLDER_NAME)
                    
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
                print(f"Added top-level item: {folder_name}")
            else:
                parent_item.addChild(item)
                parent_path = self._get_item_path(parent_item)
                print(f"Added child item: {folder_name} under {parent_path}")
            
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
                logger.debug(f"Found leaf node: {component}")
            else:
                # Process children
                for i in range(item.childCount()):
                    find_leaf_nodes(item.child(i))
        
        # Process all top-level items
        root = self.station_tree.invisibleRootItem()
        for i in range(root.childCount()):
            find_leaf_nodes(root.child(i))
            
        logger.debug("End nodes found:")
        for component, items in self.end_nodes.items():
            logger.debug(f"{component}: {len(items)} items")
    
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
        
        # Scan files after selection change
        self.scan_files()
        
    def _deselect_all_components(self):
        """Deselect all components."""
        # Get all top-level items
        root = self.station_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, Qt.Unchecked)
        
        # Scan files after selection change
        self.scan_files()
        
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
        
        # Scan files after selection change
        self.scan_files()
    
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
        logger.debug("Syncing component checkboxes")
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
                    logger.debug(f"Component {component}: All checked")
                    self.component_checkboxes[component].setCheckState(Qt.Checked)
                elif any_checked:
                    logger.debug(f"Component {component}: Partially checked")
                    self.component_checkboxes[component].setCheckState(Qt.PartiallyChecked)
                else:
                    logger.debug(f"Component {component}: None checked")
                    self.component_checkboxes[component].setCheckState(Qt.Unchecked)
        
        # Unblock signals
        for checkbox in self.component_checkboxes.values():
            checkbox.blockSignals(False)
    
    def _get_checked_paths(self):
        """Get all checked paths from the tree."""
        checked_paths = []
        logger.debug("Getting checked paths from end nodes:")
        
        # Process all end nodes (components)
        for component, items in self.end_nodes.items():
            logger.debug(f"  Checking component: {component} with {len(items)} items")
            for item in items:
                # Only include checked or partially checked items
                check_state = item.checkState(0)
                if check_state != Qt.Unchecked:
                    logger.debug(f"    Item {item.text(0)} is checked ({check_state})")
                    # Build path by traversing backwards from leaf to root
                    path = self._build_path_from_item(item)
                    if path:
                        checked_paths.append(path)
                        logger.debug(f"    Added path: {path}")
                else:
                    logger.debug(f"    Item {item.text(0)} is unchecked")
        
        logger.debug(f"Total checked paths: {len(checked_paths)}")
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
            full_path = os.path.join(*path_parts)
            logger.debug(f"    Built path: {full_path} from parts: {path_parts}")
            return full_path
        return ""
    
    def scan_files(self):
        """Scan for files in checked directories within the time range."""
        self.selected_files = []
        logger.debug("scan_files")
        
        try:
            # Get global time range
            start_time = self.start_time.dateTime().toPyDateTime()
            end_time = self.end_time.dateTime().toPyDateTime()
            
            # Get output folder from project data
            output_folder = self.project_data['data_params'].get('outputFolder', DEFAULT_OUTPUT_FOLDER)
            output_dir = Path(self.project_dir) / output_folder
            logger.debug(f"Output directory: {output_dir}")
            
            # Get checked paths from the tree
            checked_paths = self._get_checked_paths()
            logger.debug(f"Checked paths ({len(checked_paths)}):")
            for path in checked_paths:
                logger.debug(f"  - {path}")
            
            # Process files in checked directories
            for rel_path in checked_paths:
                # Convert to Path object for reliable path joining
                rel_path_obj = Path(rel_path)
                dir_path = output_dir / rel_path_obj
                logger.debug(f"Checking directory: {dir_path}")
                
                # Skip if directory doesn't exist
                if not dir_path.exists():
                    logger.debug(f"Directory does not exist: {dir_path}")
                    continue
                    
                # Find all files in this directory
                try:
                    files = os.listdir(dir_path)
                    logger.debug(f"Found {len(files)} files in {dir_path}")
                    
                    for file in files:
                        file_path = dir_path / file
                        
                        # Skip directories and PSD folders
                        if os.path.isdir(file_path):
                            continue
                        
                        # Check if file matches our format (Station.Component.Datetime)
                        parts = file.split('.')
                        if len(parts) >= 3:
                            # Extract datetime from filename
                            dt_str = parts[2]  # Datetime is the third part
                            try:
                                dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                                if start_time <= dt <= end_time:
                                    self.selected_files.append(str(file_path))
                                    logger.debug(f"Added file: {file_path}")
                            except ValueError:
                                # Skip files with invalid datetime format
                                logger.debug(f"Invalid datetime format: {file}")
                                continue
                except Exception as e:
                    logger.debug(f"Error listing directory {dir_path}: {e}")
                                
            # Update file count
            self.file_count_label.setText(f"Selected Files: {len(self.selected_files)}")
            logger.debug(f"Total selected files: {len(self.selected_files)}")
            
            # Enable start button if files are selected
            self.start_button.setEnabled(len(self.selected_files) > 0)
            
        except Exception as e:
            logger.error(f"Error scanning files: {e}")
            logger.debug(f"Error: {e}")
            QMessageBox.critical(self, "Error", f"Error scanning files: {str(e)}")

    def _select_component_for_all(self, component, state):
        """Select all directories with the given component."""
        try:
            logger.debug(f"Selecting component {component}, state={state}")
            # Block signals to prevent recursive updates
            self.station_tree.blockSignals(True)
            
            # Update all tree items for this component
            if component in self.end_nodes:
                logger.debug(f"Found {len(self.end_nodes[component])} items for component {component}")
                for item in self.end_nodes[component]:
                    logger.debug(f"Setting {self._build_path_from_item(item)} to {'checked' if state else 'unchecked'}")
                    item.setCheckState(0, Qt.Checked if state else Qt.Unchecked)
                    
                    # Update parent check states
                    parent = item.parent()
                    while parent:
                        self._update_parent_check_state(parent)
                        parent = parent.parent()
            else:
                logger.debug(f"Component {component} not found in end_nodes")
            
            # Unblock signals
            self.station_tree.blockSignals(False)
            
            # Scan files after selection change
            self.scan_files()
            
        except Exception as e:
            logger.error(f"Error selecting component {component}: {e}")
            logger.debug(f"Error selecting component {component}: {e}")
            QMessageBox.critical(self, "Error", f"Error selecting component {component}: {str(e)}")

    def start_processing(self):
        """Start processing files."""
        if not self.selected_files:
            logger.warning("No files selected")
            QMessageBox.warning(
                self,
                "Warning",
                "No files selected for processing"
            )
            return
            
        # Create worker and thread
        self.thread = QThread()
        self.worker = PSDProcessingWorker()
        
        # Set worker parameters
        self.worker.file_list = self.selected_files

        # instrument parameters
        self.worker.natural_period = self.natural_period
        self.worker.damping = self.damping
        self.worker.sensitivity = self.sensitivity
        self.worker.instrument_type = self.instrument_type
        self.worker.sampling_rate = self.sampling_rate
        # filter parameters
        self.worker.filter_enabled = self.filter_enabled
        self.worker.filter_type = self.filter_type
        if self.filter_type == "High Pass":
            self.worker.filter_freq = self.filter_freq
        else:  # Band Pass
            self.worker.high_freq = self.high_freq
            self.worker.low_freq = self.low_freq
        # instrument response
        self.worker.response_enabled = self.response_enabled
        # PSD welch parameters
        self.worker.window_size = self.window_size
        self.worker.window_type = self.window_type
        self.worker.overlap =  self.overlap
        # PSD frequency range
        self.worker.psd_freq_min = self.psd_freq_min
        self.worker.psd_freq_max = self.psd_freq_max
        
        # Ensure project_dir is a string path
        project_path = str(self.project_dir)
        self.worker.project_dir = project_path
        
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
        self.scan_button.setEnabled(False)
        self.station_tree.setEnabled(False)
        self.start_time.setEnabled(False)
        self.end_time.setEnabled(False)
            
        # Start processing
        self.thread.start()
        
    def _on_processing_finished(self):
        """Handle processing completion."""
        # Re-enable UI
        self.start_button.setEnabled(True)
        self.scan_button.setEnabled(True)
        self.station_tree.setEnabled(True)
        self.start_time.setEnabled(True)
        self.end_time.setEnabled(True)
        
        # Show completion message
        QMessageBox.information(
            self,
            "Complete",
            f"PSD calculation complete. Processed {len(self.selected_files)} files."
        )
        
    def _show_error(self, message):
        """Show error message."""
        QMessageBox.critical(self, "Error", message)

    def _load_config_path(self):
        """Load last used config path from config.ini."""
        try:
            config = configparser.ConfigParser()
            config.read('config.ini')
            
            if 'PSD' in config and 'config_file' in config['PSD']:
                path = Path(config['PSD']['config_file'])
                if path.exists():
                    self.config_path.setText(str(path))
                    self._load_config(path)
        except Exception as e:
            logger.error(f"Error loading config path: {e}")

    def _save_config_path(self, path):
        """Save config path to config.ini."""
        try:
            config = configparser.ConfigParser()
            config.read('config.ini')
            
            if 'PSD' not in config:
                config['PSD'] = {}
            
            config['PSD']['config_file'] = str(path)
            
            with open('config.ini', 'w') as f:
                config.write(f)
        except Exception as e:
            logger.error(f"Error saving config path: {e}")

    def _select_config(self):
        """Open file dialog to select config file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PSD Configuration File",
            "",
            "JSON Files (*.json)"
        )
        
        if file_path:
            path = Path(file_path)
            self.config_path.setText(str(path))
            self._save_config_path(path)
            self._load_config_path()

    def _load_config(self, path):
        """Load configuration from file."""
        try:
            with open(path) as f:
                config = json.load(f)
                
            # Load filter settings
            self.filter_enabled = config.get('filter_enabled', False)
            self.filter_type = config.get('filter_type', 'High Pass')
            
            # Handle filter frequencies based on type
            filter_freq = config.get('filter_freq', 0.1)
            if isinstance(filter_freq, (list, tuple)):
                self.low_freq = float(filter_freq[0])
                self.high_freq = float(filter_freq[1])
            else:
                self.filter_freq = float(filter_freq)
            
            # Load response settings
            self.response_enabled = config.get('response_enabled', False)
            
            # Load window settings
            self.window_size = float(config.get('window_size', 1000))
            self.overlap = float(config.get('overlap', 80))/100
            self.window_type = config.get('window_type', 'hann')
            
            # Load frequency range
            self.psd_freq_min = float(config.get('psd_freq_min', 1))
            self.psd_freq_max = float(config.get('psd_freq_max', 20))
            
            # Update info text with loaded configuration
            self._update_info_text(self.instrument_info)
            
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load configuration: {e}")

    def _update_ui_from_config(self):
        """Update UI elements with loaded configuration."""
        # Update filter UI
        self.filter_checkbox.setChecked(self.filter_enabled)
        self.filter_type_combo.setCurrentText(self.filter_type)
        self.filter_freq_spin.setValue(self.filter_freq)
        
        # Update response UI
        self.response_checkbox.setChecked(self.response_enabled)
        self.natural_period_spin.setValue(self.natural_period)
        self.damping_spin.setValue(self.damping)
        self.sensitivity_spin.setValue(self.sensitivity)
        
        # Update window UI
        self.window_size_spin.setValue(self.window_size)
        self.overlap_spin.setValue(self.overlap)
        self.window_type_combo.setCurrentText(self.window_type)
        
        # Update frequency range UI
        self.freq_min_spin.setValue(self.psd_freq_min)
        self.freq_max_spin.setValue(self.psd_freq_max)

    def load_psd_info(self):
        """Load instrument information from data.json."""
        try:
            data_file = Path(self.project_dir) / 'data.json'
            if not data_file.exists():
                self._update_info_text()
                return
                
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Get instrument parameters
            params = data.get('data_params', {})
            self.sensitivity = params.get('wholeSensitivity', 'Unknown')
            self.instrument_type = params.get('instrumentType', 0)
            self.damping = params.get('damp', 'Unknown')
            self.natural_period = params.get('naturalPeriod', 'Unknown')
            
            # Build info text
            info = []
            info.append("Instrument Parameters:")
            if self.instrument_type == 0:
                info.append(f"Whole Sensitivity: {self.sensitivity} count/(m/s)")
            elif self.instrument_type == 1:
                info.append(f"Whole Sensitivity: {self.sensitivity} count/(m/s^2)")
            info.append(f"Damping Ratio: {self.damping}")
            info.append(f"Natural Period: {self.natural_period} s")
            
            # Add poles and zeros if available
            if 'poles' in params and 'zeros' in params:
                info.append("\nPoles and Zeros:")
                info.append(f"poles = {params['poles']}")
                info.append(f"zeros = {params['zeros']}")
            elif 'transfer_function' in params:
                tf = params['transfer_function']
                info.append("\nTransfer Function:")
                info.append(f"numerator = {tf.get('numerator', [])}")
                info.append(f"denominator = {tf.get('denominator', [])}")
            else:
                info.append("\nNote: Instrument response will use theoretical transfer function")
            self.instrument_info = info
            self._update_info_text(info)
            
        except Exception as e:
            logger.error(f"Error loading PSD info: {e}")
            self._update_info_text(["Failed to load instrument information"])

    def _update_info_text(self, instrument_info=None):
        """Update info text with current parameters."""
        info = []
        
        # Add instrument info if provided
        if instrument_info:
            info.extend(instrument_info)
        
        # Add PSD configuration info
        info.append("\nPSD Configuration:")
        info.append(f"Filter Enabled: {self.filter_enabled}")
        info.append(f"Filter Type: {self.filter_type}")
        
        # Show filter frequency based on type
        if self.filter_type == "Band Pass":
            info.append(f"Low Frequency: {self.low_freq} Hz")
            info.append(f"High Frequency: {self.high_freq} Hz")
        else:
            info.append(f"Filter Frequency: {self.filter_freq} Hz")
        
        info.append(f"\nResponse Removal: {self.response_enabled}")
        
        info.append("\nWindow Parameters:")
        info.append(f"Window Size: {self.window_size} s")
        info.append(f"Overlap: {self.overlap}%")
        info.append(f"Window Type: {self.window_type}")
        
        info.append("\nFrequency Range:")
        info.append(f"Minimum: {self.psd_freq_min} Hz")
        info.append(f"Maximum: {self.psd_freq_max} Hz")
        
        self.info_text.setPlainText('\n'.join(info))