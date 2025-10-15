"""
Project scan dialog for analyzing project data and visualizing station locations.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from obspy import read_inventory

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, 
                           QTextEdit, QPushButton,
                           QProgressBar, QLabel, QSplitter, QWidget, QMessageBox,
                           QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog)
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import utm

from core.plugin_manager import PluginManager
from plugins.base_reader import DataReader
from utils.file_name_parser import FileNameParser
from utils.window_utils import set_dialog_size, center_dialog
from utils.file_utils import get_file_format_and_reader

logger = logging.getLogger(__name__)

class ProjectScanWorker(QObject):
    """Worker thread for scanning project files."""
    
    progress = pyqtSignal(int)
    status_update = pyqtSignal(str)
    file_count_update = pyqtSignal(int)  # New signal for file counting progress
    station_found = pyqtSignal(str, dict)  # station_name, station_info
    scan_complete = pyqtSignal(dict)  # summary_data
    error = pyqtSignal(str)
    
    def __init__(self, project_dir: str, project_data: dict):
        """Initialize worker."""
        super().__init__()
        self.project_dir = project_dir
        self.project_data = project_data
        self.plugin_manager = PluginManager()
        self.plugin_manager.reload_plugins()
        self._is_cancelled = False
        
        # Initialize file name parser
        self.parser = FileNameParser(project_dir)
    
    def cancel(self):
        """Cancel the scanning process."""
        self._is_cancelled = True
    
    def run(self):
        """Run the scanning process."""
        try:
            self.status_update.emit("Start scanning...")
            
            # Determine data folder - use project directory as default
            data_folder = Path(self.project_dir)
            
            if not data_folder.exists():
                self.error.emit(f"Data folder does not exist: {data_folder}")
                return
            
            # Scan files
            self._scan_files(data_folder)
            
        except Exception as e:
            logger.error(f"Scanning error: {e}")
            self.error.emit(f"Scanning error: {str(e)}")
    
    def _scan_files(self, data_folder: Path):
        """Scan files in the data folder."""
        stations = defaultdict(lambda: {
            'files': [],
            'coordinates': None,
            'file_count': 0,
            'start_times': [],
            'end_times': []
        })
        
        # Get reader once before processing files
        try:
            _, reader = get_file_format_and_reader(self.project_data)
            if not reader:
                self.error.emit("No suitable reader found for the project format.")
                return
        except Exception as e:
            self.error.emit(f"Failed to get reader: {e}")
            return
        
        # Get all files in project folder, excluding tool4s output folder
        all_files = []
        file_count = 0
        
        self.status_update.emit("Scanning files...")
        
        for file_path in data_folder.rglob('*'):
            if self._is_cancelled:
                return
                
            # Skip directories
            if file_path.is_dir():
                continue
            # Skip tool4s output folder
            data_params = self.project_data.get('data_params', {})
            output_folder = data_params.get('outputFolder', 'output')
            if output_folder in file_path.parts:
                continue
            # Skip common non-data files
            if file_path.name in ['data.json', 'psd.json', 'README.md', '.gitignore']:
                continue
            # Skip hidden files and system files
            if file_path.name.startswith('.') or file_path.name.startswith('~'):
                continue
            
            all_files.append(file_path)
            file_count += 1
            
            # Update file count every 100 files to avoid too frequent updates
            if file_count % 100 == 0:
                self.file_count_update.emit(file_count)
                self.status_update.emit(f"Found {file_count} files...")
        
        # Final file count update
        self.file_count_update.emit(file_count)
        
        if not all_files:
            self.error.emit(f"In {data_folder} no files found.")
            return
        
        total_files = len(all_files)
        self.status_update.emit(f"Found {total_files} files, start parsing...")
        
        processed = 0
        for file_path in all_files:
            if self._is_cancelled:
                return
            
            try:
                # Process each file using the same method as format_change_dialog
                self._process_file(str(file_path.relative_to(self.project_dir)), stations, reader)
                
                processed += 1
                progress = int(processed / total_files * 100)
                self.progress.emit(progress)
                self.status_update.emit(f"Processed {processed}/{total_files} files...")
                
            except Exception as e:
                logger.warning(f"Processing file {file_path} failed: {e}")  
                processed += 1
        
        # Calculate overall time ranges for each station and the entire project
        project_start_times = []
        project_end_times = []
        
        for station_name, station_info in stations.items():
            if station_info['start_times']:
                station_start = min(station_info['start_times'])
                station_end = max(station_info['end_times']) if station_info['end_times'] else station_start
                station_info['overall_start_time'] = station_start
                station_info['overall_end_time'] = station_end
                
                project_start_times.append(station_start)
                project_end_times.append(station_end)
        
        # Calculate project overall time range
        project_overall_start = min(project_start_times) if project_start_times else None
        project_overall_end = max(project_end_times) if project_end_times else None
        
        # Prepare summary data
        summary = {
            'total_files': total_files,
            'total_stations': len(stations),
            'stations_with_coords': sum(1 for s in stations.values() if s['coordinates']),
            'project_start_time': project_overall_start,
            'project_end_time': project_overall_end,
            'stations': dict(stations)
        }
        
        self.scan_complete.emit(summary)
        self.status_update.emit("Scanning completed.")
    
    def _process_file(self, filepath: str, stations: dict, reader_class):
        """Process a single file to extract station information.
        
        Args:
            filepath: Relative path of file to process
            stations: Dictionary to store station information
            reader: Pre-obtained reader  for the file format
        """
        logger.info(f"Processing file: {filepath}")
        
        try:
            # Parse filename using FileNameParser
            success, parsed_parts, _, error = self.parser.parse_filename(Path(filepath).name)
            if not success:
                logger.warning(f"Cannot parse filename {filepath}: {error}")
                return
                
            # Get file info from parsed parts
            station_name = parsed_parts.get('Station', 'Unknown')
            print(station_name)
            channel = parsed_parts.get('Channel', 'Unknown')
            
            reader = reader_class()
            # Read header to get coordinates
            file_path = Path(self.project_dir) / filepath
            try:
                header_stream = reader.read_header(str(file_path))
                
                if header_stream and len(header_stream) > 0:
                    stats = header_stream[0].stats
                    print(stats)
                    # Extract coordinates if available
                    coordinates = None
                    if hasattr(stats, 'coordinates'):
                        coords = stats.coordinates
                        if coords and 'latitude' in coords and 'longitude' in coords:
                            lat = coords['latitude']
                            lon = coords['longitude']
                            
                            # Validate coordinate ranges
                            if not (-90 <= lat <= 90):
                                logger.warning(f"File {filepath} latitude out of range: {lat}, skip this station.")
                                return
                            if not (-180 <= lon <= 180):
                                logger.warning(f"File {filepath} longitude out of range: {lon}, skip this station.")
                                return
                            
                            coordinates = {
                                'latitude': lat,
                                'longitude': lon,
                                'elevation': coords.get('elevation', 0)
                            }
                            logger.debug(f"File {filepath} coordinates from attributes: {coordinates}")
                    elif hasattr(stats, 'sac') and stats.sac:
                        # SAC format coordinates
                        if hasattr(stats.sac, 'stla') and hasattr(stats.sac, 'stlo'):
                            # Note: stla is latitude, stlo is longitude
                            # Check if coordinates seem to be swapped (common issue)
                            lat_val = stats.sac.stla
                            lon_val = stats.sac.stlo
                            
                            # If latitude > longitude, they might be swapped
                            if lat_val > lon_val and lat_val > 90:
                                logger.warning(f"File {filepath} coordinates may be swapped: lat={lat_val}, lon={lon_val}, swap to: lon={lat_val}, lat={lon_val}")
                                lat_val, lon_val = lon_val, lat_val
                            
                            # Validate coordinate ranges after potential swap
                            if not (-90 <= lat_val <= 90):
                                logger.warning(f"File {filepath} latitude out of range: {lat_val}, skip this station.")
                                return
                            if not (-180 <= lon_val <= 180):
                                logger.warning(f"File {filepath} longitude out of range: {lon_val}, skip this station.")
                                return
                            
                            coordinates = {
                                'latitude': lat_val,
                                'longitude': lon_val,
                                'elevation': getattr(stats.sac, 'stel', 0)
                            }
                            logger.debug(f"File {filepath} coordinates from SAC attributes: {coordinates}")
                    
                    # Only process stations with valid coordinates
                    if not coordinates:
                        logger.debug(f"File {filepath} has no valid coordinate information, skip station: {station_name}")
                        return
                    
                    # Store station info
                    station_info = stations[station_name]
                    station_info['files'].append(filepath)
                    station_info['file_count'] += 1
                    
                    if coordinates and station_info['coordinates'] is None:
                        station_info['coordinates'] = coordinates
                    
                    # Store time info
                    if hasattr(stats, 'starttime'):
                        station_info['start_times'].append(stats.starttime)
                    if hasattr(stats, 'endtime'):
                        station_info['end_times'].append(stats.endtime)
                    
                    # Emit station found signal
                    self.station_found.emit(station_name, dict(station_info))
            
            except Exception as e:
                logger.warning(f"File {filepath} header read error: {e}")
                
        except Exception as e:
            logger.error(f"Error processing file {filepath}: {str(e)}")
            raise


class ProjectScanDialog(QDialog):
    """Dialog for scanning and analyzing project data."""
    
    def __init__(self, project_dir: str, parent=None):
        """Initialize dialog."""
        super().__init__(parent)
        self.project_dir = project_dir
        self.project_data = None
        self.worker = None
        self.thread = None
        self.stations_data = {}
        
        # Load project data
        self._load_project_data()
        
        # Initialize UI
        self._init_ui()
        
       
    
    def _load_project_data(self):
        """Load project data from data.json."""
        try:
            data_json_path = Path(self.project_dir) / 'data.json'
            if data_json_path.exists():
                with open(data_json_path, 'r', encoding='utf-8') as f:
                    self.project_data = json.load(f)
        except Exception as e:
            logger.error(f"Error loading project data.json: {e}")
    
    def _init_ui(self):
        """Initialize UI components."""
        self.setWindowTitle("Project Scan")
        set_dialog_size(self, 0.8, 0.7)
        center_dialog(self)
        
        layout = QVBoxLayout()
        
        # Create splitter for main content
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel - Station list and info
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Station table
        station_group = QGroupBox(" Detected Stations")
        station_layout = QVBoxLayout()
        
        self.station_table = QTableWidget()
        self.station_table.setColumnCount(4)
        self.station_table.setHorizontalHeaderLabels(["Station Name", "Latitude", "Longitude", "Elevation"])
        
        # Set column widths
        header = self.station_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        
        self.station_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.station_table.itemSelectionChanged.connect(self._on_station_selected)
        station_layout.addWidget(self.station_table)
        
        station_group.setLayout(station_layout)
        left_layout.addWidget(station_group)
        
        # Info display
        info_group = QGroupBox(" Station Information")
        info_layout = QVBoxLayout()
        
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(200)
        info_layout.addWidget(self.info_text)
        
        info_group.setLayout(info_layout)
        left_layout.addWidget(info_group)
        
        # Right panel - Plot
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        plot_group = QGroupBox(" Station Distribution Plot")
        plot_layout = QVBoxLayout()
        
        # Create matplotlib figure
        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        
        # Add navigation toolbar for zoom/pan tools
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.canvas)
        plot_group.setLayout(plot_layout)
        right_layout.addWidget(plot_group)
        
        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 500])
        
        layout.addWidget(splitter)
        
        # Progress and status
        progress_layout = QHBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.status_label = QLabel("Ready to scan...")
        
        progress_layout.addWidget(self.status_label)
        progress_layout.addWidget(self.progress_bar)
        
        layout.addLayout(progress_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.refresh_button = QPushButton("Scan")
        self.refresh_button.clicked.connect(self._start_scan)
        self.refresh_button.setEnabled(True)

        self.load_metadata_button = QPushButton("Load Station Metadata")
        self.load_metadata_button.clicked.connect(self._load_station_metadata)
        
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_button)
        button_layout.addWidget(self.load_metadata_button)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _load_station_metadata(self):
        """Load station metadata from external file (StationXML or text file)."""
        file_dialog = QFileDialog()
        file_path, _ = file_dialog.getOpenFileName(
            self,
            "Load Station Metadata",
            "",
            "StationXML files (*.xml);;Text files (*.txt);;All files (*.*)"
        )
        
        if not file_path:
            return
        
        try:
            if file_path.lower().endswith('.xml'):
                self._load_stationxml(file_path)
            else:
                self._load_text_metadata(file_path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load metadata: {str(e)}")
    
    def _load_stationxml(self, file_path: str):
        """Load station coordinates from StationXML file using obspy."""
        try:
            # Use obspy to read the inventory
            inventory = read_inventory(file_path)
            
            loaded_count = 0
            updated_count = 0
            
            # Iterate through networks and stations
            for network in inventory:
                for station in network:
                    station_code = station.code
                    if not station_code:
                        continue
                    
                    # Get coordinates from station
                    lat = station.latitude
                    lon = station.longitude
                    elev = station.elevation if station.elevation is not None else 0.0
                    
                    if lat is not None and lon is not None:
                        try:
                            # Validate coordinates
                            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                                logger.warning(f"Invalid coordinates for station {station_code}: lat={lat}, lon={lon}")
                                continue
                            
                            coordinates = {
                                'latitude': lat,
                                'longitude': lon,
                                'elevation': elev
                            }
                            
                            # Update existing station or create new one
                            if station_code in self.stations_data:
                                self.stations_data[station_code]['coordinates'] = coordinates
                                updated_count += 1
                            else:
                                # Create new station entry
                                self.stations_data[station_code] = {
                                    'files': [],
                                    'coordinates': coordinates,
                                    'file_count': 0,
                                    'start_times': [],
                                    'end_times': []
                                }
                                loaded_count += 1
                            
                        except ValueError as e:
                            logger.warning(f"Invalid coordinate values for station {station_code}: {e}")
                            continue
            
            # Update UI
            self._update_station_table()
            self._update_plot()
            
            QMessageBox.information(
                self, 
                "Metadata Loaded", 
                f"Successfully loaded metadata for {loaded_count} new stations and updated {updated_count} existing stations."
            )
            
        except Exception as e:
            raise Exception(f"StationXML loading error: {e}")
    
    def _load_text_metadata(self, file_path: str):
        """Load station coordinates from text file.
        
        Expected format: station_name, latitude, longitude, elevation (optional)
        Lines starting with # are treated as comments.
        """
        loaded_count = 0
        updated_count = 0
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                
                try:
                    parts = [part.strip() for part in line.split(',')]
                    
                    if len(parts) < 3:
                        logger.warning(f"Line {line_num}: insufficient data (need at least station, lat, lon)")
                        continue
                    
                    station_name = parts[0]
                    lat = float(parts[1])
                    lon = float(parts[2])
                    elev = float(parts[3]) if len(parts) > 3 else 0.0
                    
                    # Validate coordinates
                    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                        logger.warning(f"Line {line_num}: invalid coordinates for station {station_name}: lat={lat}, lon={lon}")
                        continue
                    
                    coordinates = {
                        'latitude': lat,
                        'longitude': lon,
                        'elevation': elev
                    }
                    
                    # Update existing station or create new one
                    if station_name in self.stations_data:
                        self.stations_data[station_name]['coordinates'] = coordinates
                        updated_count += 1
                    else:
                        # Create new station entry
                        self.stations_data[station_name] = {
                            'files': [],
                            'coordinates': coordinates,
                            'file_count': 0,
                            'start_times': [],
                            'end_times': []
                        }
                        loaded_count += 1
                        
                except ValueError as e:
                    logger.warning(f"Line {line_num}: invalid data format: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Line {line_num}: error processing line: {e}")
                    continue
        
        # Update UI
        self._update_station_table()
        self._update_plot()
        
        QMessageBox.information(
            self, 
            "Metadata Loaded", 
            f"Successfully loaded metadata for {loaded_count} new stations and updated {updated_count} existing stations."
        )
    
    def _update_station_table(self):
        """Update the station table with current station data."""
        self.station_table.setRowCount(0)
        
        for station_name, station_info in self.stations_data.items():
            coords = station_info.get('coordinates')
            if coords:
                row_count = self.station_table.rowCount()
                self.station_table.insertRow(row_count)
                
                self.station_table.setItem(row_count, 0, QTableWidgetItem(station_name))
                self.station_table.setItem(row_count, 1, QTableWidgetItem(f"{coords['latitude']:.6f}"))
                self.station_table.setItem(row_count, 2, QTableWidgetItem(f"{coords['longitude']:.6f}"))
                self.station_table.setItem(row_count, 3, QTableWidgetItem(f"{coords.get('elevation', 0):.2f}"))
    
    def _add_station_to_table(self, station_name: str, station_info: dict):
        """Add a station to the table with real-time update."""
        coords = station_info.get('coordinates')
        if not coords:
            return
            
        # Add new row
        row_count = self.station_table.rowCount()
        self.station_table.insertRow(row_count)
        
        # Set station data
        self.station_table.setItem(row_count, 0, QTableWidgetItem(station_name))
        self.station_table.setItem(row_count, 1, QTableWidgetItem(f"{coords['latitude']:.6f}"))
        self.station_table.setItem(row_count, 2, QTableWidgetItem(f"{coords['longitude']:.6f}"))
        self.station_table.setItem(row_count, 3, QTableWidgetItem(f"{coords.get('elevation', 0):.2f}"))
        
        # Update plot in real-time
        self._update_plot_realtime(station_name, station_info)
    
    def _convert_coordinates(self, lat: float, lon: float) -> tuple:
        """Convert latitude/longitude to UTM coordinates.
        
        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            
        Returns:
            Tuple of (x, y) coordinates in UTM
        """
        try:
            logger.debug(f"Input coordinates conversion: lat={lat}, lon={lon}")
            
            # Check if input coordinates are valid
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                logger.warning(f"Input coordinates out of valid range: lat={lat}, lon={lon}")
                return None, None
            
            # Convert to UTM coordinates
            x, y, zone_number, zone_letter = utm.from_latlon(lat, lon)
            logger.debug(f"Converted UTM coordinates: x={x}, y={y}, zone={zone_number}{zone_letter}")
            
            return x, y
        except Exception as e:
            logger.warning(f"UTM coordinates conversion failed: {e}")
            return None, None
    
    def _update_plot_realtime(self, station_name: str, station_info: dict):
        """Update plot with new station in real-time."""
        coords = station_info.get('coordinates')
        if not coords or 'latitude' not in coords or 'longitude' not in coords:
            # Skip plotting if coordinates are not available
            logger.debug(f"Skip plotting station {station_name}: missing coordinates")
            return
        
        logger.debug(f"Real-time update plot, add station: {station_name}")
        
        # Clear and redraw all stations to ensure consistency
        self.ax.clear()
        
        # Re-initialize plot settings
        self.ax.set_xlabel('X Coordinate (m)')
        self.ax.set_ylabel('Y Coordinate (m)')
        self.ax.set_title(' Station Distribution Plot')
        self.ax.grid(True, alpha=0.3)
        
        # Collect all station coordinates including the new one
        x_coords, y_coords, names = [], [], []
        
        for name, info in self.stations_data.items():
            station_coords = info.get('coordinates')
            if station_coords and 'latitude' in station_coords and 'longitude' in station_coords:
                lat = station_coords['latitude']
                lon = station_coords['longitude']
                
                logger.debug(f"Station {name} coordinates: lat={lat}, lon={lon}")
                
                # Convert to x,y coordinates
                x, y = self._convert_coordinates(lat, lon)
                logger.debug(f"Station {name} converted coordinates: x={x}, y={y}")
                
                # Check if converted coordinates are reasonable
                if abs(x) > 1e10 or abs(y) > 1e10:
                    logger.warning(f"Station {name} converted coordinates out of valid range: x={x}, y={y}")
                    continue
                
                x_coords.append(x)
                y_coords.append(y)
                names.append(name)
        
        # Plot all stations if we have coordinates
        if x_coords:
            logger.debug(f"Plotting {len(x_coords)} stations, coordinate range: x=[{min(x_coords):.2f}, {max(x_coords):.2f}], y=[{min(y_coords):.2f}, {max(y_coords):.2f}]")
            
            # Plot stations with larger markers for better visibility
            scatter = self.ax.scatter(x_coords, y_coords, c='blue', s=100, alpha=0.8, label='Stations', edgecolors='black', linewidth=1)
            
            # Add station labels
            for x, y, name in zip(x_coords, y_coords, names):
                self.ax.annotate(name, (x, y), xytext=(5, 5), 
                               textcoords='offset points', fontsize=10, fontweight='bold')
            
            # Set axis limits with some padding
            x_range = max(x_coords) - min(x_coords)
            y_range = max(y_coords) - min(y_coords)
            padding_x = x_range * 0.1 if x_range > 0 else 1000
            padding_y = y_range * 0.1 if y_range > 0 else 1000
            
            self.ax.set_xlim(min(x_coords) - padding_x, max(x_coords) + padding_x)
            self.ax.set_ylim(min(y_coords) - padding_y, max(y_coords) + padding_y)
            
            self.ax.legend()
        else:
            logger.debug("No valid station coordinates available for plotting")
            self.ax.text(0.5, 0.5, 'No valid station coordinates available', 
                        ha='center', va='center', transform=self.ax.transAxes, fontsize=14)
        
        # Refresh canvas
        self.canvas.draw()
        logger.debug("Station distribution plot updated successfully")

    def _on_station_found(self, station_name: str, station_info: dict):
        """Handle station found signal with real-time updates."""
        # Only add if this is a new station
        if station_name not in self.stations_data:
            # Check if station has valid coordinates
            coords = station_info.get('coordinates')
            if coords and 'latitude' in coords and 'longitude' in coords:
                lat = coords['latitude']
                lon = coords['longitude']
                
                # Validate coordinate ranges
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    # Test coordinate conversion to ensure it works
                    x, y = self._convert_coordinates(lat, lon)
                    if x is not None and y is not None:
                        # Only add station if coordinates are valid and conversion succeeds
                        self.stations_data[station_name] = station_info
                        # Add to table immediately for new stations only
                        self._add_station_to_table(station_name, station_info)
                        # Add to plot immediately if coordinates are available
                        self._update_plot_realtime(station_name, station_info)
                        logger.debug(f"Station {station_name} added to table and plot, coordinates: lat={lat}, lon={lon}")
                    else:
                        logger.warning(f"Station {station_name} coordinate conversion failed, skipped: lat={lat}, lon={lon}")
                else:
                    logger.warning(f"Station {station_name} coordinates out of valid range: lat={lat}, lon={lon}")
            else:
                logger.debug(f"Station {station_name} missing valid coordinate information, skipped")
    
    def _on_progress_update(self, progress: int):
        """Handle progress update during file processing phase."""
        # Map 0-100% file processing progress to 10-100% total progress
        total_progress = 10 + int(progress * 0.9)
        self.progress_bar.setValue(total_progress)
    
    def _on_file_count_update(self, file_count: int):
        """Handle file count update during scanning phase."""
        # Update progress bar to show file counting progress (use a small percentage)
        # Reserve 0-10% for file counting, 10-100% for file processing
        progress = min(10, int(file_count / 1000))  # Assume max 1000 files for 10%
        self.progress_bar.setValue(progress)
    
    def _on_scan_complete(self, summary: dict):
        """Handle scan completion."""
        self.stations_data = summary['stations']
        
        # Update info display with time information
        info_text = f"""Project scan completed successfully!

