"""
Plot widget for displaying seismic data.
"""

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
                           QLabel, QPushButton, QSizePolicy, QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import matplotlib
matplotlib.use('Qt5Agg')
# Optimize matplotlib settings for performance
matplotlib.rcParams['path.simplify'] = True
matplotlib.rcParams['path.simplify_threshold'] = 1.0
matplotlib.rcParams['agg.path.chunksize'] = 10000
# Disable animations for better performance
matplotlib.rcParams['animation.html'] = 'none'
# Use a faster renderer
matplotlib.rcParams['figure.facecolor'] = 'white'
matplotlib.rcParams['figure.autolayout'] = False
# Optimize line plotting
matplotlib.rcParams['lines.antialiased'] = True
matplotlib.rcParams['lines.dash_capstyle'] = 'butt'

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import numpy as np
from obspy import Stream
import logging
import os
import json
from pathlib import Path
import traceback
from core.plugin_manager import PluginManager
from utils.constants import DEFAULT_OUTPUT_FOLDER, PSD_FOLDER_NAME, PSD_FILE_EXTENSION

logger = logging.getLogger(__name__)

class PlotWorker(QThread):
    """Worker thread for loading and plotting data."""
    
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    plot_ready = pyqtSignal(list, list, str, object)  # New signal for plot data
    
    def __init__(self, file_path: str, project_dir: str, plugin_manager, ax, canvas, enable_downsampling=True, chunk_size=10000, selected_traces=None):
        """Initialize worker.
        
        Args:
            file_path: Path to the data file
            project_dir: Project directory path
            plugin_manager: Plugin manager instance
            ax: Matplotlib axes object
            canvas: Matplotlib canvas object
            enable_downsampling: Whether to enable downsampling (default value)
            chunk_size: Number of points to plot (default value)
            selected_traces: List of trace indices to plot
        """
        super().__init__()
        self.file_path = file_path
        self.project_dir = project_dir
        self.plugin_manager = plugin_manager
        self.ax = ax
        self.canvas = canvas
        self.enable_downsampling = bool(enable_downsampling)  # Ensure boolean
        self.chunk_size = int(chunk_size)  # Ensure integer
        self.selected_traces = selected_traces
        
        # Load plot parameters from data.json
        try:
            if project_dir:
                data_json_path = os.path.join(project_dir, 'data.json')
                if os.path.exists(data_json_path):
                    with open(data_json_path, 'r', encoding='utf-8') as f:
                        data_config = json.load(f)
                        plot_params = data_config.get('plot_params', {})
                        self.enable_downsampling = bool(plot_params.get('enable_downsampling', self.enable_downsampling))
                        self.chunk_size = int(plot_params.get('chunk_size', self.chunk_size))
                        logger.info(f"Loaded plot parameters from data.json: enable_downsampling={self.enable_downsampling}, chunk_size={self.chunk_size}")
                else:
                    logger.warning(f"data.json not found at {data_json_path}, using default values")
            else:
                logger.warning("Project directory not set, using default values")
        except Exception as e:
            logger.warning(f"Could not load plot parameters from data.json: {e}")
            
        logger.info(f"PlotWorker initialized with enable_downsampling={self.enable_downsampling}, chunk_size={self.chunk_size}")
        
    def run(self):
        """Load and plot data in separate thread."""
        try:
            # Load data
            self.progress.emit("Loading data file...")
            file_path = Path(self.file_path)
            
            # Check if file is a PSD file (in PSD folder and has .npz extension)
            if file_path.suffix.lower() == PSD_FILE_EXTENSION and PSD_FOLDER_NAME in file_path.parts:
                self._plot_psd_file(file_path)
                return
                
            # For non-PSD files, require project directory and data.json
            if not self.project_dir:
                raise ValueError("Project directory is required for non-PSD files")
                
            # Load data.json from project directory
            data_json_path = os.path.join(self.project_dir, 'data.json')
            if not os.path.exists(data_json_path):
                raise ValueError("data.json not found in project directory. Please set up project parameters first.")
                
            with open(data_json_path, 'r', encoding='utf-8') as f:
                data_config = json.load(f)
                
            # Check if file is in output folder
            output_default = Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER
            output_dir = Path(data_config.get('data_params', {}).get('outputFolder', output_default))
            
            # If file is in output folder, get format from suffix
            # Normalize both paths for comparison
            output_dir = output_dir.absolute()
            
            if output_dir in file_path.parents: 
                format_type = file_path.suffix[1:].lower()  # Remove the dot from suffix
            else:
                # Get format from data_params
                if 'data_params' not in data_config:
                    raise ValueError("data_params not found in data.json. Please set up project parameters first.")
                format_type = data_config['data_params'].get('dataFormat', 'MSEED').lower()
                if not format_type:
                    raise ValueError("Data format not specified in data.json. Please set up project parameters first.")
            
            # Get reader for format - try both with and without dot
            reader_class = self.plugin_manager.get_available_readers().get(f".{format_type}") or \
                          self.plugin_manager.get_available_readers().get(format_type)
            if not reader_class:
                raise ValueError(f"Unsupported data format: {format_type}")
                
            # Read data - returns ObsPy Stream
            reader = reader_class()
            stream = reader.read(self.file_path)
            
            if stream is None or len(stream) == 0:
                raise ValueError("No data found in file")
                
            self.progress.emit("Data loaded successfully")
            
            # Get traces to plot
            traces_to_plot = stream
            if self.selected_traces is not None:
                traces_to_plot = [stream[i] for i in self.selected_traces]
                
            self.progress.emit("Processing data...")
            
            # Prepare plot data
            plot_data = []
            labels = []
            start_time = None
            
            for tr in traces_to_plot:
                # Get trace start time
                if start_time is None:
                    start_time = tr.stats.starttime
                
                # Get times in matplotlib format
                times = tr.times("matplotlib")
                
                # Verify times are valid
                if not np.all(np.isfinite(times)) or np.any(times < 0):
                    logger.warning(f"Invalid times detected in trace {tr.stats.channel}, using relative times")
                    times = np.arange(len(tr.data)) / tr.stats.sampling_rate
                
                data = tr.data
                
                # Downsample if enabled and needed
                if self.enable_downsampling and len(times) > self.chunk_size:
                    logger.info(f"Downsampling trace from {len(times)} points to {self.chunk_size} points")
                    # Use numpy's linspace for efficient downsampling with exact number of points
                    indices = np.linspace(0, len(times)-1, self.chunk_size, dtype=int)
                    times = times[indices]
                    data = data[indices]
                    logger.info(f"After downsampling: {len(times)} points")
                else:
                    # When downsampling is disabled, use numpy arrays directly
                    times = np.array(times)
                    data = np.array(data)
                    logger.info(f"No downsampling applied: enable_downsampling={self.enable_downsampling}, data points={len(times)}, chunk_size={self.chunk_size}")
                
                # Store channel name before freeing the trace
                channel = tr.stats.channel
                
                plot_data.append((times, data))
                labels.append(channel)
                
                # Free memory for large arrays - do this at the end of each iteration
                del times, data
            
            # Get title
            title = None
            if traces_to_plot:
                start_time_str = traces_to_plot[0].stats.starttime.strftime('%Y-%m-%d %H:%M:%S')
                title = f'Start Time: {start_time_str}'
            self.progress.emit("Plot ready")
            # Emit plot data to main thread
            self.plot_ready.emit(plot_data, labels, title, start_time)
            
            self.progress.emit("Plot completed successfully")
            
        except Exception as e:
            logger.error(f"Error in plot worker: {e}")
            self.error.emit(str(e))
            
        self.finished.emit()
        
    def _plot_psd_file(self, file_path):
        """Plot PSD data from .npz file."""
        try:
            self.progress.emit("Loading PSD data...")
            
            # Load PSD data
            psd_data = self._load_psd_data(file_path)
            if not psd_data:
                raise ValueError("Failed to load PSD data")
                
            # Load noise models
            noise_models = self._load_noise_models()
            
            # Prepare plot data
            plot_data, labels = self._prepare_psd_plot_data(psd_data, noise_models)
            
            # Get title from filename
            title = f'PSD: {file_path.stem}'
            
            self.progress.emit("Plot ready")
            # Emit plot data to main thread
            self.plot_ready.emit(plot_data, labels, title, None)
            
            self.progress.emit("Plot completed successfully")
            
        except Exception as e:
            logger.error(f"Error plotting PSD: {e}")
            raise
            
    def _load_psd_data(self, file_path):
        """Load PSD data from .npz file.
        
        Args:
            file_path: Path to the PSD file
            
        Returns:
            dict: Dictionary containing PSD data
        """
        try:
            data = np.load(file_path)
            return {
                'frequencies': data['frequencies'],
                'psd': data['psd'],
                'f_smoothed': data['f_smoothed'],
                'smoothed_psd': data['smoothed_psd']
            }
        except Exception as e:
            logger.error(f"Error loading PSD data: {e}")
            return None
            
    def _load_noise_models(self):
        """Load noise models from file.
        
        Returns:
            dict: Dictionary containing noise model data or None if not found
        """
        try:
            # Load noise models - use Path for cross-platform compatibility
            noise_models_path = Path(__file__).parent.parent / 'core' / 'data' / 'noise_models.npz'
            if not noise_models_path.exists():
                logger.warning(f"Noise models file not found: {noise_models_path}")
                return None
                
            noise_models = np.load(noise_models_path)
            model_periods = noise_models['model_periods']
            nlnm = noise_models['low_noise']
            nhnm = noise_models['high_noise']
            
            return {
                'frequency': 1/model_periods[::-1],
                'nlnm': nlnm[::-1],
                'nhnm': nhnm[::-1]
            }
        except Exception as e:
            logger.error(f"Error loading noise models: {e}")
            return None
            
    def _prepare_psd_plot_data(self, psd_data, noise_models):
        """Prepare data for PSD plotting.
        
        Args:
            psd_data: Dictionary containing PSD data
            noise_models: Dictionary containing noise model data
            
        Returns:
            tuple: (plot_data, labels) for plotting
        """
        plot_data = []
        labels = []
        
        # Add PSD data
        plot_data.append((psd_data['frequencies'], psd_data['psd']))
        labels.append('PSD')
        
        # Add smoothed PSD data
        plot_data.append((psd_data['f_smoothed'], psd_data['smoothed_psd']))
        labels.append('Smoothed PSD')
        
        # Add noise models if available
        if noise_models is not None:
            plot_data.append((noise_models['frequency'], noise_models['nlnm']))
            labels.append('NLNM')
            plot_data.append((noise_models['frequency'], noise_models['nhnm']))
            labels.append('NHNM')
            
        return plot_data, labels

