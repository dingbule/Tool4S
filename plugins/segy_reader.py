"""
SEGY data reader plugin.
"""

import numpy as np
from obspy import read, Stream
from obspy.core import UTCDateTime

from plugins.base_reader import DataReader

class SEGYReader(DataReader):
    """Reader for SEGY format files."""
    
    def read(self, file_path: str) -> Stream:
        """Read data from a SEGY file.
        
        Args:
            file_path: Path to the SEGY file
            
        Returns:
            ObsPy Stream object containing the data traces
        """
        try:
            # Read the SEGY file
            st = read(file_path)
            
            # Return the Stream object directly
            return st
            
        except Exception as e:
            raise ValueError(f"Failed to read SEGY file: {e}")
    
    def read_header(self, file_path: str) -> Stream:
        """Read header from a SEGY file.
        
        Args:
            file_path: Path to the SEGY file
            
        Returns:
            ObsPy Stream object containing the data header info
        """
        try:
            # Read the SEGY file with headonly=True to only read headers
            st = read(file_path, headonly=True)
            
            # Return the Stream object directly
            return st
            
        except Exception as e:
            raise ValueError(f"Failed to read SEGY file header: {e}")
            
    def write(self, file_path: str, stream: Stream):
        """Write data to a SEGY file.
        
        Args:
            file_path: Path to save the SEGY file
            stream: ObsPy Stream object containing the data to write
        """
        try:
            # Write Stream directly to file
            stream.write(file_path, format='SEGY')
            
        except Exception as e:
            raise ValueError(f"Failed to write SEGY file: {e}")
            
    def get_format_name(self) -> str:
        """Get name of data format.
        
        Returns:
            Format name as string
        """
        return "SEGY" 