Total files processed: {summary['total_files']}
Total stations detected: {summary['total_stations']}
Stations with valid coordinates: {summary['stations_with_coords']}

Project Time Range:
Start: {summary['project_start_time'].strftime('%Y-%m-%d %H:%M:%S') if summary['project_start_time'] else 'N/A'}
End: {summary['project_end_time'].strftime('%Y-%m-%d %H:%M:%S') if summary['project_end_time'] else 'N/A'}

Station details:
"""
        
        for station_name, station_info in self.stations_data.items():
            coords = station_info.get('coordinates')
            coord_str = f"({coords['latitude']:.4f}, {coords['longitude']:.4f})" if coords else "无坐标"
            
            # Add time information for each station
            start_time_str = station_info.get('overall_start_time').strftime('%Y-%m-%d %H:%M:%S') if station_info.get('overall_start_time') else 'N/A'
            end_time_str = station_info.get('overall_end_time').strftime('%Y-%m-%d %H:%M:%S') if station_info.get('overall_end_time') else 'N/A'
            
            info_text += f"• {station_name}: {station_info['file_count']} files, coordinates: {coord_str}\n"
            info_text += f"  Time range: {start_time_str} to {end_time_str}\n"
        
        self.info_text.setText(info_text)
        
        # Update plot
        self._update_plot()
        
        # Note: Buttons will be re-enabled in _on_thread_finished
        self.refresh_button.setEnabled(True)
        self.load_metadata_button.setEnabled(True)
    
    def _on_error(self, error_msg: str):
        """Handle error signal."""
        QMessageBox.critical(self, "Error", error_msg)
        # Re-enable buttons after error
        self.refresh_button.setEnabled(True)
        self.load_metadata_button.setEnabled(True)
    
    def _on_thread_finished(self):
        """Handle thread completion."""
        # Re-enable buttons after scanning
        self.refresh_button.setEnabled(True)
        self.load_metadata_button.setEnabled(True)
        
        if self.thread:
            self.thread.deleteLater()
            self.thread = None
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
    
    def _on_station_selected(self):
        """Handle station selection in table."""
        current_row = self.station_table.currentRow()
        if current_row < 0:
            return
        
        station_name_item = self.station_table.item(current_row, 0)
        if not station_name_item:
            return
        
        station_name = station_name_item.text()
        station_info = self.stations_data.get(station_name)
        
        if station_info:
            # Highlight selected station in plot
            self._update_plot(highlight_station=station_name)
    
    def _update_plot(self, highlight_station: str = None):
        """Update the station distribution plot using x,y coordinates."""
        self.ax.clear()
        
        # Collect coordinates
        x_coords, y_coords, names = [], [], []
        highlight_x, highlight_y = None, None
        
        for station_name, station_info in self.stations_data.items():
            coords = station_info.get('coordinates')
            if coords:
                lat = coords['latitude']
                lon = coords['longitude']
                
                # Convert to x,y coordinates
                x, y = self._convert_coordinates(lat, lon)
                x_coords.append(x)
                y_coords.append(y)
                names.append(station_name)
                
                if station_name == highlight_station:
                    highlight_x, highlight_y = x, y
        
        if not x_coords:
            self.ax.text(0.5, 0.5, 'No valid coordinate data available', 
                        ha='center', va='center', transform=self.ax.transAxes)
            self.canvas.draw()
            return
        
        # Plot all stations
        self.ax.scatter(x_coords, y_coords, c='blue', s=50, alpha=0.7, label='Stations')
        
        # Highlight selected station
        if highlight_x is not None and highlight_y is not None:
            self.ax.scatter([highlight_x], [highlight_y], c='red', s=100, 
                          marker='*', label='Selected Station')
        
        # Add station labels
        for x, y, name in zip(x_coords, y_coords, names):
            self.ax.annotate(name, (x, y), xytext=(5, 5), 
                           textcoords='offset points', fontsize=8)
        
        self.ax.set_xlabel('X Coordinate (m)')
        self.ax.set_ylabel('Y Coordinate (m)')
        self.ax.set_title('Station Distribution Plot')
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()
        
        # Adjust layout
        self.figure.tight_layout()
        self.canvas.draw()
    
    def closeEvent(self, event):
        """Handle dialog close event."""
        if self.worker:
            self.worker.cancel()
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(3000)  # Wait up to 3 seconds
        event.accept()


    def _start_scan(self):
        """Start the scanning process."""
        if not self.project_data:
            QMessageBox.warning(self, "Warning", "No project data found. Please ensure data.json exists in the project directory.")
            return
        
        # Clear previous data
        self.stations_data.clear()
        self.station_table.setRowCount(0)
        self.info_text.clear()
        self.ax.clear()
        self.canvas.draw()
        
        # Disable buttons during scanning
        self.refresh_button.setEnabled(False)
        self.load_metadata_button.setEnabled(False)
        
        # Reset progress bar
        self.progress_bar.setValue(0)
        
        # Create worker and thread
        self.worker = ProjectScanWorker(self.project_dir, self.project_data)
        self.thread = QThread()
        
        # Move worker to thread
        self.worker.moveToThread(self.thread)
        
        # Connect signals
        self.worker.progress.connect(self._on_progress_update)
        self.worker.status_update.connect(self.status_label.setText)
        self.worker.file_count_update.connect(self._on_file_count_update)
        self.worker.station_found.connect(self._on_station_found)
        self.worker.scan_complete.connect(self._on_scan_complete)
        self.worker.error.connect(self._on_error)
        
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self._on_thread_finished)
        
        # Start thread
        self.thread.start()