class PlotWidget(QWidget):
    """Widget for loading and plotting seismic data."""
    
    # Signals
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()
    loading_error = pyqtSignal(str)
    progress_updated = pyqtSignal(str)
    
    def __init__(self, parent=None):
        """Initialize the widget."""
        super().__init__(parent)
        
        # Initialize components
        self.plugin_manager = PluginManager()
        self.worker = None
        self.is_loading = False
        self.project_dir = None
        self.stream = None
        self.is_plotting = False
        self.enable_downsampling = True
        self.chunk_size = 10000
        
        # Load plugins at startup
        self.plugin_manager.reload_plugins()
        
        # Initialize UI
        self._init_ui()
        
    def _init_ui(self):
        """Initialize UI components."""
        layout = QVBoxLayout()
        
        # Create figure and canvas with optimized settings
        self.figure = Figure(dpi=100)  # Reduced DPI for better performance
        self.figure.set_tight_layout(False)  # Disable tight layout for better performance
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.canvas)
        
        # Create subplot with optimized settings
        self.ax = self.figure.add_subplot(111)
        self.ax.set_adjustable('datalim')  # Optimize axis adjustments
        self.setLayout(layout)
        
    def set_project_dir(self, project_dir):
        """Set the project directory."""
        self.project_dir = project_dir
        logger.info(f"Project directory set to: {project_dir}")
        
    def load_file(self, file_path: str, project_dir: str, format_type: str = None):
        """Load and plot data file.
        
        Args:
            file_path: Path to the data file
            project_dir: Project directory path
            format_type: Optional format type override
        """
        if self.is_loading:
            return
            
        self.is_loading = True
        self.loading_started.emit()
        
        # Create worker thread
        self.worker = PlotWorker(
            file_path=file_path,
            project_dir=project_dir,
            plugin_manager=self.plugin_manager,
            ax=self.ax,
            canvas=self.canvas
        )
        
        # Connect signals
        self.worker.finished.connect(self._on_plot_finished)
        self.worker.error.connect(self._on_plot_error)
        self.worker.progress.connect(self._on_plot_progress)
        self.worker.plot_ready.connect(self._on_plot_ready)
        
        # Start worker
        self.worker.start()

    def load_psd_file(self, file_path: str):
        """Load and plot PSD file.
        
        Args:
            file_path: Path to the PSD file
        """
        if self.is_loading:
            return
            
        self.is_loading = True
        self.loading_started.emit()
        
        # Create worker thread
        self.worker = PlotWorker(
            file_path=file_path,
            project_dir=None,  # Not needed for PSD files
            plugin_manager=self.plugin_manager,
            ax=self.ax,
            canvas=self.canvas
        )
        
        # Connect signals
        self.worker.finished.connect(self._on_plot_finished)
        self.worker.error.connect(self._on_plot_error)
        self.worker.progress.connect(self._on_plot_progress)
        self.worker.plot_ready.connect(self._on_plot_ready)
        
        # Start worker
        self.worker.start()

    def _on_plot_finished(self):
        """Handle plot completion."""
        self.is_plotting = False
        self.is_loading = False
        self.loading_finished.emit()
        
    def _on_plot_error(self, error_msg: str):
        """Handle plot error."""
        self.clear()
        self.is_plotting = False
        self.is_loading = False
        self.loading_error.emit(error_msg)
        logger.error(f"Plot error: {error_msg}")
        QMessageBox.critical(self, "Plot Error", f"Failed to plot data: {error_msg}")
        if hasattr(self.parent(), 'statusBar'):
            self.parent().statusBar().showMessage("Plot error")
            
    def _on_plot_progress(self, message: str):
        """Handle plot progress updates."""
        logger.info(f"Plot progress: {message}")  # Use logger instead of print
        self.progress_updated.emit(message)  # Emit signal for status bar update
        
    def _on_plot_ready(self, plot_data, labels, title, start_time):
        """Handle plot data ready."""
        try:
            # Draw the plot
            self._draw_plot(plot_data, labels, title, start_time)
            # Reset loading state
            self.is_loading = False
            self.loading_finished.emit()
        except Exception as e:
            logger.error(f"Error in plot ready handler: {e}")
            self._on_plot_error(str(e))
        
    def _cleanup_worker(self):
        """Clean up any existing worker thread."""
        if self.worker is not None:
            if self.worker.isRunning():
                logger.debug("Waiting for worker thread to finish...")
                self.worker.wait()  # Wait for the thread to finish
            self.worker.deleteLater()
            self.worker = None
        self.is_plotting = False
        self.is_loading = False  # Ensure loading state is reset
        
    def clear(self):
        """Clear the plot."""
        # Clean up any existing worker
        self._cleanup_worker()
        
        # Clear the plot
        if hasattr(self, 'ax') and self.ax:
            self.ax.clear()
            
        # Force garbage collection for large arrays
        import gc
        gc.collect()
        
        if hasattr(self, 'canvas') and self.canvas:
            self.canvas.draw()
            
        self.stream = None
        
    def closeEvent(self, event):
        """Handle widget close event."""
        self._cleanup_worker()
        super().closeEvent(event) 

    def is_loading_data(self):
        """Check if currently loading data."""
        return self.is_loading 

    def _draw_plot(self, plot_data, labels, title, start_time):
        """Draw plot in main thread with prepared data."""
        try:
            # Clear previous plot
            self.ax.clear()
            
            # Check if this is a PSD plot by looking at the first label
            is_psd_plot = labels and labels[0] == 'PSD'
            
            if is_psd_plot:
                # Plot PSD data with specific styling
                for (x, y), label in zip(plot_data, labels):
                    if label in ['NLNM', 'NHNM']:
                        # Plot noise models with gray color and thinner line
                        self.ax.plot(x, y, color='0.4', linewidth=1, label=label, zorder=1)
                    else:
                        # Plot PSD data with blue/red color
                        color = 'b' if label == 'PSD' else 'r'
                        self.ax.plot(x, y, color=color, label=label)
                
                # Set PSD-specific labels and formatting
                self.ax.set_xlabel('Frequency (Hz)')
                self.ax.set_ylabel('Power Spectral Density (dB)')
                self.ax.set_xscale('log')
                self.ax.grid(True)
            else:
                # Plot regular time series data
                for (times, data), label in zip(plot_data, labels):
                    self.ax.plot(times, data, 
                               label=label,
                               linewidth=0.5,
                               alpha=0.8,
                               animated=False,
                               snap=True,
                               rasterized=True,  # Rasterize for better performance
                               antialiased=False,  # Disable antialiasing for better performance
                               drawstyle='steps-post',  # Use steps for better performance
                               markevery=100)  # Reduce number of points plotted
                
                # Set time series specific labels
                self.ax.set_xlabel('Time')
                self.ax.set_ylabel('Amplitude')
                
                # Format x-axis to show datetime if using matplotlib times
                if len(plot_data) > 0:
                    times = plot_data[0][0]
                    # Check if these are matplotlib dates (which are days since 0001-01-01)
                    # A better check than just value size is to see if the range makes sense
                    # Modern matplotlib dates are typically > 700000 (around year 1900)
                    if start_time is not None or (np.min(times) > 700000 and np.max(times) < 800000):
                        self.ax.xaxis_date()  # Enable datetime formatting
                        self.ax.figure.autofmt_xdate()  # Rotate and align the tick labels
                        
                        # Set reasonable time limits
                        if len(times) > 0:
                            self.ax.set_xlim(times[0], times[-1])
            
            # Add legend if there are multiple traces
            if len(labels) > 1:
                self.ax.legend(loc='upper right', frameon=False)
                
            # Add title
            if title:
                self.ax.set_title(title)
            
            # Optimize canvas update
            self.canvas.draw_idle()
            
            # Force a small delay to allow UI to update
            
        except Exception as e:
            logger.error(f"Error drawing plot: {e}")
            self._on_plot_error(str(e)) 