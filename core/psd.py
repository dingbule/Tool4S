"""
Power Spectral Density (PSD) calculation module for seismic data.
"""

import numpy as np
from scipy import signal
from scipy.signal import butter, filtfilt, welch, detrend, freqresp
from typing import Tuple, Optional, Union
import logging
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

class PSDCalculator:
    """Power Spectral Density calculator for seismic data."""

    NOISE_MODEL_FILE = Path(__file__).parent / "data/noise_models.npz"
    PSD_DB_RANGE = np.arange(-200, -49)  # -200 to -50 dB with 1 dB interval

    def __init__(self, 
                 sample_rate: float,
                 sensitivity: float,
                 instrument_type: int,
                 damping_ratio: float = 0.707,
                 natural_period: float = 10):
        """Initialize PSD calculator.
        
        Args:
            sample_rate: Sampling rate in Hz
            sensitivity: Sensor sensitivity (count/(m/s))
            instrument_type: Type of instrument (0 for velocity, 1 for acceleration)
            damping_ratio: Damping ratio (default: 0.707)
            natural_period: Natural period in s (second)
        """
        self.sample_rate = sample_rate
        self.sensitivity = sensitivity
        self.damping_ratio = damping_ratio
        self.natural_period = natural_period
        self.instrument_type = instrument_type
        
        # Filter parameters
        self._filter_enabled = False
        self._filter_type = "High Pass"  # "High Pass" or "Band Pass"
        self._cutoff_freq = 0.1  # For high pass
        self._low_freq = 0.1  # For band pass
        self._high_freq = 100.0  # For band pass
        
        # Window parameters
        self._window_size = 1000  # seconds
        self._overlap = 0.8  # fraction
        self._window_type = "hann"
        
        # Response removal
        self._response_removal_enabled = False
        
        # PSD frequency range
        self._psd_freq_min = 0.001  # Hz
        self._psd_freq_max = 100.0  # Hz
        
        # Results storage
        self.frequencies = None
        self.psd = None
        self.psd_v = None
        self.smoothed_frequencies = None
        self.smoothed_psd = None
        self.smoothed_psd_v = None
        self.rms = None
        
        # Add new attribute for PSD distribution
        self.psd_distribution = None

    @staticmethod
    def get_noise_models() -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Get New High/Low Noise Model data."""
        try:
            data = np.load(PSDCalculator.NOISE_MODEL_FILE)
            try:
                periods = data['model_periods']
                nlnm = data['low_noise']
                nhnm = data['high_noise']
                return periods, nlnm, nhnm
            except KeyError as e:
                logger.error(f"Missing key in noise model file: {e}")
                raise ValueError(f"Invalid noise model file format: {e}")
        except FileNotFoundError:
            logger.error(f"Noise model file not found: {PSDCalculator.NOISE_MODEL_FILE}")
            raise
        except Exception as e:
            logger.error(f"Error loading noise model file: {e}")
            raise

    def calculate_psd(self, data: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Calculate Power Spectral Density."""
        if not isinstance(data, np.ndarray):
            raise ValueError("Input data must be a numpy array")
            
        if data.size == 0:
            raise ValueError("Input data is empty")

        # Remove mean and detrend
        data = detrend(data - np.mean(data))

        # Convert to physical unit by whole sensitivity
        data = data / self.sensitivity

        # Apply filter if enabled
        if self._filter_enabled:
            if self._filter_type == "High Pass":
                data = self._apply_highpass_filter(data)
            else:  # Band Pass
                data = self._apply_bandpass_filter(data)

        # Calculate raw PSD using welch method
        nperseg = min(int(self._window_size * self.sample_rate), data.size)
        noverlap = int(self._overlap * nperseg)
        
        self.frequencies, psd = welch(data, 
                                    fs=self.sample_rate,
                                    window=self._window_type,
                                    nperseg=nperseg,
                                    noverlap=noverlap)

        # Filter frequencies based on PSD frequency range
        freq_mask = (self.frequencies >= self._psd_freq_min) & (self.frequencies <= self._psd_freq_max)
        self.frequencies = self.frequencies[freq_mask]
        psd = psd[freq_mask]

        
        self.psd_v = psd.copy()
        if self._response_removal_enabled:
            self.psd_v = self._remove_response(self.psd_v, self.frequencies)
            psd = self.psd_v.copy()

        # Convert to acceleration PSD
        if self.instrument_type == 0:
            omega = 2 * np.pi * self.frequencies
            psd = (omega ** 2) * psd
        elif self.instrument_type == 1:
            # This is already acceleration data, no conversion needed
            pass  # Remove print statement
        else:
            raise ValueError("Invalid instrument type")
        
        # Convert to dB
        self.psd = 10 * np.log10(psd)

        # Calculate smoothed PSDs
        self.smoothed_frequencies, self.smoothed_psd = self._smooth_psd(self.frequencies, self.psd)
        
        
        return self.frequencies, self.psd

    def _smooth_psd(self, frequencies: np.ndarray, psd: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Smooth PSD using octave binning and calculate PSD value distribution.
        
        For each frequency bin, counts the number of PSD values falling into 1dB bins
        from -200 to -50 dB.
        """
        # Convert to periods
        periods = 1.0 / frequencies[::-1]
        psd_by_period = psd[::-1]

        # Set up period binning
        period_binning = self._setup_period_binning(
            period_smoothing_width_octaves=1.0,
            period_step_octaves=0.125,  # 1/8 octave
            period_limits=(periods[0], periods[-1])
        )

        # Perform smoothing and calculate PSD distribution
        smoothed_psd = []
        psd_dist = []  # List to store PSD distribution for each frequency bin
        
        for per_left, per_right in zip(period_binning[0, :], period_binning[4, :]):
            mask = (per_left <= periods) & (periods <= per_right)
            if np.any(mask):
                # Calculate mean PSD for the bin
                bin_psd = psd_by_period[mask].mean()
                smoothed_psd.append(bin_psd)
                
                # Calculate PSD value distribution
                bin_values = psd_by_period[mask]
                hist, _ = np.histogram(bin_values, bins=self.PSD_DB_RANGE)
                psd_dist.append(hist)
            else:
                smoothed_psd.append(np.nan)
                psd_dist.append(np.zeros_like(self.PSD_DB_RANGE[:-1]))

        smoothed_psd = np.array(smoothed_psd)
        self.psd_distribution = np.array(psd_dist)
        
        # Calculate smoothed frequencies
        smoothed_periods = period_binning[2, :]  # Center periods
        smoothed_frequencies = 1.0 / smoothed_periods[::-1]
        smoothed_psd = smoothed_psd[::-1]
        self.psd_distribution = self.psd_distribution[::-1]  # Reverse to match frequency order

        return smoothed_frequencies, smoothed_psd

    def _apply_highpass_filter(self, data: np.ndarray) -> np.ndarray:
        """Apply high-pass Butterworth filter."""
        nyquist = self.sample_rate / 2.0
        normalized_cutoff = self._cutoff_freq / nyquist
        b, a = butter(5, normalized_cutoff, btype='high')
        return filtfilt(b, a, data)
    
    def _apply_bandpass_filter(self, data: np.ndarray) -> np.ndarray:
        """Apply band-pass Butterworth filter."""
        nyquist = self.sample_rate / 2.0
        low = self._low_freq / nyquist
        high = self._high_freq / nyquist
        b, a = butter(5, [low, high], btype='band')
        return filtfilt(b, a, data)

    def _remove_response(self, psd: np.ndarray, frequencies: np.ndarray) -> np.ndarray:
        """Using theoretical transfer function to remove instrument response from PSD."""
        omega_n = 2 * np.pi / self.natural_period
        num = [1,0,0]  # numerator
        den = [1, 2 * self.damping_ratio * omega_n, omega_n**2]  # denominator
        
        system = signal.lti(num, den)
        w, h = signal.freqresp(system, 2 * np.pi * frequencies)
        return psd / np.abs(h)**2

    def _setup_period_binning(self,
                            period_smoothing_width_octaves: float,
                            period_step_octaves: float,
                            period_limits: Tuple[float, float]) -> np.ndarray:
        """Set up period binning for smoothing."""
        # Calculate factors
        step_factor = 2 ** period_step_octaves
        smoothing_factor = 2 ** period_smoothing_width_octaves

        # Calculate first bin
        per_left = period_limits[0] / (smoothing_factor ** 0.5)
        per_right = per_left * smoothing_factor
        per_center = np.sqrt(per_left * per_right)

        # Build lists of bin edges and centers
        edges_left = [per_left]
        edges_right = [per_right]
        centers = [per_center]

        while per_center < period_limits[1]:
            per_left *= step_factor
            per_right = per_left * smoothing_factor
            per_center = np.sqrt(per_left * per_right)
            
            edges_left.append(per_left)
            edges_right.append(per_right)
            centers.append(per_center)

        # Convert to arrays
        edges_left = np.array(edges_left)
        edges_right = np.array(edges_right)
        centers = np.array(centers)

        # Create plotting edges
        plot_edges_left = centers / (step_factor ** 0.5)
        plot_edges_right = centers * (step_factor ** 0.5)

        return np.vstack([edges_left, plot_edges_left, centers, plot_edges_right, edges_right])

    # Properties for parameter access
    @property
    def filter_enabled(self) -> bool:
        """Get filter enabled state."""
        return self._filter_enabled

    @filter_enabled.setter
    def filter_enabled(self, value: bool) -> None:
        """Set filter enabled state."""
        self._filter_enabled = bool(value)

    @property
    def filter_type(self) -> str:
        """Get filter type."""
        return self._filter_type

    @filter_type.setter
    def filter_type(self, value: str) -> None:
        """Set filter type."""
        if value not in ["High Pass", "Band Pass"]:
            raise ValueError("Filter type must be 'High Pass' or 'Band Pass'")
        self._filter_type = value

    @property
    def cutoff_freq(self) -> Union[float, Tuple[float, float]]:
        """Get filter cutoff frequency."""
        if self._filter_type == "High Pass":
            return self._cutoff_freq
        return (self._low_freq, self._high_freq)

    @cutoff_freq.setter
    def cutoff_freq(self, value: Union[float, Tuple[float, float]]) -> None:
        """Set filter cutoff frequency."""
        if isinstance(value, (list, tuple)):
            if len(value) != 2:
                raise ValueError("Band pass filter requires (low, high) frequency tuple")
            self._low_freq = float(value[0])
            self._high_freq = float(value[1])
        else:
            self._cutoff_freq = float(value)

    @property
    def window_size(self) -> float:
        """Get window size in seconds."""
        return self._window_size

    @window_size.setter
    def window_size(self, value: float) -> None:
        """Set window size in seconds."""
        self._window_size = float(value)

    @property
    def overlap(self) -> float:
        """Get overlap fraction."""
        return self._overlap

    @overlap.setter
    def overlap(self, value: float) -> None:
        """Set overlap fraction."""
        self._overlap = float(value)

    @property
    def window_type(self) -> str:
        """Get window type."""
        return self._window_type

    @window_type.setter
    def window_type(self, value: str) -> None:
        """Set window type."""
        valid_windows = ["hann", "hamming", "blackman", "bartlett", "flattop", "boxcar"]
        if value not in valid_windows:
            raise ValueError(f"Window type must be one of {valid_windows}")
        self._window_type = str(value)

    @property
    def response_removal_enabled(self) -> bool:
        """Get response removal enabled state."""
        return self._response_removal_enabled

    @response_removal_enabled.setter
    def response_removal_enabled(self, value: bool) -> None:
        """Set response removal enabled state."""
        self._response_removal_enabled = bool(value)

    @property
    def psd_freq_min(self) -> float:
        """Get minimum frequency for PSD calculation."""
        return self._psd_freq_min

    @psd_freq_min.setter
    def psd_freq_min(self, value: float) -> None:
        """Set minimum frequency for PSD calculation."""
        self._psd_freq_min = float(value)

    @property
    def psd_freq_max(self) -> float:
        """Get maximum frequency for PSD calculation."""
        return self._psd_freq_max

    @psd_freq_max.setter
    def psd_freq_max(self, value: float) -> None:
        """Set maximum frequency for PSD calculation."""
        self._psd_freq_max = float(value) 