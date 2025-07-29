"""
Dialog for setting project parameters.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                           QLineEdit, QComboBox, QPushButton, QGroupBox,
                           QMessageBox, QFileDialog, QCheckBox, QSpinBox,
                           QDoubleSpinBox, QTabWidget, QWidget, QGridLayout,
                           QTextEdit)
from PyQt5.QtCore import Qt, pyqtSignal
import json
from pathlib import Path
import logging
import os
from utils.config import config
from core.plugin_manager import PluginManager
from utils.file_name_parser import FileNameParser
from utils.window_utils import set_dialog_size, center_dialog
from utils.constants import DEFAULT_OUTPUT_FOLDER

logger = logging.getLogger(__name__)

# Constants for default values
DEFAULT_COMPONENT_NAMES = "N,E,Z"
DEFAULT_NAME_MAPPING = "Network:1;Station:2;Location:3;Channel:4"

class ProjectParametersDialog(QDialog):
    """Dialog for setting project parameters."""
    
    # Add signal for parameters saved
    parameters_saved = pyqtSignal(str)  # Signal to emit the new output folder path
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog.
        
        Args:
            project_dir: Project directory path
            parent: Parent widget
        """
        super().__init__(parent)
        self.project_dir = project_dir
        self.data_json_path = Path(project_dir) / 'data.json'
        # Test file result
        self.testfile_result = False
        self.trace_num = 1  # Initialize trace_num with default value
        
        # Initialize plugin manager for format list
        self.plugin_manager = PluginManager()
        
        self._init_ui()
        self._load_parameters()

        
        
    def _init_ui(self):
        """Initialize UI components."""
        self.setWindowTitle("Project Parameters")
        #self.setMinimumWidth(500)

        set_dialog_size(self, 0.4, 0.7)
        center_dialog(self)
        
        layout = QVBoxLayout()
        
        # Create tab widget
        tab_widget = QTabWidget()
        
        # Data Parameters Tab
        data_tab = QWidget()
        data_layout = QVBoxLayout()
        
        # File format group
        format_group = QGroupBox("File Name Rules")
        format_layout = QVBoxLayout()
        
        # Delimiters
        delim_layout = QHBoxLayout()
        delim_layout.addWidget(QLabel("Delimiters:"))
        self.delimiters = QLineEdit()
        self.delimiters.setPlaceholderText("delimiters seperated by space.e.g.:_ _ _ .")
        delim_layout.addWidget(self.delimiters)
        format_layout.addLayout(delim_layout)
        
        # Segments info
        parts_layout = QHBoxLayout()
        parts_layout.addWidget(QLabel("Segments:"))
        self.parts_info = QLineEdit()
        self.parts_info.setPlaceholderText("The segments seperated by delimiters.e.g.:NAN1 NAN2 STA KEEP zw")
        parts_layout.addWidget(self.parts_info)
        format_layout.addLayout(parts_layout)

        #Name parser
        '''
        Use any word to reference network, station, location, and channel codes
        in segments. If the file name doesn't contain some codes, you can set
        them below. Leave the content after the colon empty or with a space 
        if you think some codes are unnecessary. The files created by this application
        will be in a network/station/location/channel directory architecture.
        '''
        
        self.name_info = QTextEdit()
        self.name_info.setText(DEFAULT_NAME_MAPPING)

         # Add hint for component names
        name_hint = QLabel(
            "Use any word to reference network, station, location, and channel codes "
            "in segments. If the file name doesn't contain some codes, you can set "
            "them below. Leave the content after the colon empty or with a space "
            "if you think some codes are unnecessary. The files created by this application "
            "will be in a network/station/location/channel directory architecture."
        )
        name_hint.setWordWrap(True)
        name_hint.setStyleSheet("color: gray;")
        name_layout = QVBoxLayout()
        name_layout.addWidget(QLabel("Name Mapping With Codes:"))
        name_layout.addWidget(self.name_info)
        name_layout.addWidget(name_hint)
        format_layout.addLayout(name_layout)
        
        # Data format selection
        format_layout_h = QHBoxLayout()
        format_layout_h.addWidget(QLabel("Data Format:"))
        self.data_format = QComboBox()
        # Will be populated with available formats in _load_parameters
        format_layout_h.addWidget(self.data_format)
        
        # Test file
        test_group = QGroupBox("")
        test_layout = QHBoxLayout()
        test_layout.addWidget(QLabel("Test File:"))
        self.test_file = QLineEdit()
        self.test_file.setPlaceholderText("Select a file to test")
        test_layout.addWidget(self.test_file)
        test_button = QPushButton("Test File")
        test_button.clicked.connect(self._test_file)
        test_layout.addWidget(test_button)
        open_button = QPushButton("Open File")
        open_button.clicked.connect(self._open_file)
        test_layout.addWidget(open_button)
        
        test_group.setLayout(test_layout)

        # Create file info group
        fileinfo_group = QGroupBox("File Information")
        fileinfo_layout = QVBoxLayout()
        self.file_info = QTextEdit()
        self.file_info.setReadOnly(True)
        fileinfo_layout.addWidget(self.file_info)
        fileinfo_group.setLayout(fileinfo_layout)
        
        
        format_group.setLayout(format_layout)
        data_layout.addWidget(format_group)
        data_layout.addLayout(format_layout_h)
        data_layout.addWidget(test_group)
        data_layout.addWidget(fileinfo_group)

        
        
        data_tab.setLayout(data_layout)
        tab_widget.addTab(data_tab, "Data Parameters")
        
        # Tool Parameters Tab
        tool_tab = QWidget()
        tool_layout = QVBoxLayout()
        
        # Output format group
        output_format_group = QGroupBox("Output Format")
        output_format_layout = QVBoxLayout()
        
        # Data format selection
        format_layout_h = QHBoxLayout()
        format_layout_h.addWidget(QLabel("Data Format:"))
        self.output_format = QComboBox()
        # Will be populated with available formats in _load_parameters
        format_layout_h.addWidget(self.output_format)
        output_format_layout.addLayout(format_layout_h)

        # Add output folder selection
        output_folder_layout = QHBoxLayout()
        output_folder_layout.addWidget(QLabel("Output Folder:"))
        self.output_folder = QLineEdit()
       
        output_folder_layout.addWidget(self.output_folder)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._browse_output_folder)
        output_folder_layout.addWidget(browse_button)
        output_format_layout.addLayout(output_folder_layout)
        
        output_format_group.setLayout(output_format_layout)
        tool_layout.addWidget(output_format_group)
        
        # Component name group
        component_group = QGroupBox("Component Name")
        component_layout = QVBoxLayout()
        
        # Component name input
        component_name_layout = QHBoxLayout()
        component_name_layout.addWidget(QLabel("Component Name:"))
        self.component_name = QLineEdit()
        self.component_name.setText(DEFAULT_COMPONENT_NAMES)
        component_name_layout.addWidget(self.component_name)
        component_layout.addLayout(component_name_layout)
        
        # Add hint for component names
        component_hint = QLabel(
            "For files with multiple traces (e.g. three-component data), each trace will be saved as a separate file. "
            "Enter the component names separated by commas (e.g. N,E,Z). The number of names should match the number of traces."
        )
        component_hint.setWordWrap(True)
        component_hint.setStyleSheet("color: gray;")
        component_layout.addWidget(component_hint)
        
        component_group.setLayout(component_layout)
        tool_layout.addWidget(component_group)
        
        # Start on hour group
        start_hour_group = QGroupBox("Start Time")
        start_hour_layout = QVBoxLayout()
        
        # Start on hour checkbox
        self.start_on_hour = QCheckBox("Start on the hour")
        start_hour_layout.addWidget(self.start_on_hour)
        
        # Add hint for start on hour
        start_hour_hint = QLabel(
            "When enabled, the first file will begin on the hour (e.g. 00:00:00, 01:00:00, etc.). "
            "This is useful for ensuring consistent file boundaries when cutting or merging files."
        )
        start_hour_hint.setStyleSheet("color: gray;")
        start_hour_hint.setWordWrap(True)
        start_hour_layout.addWidget(start_hour_hint)
        
        start_hour_group.setLayout(start_hour_layout)
        tool_layout.addWidget(start_hour_group)
        
        tool_tab.setLayout(tool_layout)
        tab_widget.addTab(tool_tab, "Tool Parameters")
        
        # Instrument Parameters Tab
        instrument_tab = QWidget()
        instrument_layout = QVBoxLayout()
        
        # Instrument response group
        response_group = QGroupBox("Instrument Response")
        response_layout = QVBoxLayout()
        
      
        
        # Add response type switcher
        response_type_layout = QHBoxLayout()
        response_type_layout.addWidget(QLabel("Response Type:"))
        self.response_type = QComboBox()
        self.response_type.addItems(["Poles and Zeros", "Transfer Function"])
        self.response_type.currentIndexChanged.connect(self._on_response_type_changed)
        self.load_response_btn = QPushButton("Load Response File")
        self.load_response_btn.clicked.connect(self._load_response_file)
        response_type_layout.addWidget(self.response_type)
        response_type_layout.addWidget(self.load_response_btn)
        response_layout.addLayout(response_type_layout)
        
        # Poles and zeros
        self.poles_zeros_group = QGroupBox("Poles and Zeros")
        poles_zeros_layout = QVBoxLayout()
        self.poles_zeros_edit = QTextEdit()
        self.poles_zeros_edit.setPlaceholderText(
            "Enter poles and zeros in format:\n"
            "poles = [p1, p2, ...]\n"
            "zeros = [z1, z2, ...]\n"
            "Example:\npoles = [(1+2j), (3+4j)]\n"
            "zeros = [0j, 0j, 0j]"
        )
        poles_zeros_layout.addWidget(self.poles_zeros_edit)
        self.poles_zeros_group.setLayout(poles_zeros_layout)
        response_layout.addWidget(self.poles_zeros_group)
        
        # Transfer function
        self.tf_group = QGroupBox("Transfer Function")
        tf_layout = QVBoxLayout()
        self.transfer_function_edit = QTextEdit()
        self.transfer_function_edit.setPlaceholderText(
            "Enter transfer function coefficients in format:\n"
            "numerator = [b0, b1, ...]\n"
            "denominator = [a0, a1, ...]"
        )
        tf_layout.addWidget(self.transfer_function_edit)
        self.tf_group.setLayout(tf_layout)
        response_layout.addWidget(self.tf_group)
        
        # Initially hide transfer function group
        self.tf_group.setVisible(False)
        
        response_group.setLayout(response_layout)
        instrument_layout.addWidget(response_group)
        
        # Instrument parameters group
        instrument_params_group = QGroupBox("Instrument Parameters")
        instrument_params_layout = QVBoxLayout()
        
        # Natural period
        period_layout = QHBoxLayout()
        period_layout.addWidget(QLabel("Natural Period (s):"))
        self.natural_period = QLineEdit()
        self.natural_period.setText("1")
        period_layout.addWidget(self.natural_period)
        instrument_params_layout.addLayout(period_layout)
        
        # Sensitivity
        sens_layout = QHBoxLayout()
        sens_layout.addWidget(QLabel("Whole Sensitivity:"))
        self.sensitivity = QLineEdit()
        self.sensitivity.setText("1")
        self.sens_unit = QComboBox()
        self.sens_unit.addItem("count/(m/s)")
        self.sens_unit.addItem("count/(m/s^2)")
        sens_layout.addWidget(self.sensitivity)
        sens_layout.addWidget(self.sens_unit)
        instrument_params_layout.addLayout(sens_layout)
        
        # Damping
        damp_layout = QHBoxLayout()
        damp_layout.addWidget(QLabel("Damping:"))
        self.damping = QLineEdit()
        self.damping.setText("0.707")
        damp_layout.addWidget(self.damping)
        instrument_params_layout.addLayout(damp_layout)
        
        instrument_params_group.setLayout(instrument_params_layout)
        instrument_layout.addWidget(instrument_params_group)
        
        instrument_tab.setLayout(instrument_layout)
        tab_widget.addTab(instrument_tab, "Instrument Parameters")
        
        # Plot Parameters Tab
        plot_tab = QWidget()
        plot_layout = QVBoxLayout()
        
        # Plot settings group
        plot_group = QGroupBox("Plot Settings")
        plot_group_layout = QVBoxLayout()
        
        # Downsampling control
        downsample_layout = QHBoxLayout()
        self.enable_downsampling = QCheckBox("Enable downsampling")
        self.enable_downsampling.setChecked(True)
        self.enable_downsampling.stateChanged.connect(self._on_downsample_changed)
        downsample_layout.addWidget(self.enable_downsampling)
        plot_group_layout.addLayout(downsample_layout)
        
        # Add chunk size setting
        chunk_size_layout = QHBoxLayout()
        chunk_size_layout.addWidget(QLabel("Chunk Size:"))
        self.chunk_size_spinner = QSpinBox()
        self.chunk_size_spinner.setRange(1000, 10000000)
        self.chunk_size_spinner.setValue(10000)
        self.chunk_size_spinner.setSingleStep(1000)
        self.chunk_size_spinner.setEnabled(True)
        chunk_size_layout.addWidget(self.chunk_size_spinner)
        plot_group_layout.addLayout(chunk_size_layout)
        
        # Add description for chunk size
        chunk_size_desc = QLabel(
            "Number of points to plot at once. Larger values show more detail but may be slower. "
            "Maximum value is 10 million points."
        )
        chunk_size_desc.setWordWrap(True)
        plot_group_layout.addWidget(chunk_size_desc)
        
        plot_group.setLayout(plot_group_layout)
        plot_layout.addWidget(plot_group)
        plot_layout.addStretch()
        
        plot_tab.setLayout(plot_layout)
        tab_widget.addTab(plot_tab, "Plot Parameters")
        
        layout.addWidget(tab_widget)
        
        # Buttons
        button_layout = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_parameters)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
        
    def _open_file(self):
        """Open file selection dialog."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select File",
            str(Path(self.project_dir)),
            "All Files (*.*)"
        )
        if file_path:
            self.test_file.setText(file_path)
            

    def _test_file(self):
        """Test if a filename matches the current pattern and read file header."""
        filepath = self.test_file.text().strip()
        if not filepath:
            QMessageBox.warning(self, "Warning", "Please select a file to test")
            return
        filename = Path(filepath).name
            
        try:
            # Create parser with current UI values
            parser = FileNameParser(
                delimiters=self.delimiters.text().strip(),
                parts_info=self.parts_info.text().strip(),
                name_info=self.name_info.toPlainText().strip()
            )
            
            # Parse filename
            success, parsed_parts,channel, error = parser.parse_filename(filename)
            
            
            if success:
                self.testfile_result = True
                # Get format from last part of pattern
                format_type = self.data_format.currentText()
                
                # Create success message
                message = (
                    f"Success! The filename matches the pattern.\n\n"
                    f"Filename: {filename}\n"
                    f"Delimiters: {self.delimiters.text().strip()}\n"
                    f"Pattern parts: {self.parts_info.text().strip().split()}\n"
                    f"Parts found: {list(parsed_parts.values())}\n"
                    f"File format (Actual format): {format_type}\n\n"
                    f"Part meanings:"
                )
                
                # Add meaning of each part
                for i, (code_type, value) in enumerate(parsed_parts.items()):
                    message += f"\n{i+1}. {code_type}: {value}"
                
                # Get name info string and folder architecture
                name_info_str = parser.get_name_info_string(parsed_parts)
                folder_arch = parser.get_folder_architecture(parsed_parts)
                
                # Add name info and folder architecture to message
                message += "\n\nName Information:"
                message += f"\n{name_info_str}"
                message += "\n\nFolder Architecture:"
                message += f"\n{folder_arch}"
                
                # Try to read file header
                try:
                    # Get reader for the format
                    reader_class = self.plugin_manager.get_reader(format_type.upper())
                    if reader_class:
                        reader = reader_class()
                        # Read header using the reader
                        header = reader.read_header(filepath)
                         
                        if header:
                            self.trace_num = header.__len__()
                            message += "\n\nFile Header Information:"
                            message += f"\nStart Time: {header[0].stats.starttime}"
                            message += f"\nSampling Rate: {header[0].stats.sampling_rate} Hz"
                            message += f"\nTrace number: {header.__len__()}"
                            # Single trace file, but no channel info in file name
                            if self.trace_num == 1 and not channel:
                                show_message=f"\nWarning!!!Trace number: {self.trace_num},"\
                                  "but no channel info in filename."\
                                  "Please set a channel code."
                                message += show_message
                                QMessageBox.critical(self, "Warning", show_message)

                    else:
                        message += f"\n\nWarning: No reader found for format {format_type}"
                except Exception as e:
                    message += f"\n\nError reading file header: {str(e)}"
                
                # Show message in textbox
                self.file_info.setPlainText(message)
            else:
                self.testfile_result=False
                # Create failure message
                message = (
                    f"The filename does not match the pattern.\n\n"
                    f"Filename: {filename}\n"
                    f"Delimiters: {self.delimiters.text().strip()}\n"
                    f"Pattern parts: {self.parts_info.text().strip().split()}\n"
                    f"Error: {error}"
                )
                self.file_info.setPlainText(message)
                
        except Exception as e:
            logger.error(f"Error testing filename: {e}")
            self.file_info.setPlainText(f"Error testing filename: {str(e)}")
            
    def _on_downsample_changed(self, state):
        """Handle downsampling checkbox state change."""
        self.chunk_size_spinner.setEnabled(state == Qt.Checked)

    def _on_response_type_changed(self, index):
        """Handle response type change."""
        if index == 0:  # Poles and Zeros
            self.poles_zeros_group.setVisible(True)
            self.tf_group.setVisible(False)
        else:  # Transfer Function
            self.poles_zeros_group.setVisible(False)
            self.tf_group.setVisible(True)

    def _load_response_file(self):
        """Load instrument response file (.pz format)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Response File",
            self.project_dir,
            "Response Files (*.pz);;All Files (*.*)"
        )
        
        if not file_path:
            return
            
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                
            # Parse .pz file
            poles = []
            zeros = []
            constant = None
            
            current_section = None
            count = 0
            remaining_count = 0
            
            for line in content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                if line.startswith('ZEROS'):
                    current_section = 'ZEROS'
                    count = int(line.split()[1])
                    remaining_count = count
                    if count == 0:
                        zeros = [complex(0, 0)]  # Default zero
                        current_section = None
                elif line.startswith('POLES'):
                    current_section = 'POLES'
                    count = int(line.split()[1])
                    remaining_count = count
                elif line.startswith('CONSTANT'):
                    current_section = None
                    constant = float(line.split()[1])
                elif current_section == 'ZEROS' and remaining_count > 0:
                    # Parse complex number
                    real, imag = map(float, line.split())
                    zeros.append(complex(real, imag))
                    remaining_count -= 1
                elif current_section == 'POLES' and remaining_count > 0:
                    # Parse complex number
                    real, imag = map(float, line.split())
                    poles.append(complex(real, imag))
                    remaining_count -= 1
                    
            # Update UI
            self.poles_zeros_edit.setPlainText(
                f"poles = {poles}\n"
                f"zeros = {zeros}"
            )
            self.response_type.setCurrentIndex(0)
            
            if constant is not None:
                self.sensitivity.setText(str(constant))
                
        except Exception as e:
            logger.error(f"Error loading response file: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load response file: {str(e)}"
            )
            
    def _browse_output_folder(self):
        """Open folder selection dialog for output folder."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            str(Path(self.project_dir)),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if folder:
            # Always use absolute path
            self.output_folder.setText(str(Path(folder).absolute()))

    def _load_parameters(self):
        """Load parameters from data.json."""
        try:
            # Load available formats from plugin manager
            readers = self.plugin_manager.get_available_readers()
            formats = sorted([fmt.strip('.').upper() for fmt in readers.keys() if fmt])
            self.data_format.clear()
            self.output_format.clear()
            self.data_format.addItems(formats)
            self.output_format.addItems(formats)
            
            # Check if data.json exists
            if not self.data_json_path.exists():
                logger.info(f"data.json not found at {self.data_json_path}, will create new one on save")
                # Set default output folder as complete path
                default_output = str(Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER)
                self.output_folder.setText(default_output)
                return
                
            # Load data.json
            with open(self.data_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Load parameters
            if 'name_parser' in data:
                parser = data['name_parser']
                self.delimiters.setText(parser.get('delimiters', ''))
                self.parts_info.setText(parser.get('parts_info', ''))
                self.name_info.setText(parser.get('name_info', DEFAULT_NAME_MAPPING))
                
            # Load data parameters
            if 'data_params' in data:
                params = data['data_params']
                
                # Set data format
                format_str = params.get('dataFormat', 'MSEED').upper()
                index = self.data_format.findText(format_str)
                if index >= 0:
                    self.data_format.setCurrentIndex(index)
                    
                # Set output format
                out_format = params.get('outputFormat', format_str).upper()
                index = self.output_format.findText(out_format)
                if index >= 0:
                    self.output_format.setCurrentIndex(index)
                
                # Load output folder, use complete path for default
                default_output = str(Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER)
                self.output_folder.setText(params.get('outputFolder', default_output))
                
                self.component_name.setText(params.get('componentName', DEFAULT_COMPONENT_NAMES))
                self.start_on_hour.setChecked(params.get('startOnHour', False))
                
                # Load instrument parameters
                self.sensitivity.setText(str(params.get('wholeSensitivity', '')))
                
                # Set instrument type
                instrument_type = params.get('instrumentTpye', 0)
                self.sens_unit.setCurrentIndex(instrument_type)
                
                # Load response parameters
                self.response_type.setCurrentIndex(params.get('responseType', 0))
                self.damping.setText(str(params.get('damp', '')))
                self.natural_period.setText(str(params.get('naturalPeriod', '')))
                
                # Load poles and zeros if available
                if 'poles' in params and 'zeros' in params:
                    poles_str = ';'.join([str(p) for p in params['poles']])
                    zeros_str = ';'.join([str(z) for z in params['zeros']])
                    self.poles_zeros_edit.setPlainText(f"poles = {poles_str}\nzeros = {zeros_str}")
                    
                # Load transfer function if available
                if 'transfer_function' in params:
                    tf = params['transfer_function']
                    if 'numerator' in tf and 'denominator' in tf:
                        num_str = ';'.join([str(n) for n in tf['numerator']])
                        den_str = ';'.join([str(d) for d in tf['denominator']])
                        self.transfer_function_edit.setPlainText(f"numerator = {num_str}\ndenominator = {den_str}")
                
                # Load plot parameters
                if 'plot_params' in data:
                    plot_params = data['plot_params']
                    self.enable_downsampling.setChecked(plot_params.get('enable_downsampling', True))
                    self.chunk_size_spinner.setValue(plot_params.get('chunk_size', 10000))
                
        except Exception as e:
            logger.error(f"Error loading parameters: {e}")
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to load parameters: {str(e)}"
            )
            
    def save_parameters(self):
        """Save parameters to data.json."""
        try:
            # Load existing data if available
            existing_data = {}
            if os.path.exists(self.data_json_path):
                try:
                    with open(self.data_json_path, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except Exception as e:
                    logger.warning(f"Could not load existing data.json: {e}")
            
            # Ensure output folder is absolute path
            output_folder = self.output_folder.text().strip()
            if not os.path.isabs(output_folder):
                output_folder = str(Path(self.project_dir) / output_folder)
            
            # Prepare new data
            data = {
                'name_parser': {
                    'delimiters': self.delimiters.text().strip(),
                    'parts_info': self.parts_info.text().strip(),
                    'name_info': self.name_info.toPlainText().strip()
                },
                'test_result': self.testfile_result,
                'data_params': {
                    'dataFormat': self.data_format.currentText().lower(),
                    'outputFormat': self.output_format.currentText().lower(),
                    'outputFolder': self.output_folder.text(),
                    'traceNum': self.trace_num,
                    'componentName': self.component_name.text(),
                    'startOnHour': self.start_on_hour.isChecked(),
                    'instrumentTpye': self.sens_unit.currentIndex(),
                    'naturalPeriod': self.natural_period.text(),
                    'wholeSensitivity': self.sensitivity.text(),
                    'damp': self.damping.text()
                },
                'plot_params': {
                    'enable_downsampling': self.enable_downsampling.isChecked(),
                    'chunk_size': self.chunk_size_spinner.value()
                }
            }
            
            # Parse poles and zeros if provided
            poles_zeros_text = self.poles_zeros_edit.toPlainText()
            if poles_zeros_text:
                try:
                    # Simple parsing of poles and zeros
                    poles = []
                    zeros = []
                    for line in poles_zeros_text.split('\n'):
                        line = line.strip()
                        if line.startswith('poles ='):
                            # Convert complex numbers to string representation
                            poles_str = line.split('=', 1)[1].strip()
                            poles = eval(poles_str)
                            # Convert complex numbers to list of [real, imag] pairs
                            poles = [[p.real, p.imag] for p in poles]
                        elif line.startswith('zeros ='):
                            # Convert complex numbers to string representation
                            zeros_str = line.split('=', 1)[1].strip()
                            zeros = eval(zeros_str)
                            # Convert complex numbers to list of [real, imag] pairs
                            zeros = [[z.real, z.imag] for z in zeros]
                    data['data_params']['poles'] = poles
                    data['data_params']['zeros'] = zeros
                except Exception as e:
                    logger.warning(f"Could not parse poles and zeros: {e}")
                    
            # Parse transfer function if provided
            tf_text = self.transfer_function_edit.toPlainText()
            if tf_text:
                try:
                    # Simple parsing of transfer function
                    numerator = []
                    denominator = []
                    for line in tf_text.split('\n'):
                        line = line.strip()
                        if line.startswith('numerator ='):
                            # Parse numerator coefficients
                            num_str = line.split('=', 1)[1].strip()
                            numerator = eval(num_str)
                            # Ensure all coefficients are real numbers
                            numerator = [float(n) for n in numerator]
                        elif line.startswith('denominator ='):
                            # Parse denominator coefficients
                            den_str = line.split('=', 1)[1].strip()
                            denominator = eval(den_str)
                            # Ensure all coefficients are real numbers
                            denominator = [float(d) for d in denominator]
                    data['data_params']['transfer_function'] = {
                        'numerator': numerator,
                        'denominator': denominator
                    }
                except Exception as e:
                    logger.warning(f"Could not parse transfer function: {e}")
            
            # Preserve existing cut_params if they exist
            if 'cut_params' in existing_data:
                data['cut_params'] = existing_data['cut_params']
            
            # Create project directory if it doesn't exist
            os.makedirs(self.project_dir, exist_ok=True)
            
            # Save the data
            with open(self.data_json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
                
            logger.info(f"Saved parameters to {self.data_json_path}")
            
            # Emit signal with new output folder path
            self.parameters_saved.emit(str(Path(output_folder).absolute()))
            
            # Show success message without closing dialog
            QMessageBox.information(
                self,
                "Success",
                f"Parameters saved successfully to:\n{self.data_json_path}"
            )
            
        except Exception as e:
            logger.error(f"Error saving parameters: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save parameters: {str(e)}"
            ) 