"""
Base reader class for seismic data readers.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any

class DataReader(ABC):
    """Abstract base class for data readers."""
    
    @abstractmethod
    def read(self, file_path: str) -> Dict[str, Any]:
        """Read data from a file.
        
        Args:
            file_path: Path to the file to read
            
        Returns:
            Dictionary containing the data and metadata
        """
        pass

    @abstractmethod
    def read_header(self, file_path: str) -> Dict[str, Any]:
        """Read only the header information from a file.
        
        This method should be faster than read() as it doesn't process the actual data.
        
        Args:
            file_path: Path to the file to read
            
        Returns:
            Dictionary containing the header metadata
        """
        pass
        
    @abstractmethod
    def write(self, file_path: str, data: Dict[str, Any]):
        """Write data to a file.
        
        Args:
            file_path: Path to save the file
            data: Dictionary containing the data and metadata
        """
        pass
        
    @abstractmethod
    def get_format_name(self) -> str:
        """Get name of data format.
        
        Returns:
            Format name as string
        """
        pass 