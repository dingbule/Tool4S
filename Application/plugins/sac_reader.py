"""
SAC data reader plugin.
"""

from obspy import read,Stream
from obspy.core import UTCDateTime
import numpy as np

from plugins.base_reader import DataReader

class SACReader(DataReader):
    """Reader for SAC format files."""
    
    def read(self, file_path: str) -> Stream:
        """Read data from a SAC file.
        
        Args:
            file_path: Path to the SAC file
            
        Returns:
            ObsPy Stream object containing the data traces
        """
        try:
            # Read the SAC file
            st = read(file_path, format='SAC')
            
            # Return the Stream object directly
            return st
            
        except Exception as e:
            raise ValueError(f"Failed to read SAC file: {e}")
    
    def read_header(self, file_path: str) -> Stream:
        """Read header from a SAC file.
        
        Args:
            file_path: Path to the SAC file
            
        Returns:
            ObsPy Stream object containing the data header info
        """
        try:
            # Read the SAC file with headonly=True to only read headers
            st = read(file_path, format='SAC', headonly=True)
            
            # Return the Stream object directly
            return st
            
        except Exception as e:
            raise ValueError(f"Failed to read SAC file header: {e}")
            
    def write(self, file_path: str, stream: Stream):
        """Write data to a SAC file.
        
        Args:
            file_path: Path to save the SAC file
            stream: ObsPy Stream object containing the data to write
        """
        try:
            # Write Stream directly to file
            stream.write(file_path, format='SAC')
            
        except Exception as e:
            raise ValueError(f"Failed to write SAC file: {e}")
            
    def get_format_name(self) -> str:
        """Get name of data format.
        
        Returns:
            Format name as string
        """
        return "sac" 