"""
MSEED data reader plugin.
"""

from obspy import read,Stream
from obspy.core import UTCDateTime
import numpy as np

from plugins.base_reader import DataReader

class MSEEDReader(DataReader):
    """Reader for MSEED format files."""
    
    def read(self, file_path: str) -> Stream:
        """Read data from a MSEED file.
        
        Args:
            file_path: Path to the MSEED file
            
        Returns:
            ObsPy Stream object containing the data traces
        """
        try:
            # Read the MSEED file
            st = read(file_path, format='MSEED')
            
            # Return the Stream object directly
            return st
            
        except Exception as e:
            raise ValueError(f"Failed to read MSEED file: {e}")
        
    def read_header(self, file_path: str) -> Stream:
        """Read header from a MSEED file.
        
        Args:
            file_path: Path to the MSEED file
            
        Returns:
            ObsPy Stream object containing the data header info
        """
        try:
            # Read the MSEED file
            st = read(file_path, format='MSEED',headonly=True)
            
            # Return the Stream object directly
            return st
            
        except Exception as e:
            raise ValueError(f"Failed to read MSEED file: {e}")
            
    def write(self, file_path: str, stream: Stream):
        """Write data to a MSEED file.
        
        Args:
            file_path: Path to save the MSEED file
            stream: ObsPy Stream object containing the data to write
        """
        try:
            # Write Stream directly to file
            stream.write(file_path, format='MSEED')
            
        except Exception as e:
            raise ValueError(f"Failed to write MSEED file: {e}")
            
    def get_format_name(self) -> str:
        """Get name of data format.
        
        Returns:
            Format name as string
        """
        return "mseed" 