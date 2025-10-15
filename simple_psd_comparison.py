#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple PSD Comparison Script: matplotlib mlab.psd vs tool4s
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.mlab as mlab
import obspy
from scipy.signal import detrend
import os
import sys

# Add tool4s path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.psd import PSDCalculator

def calculate_mlab_psd(stream, sensitivity=1.0):
    """Calculate PSD using matplotlib mlab.psd method"""
    trace = stream[0]
    data = trace.data.astype(np.float64)
    sr = trace.stats.sampling_rate
    
    # Detrend and remove mean
    data = detrend(data, type='linear')
    data = data - np.mean(data)
    
    # Sensitivity correction
    data = data / sensitivity
    
    # Calculate PSD using matplotlib mlab.psd
    window_size = min(100000, len(data))
    overlap = int(0.8 * window_size)
    
    psd, freqs = mlab.psd(data, NFFT=window_size, Fs=sr, 
                          window=mlab.window_hanning, 
                          noverlap=overlap, 
                          scale_by_freq=True)
    
    # Frequency filtering (0.01-50 Hz)
    freq_mask = (freqs >= 0.01) & (freqs <= 50.0)
    freqs = freqs[freq_mask]
    psd = psd[freq_mask]
    
    # Convert to acceleration PSD (assuming input is velocity data)
    omega = 2 * np.pi * freqs
    psd = (omega ** 2) * psd
    
    # Convert to dB
    psd_db = 10 * np.log10(psd)
    
    return freqs, psd_db

def calculate_tool4s_psd(file_path, sensitivity=1.0):
    """Calculate PSD using tool4s method"""
    # Read file
    stream = obspy.read(file_path)
    trace = stream[0]
    data = trace.data.astype(np.float64)
    sr = trace.stats.sampling_rate
    
    # Create PSDCalculator
    calculator = PSDCalculator(
        sample_rate=sr,
        sensitivity=sensitivity,
        instrument_type=0,  # Velocity sensor
        damping_ratio=0.707,
        natural_period=10
    )
    
    # Set parameters
    calculator.filter_enabled = False
    calculator.response_removal_enabled = False
    calculator.psd_freq_min = 0.01
    calculator.psd_freq_max = 50.0
    
    # Calculate PSD
    freqs, psd_db = calculator.calculate_psd(data)
    
    return freqs, psd_db

def compare_methods(file_path, sensitivity=1.0):
    """Compare matplotlib mlab.psd and tool4s PSD calculation methods"""
    print("=" * 60)
    print("Simple PSD Comparison: matplotlib mlab.psd vs tool4s")
    print("=" * 60)
    
    # Read file
    stream = obspy.read(file_path)
    trace = stream[0]
    print(f"Reading file: {file_path}")
    print(f"Data points: {len(trace.data)}")
    print(f"Sampling rate: {trace.stats.sampling_rate} Hz")
    print()
    
    # Calculate PSD using matplotlib mlab.psd
    print("1. matplotlib mlab.psd method:")
    try:
        freqs_mlab, psd_mlab = calculate_mlab_psd(stream, sensitivity)
        print(f"   Frequency range: {freqs_mlab[0]:.4f} - {freqs_mlab[-1]:.4f} Hz")
        print(f"   PSD range: {psd_mlab.min():.2f} - {psd_mlab.max():.2f} dB")
        print(f"   Frequency points: {len(freqs_mlab)}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print()
    
    # Calculate PSD using tool4s
    print("2. tool4s method:")
    try:
        freqs_tool4s, psd_tool4s = calculate_tool4s_psd(file_path, sensitivity)
        print(f"   Frequency range: {freqs_tool4s[0]:.4f} - {freqs_tool4s[-1]:.4f} Hz")
        print(f"   PSD range: {psd_tool4s.min():.2f} - {psd_tool4s.max():.2f} dB")
        print(f"   Frequency points: {len(freqs_tool4s)}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print()
    
    # Interpolate to common frequency grid
    freq_common = np.logspace(np.log10(0.01), np.log10(50), 1000)
    psd_mlab_interp = np.interp(freq_common, freqs_mlab, psd_mlab)
    psd_tool4s_interp = np.interp(freq_common, freqs_tool4s, psd_tool4s)
    
    # Calculate differences
    diff = psd_mlab_interp - psd_tool4s_interp
    mean_diff = np.mean(diff)
    std_diff = np.std(diff)
    max_diff = np.max(np.abs(diff))
    rms_diff = np.sqrt(np.mean(diff**2))
    
    print("3. Method comparison:")
    print(f"   Mean difference: {mean_diff:.2f} dB")
    print(f"   Standard deviation: {std_diff:.2f} dB")
    print(f"   Maximum difference: {max_diff:.2f} dB")
    print(f"   RMS difference: {rms_diff:.2f} dB")
    print()
    
    # Create comparison plot
    plt.figure(figsize=(12, 6))
    
    plt.loglog(freqs_mlab, 10**(psd_mlab/10), 'b-', label='matplotlib mlab.psd', linewidth=1.5)
    plt.loglog(freqs_tool4s, 10**(psd_tool4s/10), 'r--', label='tool4s', linewidth=1.5)
    
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('PSD ((m/s²)²/Hz)')
    plt.title('PSD Comparison: matplotlib mlab.psd vs tool4s')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xlim(0.01, 50)
    
    # Save plot
    filename = os.path.basename(file_path).replace('.mseed', '')
    plot_filename = f"simple_psd_comparison_{filename}.png"
    plt.tight_layout()
    plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
    plt.show()
    
    print(f"Comparison plot saved: {plot_filename}")
    print("Comparison completed!")

def main():
    """Main function"""
    # Hardcoded file path
    file_path = r"f:\tool4s_20250814\output\00D766\S0SeisEA\00D766.S0SeisEA.20231205030000.mseed"
    sensitivity = 1.0
    
    compare_methods(file_path, sensitivity)

if __name__ == "__main__":
    main()