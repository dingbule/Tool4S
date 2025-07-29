"""
Dialog for testing PSD parameters.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                           QLabel, QLineEdit, QPushButton, QCheckBox,
                           QDoubleSpinBox, QTextEdit, QListWidget, QSplitter,
                           QFileDialog, QMessageBox, QWidget, QListWidgetItem,
                           QComboBox, QScrollArea, QSizePolicy)
from PyQt5.QtCore import Qt
import os
from pathlib import Path
import numpy as np
import json
import logging
import configparser
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from core.psd import PSDCalculator
from core.plugin_manager import PluginManager
from utils.window_utils import set_dialog_size, center_dialog

logger = logging.getLogger(__name__)

class PSDParameterTestDialog(QDialog):
    """Dialog for testing PSD parameters."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog."""
        super().__init__(parent)
        self.project_dir = project_dir
        self.plugin_manager = PluginManager()
        self.psd_results = []  # Store up to 10 PSD results
        
        # Get application root directory (two levels up from this file)
        app_root = str(Path(__file__).parent.parent.parent)
        self.config_ini_path = os.path.join(app_root, 'config.ini')
        
        self._init_ui()
        self._load_config_path()
        self._load_instrument_info()
        
    def _init_ui(self):
        """Initialize UI components."""
        self.setWindowTitle("PSD Parameter Test")

        # Set window size to 80% of screen size
        set_dialog_size(self, 0.7, 0.7)
        center_dialog(self)
        
        # Create main layout
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Create splitter
        splitter = QSplitter(Qt.Horizontal)
        
        
        # Create left panel widget
        left_widget = QWidget()
        left_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        left_panel = QVBoxLayout(left_widget)
        left_panel.setSpacing(10)
        left_panel.setContentsMargins(5, 5, 5, 5)
        
        # Create instrument info group
        instrument_group = QGroupBox("Instrument Information")
        instrument_layout = QVBoxLayout()
        self.instrument_info = QTextEdit()
        self.instrument_info.setReadOnly(True)
        self.instrument_info.setMaximumHeight(100)
        instrument_layout.addWidget(self.instrument_info)
        instrument_group.setLayout(instrument_layout)
        left_panel.addWidget(instrument_group)
        
        # Create parameters group
        params_group = QGroupBox("PSD Parameters")
        params_layout = QVBoxLayout()
        params_layout.setSpacing(10)
        
        # Filter parameters group
        filter_group = QGroupBox("Filter Parameters")
        filter_layout = QVBoxLayout()
        filter_layout.setSpacing(5)
        
        # Enable filter checkbox
        self.filter_check = QCheckBox("Enable Filter")
        self.filter_check.stateChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_check)
        
        # Create container for filter settings
        self.filter_settings = QWidget()
        filter_settings_layout = QVBoxLayout()
        filter_settings_layout.setContentsMargins(20, 0, 0, 0)  # Add left margin for indentation
        self.filter_settings.setLayout(filter_settings_layout)
        
        # Filter type selection
        filter_type_layout = QHBoxLayout()
        filter_type_layout.addWidget(QLabel("Filter Type:"))
        self.filter_type = QComboBox()
        self.filter_type.addItems(["High Pass", "Band Pass"])
        self.filter_type.currentIndexChanged.connect(self._on_filter_type_changed)
        filter_type_layout.addWidget(self.filter_type)
        filter_settings_layout.addLayout(filter_type_layout)
        
        # Container for frequency settings
        self.freq_container = QWidget()
        freq_container_layout = QVBoxLayout()
        freq_container_layout.setContentsMargins(0, 0, 0, 0)
        self.freq_container.setLayout(freq_container_layout)
        
        # High pass frequency
        self.high_pass_widget = QWidget()
        high_pass_layout = QHBoxLayout()
        high_pass_layout.setContentsMargins(0, 0, 0, 0)
        self.high_pass_widget.setLayout(high_pass_layout)
        self.high_pass_freq = QDoubleSpinBox()
        self.high_pass_freq.setRange(0.001, 1000)
        self.high_pass_freq.setValue(0.1)
        self.high_pass_freq.setDecimals(3)
        self.high_pass_freq.setSuffix(" Hz")
        high_pass_layout.addWidget(QLabel("Frequency:"))
        high_pass_layout.addWidget(self.high_pass_freq)
        high_pass_layout.addStretch()
        freq_container_layout.addWidget(self.high_pass_widget)
        
        # Band pass frequencies
        self.band_pass_widget = QWidget()
        band_pass_layout = QHBoxLayout()
        band_pass_layout.setContentsMargins(0, 0, 0, 0)
        self.band_pass_widget.setLayout(band_pass_layout)
        self.low_freq = QDoubleSpinBox()
        self.low_freq.setRange(0.001, 1000)
        self.low_freq.setValue(0.1)
        self.low_freq.setDecimals(3)
        self.low_freq.setSuffix(" Hz")
        self.high_freq = QDoubleSpinBox()
        self.high_freq.setRange(0.001, 1000)
        self.high_freq.setValue(100)
        self.high_freq.setDecimals(3)
        self.high_freq.setSuffix(" Hz")
        band_pass_layout.addWidget(QLabel("Low Frequency:"))
        band_pass_layout.addWidget(self.low_freq)
        band_pass_layout.addWidget(QLabel("High Frequency:"))
        band_pass_layout.addWidget(self.high_freq)
        band_pass_layout.addStretch()
        freq_container_layout.addWidget(self.band_pass_widget)
        
        # Add frequency container to filter settings
        filter_settings_layout.addWidget(self.freq_container)
        
        # Add filter settings to filter group
        filter_layout.addWidget(self.filter_settings)
        filter_group.setLayout(filter_layout)
        params_layout.addWidget(filter_group)
        
        # Response removal
        self.response_check = QCheckBox("Enable Response Removal")
        params_layout.addWidget(self.response_check)
        
        # PSD frequency range group
        freq_range_group = QGroupBox("PSD Frequency Range")
        freq_range_layout = QHBoxLayout()
        freq_range_layout.setSpacing(5)
        
        # Min frequency
        min_freq_layout = QHBoxLayout()
        self.min_freq = QDoubleSpinBox()
        self.min_freq.setRange(0.001, 1000)
        self.min_freq.setValue(0.001)
        self.min_freq.setDecimals(3)
        self.min_freq.setSuffix(" Hz")
        min_freq_layout.addWidget(QLabel("Minimum:"))
        min_freq_layout.addWidget(self.min_freq)
        min_freq_layout.addStretch()
        freq_range_layout.addLayout(min_freq_layout)
        
        # Max frequency
        max_freq_layout = QHBoxLayout()
        self.max_freq = QDoubleSpinBox()
        self.max_freq.setRange(0.001, 1000)
        self.max_freq.setValue(100)
        self.max_freq.setDecimals(3)
        self.max_freq.setSuffix(" Hz")
        max_freq_layout.addWidget(QLabel("Maximum:"))
        max_freq_layout.addWidget(self.max_freq)
        max_freq_layout.addStretch()
        freq_range_layout.addLayout(max_freq_layout)
        
        freq_range_group.setLayout(freq_range_layout)
        params_layout.addWidget(freq_range_group)
        
        # Window parameters
        window_group = QGroupBox("Welch Parameters")
        window_layout = QVBoxLayout()
        window_layout.setSpacing(5)
        
        # Window size
        window_size_layout = QHBoxLayout()
        self.window_size = QDoubleSpinBox()
        self.window_size.setRange(1, 10000)
        self.window_size.setValue(1000)
        self.window_size.setSuffix(" s")
        window_size_layout.addWidget(QLabel("Window Size:"))
        window_size_layout.addWidget(self.window_size)
        window_size_layout.addStretch()
        window_layout.addLayout(window_size_layout)
        
        # Overlap
        overlap_layout = QHBoxLayout()
        self.overlap = QDoubleSpinBox()
        self.overlap.setRange(0, 100)
        self.overlap.setValue(80)
        self.overlap.setSuffix(" %")
        overlap_layout.addWidget(QLabel("Overlap:"))
        overlap_layout.addWidget(self.overlap)
        overlap_layout.addStretch()
        window_layout.addLayout(overlap_layout)
        
        # Window type
        window_type_layout = QHBoxLayout()
        self.window_type = QComboBox()
        window_types = [
            "hann", "boxcar", "triang", "blackman", "hamming",
            "bartlett", "flattop", "parzen", "bohman", "blackmanharris",
            "nuttall", "barthann"
        ]
        self.window_type.addItems(window_types)
        window_size_layout.addWidget(QLabel("Window Type:"))
        window_size_layout.addWidget(self.window_type)
        window_size_layout.addStretch()
        
        window_group.setLayout(window_layout)
        params_layout.addWidget(window_group)
        
        params_group.setLayout(params_layout)
        left_panel.addWidget(params_group)
        
        # Create config file group
        config_group = QGroupBox("Parameter Configuration")
        config_layout = QVBoxLayout()
        
        # Config file path
        config_path_layout = QHBoxLayout()
        self.config_path = QLineEdit()
        self.config_path.setReadOnly(True)
        self.select_config_btn = QPushButton("Select Config")
        self.select_config_btn.clicked.connect(self._select_config)
        self.save_config_btn = QPushButton("Save Config")
        self.save_config_btn.clicked.connect(self._save_config)
        config_path_layout.addWidget(self.config_path)
        config_path_layout.addWidget(self.select_config_btn)
        config_path_layout.addWidget(self.save_config_btn)
        config_layout.addLayout(config_path_layout)
        
        config_group.setLayout(config_layout)
        left_panel.addWidget(config_group)
        
        # Create test file group
        test_file_group = QGroupBox("Test File")
        test_file_layout = QHBoxLayout()
        self.test_file_path = QLineEdit()
        self.test_file_path.setReadOnly(True)
        self.select_file_btn = QPushButton("Select File")
        self.select_file_btn.clicked.connect(self._select_test_file)
        test_file_layout.addWidget(self.test_file_path)
        test_file_layout.addWidget(self.select_file_btn)
        test_file_group.setLayout(test_file_layout)
        left_panel.addWidget(test_file_group)
        
        # Add stretch to push everything up
        left_panel.addStretch()
        
        # Create right panel with plot and results
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)
        
        # Add the canvas to right panel
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_panel.addWidget(self.canvas)
        
        # Create results area at the bottom of the right panel
        bottom_layout = QHBoxLayout()
        
        # Create results list
        results_group = QGroupBox("Saved Results")
        results_layout = QVBoxLayout()
        self.results_list = QListWidget()
        self.results_list.setMinimumHeight(100)
        self.results_list.setMaximumHeight(150)
        self.results_list.itemClicked.connect(self._on_result_selected)
        results_layout.addWidget(self.results_list)
        results_group.setLayout(results_layout)
        
        # Create test button
        self.test_btn = QPushButton("Test Parameters")
        self.test_btn.setMinimumHeight(40)
        self.test_btn.clicked.connect(self._test_parameters)
        
        # Add results group and test button to bottom layout
        bottom_layout.addWidget(results_group, 3)
        bottom_layout.addWidget(self.test_btn, 1)
        
        # Add bottom layout to right panel
        right_panel.addLayout(bottom_layout)
        
        # Create right widget to hold the right panel
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        right_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Add both panels to main layout with proper stretching

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        
        # Set splitter sizes (20% for tree, 80% for plot)
        splitter.setSizes([200, 800])
        main_layout.addWidget(splitter)
        
        # Set size policies for input widgets
        self.config_path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.test_file_path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Set fixed widths for buttons
        self.select_config_btn.setFixedWidth(100)
        self.save_config_btn.setFixedWidth(100)
        self.select_file_btn.setFixedWidth(100)
        
        # Set size policies for all spinboxes
        for spinbox in [self.high_pass_freq, self.low_freq, self.high_freq,
                       self.min_freq, self.max_freq, self.window_size, self.overlap]:
            spinbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Set size policies for combo boxes
        self.filter_type.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.window_type.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        # Set size policies for group boxes
        for group in [instrument_group, params_group, filter_group, freq_range_group,
                     window_group, config_group, test_file_group, results_group]:
            group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        
        # Set minimum sizes for text areas
        self.instrument_info.setMinimumHeight(80)
        
        # Initialize filter UI state
        self.filter_settings.setEnabled(False)
        self._on_filter_type_changed(0)
        
    def _load_instrument_info(self):
        """Load instrument information from data.json."""
        try:
            data_file = Path(self.project_dir) / 'data.json'
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Get instrument parameters
            self.sensitivity = data['data_params'].get('wholeSensitivity', 'Unknown')
            self.instrument_type = data['data_params'].get('instrumentType', 0)
            self.damping_ratio = data['data_params'].get('damp', 'Unknown')
            self.natural_period = data['data_params'].get('naturalPeriod', 'Unknown')
            
            # Build info text
            info = []
            if self.instrument_type == 0:
                info.append(f"Whole Sensitivity: {self.sensitivity} count/(m/s)")
            elif self.instrument_type == 1:
                info.append(f"Whole Sensitivity: {self.sensitivity} count/(m/s^2)")
            info.append(f"Damping Ratio: {self.damping_ratio}")
            info.append(f"Natural Period: {self.natural_period} s")
            
            # Add poles and zeros if available
            if 'poles' in data['data_params'] and 'zeros' in data['data_params']:
                info.append("\nPoles and Zeros:")
                info.append(f"poles = {data['data_params']['poles']}")
                info.append(f"zeros = {data['data_params']['zeros']}")
            elif  'transfer_function' in data['data_params']:
                tf = data['data_params']['transfer_function']
                info.append("\nTransfer Function:")
                info.append(f"numerator = {tf.get('numerator', [])}")
                info.append(f"denominator = {tf.get('denominator', [])}")
            else:
                info.append("\nNote: Instrument response will use theoretical transfer function")
                
            self.instrument_info.setPlainText('\n'.join(info))
            
        except Exception as e:
            logger.error(f"Error loading instrument info: {e}")
            self.instrument_info.setPlainText("Failed to load instrument information")
            
    def _on_filter_changed(self, state):
        """Handle filter checkbox state change."""
        enabled = state == Qt.Checked
        self.filter_settings.setEnabled(enabled)
        self.filter_type.setEnabled(enabled)
        self._on_filter_type_changed(self.filter_type.currentIndex())
        
    def _on_filter_type_changed(self, index):
        """Handle filter type change."""
        # Only show/hide if filter is enabled
        if self.filter_check.isChecked():
            if index == 0:  # High Pass
                self.high_pass_widget.show()
                self.band_pass_widget.hide()
            else:  # Band Pass
                self.high_pass_widget.hide()
                self.band_pass_widget.show()
        else:
            self.high_pass_widget.hide()
            self.band_pass_widget.hide()
            
    def _load_config_path(self):
        """Load PSD config file path from config.ini."""
        try:
            config = configparser.ConfigParser()
            if os.path.exists(self.config_ini_path):
                config.read(self.config_ini_path)
                
                if 'PSD' in config and 'config_file' in config['PSD']:
                    path = config['PSD']['config_file']
                    if os.path.exists(path):
                        self.config_path.setText(path)
                        self._load_config(path)
        except Exception as e:
            logger.error(f"Error loading config path: {e}")
            
    def _save_config_path(self, path):
        """Save PSD config file path to config.ini."""
        try:
            config = configparser.ConfigParser()
            if os.path.exists(self.config_ini_path):
                config.read(self.config_ini_path)
            
            if 'PSD' not in config:
                config['PSD'] = {}
                
            config['PSD']['config_file'] = path
            
            with open(self.config_ini_path, 'w') as f:
                config.write(f)
                
            logger.info(f"Saved PSD config file path to config.ini: {path}")
                
        except Exception as e:
            logger.error(f"Error saving config path: {e}")
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to save config path to config.ini: {str(e)}"
            )
            
    def _select_config(self):
        """Select parameter configuration file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Parameter Configuration",
            str(Path(self.project_dir)),
            "JSON Files (*.json)"
        )
        if file_path:
            self.config_path.setText(file_path)
            self._save_config_path(file_path)
            self._load_config(file_path)
            
    def _save_config(self):
        """Save current parameters to configuration file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Parameter Configuration",
            str(Path(self.project_dir)),
            "JSON Files (*.json)"
        )
        if file_path:
            if self._save_config_to_file(file_path):
                self.config_path.setText(file_path)
                self._save_config_path(file_path)
            
    def _load_config(self, file_path):
        """Load parameters from configuration file."""
        try:
            with open(file_path, 'r') as f:
                config = json.load(f)
                
            self.filter_check.setChecked(config.get('filter_enabled', False))
            self.filter_type.setCurrentText(config.get('filter_type', 'High Pass'))
            
            # Handle filter frequencies based on type
            filter_freq = config.get('filter_freq', 0.1)
            if isinstance(filter_freq, (list, tuple)):
                self.low_freq.setValue(filter_freq[0])
                self.high_freq.setValue(filter_freq[1])
            else:
                self.high_pass_freq.setValue(filter_freq)
                
            self.response_check.setChecked(config.get('response_enabled', False))
            self.window_size.setValue(config.get('window_size', 1000))
            self.overlap.setValue(config.get('overlap', 80))
            self.window_type.setCurrentText(config.get('window_type', 'hann'))
            self.min_freq.setValue(config.get('psd_freq_min', 0.001))
            self.max_freq.setValue(config.get('psd_freq_max', 100))
            
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load configuration: {e}")
            
    def _save_config_to_file(self, file_path):
        """Save current parameters to configuration file."""
        try:
            config = {
                'filter_enabled': self.filter_check.isChecked(),
                'filter_type': self.filter_type.currentText(),
                'filter_freq': (self.low_freq.value(), self.high_freq.value()) 
                              if self.filter_type.currentText() == "Band Pass" 
                              else self.high_pass_freq.value(),
                'response_enabled': self.response_check.isChecked(),
                'window_size': self.window_size.value(),
                'overlap': self.overlap.value(),
                'window_type': self.window_type.currentText(),
                'psd_freq_min': self.min_freq.value(),
                'psd_freq_max': self.max_freq.value()
            }
            
            with open(file_path, 'w') as f:
                json.dump(config, f, indent=4)
                
            return True
                
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
            return False
            
    def _select_test_file(self):
        """Select test data file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Test File",
            str(Path(self.project_dir)),
            "All Files (*.*)"
        )
        if file_path:
            self.test_file_path.setText(file_path)
            
    def _test_parameters(self):
        """Test current parameters on selected file."""
        if not self.test_file_path.text():
            QMessageBox.warning(self, "Warning", "Please select a test file first")
            return
            
        # Check for required parameters
        if self.response_check.isChecked():
            if (self.sensitivity == 'Unknown' or 
                (self.damping_ratio == 'Unknown' and self.natural_period == 'Unknown')):
                QMessageBox.warning(
                    self,
                    "Warning",
                    "Cannot process response removal without sensitivity and damping/natural period information"
                )
                return
                
        if self.sensitivity == 'Unknown':
            QMessageBox.warning(
                self,
                "Warning",
                "PSD calculation requires sensitivity information"
            )
            return
            
        try:
            # Get file extension and reader
            ext = Path(self.test_file_path.text()).suffix.lower()
            reader_class = self.plugin_manager.get_available_readers().get(ext)
            if not reader_class:
                raise ValueError(f"Please select a file produced by this application")
                
            # Read data
            reader = reader_class()
            data = reader.read(self.test_file_path.text())
            
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
                damping_ratio=float(self.damping_ratio),
                natural_period=float(self.natural_period)
            )
            
            # Configure calculator
            calculator.filter_enabled = self.filter_check.isChecked()
            calculator.response_removal_enabled = self.response_check.isChecked()
            
            if calculator.filter_enabled:
                calculator.filter_type = self.filter_type.currentText()
                if calculator.filter_type == "High Pass":
                    calculator.cutoff_freq = self.high_pass_freq.value()
                else:  # Band Pass
                    calculator.cutoff_freq = (self.low_freq.value(), self.high_freq.value())
                    
            # Configure window parameters
            calculator.window_size = self.window_size.value()
            calculator.overlap = self.overlap.value() / 100  # Convert percentage to fraction
            calculator.window_type = self.window_type.currentText()
            
            # Configure PSD frequency range
            calculator.psd_freq_min = self.min_freq.value()
            calculator.psd_freq_max = self.max_freq.value()
            
            # Calculate PSD and smoothed PSD
            calculator.calculate_psd(data_array)
            
            # Store results
            result = {
                'parameters': {
                    'filter_enabled': calculator.filter_enabled,
                    'filter_type': self.filter_type.currentText(),
                    'filter_freq': calculator.cutoff_freq,
                    'response_enabled': calculator.response_removal_enabled,
                    'window_size': calculator.window_size,
                    'overlap': calculator.overlap * 100,
                    'window_type': calculator.window_type,
                    'psd_freq_min': calculator.psd_freq_min,
                    'psd_freq_max': calculator.psd_freq_max
                },
                'frequencies': calculator.frequencies,
                'psd': calculator.psd,
                'f_smoothed': calculator.smoothed_frequencies,
                'smoothed_psd': calculator.smoothed_psd
            }
            
            # Add to results list (keep only last 10)
            self.psd_results.append(result)
            if len(self.psd_results) > 10:
                self.psd_results.pop(0)
                
            # Update results list
            self._update_results_list()
            
            # Plot results
            self._plot_results(result)
            
        except Exception as e:
            logger.error(f"Error testing parameters: {e}")
            QMessageBox.critical(self, "Error", f"Failed to test parameters: {e}")
            
    def _update_results_list(self):
        """Update the results list widget."""
        self.results_list.clear()
        for i, result in enumerate(self.psd_results):
            params = result['parameters']
            filter_info = ""
            if params['filter_enabled']:
                if isinstance(params['filter_freq'], tuple):
                    filter_info = f"Band Pass {params['filter_freq'][0]:.3f}-{params['filter_freq'][1]:.3f}Hz"
                else:
                    filter_info = f"High Pass {params['filter_freq']:.3f}Hz"
                    
            item = QListWidgetItem(
                f"Test {i+1}: {filter_info}, "
                f"Response={params['response_enabled']}, "
                f"Window={params['window_size']}s, "
                f"Overlap={params['overlap']}%, "
                f"Window={params['window_type']}, "
                f"Freq={params['psd_freq_min']:.3f}-{params['psd_freq_max']:.3f}Hz"
            )
            item.setData(Qt.UserRole, i)
            self.results_list.addItem(item)
            
    def _on_result_selected(self, item):
        """Handle result selection."""
        index = item.data(Qt.UserRole)
        if 0 <= index < len(self.psd_results):
            result = self.psd_results[index]
            
            # Update parameters
            params = result['parameters']
            self.filter_check.setChecked(params['filter_enabled'])
            self.filter_type.setCurrentText(params['filter_type'])
            
            if isinstance(params['filter_freq'], tuple):
                self.low_freq.setValue(params['filter_freq'][0])
                self.high_freq.setValue(params['filter_freq'][1])
            else:
                self.high_pass_freq.setValue(params['filter_freq'])
                
            self.response_check.setChecked(params['response_enabled'])
            self.window_size.setValue(params['window_size'])
            self.overlap.setValue(params['overlap'])
            self.window_type.setCurrentText(params['window_type'])
            self.min_freq.setValue(params['psd_freq_min'])
            self.max_freq.setValue(params['psd_freq_max'])
            
            # Plot results
            self._plot_results(result)
            
    def _plot_results(self, result):
        """Plot PSD results."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        # Plot PSD
        ax.plot(result['frequencies'], result['psd'], 'b-', label='PSD')
        ax.plot(result['f_smoothed'], result['smoothed_psd'], 'r-', label='Smoothed PSD')
        
        # Load and plot noise models
        noise_models_path = Path(__file__).parent.parent.parent / 'core' / 'data' / 'noise_models.npz'
        if noise_models_path.exists():
            noise_models = np.load(noise_models_path)
            model_periods = noise_models['model_periods']
            nlnm = noise_models['low_noise']
            nhnm = noise_models['high_noise']
            model_frequency = 1/model_periods[::-1]
            model_nlnm = nlnm[::-1]
            model_nhnm = nhnm[::-1]
            
            # Plot noise models
            ax.plot(model_frequency, model_nlnm, 'k--', label='NLNM')
            ax.plot(model_frequency, model_nhnm, 'k--', label='NHNM')
        
        # Set labels and title
        ax.set_xlabel('Frequency (Hz)')
        ax.set_ylabel('Power Spectral Density (dB)')
        ax.set_title('PSD Test Results')
        ax.set_xscale('log')
        ax.grid(True)
        ax.legend()
        
        # Refresh canvas
        self.canvas.draw() 

    def closeEvent(self, event):
        """Handle dialog close event."""
        # Clean up matplotlib resources
        if hasattr(self, 'figure'):
            import matplotlib.pyplot as plt
            plt.close(self.figure)
            
        # Clean up any other resources
        if hasattr(self, 'psd_results'):
            self.psd_results.clear()
            
        super().closeEvent(event) 