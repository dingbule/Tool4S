"""
Dialog for viewing and analyzing Power Spectral Density (PSD) data.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                           QLabel, QTreeWidget, QTreeWidgetItem, QCheckBox,
                           QPushButton, QDateTimeEdit, QSplitter, QWidget,
                           QTextEdit, QMessageBox, QComboBox, QToolBar, QAction,
                           QFileDialog, QProgressBar, QSizePolicy, QLineEdit)
from PyQt5.QtCore import Qt, QDateTime, QThread, pyqtSignal
from PyQt5.QtGui import QIcon
import numpy as np
import os
from pathlib import Path
import logging
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import json
import matplotlib.gridspec as gridspec

from utils.window_utils import set_dialog_size, center_dialog
from utils.constants import DEFAULT_OUTPUT_FOLDER, PSD_FOLDER_NAME, PSD_FILE_SUFFIX

logger = logging.getLogger(__name__)

class PSDLoadingWorker(QThread):
    """Worker thread for loading PSD data."""
    
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # current, total
    data_ready = pyqtSignal(dict)
    
    def __init__(self, files, plot_type):
        """Initialize worker."""
        super().__init__()
        self.files = files  # Dictionary of {group_path: [file_paths]}
        self.plot_type = plot_type
        
    def run(self):
        """Load PSD data in separate thread."""
        try:
            # Container for loaded data by group
            result_data = {
                'groups': {}  # Will contain data for each group
            }
            
            if not self.files:
                self.error.emit("No files to process")
                return
                
            # Total file count for progress tracking
            total_files = sum(len(files) for files in self.files.values())
            processed_files = 0
            
            # Process each group
            for group_path, group_files in self.files.items():
                if not group_files:
                    continue
                    
                # Initialize data structure for this group
                group_data = {
                    'total_distribution': None,
                    'smoothed_frequencies': None,
                    'psd_db_range': None,
                    'probability_distribution': None,
                    'file_times': [],
                    'times': [],
                    'psd_values': [],
                    'group_name': group_path
                }
                
                # Load first file to get dimensions
                try:
                    data = np.load(group_files[0])
                    if 'f_smoothed' in data:
                        group_data['smoothed_frequencies'] = data['f_smoothed']
                    elif 'frequencies' in data:
                        group_data['smoothed_frequencies'] = data['frequencies']
                    
                    # Load data based on plot type
                    if self.plot_type == "PDF":
                        self._load_pdf_data(group_files, group_data)
                    elif self.plot_type == "PSD":
                        self._load_psd_line_data(group_files, group_data)
                    else:
                        self._load_timefreq_data(group_files, group_data)
                    
                    # Add this group's data to the result
                    result_data['groups'][group_path] = group_data
                
                except Exception as e:
                    logger.error(f"Error processing group {group_path}: {e}")
                
                # Update progress (count all files in this group as processed)
                processed_files += len(group_files)
                self.progress.emit(processed_files, total_files)
            
            # Emit results
            self.data_ready.emit(result_data)
            
        except Exception as e:
            logger.error(f"Error in PSD loading worker: {e}")
            self.error.emit(str(e))
            
        self.finished.emit()
        
    def _load_pdf_data(self, files, group_data):
        """Load data for PDF plot for a group of files."""
        if not files:
            return
            
        # Get dimensions from first file
        data = np.load(files[0])
        if 'psd_distribution' not in data:
            raise ValueError(f"Required 'psd_distribution' data not found in {files[0]}")
            
        psd_distribution = data['psd_distribution']
        group_data['psd_db_range'] = data['psd_db_range']
        
        # Initialize total distribution
        total_distribution = np.zeros_like(psd_distribution, dtype=float)
        
        # Load and sum all distributions
        for file in files:
            try:
                data = np.load(file)
                total_distribution += data['psd_distribution']
                
                # Get file time for info
                self._extract_file_time(file, group_data)
            except Exception as e:
                logger.warning(f"Error loading file {file}: {e}")
        
        # Calculate probabilities
        # Sum across dB bins to get total counts for each frequency
        total_counts = total_distribution.sum(axis=1, keepdims=True)
        # Avoid division by zero
        total_counts[total_counts == 0] = 1
        group_data['probability_distribution'] = total_distribution / total_counts
        group_data['total_distribution'] = total_distribution
        
    def _load_psd_line_data(self, files, group_data):
        """Load data for PSD line plot for a group of files."""
        if not files:
            return
            
        file_data = []
        frequencies = None
        
        # Use group_length from attribute, defaulting to 1 if not available
        group_length_hours = getattr(self, 'group_length', 1)
        
        # Load all PSD files in this group
        for file in files:
            try:
                # Load PSD data
                data = np.load(file)
                
                # Get frequencies from first file
                if frequencies is None:
                    if 'frequencies' in data:
                        frequencies = data['frequencies']
                    elif 'f_smoothed' in data:
                        frequencies = data['f_smoothed']
                    else:
                        # If no frequency data, create a default range
                        psd_data = data.get('psd', data.get('smoothed_psd'))
                        if psd_data is not None:
                            frequencies = np.logspace(-3, 2, len(psd_data))
                        else:
                            raise ValueError(f"No PSD or frequency data found in {file}")
                
                # Get PSD data - prioritize raw PSD over smoothed
                if 'psd' in data:
                    psd_data = data['psd']
                elif 'smoothed_psd' in data:
                    psd_data = data['smoothed_psd']
                else:
                    logger.warning(f"No PSD data found in {file}")
                    continue
                
                # Ensure PSD data has the same length as frequencies
                if len(psd_data) != len(frequencies):
                    logger.warning(f"PSD data length ({len(psd_data)}) doesn't match frequency length ({len(frequencies)}) in {file}")
                    # Resize PSD data to match frequencies if possible
                    if len(psd_data) > len(frequencies):
                        psd_data = psd_data[:len(frequencies)]
                    else:
                        # Pad with zeros or interpolate
                        psd_data = np.pad(psd_data, (0, len(frequencies) - len(psd_data)), mode='constant')
                
                # Extract time from filename
                file_time = self._extract_file_time(file, group_data)
                
                if file_time:
                    file_data.append({
                        'file': file,
                        'time': file_time,
                        'psd': psd_data
                    })
                
            except Exception as e:
                logger.warning(f"Error loading file {file}: {e}")
                continue
        
        if not file_data:
            logger.warning(f"No valid PSD data found for line plot in group")
            return
            
        # Sort files by time
        file_data.sort(key=lambda x: x['time'])
        
        # Group files by time periods if group_length > 1
        grouped_data = []
        if group_length_hours > 1:
            groups = {}
            for item in file_data:
                # Calculate group start time (rounded to nearest group_length_hours)
                group_time = item['time'].replace(
                    hour=item['time'].hour - (item['time'].hour % group_length_hours),
                    minute=0,
                    second=0,
                    microsecond=0
                )
                
                # Add to group or create new group
                if group_time in groups:
                    groups[group_time]['psds'].append(item['psd'])
                else:
                    groups[group_time] = {
                        'time': group_time,
                        'psds': [item['psd']]
                    }
            
            # Calculate average PSD for each group
            for group_time, group in groups.items():
                if group['psds']:
                    # Calculate average PSD for this group
                    avg_psd = np.mean(group['psds'], axis=0)
                    
                    # Format time for legend
                    time_str = group_time.strftime('%Y-%m-%d %H:%M')
                    
                    grouped_data.append({
                        'time': group_time,
                        'psd': avg_psd,
                        'label': time_str
                    })
        else:
            # No grouping, just use individual files
            for item in file_data:
                time_str = item['time'].strftime('%Y-%m-%d %H:%M')
                grouped_data.append({
                    'time': item['time'],
                    'psd': item['psd'],
                    'label': time_str
                })
        
        # Sort the final grouped data by time
        grouped_data.sort(key=lambda x: x['time'])
        
        # Store the processed data
        group_data['psd_lines'] = [item['psd'] for item in grouped_data]
        group_data['file_names'] = [item['label'] for item in grouped_data]
        group_data['frequencies'] = frequencies
        
    def _load_timefreq_data(self, files, group_data):
        """Load data for time-frequency plot for a group of files."""
        if not files:
            return
            
        times = []
        psd_values = []
        
        # Load all PSD files in this group
        for file in files:
            try:
                # Extract datetime from filename and store
                dt = self._extract_file_time(file, group_data)
                if dt:
                    times.append(dt)
                    
                    # Load PSD data
                    data = np.load(file)
                    if 'smoothed_psd' in data:
                        psd_values.append(data['smoothed_psd'])
                    elif 'psd' in data:
                        psd_values.append(data['psd'])
                    else:
                        logger.warning(f"No PSD data found in {file}")
                        continue
            except Exception as e:
                logger.warning(f"Error processing file {file}: {e}")
                continue
        
        if not times or not psd_values:
            logger.warning(f"No valid PSD data found for time-frequency plot in group")
            return
            
        # Convert to numpy arrays
        times_array = np.array(times)
        psd_values_array = np.array(psd_values)
        
        # Sort by time
        sort_idx = np.argsort(times_array)
        group_data['times'] = times_array[sort_idx]
        group_data['psd_values'] = psd_values_array[sort_idx]
        
    def _extract_file_time(self, file, group_data):
        """Extract time from file name and add to file_times list."""
        try:
            file_name = Path(file).name
            parts = file_name.split('.')
            if len(parts) >= 3:
                dt_str = parts[2].split('_')[0]
                dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                group_data['file_times'].append(dt)
                return dt
        except Exception as e:
            logger.debug(f"Could not extract time from file {file}: {e}")
        return None

class PSDPDFDialog(QDialog):
    """Dialog for viewing PSD Probability Density Functions and Time-Frequency plots."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog."""
        super().__init__(parent)
        self.project_dir = project_dir
        self.stations = {}
        self.selected_files = {}  # Changed to dictionary to store groups of files by path
        self.plot_type = "PDF"  # Default plot type
        self.colormap = "viridis"  # Default colormap
        self.group_length = 1  # Default group length in hours
        self.loading_worker = None
        
        # Pagination and grid variables
        self.current_page = 1
        self.total_pages = 1
        self.rows = 2  # Default grid rows
        self.cols = 3  # Default grid columns
        self.max_plots_per_page = 6  # Default max plots per page (rows * cols)
        self.current_plot_data = None  # Store the current plot data for pagination
        
        self._init_ui()
        
        # Set dialog size and center it
        set_dialog_size(self, 0.8, 0.8)
        center_dialog(self)
        
        self.scan_stations()
        
    def _init_ui(self):
        """Initialize UI components."""
        self.setWindowTitle("PSD Analysis")
        
        # Create main layout
        main_layout = QHBoxLayout(self)
        
        # Create main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Create left panel with scroll area
        left_panel = QWidget()
        left_panel.setMaximumWidth(350)  # Limit max width
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Station selection
        station_group = QGroupBox("Stations and Components")
        station_layout = QVBoxLayout()
        station_layout.setContentsMargins(5, 5, 5, 5)
        
        # Station tree widget
        self.station_tree = QTreeWidget()
        self.station_tree.setHeaderLabels(["Station/Component", "Select"])
        self.station_tree.setColumnCount(2)
        self.station_tree.setColumnWidth(0, 200)
        self.station_tree.itemChanged.connect(self._on_item_changed)
        
        # Component selection checkboxes
        self.component_group = QGroupBox("Select Component for All Stations")
        self.component_layout = QHBoxLayout()
        self.component_group.setLayout(self.component_layout)
        
        # Dictionary to store component checkboxes
        self.component_checkboxes = {}
        
        # Select all buttons
        select_all_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self._select_all_components)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self._deselect_all_components)
        select_all_layout.addWidget(self.select_all_btn)
        select_all_layout.addWidget(self.deselect_all_btn)
        
        station_layout.addWidget(self.station_tree)
        station_layout.addLayout(select_all_layout)
        station_layout.addWidget(self.component_group)
        station_group.setLayout(station_layout)
        
        # Time range selection
        time_group = QGroupBox("Time Range")
        time_layout = QVBoxLayout()
        time_layout.setContentsMargins(5, 5, 5, 5)
        
        # Global time range
        global_time_layout = QHBoxLayout()
        global_time_layout.addWidget(QLabel("Time Range:"))
        
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
        time_group.setLayout(time_layout)
        
        left_layout.addWidget(station_group)
        left_layout.addWidget(time_group)
        
        # Create central plotting area
        plot_panel = QWidget()
        plot_layout = QVBoxLayout(plot_panel)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        
        # Add matplotlib figure
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        
        # Add navigation toolbar
        self.toolbar = NavigationToolbar(self.canvas, plot_panel)
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas)
        
        # Add pagination controls
        pagination_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton("< Previous")
        self.prev_page_btn.clicked.connect(self._on_prev_page)
        self.prev_page_btn.setEnabled(False)
        
        self.page_indicator = QLabel("Page 1 of 1")
        self.page_indicator.setAlignment(Qt.AlignCenter)
        
        self.next_page_btn = QPushButton("Next >")
        self.next_page_btn.clicked.connect(self._on_next_page)
        self.next_page_btn.setEnabled(False)
        
        pagination_layout.addWidget(self.prev_page_btn)
        pagination_layout.addWidget(self.page_indicator)
        pagination_layout.addWidget(self.next_page_btn)
        
        plot_layout.addLayout(pagination_layout)
        
        # Add progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        plot_layout.addWidget(self.progress_bar)
        
        # Create right panel
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Plot type selection
        plot_type_group = QGroupBox("Plot Type")
        plot_type_layout = QHBoxLayout()
        plot_type_layout.setContentsMargins(5, 5, 5, 5)
        
        self.plot_type_combo = QComboBox()
        self.plot_type_combo.addItems(["PDF", "PSD", "PSD Time-Frequency"])
        self.plot_type_combo.currentTextChanged.connect(self._on_plot_type_changed)
        plot_type_layout.addWidget(QLabel("Plot Type:"))
        plot_type_layout.addWidget(self.plot_type_combo)
        
        # Visualization options
        vis_options_group = QGroupBox("Visualization Options")
        vis_options_layout = QVBoxLayout()
        vis_options_layout.setContentsMargins(5, 5, 5, 5)
        
        # Colormap selection
        colormap_layout = QHBoxLayout()
        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(["viridis", "plasma", "inferno", "magma", "cividis", 
                                    "jet", "rainbow", "coolwarm", "seismic", "terrain"])
        colormap_label = QLabel("Colormap:")
        colormap_label.setObjectName("colormap_label")
        colormap_layout.addWidget(colormap_label)
        colormap_layout.addWidget(self.colormap_combo)
        self.colormap_combo.currentTextChanged.connect(self._on_colormap_changed)
        
        # Grid layout selection
        grid_layout = QHBoxLayout()
        grid_layout.addWidget(QLabel("Grid:"))
        
        # Row selection
        self.row_combo = QComboBox()
        self.row_combo.addItems(["1", "2", "3", "4"])
        self.row_combo.setCurrentText("2")
        self.row_combo.currentTextChanged.connect(self._on_grid_changed)
        
        # Column selection
        self.col_combo = QComboBox()
        self.col_combo.addItems(["1", "2", "3", "4"])
        self.col_combo.setCurrentText("3")
        self.col_combo.currentTextChanged.connect(self._on_grid_changed)
        
        grid_layout.addWidget(QLabel("Rows:"))
        grid_layout.addWidget(self.row_combo)
        grid_layout.addWidget(QLabel("Cols:"))
        grid_layout.addWidget(self.col_combo)
        
        # Group length selection (for PSD plot type)
        group_length_layout = QHBoxLayout()
        self.group_length_label = QLabel("Group Length:")
        
        # Create a layout for the input and unit selection
        input_layout = QHBoxLayout()
        input_layout.setSpacing(5)
        
        # Line edit for numeric input
        self.group_length_edit = QLineEdit("1")
        self.group_length_edit.setMaximumWidth(50)
        self.group_length_edit.textChanged.connect(self._on_group_length_changed)
        
        # Unit selection combo box
        self.group_length_unit = QComboBox()
        self.group_length_unit.addItems(["hour", "day"])
        self.group_length_unit.currentTextChanged.connect(self._on_group_unit_changed)
        
        input_layout.addWidget(self.group_length_edit)
        input_layout.addWidget(self.group_length_unit)
        
        group_length_layout.addWidget(self.group_length_label)
        group_length_layout.addLayout(input_layout)
        group_length_layout.addStretch(1)  # Add stretch to keep controls aligned left
        
        # Initially hide group length controls (shown only for PSD plot type)
        self.group_length_label.setVisible(False)
        self.group_length_edit.setVisible(False)
        self.group_length_unit.setVisible(False)
        
        vis_options_layout.addLayout(colormap_layout)
        vis_options_layout.addLayout(grid_layout)
        vis_options_layout.addLayout(group_length_layout)
        vis_options_group.setLayout(vis_options_layout)
        
        plot_type_group.setLayout(plot_type_layout)
        right_layout.addWidget(plot_type_group)
        right_layout.addWidget(vis_options_group)
        
        # Info text
        info_group = QGroupBox("Information")
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(5, 5, 5, 5)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        info_layout.addWidget(self.info_text)
        info_group.setLayout(info_layout)
        
        # Scan and plot buttons
        button_layout = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Files")
        self.scan_btn.clicked.connect(self.scan_files)
        self.plot_btn = QPushButton("Plot")
        self.plot_btn.clicked.connect(self.plot)
        self.plot_btn.setEnabled(False)
        button_layout.addWidget(self.scan_btn)
        button_layout.addWidget(self.plot_btn)
        
        right_layout.addWidget(info_group)
        right_layout.addLayout(button_layout)
        
        # Add panels to main splitter
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(plot_panel)
        main_splitter.addWidget(right_panel)
        
        # Set initial splitter sizes (20% left, 60% center, 20% right)
        main_splitter.setSizes([250, 700, 250])
        
        # Add main splitter to layout
        main_layout.addWidget(main_splitter)
        
        # Set size policy for panels
        left_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        plot_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        
    def _on_plot_type_changed(self, plot_type):
        """Handle plot type change."""
        self.plot_type = plot_type
        
        # Show/hide group length controls based on plot type
        is_psd_plot = (plot_type == "PSD")
        self.group_length_label.setVisible(is_psd_plot)
        self.group_length_edit.setVisible(is_psd_plot)
        self.group_length_unit.setVisible(is_psd_plot)
        
        # Hide colormap selector for PSD plot type since it uses line colors instead of colormap
        is_colormap_needed = (plot_type != "PSD")
        self.colormap_combo.setVisible(is_colormap_needed)
        self.findChild(QLabel, "colormap_label").setVisible(is_colormap_needed)
        
        if self.selected_files:
            self.plot()
            
    def _on_colormap_changed(self, colormap):
        """Handle colormap change."""
        self.colormap = colormap
        if self.selected_files:
            self.plot()
            
    def _on_group_length_changed(self, group_length_text):
        """Handle group length change."""
        try:
            if group_length_text:
                value = int(group_length_text)
                if value < 1:
                    value = 1
                    self.group_length_edit.setText("1")
                
                # Update group length based on unit
                if self.group_length_unit.currentText() == "day":
                    self.group_length = value * 24  # Convert days to hours
                else:
                    self.group_length = value
                
                if self.selected_files and self.plot_type == "PSD":
                    self.plot()
        except ValueError:
            # Invalid input, revert to default
            self.group_length_edit.setText("1")
            self.group_length = 1 if self.group_length_unit.currentText() == "hour" else 24
            
    def _on_group_unit_changed(self, unit):
        """Handle group unit change."""
        try:
            value = int(self.group_length_edit.text())
            if value < 1:
                value = 1
                self.group_length_edit.setText("1")
            
            # Update group length based on new unit
            if unit == "day":
                self.group_length = value * 24  # Convert days to hours
            else:
                # If changing from day to hour, we might want to adjust the value
                if self.group_length > 24:
                    # Previously was in days, convert to equivalent hours
                    self.group_length = value
                else:
                    self.group_length = value
                    
            if self.selected_files and self.plot_type == "PSD":
                self.plot()
        except ValueError:
            # Invalid input, revert to default
            self.group_length_edit.setText("1")
            self.group_length = 1 if unit == "hour" else 24
            
    def plot(self):
        """Plot based on selected plot type."""
        if not self.selected_files:
            return
            
        # Update UI before starting loading
        total_files = sum(len(files) for files in self.selected_files.values())
        self.progress_bar.setRange(0, total_files)
        self.progress_bar.setValue(0)
        self.plot_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        
        # Create and start worker thread
        self.loading_worker = PSDLoadingWorker(self.selected_files, self.plot_type)
        
        # Pass additional parameters when using PSD plot type
        if self.plot_type == "PSD":
            self.loading_worker.group_length = self.group_length
            
        self.loading_worker.finished.connect(self._on_loading_finished)
        self.loading_worker.error.connect(self._on_loading_error)
        self.loading_worker.progress.connect(self._on_loading_progress)
        self.loading_worker.data_ready.connect(self._on_data_loaded)
        
        # Start worker
        self.loading_worker.start()
            
    def _on_loading_finished(self):
        """Handle loading completion."""
        self.plot_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        
    def _on_loading_error(self, error_msg):
        """Handle loading error."""
        self.plot_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Error loading PSD data: {error_msg}")
        
    def _on_loading_progress(self, current, total):
        """Handle loading progress updates."""
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        
    def _on_data_loaded(self, data):
        """Handle loaded data and create the plot."""
        if not data or not data.get('groups'):
            return
            
        # Store the data for pagination
        self.current_plot_data = data
            
        # Get groups data
        groups_data = data['groups']
        if not groups_data:
            return
            
        # Update info text with the number of groups
        info_text = f"Found {len(groups_data)} groups with data\n\n"
        
        # Find overall time range from all groups
        all_file_times = []
        for group_key, group_data in groups_data.items():
            file_times = group_data.get('file_times', [])
            all_file_times.extend(file_times)
            if file_times:
                group_name = self._get_display_name_from_path(group_key)
                info_text += f"Group {group_name}:\n"
                info_text += f"  Files: {len(file_times)}\n"
                info_text += f"  Time range: {min(file_times).strftime('%Y-%m-%d %H:%M:%S')} - {max(file_times).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        if all_file_times:
            info_text += f"Overall time range: {min(all_file_times).strftime('%Y-%m-%d %H:%M:%S')} - {max(all_file_times).strftime('%Y-%m-%d %H:%M:%S')}"
            self.info_text.setText(info_text)
        
        # Update pagination
        self._update_total_pages()
        
        # Plot the first page
        self.current_page = 1
        self.plot_current_page()
            
    def _get_display_name_from_path(self, path):
        """Convert path to a display name (NSLC format if possible)."""
        try:
            # If path is a string representation of a pathlib.Path
            if path.startswith("WindowsPath('") or path.startswith("PosixPath('"):
                # Extract the actual path string
                path = path.split("'")[1]
            
            # Split path into components
            parts = Path(path).parts
            
            # Try to identify components as Network.Station.Location.Channel format
            if len(parts) >= 4:
                # Assuming the format is Network/Station/Location/Channel
                channel_part = parts[-1]
                location_part = parts[-2]
                station_part = parts[-3]
                network_part = parts[-4]
                
                # Format as NSLC code
                return f"{network_part}.{station_part}.{location_part}.{channel_part}"
            else:
                # If we can't identify the format, just return the path
                return path
        except Exception as e:
            logger.debug(f"Error formatting path {path}: {e}")
            return str(path)
            
    def _plot_pdf_groups(self, groups_data):
        """Plot PSD probability density function for each group in separate subplots."""
        try:
            # Clear the figure
            self.figure.clear()
            
            # Use user-defined grid layout
            rows = self.rows
            cols = self.cols
            
            # Calculate start and end indices for the current page
            start_idx = (self.current_page - 1) * self.max_plots_per_page
            end_idx = min(start_idx + self.max_plots_per_page, len(groups_data))
            
            # Get the groups for the current page
            current_page_groups = list(groups_data.items())[start_idx:end_idx]
            num_groups_on_page = len(current_page_groups)
            
            if num_groups_on_page == 0:
                logger.warning(f"No groups to display on page {self.current_page}")
                return
                
            # Create GridSpec for the layout - leave space for colorbar on right side
            gs = gridspec.GridSpec(rows, cols + 1, width_ratios=[1] * cols + [0.05])
            
            # Try to load noise models once for all subplots
            noise_models = None
            try:
                # Use Path for cross-platform path handling
                noise_models_path = Path(__file__).parent.parent.parent / 'core' / 'data' / 'noise_models.npz'
                noise_models = np.load(noise_models_path)
                model_periods = noise_models['model_periods']
                nlnm = noise_models['low_noise']
                nhnm = noise_models['high_noise']
                model_frequency = 1/model_periods[::-1]
            except Exception as e:
                logger.warning(f"Could not load noise models: {e}")
                
            # Store reference to first pcm for colorbar
            first_pcm = None
            
            # Plot each group in its own subplot
            for i, (group_key, group_data) in enumerate(current_page_groups):
                # Skip if missing required data
                if ('probability_distribution' not in group_data or 
                    'smoothed_frequencies' not in group_data or 
                    'psd_db_range' not in group_data):
                    logger.warning(f"Skipping group {group_key} due to missing data")
                    continue
                    
                # Calculate grid position
                row = i // cols
                col = i % cols
                
                # Create subplot
                ax = self.figure.add_subplot(gs[row, col])
                ax.set_xscale('log')
                
                # Get group display name
                group_name = self._get_display_name_from_path(group_key)
                
                # Ensure data has proper dimensions and types
                smoothed_frequencies = np.asarray(group_data['smoothed_frequencies'])
                psd_db_range = np.asarray(group_data['psd_db_range'])
                probability_distribution = np.asarray(group_data['probability_distribution'])
                
                if len(smoothed_frequencies) == 0 or len(psd_db_range) == 0:
                    logger.warning(f"Empty frequency or dB range data for group {group_key}")
                    continue
                    
                # Create the 2D color plot
                pcm = ax.pcolormesh(smoothed_frequencies,
                                  psd_db_range,
                                  probability_distribution.T,
                                  shading='auto',
                                  cmap=self.colormap)
                
                # Store reference to first pcm for colorbar
                if first_pcm is None:
                    first_pcm = pcm
                
                # Plot noise models if available
                if noise_models is not None:
                    # Plot noise models
                    ax.plot(model_frequency, nlnm[::-1], 'w--', linewidth=1)
                    ax.plot(model_frequency, nhnm[::-1], 'w--', linewidth=1)
                
                # Set labels and title
                # Always show x labels
                ax.set_xlabel('Frequency (Hz)', fontsize='small')
                
                if col == 0:  # Only leftmost column gets y labels
                    ax.set_ylabel('Power (dB)', fontsize='small')
                else:
                    ax.set_yticklabels([])
                    
                ax.set_title(group_name, fontsize='small')
                
                # Set axis limits - use indexing to avoid ambiguous truth value error
                if len(smoothed_frequencies) > 0:
                    ax.set_xlim(smoothed_frequencies[0], smoothed_frequencies[-1])
                if len(psd_db_range) > 0:
                    ax.set_ylim(psd_db_range[0], psd_db_range[-1])
                
                # Make tick labels smaller
                ax.tick_params(axis='both', which='major', labelsize='x-small')
                ax.tick_params(axis='both', which='minor', labelsize='xx-small')
            
            # Create a single colorbar for all subplots
            if first_pcm is not None:
                cax = self.figure.add_subplot(gs[:, -1])
                cbar = self.figure.colorbar(first_pcm, cax=cax)
                cbar.set_label('Probability')
            
            # Add a single legend for noise models (outside subplots)
            if noise_models is not None:
                # Create a small invisible axis for the legend below the figure
                legend_ax = self.figure.add_axes([0.4, 0.02, 0.2, 0.02], frameon=False)
                legend_ax.set_xticks([])
                legend_ax.set_yticks([])
                legend_ax.plot([], [], 'w--', label='NLNM/NHNM', linewidth=1, color='white')
                legend_ax.legend(loc='center', framealpha=0.7, fontsize='x-small')
            
            # Add a main title for the entire figure with page info
            if self.total_pages > 1:
                title = f'PSD Probability Density Functions by Group (Page {self.current_page}/{self.total_pages})'
            else:
                title = 'PSD Probability Density Functions by Group'
            self.figure.suptitle(title, fontsize='medium', y=0.98)
            
            # Adjust layout - use tight_layout with a rect that leaves room for the title
            self.figure.tight_layout(rect=[0, 0.03, 1, 0.95])
            
            # Update the canvas
            self.canvas.draw()
            
        except Exception as e:
            logger.error(f"Error plotting PDF groups: {e}")
            QMessageBox.critical(self, "Error", f"Error plotting PDF groups: {str(e)}")
            # Print traceback for debugging
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
    def _plot_psd_lines_groups(self, groups_data):
        """Plot PSD values as lines for each group in separate subplots."""
        try:
            # Clear the figure
            self.figure.clear()
            
            # Use user-defined grid layout
            rows = self.rows
            cols = self.cols
            
            # Calculate start and end indices for the current page
            start_idx = (self.current_page - 1) * self.max_plots_per_page
            end_idx = min(start_idx + self.max_plots_per_page, len(groups_data))
            
            # Get the groups for the current page
            current_page_groups = list(groups_data.items())[start_idx:end_idx]
            num_groups_on_page = len(current_page_groups)
            
            if num_groups_on_page == 0:
                logger.warning(f"No groups to display on page {self.current_page}")
                return
                
            # Create GridSpec for the layout
            gs = gridspec.GridSpec(rows, cols)
            
            # Try to load noise models once for all subplots
            noise_models = None
            try:
                # Use Path for cross-platform path handling
                noise_models_path = Path(__file__).parent.parent.parent / 'core' / 'data' / 'noise_models.npz'
                noise_models = np.load(noise_models_path)
                model_periods = noise_models['model_periods']
                nlnm = noise_models['low_noise']
                nhnm = noise_models['high_noise']
                model_frequency = 1/model_periods[::-1]
            except Exception as e:
                logger.warning(f"Could not load noise models: {e}")
            
            # Store references to all line handles and labels for combined legend
            legend_handles = []
            legend_labels = []
            noise_model_added = False
                
            # Plot each group in its own subplot
            for i, (group_key, group_data) in enumerate(current_page_groups):
                # Skip if missing required data
                if ('psd_lines' not in group_data or 
                    'frequencies' not in group_data):
                    logger.warning(f"Skipping group {group_key} due to missing data")
                    continue
                    
                # Calculate grid position
                row = i // cols
                col = i % cols
                
                # Create subplot
                ax = self.figure.add_subplot(gs[row, col])
                ax.set_xscale('log')
                
                # Get group display name
                group_name = self._get_display_name_from_path(group_key)
                
                # Get PSD lines and frequencies
                psd_lines = group_data['psd_lines']
                frequencies = np.asarray(group_data['frequencies'])
                file_names = group_data.get('file_names', [])
                
                if len(psd_lines) == 0 or len(frequencies) == 0:
                    logger.warning(f"Empty PSD or frequency data for group {group_key}")
                    continue
                
                # Create color map for different lines
                colors = plt.cm.tab20(np.linspace(0, 1, len(psd_lines)))
                
                # Plot each PSD line with a different color
                for j, psd_values in enumerate(psd_lines):
                    label = file_names[j] if j < len(file_names) else f"Line {j+1}"
                    # Only add to legend for the first few lines to avoid overcrowding
                    if j < 5:
                        line, = ax.plot(frequencies, psd_values, 
                               color=colors[j % len(colors)], linewidth=1, alpha=0.8,
                               label=label)
                        
                        # Only add to the legend for the first subplot to avoid duplicates
                        if i == 0:
                            legend_handles.append(line)
                            legend_labels.append(label)
                    else:
                        # Don't add to legend
                        ax.plot(frequencies, psd_values, 
                               color=colors[j % len(colors)], linewidth=1, alpha=0.8)
                
                # Plot noise models if available
                if noise_models is not None:
                    ax.plot(model_frequency, nlnm[::-1], 'k--', linewidth=1)
                    ax.plot(model_frequency, nhnm[::-1], 'k--', linewidth=1)
                    
                    # Add noise models to legend if not already added
                    if not noise_model_added:
                        noise_model_line = plt.Line2D([], [], color='k', linestyle='--', 
                                                     linewidth=1, label='NLNM/NHNM')
                        legend_handles.append(noise_model_line)
                        legend_labels.append('NLNM/NHNM')
                        noise_model_added = True
                
                # Set labels and title
                # Always show x labels
                ax.set_xlabel('Frequency (Hz)', fontsize='small')
                    
                if col == 0:  # Only leftmost column gets y labels
                    ax.set_ylabel('Power (dB)', fontsize='small')
                else:
                    ax.set_yticklabels([])
                
                # Set title with group name
                ax.set_title(group_name, fontsize='small')
                
                # Make tick labels smaller
                ax.tick_params(axis='both', which='major', labelsize='x-small')
                ax.tick_params(axis='both', which='minor', labelsize='xx-small')
            
            # Add group length info to title if applicable
            if self.plot_type == "PSD" and self.group_length > 1:
                # Determine if we should show in days or hours
                if self.group_length % 24 == 0 and self.group_length >= 24:
                    group_text = f"{self.group_length // 24} day"
                    if self.group_length > 24:
                        group_text += "s"
                else:
                    group_text = f"{self.group_length} hour"
                    if self.group_length > 1:
                        group_text += "s"
                        
                title_base = f'PSD Values by Group (Group Length: {group_text})'
            else:
                title_base = 'PSD Values by Group'
                
            # Add page info to title if multiple pages
            if self.total_pages > 1:
                title = f'{title_base} (Page {self.current_page}/{self.total_pages})'
            else:
                title = title_base
                
            # Add a main title for the entire figure
            self.figure.suptitle(title, fontsize='medium', y=0.98)
            
            # Add a single legend for all plots if we have handles
            if legend_handles:
                # Create a legend below all subplots
                self.figure.legend(legend_handles, legend_labels, 
                                 loc='lower center', ncol=min(5, len(legend_handles)),
                                 bbox_to_anchor=(0.5, 0.02), fontsize='x-small')
            
            # Adjust layout to accommodate the legend
            self.figure.tight_layout(rect=[0, 0.07 if legend_handles else 0.03, 1, 0.95])
            
            # Update the canvas
            self.canvas.draw()
            
        except Exception as e:
            logger.error(f"Error plotting PSD lines groups: {e}")
            QMessageBox.critical(self, "Error", f"Error plotting PSD lines groups: {str(e)}")
            # Print traceback for debugging
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
    def _plot_psd_time_frequency_groups(self, groups_data):
        """Plot PSD time-frequency distribution for each group in separate subplots."""
        try:
            # Clear the figure
            self.figure.clear()
            
            # Use user-defined grid layout
            rows = self.rows
            cols = self.cols
            
            # Calculate start and end indices for the current page
            start_idx = (self.current_page - 1) * self.max_plots_per_page
            end_idx = min(start_idx + self.max_plots_per_page, len(groups_data))
            
            # Get the groups for the current page
            current_page_groups = list(groups_data.items())[start_idx:end_idx]
            num_groups_on_page = len(current_page_groups)
            
            if num_groups_on_page == 0:
                logger.warning(f"No groups to display on page {self.current_page}")
                return
                
            # Create GridSpec for the layout - leave space for colorbar on right
            gs = gridspec.GridSpec(rows, cols + 1, width_ratios=[1] * cols + [0.05])
            
            # Store reference to first pcm for shared colorbar
            first_pcm = None
            
            # Plot each group in its own subplot
            for i, (group_key, group_data) in enumerate(current_page_groups):
                # Skip if missing required data
                if ('times' not in group_data or 
                    'psd_values' not in group_data or 
                    'smoothed_frequencies' not in group_data):
                    logger.warning(f"Skipping group {group_key} due to missing data")
                    continue
                    
                # Calculate grid position
                row = i // cols
                col = i % cols
                
                # Create subplot
                ax = self.figure.add_subplot(gs[row, col])
                
                # Get group display name
                group_name = self._get_display_name_from_path(group_key)
                
                # Ensure data has proper dimensions and types
                times = np.asarray(group_data['times'])
                smoothed_frequencies = np.asarray(group_data['smoothed_frequencies'])
                psd_values = np.asarray(group_data['psd_values'])
                
                if len(times) == 0 or len(smoothed_frequencies) == 0 or len(psd_values) == 0:
                    logger.warning(f"Empty time, frequency, or PSD data for group {group_key}")
                    continue
                
                # Create the 2D color plot
                pcm = ax.pcolormesh(times, 
                                   smoothed_frequencies,
                                   psd_values.T,
                                   shading='auto', 
                                   cmap=self.colormap)
                
                # Save first pcm for colorbar
                if first_pcm is None:
                    first_pcm = pcm
                
                # Format x-axis for dates
                ax.xaxis_date()
                
                # Set labels and title
                # Always show x labels
                ax.set_xlabel('Time', fontsize='small')
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
                    
                if col == 0:  # Only leftmost column gets y labels
                    ax.set_ylabel('Frequency (Hz)', fontsize='small')
                else:
                    ax.set_yticklabels([])
                
                ax.set_title(group_name, fontsize='small')
                
                # Make tick labels smaller
                ax.tick_params(axis='both', which='major', labelsize='x-small')
                ax.tick_params(axis='both', which='minor', labelsize='xx-small')
            
            # Add a single colorbar for all subplots
            if first_pcm is not None:
                cax = self.figure.add_subplot(gs[:, -1])
                cbar = self.figure.colorbar(first_pcm, cax=cax)
                cbar.set_label('Power (dB)', fontsize='small')
            
            # Add page info to title if multiple pages
            if self.total_pages > 1:
                title = f'PSD Time-Frequency Distribution by Group (Page {self.current_page}/{self.total_pages})'
            else:
                title = 'PSD Time-Frequency Distribution by Group'
                
            # Add a main title for the entire figure
            self.figure.suptitle(title, fontsize='medium', y=0.98)
            
            # Adjust layout
            self.figure.tight_layout(rect=[0, 0.03, 1, 0.95])
            
            # Update the canvas
            self.canvas.draw()
            
        except Exception as e:
            logger.error(f"Error plotting PSD time-frequency groups: {e}")
            QMessageBox.critical(self, "Error", f"Error plotting PSD time-frequency groups: {str(e)}")
            # Print traceback for debugging
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
    def _on_colormap_limits_changed(self, event):
        """Handle colorbar limits change."""
        # Get the current colorbar
        cbar = self.figure.axes[-1]
        # Get the current colormap
        cmap = plt.get_cmap(self.colormap)
        # Get the current limits
        vmin, vmax = cbar.get_ylim()
        # Update the colormap
        cbar.set_clim(vmin, vmax)
        # Redraw the canvas
        self.canvas.draw()
            
    def scan_stations(self):
        """Scan for stations and components in the project directory."""
        try:
            # Get output folder from project data
            output_folder = DEFAULT_OUTPUT_FOLDER  # Default value
            try:
                data_file = Path(self.project_dir) / 'data.json'
                if data_file.exists():
                    with open(data_file, 'r', encoding='utf-8') as f:
                        project_data = json.load(f)
                        output_folder = project_data.get('data_params', {}).get('outputFolder', DEFAULT_OUTPUT_FOLDER)
            except Exception as e:
                logger.warning(f"Error reading data.json, using default output folder: {e}")
            
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
            
            # Expand all items
            self.station_tree.expandAll()
            
            # Create component checkboxes
            self._create_component_checkboxes()
            
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
    
    def _on_item_changed(self, item, column):
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
        
        # Sync component checkboxes with tree selection
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
    
    def _select_all_components(self):
        """Select all components."""
        # Block signals to prevent multiple updates
        self.station_tree.blockSignals(True)
        
        # Get all top-level items
        root = self.station_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, Qt.Checked)
        
        # Also update component checkboxes
        for checkbox in self.component_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setCheckState(Qt.Checked)
            checkbox.blockSignals(False)
            
        self.station_tree.blockSignals(False)
        
        # Scan files after selection change
        self.scan_files()
        
    def _deselect_all_components(self):
        """Deselect all components."""
        # Block signals to prevent multiple updates
        self.station_tree.blockSignals(True)
        
        # Get all top-level items
        root = self.station_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, Qt.Unchecked)
        
        # Also update component checkboxes
        for checkbox in self.component_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setCheckState(Qt.Unchecked)
            checkbox.blockSignals(False)
            
        self.station_tree.blockSignals(False)
        
        # Scan files after selection change
        self.scan_files()
        
    def scan_files(self):
        """Scan for PSD files in selected components within the time range."""
        self.selected_files = {}  # Changed to dictionary to store groups of files by path
        
        try:
            # Get global time range
            start_time = self.start_time.dateTime().toPyDateTime()
            end_time = self.end_time.dateTime().toPyDateTime()
            
            # Get output folder from project data
            output_folder = DEFAULT_OUTPUT_FOLDER  # Default value
            try:
                data_file = Path(self.project_dir) / 'data.json'
                if data_file.exists():
                    with open(data_file, 'r', encoding='utf-8') as f:
                        project_data = json.load(f)
                        output_folder = project_data.get('data_params', {}).get('outputFolder', DEFAULT_OUTPUT_FOLDER)
            except Exception as e:
                logger.warning(f"Error reading data.json, using default output folder: {e}")
            
            output_dir = Path(self.project_dir) / output_folder
            logger.info(f"Output directory: {output_dir}")
            
            # Get checked paths from the tree
            checked_paths = self._get_checked_paths()
            logger.info(f"Found {len(checked_paths)} checked paths")
            
            if not checked_paths:
                QMessageBox.warning(self, "Warning", "Please select at least one station or component")
                return
            
            # Process files in checked directories
            total_files = 0
            for rel_path in checked_paths:
                # Convert to Path object for reliable path joining
                rel_path_obj = Path(rel_path)
                dir_path = output_dir / rel_path_obj
                logger.info(f"Scanning directory: {dir_path}")
                
                # Skip if directory doesn't exist
                if not dir_path.exists():
                    logger.warning(f"Directory does not exist: {dir_path}")
                    continue
                
                # Initialize group for this path
                group_key = str(rel_path_obj)
                self.selected_files[group_key] = []
                
                # Check both the directory itself and any PSD subdirectory
                directories_to_check = [dir_path]
                psd_subdir = dir_path / PSD_FOLDER_NAME
                if psd_subdir.exists():
                    directories_to_check.append(psd_subdir)
                
                for check_dir in directories_to_check:
                    # Find all files in this directory
                    try:
                        files = os.listdir(check_dir)
                        logger.info(f"Found {len(files)} files in {check_dir}")
                        
                        for file in files:
                            file_path = check_dir / file
                            
                            # Skip directories and non-PSD files
                            if os.path.isdir(file_path) or not file.endswith(PSD_FILE_SUFFIX):
                                continue
                            
                            # Check if file matches our format (Station.Component.Datetime)
                            parts = file.split('.')
                            if len(parts) >= 3:
                                # Extract datetime from filename
                                dt_str = parts[2]  # Datetime is the third part
                                if '_' in dt_str:
                                    dt_str = dt_str.split('_')[0]
                                try:
                                    dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                                    if start_time <= dt <= end_time:
                                        self.selected_files[group_key].append(str(file_path))
                                        total_files += 1
                                        logger.debug(f"Added file: {file_path}")
                                except ValueError:
                                    # Skip files with invalid datetime format
                                    logger.debug(f"Invalid datetime format in file: {file}")
                                    continue
                    except Exception as e:
                        logger.warning(f"Error listing directory {check_dir}: {e}")
            
            # Remove empty groups
            empty_groups = [group for group, files in self.selected_files.items() if not files]
            for group in empty_groups:
                del self.selected_files[group]
                
            # Update info text
            if total_files > 0:
                info_text = f"Found {total_files} PSD files in {len(self.selected_files)} groups\n\n"
                
                # Get time range of found files for each group
                file_times = []
                for group, files in self.selected_files.items():
                    group_times = []
                    for file_path in files:
                        try:
                            # Extract datetime from filename
                            file_name = Path(file_path).name
                            parts = file_name.split('.')
                            if len(parts) >= 3:
                                dt_str = parts[2].split('_')[0]
                                dt = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
                                group_times.append(dt)
                                file_times.append(dt)
                        except:
                            continue
                    
                    if group_times:
                        info_text += f"Group {group}:\n"
                        info_text += f"  Files: {len(files)}\n"
                        info_text += f"  Start: {min(group_times).strftime('%Y-%m-%d %H:%M:%S')}\n"
                        info_text += f"  End: {max(group_times).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                
                if file_times:
                    info_text += f"Overall time range:\n"
                    info_text += f"Start: {min(file_times).strftime('%Y-%m-%d %H:%M:%S')}\n"
                    info_text += f"End: {max(file_times).strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                info_text = "No PSD files found in the selected time range"
            
            self.info_text.setText(info_text)
            self.plot_btn.setEnabled(total_files > 0)
            logger.info(f"Scan complete, found {total_files} files in {len(self.selected_files)} groups")
            
        except Exception as e:
            logger.error(f"Error scanning files: {e}")
            QMessageBox.critical(self, "Error", f"Error scanning files: {str(e)}")
    
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
                        checked_paths.append(path)
        
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
            return full_path
        return ""
        
    def closeEvent(self, event):
        """Handle dialog close event."""
        # Stop any running worker thread
        try:
            if hasattr(self, 'loading_worker') and self.loading_worker:
                try:
                    is_running = self.loading_worker.isRunning()
                except RuntimeError:
                    is_running = False
                    
                if is_running:
                    self.loading_worker.terminate()
                    self.loading_worker.wait()
        except Exception as e:
            logger.debug(f"Error during worker thread cleanup: {e}")
            self.loading_worker = None
            
        # Clean up matplotlib resources
        if hasattr(self, 'figure') and self.figure:
            import matplotlib.pyplot as plt
            plt.close(self.figure)
            
        super().closeEvent(event)

    def _on_grid_changed(self, _):
        """Handle grid layout change.
        
        Updates the rows and columns for the plot grid layout and recalculates
        the maximum plots per page.
        
        Args:
            _: Unused parameter from signal
        """
        try:
            self.rows = int(self.row_combo.currentText())
            self.cols = int(self.col_combo.currentText())
            self.max_plots_per_page = self.rows * self.cols
            
            # Reset pagination
            self.current_page = 1
            
            # If we have plot data, update the plot
            if self.current_plot_data:
                self._update_total_pages()
                self.plot_current_page()
        except ValueError:
            pass
            
    def _update_total_pages(self):
        """Update total pages based on current data and grid size.
        
        Calculates the total number of pages needed to display all groups
        based on the current grid layout settings.
        """
        if not self.current_plot_data or 'groups' not in self.current_plot_data:
            self.total_pages = 1
            return
            
        num_groups = len(self.current_plot_data['groups'])
        self.total_pages = max(1, (num_groups + self.max_plots_per_page - 1) // self.max_plots_per_page)
        
        # Update page indicator
        self.page_indicator.setText(f"Page {self.current_page} of {self.total_pages}")
        
        # Update button states
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)
        
    def _on_prev_page(self):
        """Handle previous page button click.
        
        Decrements the current page number and updates the plot.
        """
        if self.current_page > 1:
            self.current_page -= 1
            self.plot_current_page()
            
    def _on_next_page(self):
        """Handle next page button click.
        
        Increments the current page number and updates the plot.
        """
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.plot_current_page()
            
    def plot_current_page(self):
        """Plot the current page based on plot type."""
        if not self.current_plot_data or 'groups' not in self.current_plot_data:
            return
            
        # Update page indicator
        self.page_indicator.setText(f"Page {self.current_page} of {self.total_pages}")
        
        # Update button states
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)
        
        # Plot based on current plot type
        if self.plot_type == "PDF":
            self._plot_pdf_groups(self.current_plot_data['groups'])
        elif self.plot_type == "PSD":
            self._plot_psd_lines_groups(self.current_plot_data['groups'])
        else:
            self._plot_psd_time_frequency_groups(self.current_plot_data['groups']) 

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
    
    def _select_component_for_all(self, component, state):
        """Select all directories with the given component."""
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
        
        # Scan files after selection change
        self.scan_files() 