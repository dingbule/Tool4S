"""
File name parser utility for analyzing seismic data file names.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

class FileNameParser:
    """Parser for seismic data file names based on project parameters."""
    
    def __init__(self, project_dir: str = None, delimiters: str = None, 
                 parts_info: str = None, name_info: str = None):
        """Initialize parser with either project directory or direct parameters.
        
        Args:
            project_dir: Path to project directory containing data.json
            delimiters: String of delimiters separated by spaces
            parts_info: String of parts info separated by spaces
            name_info: String in format "Network:1;Station:2;Location:3;Channel:4"
        """
        self.delimiters = None
        self.parts_info = None
        self.name_info = {}
        
        if project_dir:
            self.project_dir = Path(project_dir)
            self.data_json_path = self.project_dir / 'data.json'
            self._load_parameters()
        else:
            # Initialize from direct parameters
            if delimiters:
                self.delimiters = delimiters.split()
            if parts_info:
                self.parts_info = parts_info.split()
            if name_info:
                self.name_info = self._parse_name_info(name_info)
        
    def _load_parameters(self):
        """Load parameters from data.json."""
        try:
            if not self.data_json_path.exists():
                logger.warning(f"data.json not found at {self.data_json_path}")
                return
                
            with open(self.data_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Check if name_parser exists in data
            if 'name_parser' in data:
                parser_data = data['name_parser']
                # Load delimiters and parts info from name_parser
                if 'delimiters' in parser_data and parser_data['delimiters']:
                    self.delimiters = parser_data['delimiters'].split()
                if 'parts_info' in parser_data and parser_data['parts_info']:
                    self.parts_info = parser_data['parts_info'].split()
                if 'name_info' in parser_data:
                    self.name_info = self._parse_name_info(parser_data['name_info'])
            else:
                # For backward compatibility, try loading from root
                if 'delimiters' in data and data['delimiters']:
                    self.delimiters = data['delimiters'].split()
                if 'parts_info' in data and data['parts_info']:
                    self.parts_info = data['parts_info'].split()
                if 'name_info' in data:
                    self.name_info = self._parse_name_info(data['name_info'])
                
        except Exception as e:
            logger.error(f"Error loading parameters: {e}")
            raise
            
    def _parse_name_info(self, name_info_str: str) -> Dict[str, str]:
        """Parse name info string into dictionary.
        
        Args:
            name_info_str: String in format "Network:1;Station:2;Location:3;Channel:4"
            
        Returns:
            Dictionary mapping code types to their positions
        """
        name_parts = {}
        for part in name_info_str.split(';'):
            if ':' in part:
                key, value = part.split(':')
                name_parts[key.strip()] = value.strip()
        return name_parts
        
    def parse_filename(self, filename: str) -> Tuple[bool, Dict[str, str], bool, str]:
        """Parse a filename according to project parameters.
        
        Args:
            filename: Name of the file to parse
            
        Returns:
            Tuple containing:
            - Success flag (bool)
            - Dictionary of parsed parts (Dict[str, str])
            - Channel flag (bool)
            - Error message if any (str)
        """
        try:
            if not self.delimiters or not self.parts_info:
                return False, {}, False, "Parser not properly initialized with delimiters and parts info"
                
            # Split filename according to delimiters
            remaining = filename
            filename_parts = []
            channel_existed = False
            
            index = 0
            for delimiter in self.delimiters:
                if not remaining:
                    break
                    
                if delimiter in remaining:
                    parts = remaining.split(delimiter, 1)
                    filename_parts.append(parts[0])
                    remaining = parts[1]
                    if index == len(self.delimiters) - 1:
                        filename_parts.append(remaining)
                    index = index + 1

                else:
                    return False, {}, False, f"Delimiter '{delimiter}' not found in remaining string '{remaining}'"
                    
            # Check if number of parts matches
            if len(filename_parts) != len(self.parts_info):  
                return False, {}, False, (
                    f"Expected {len(self.parts_info)} parts but got {len(filename_parts)} parts"
                )
            for part in filename_parts:
                if self._has_special_characters(part):
                    return False, {}, False, f"Special characters found in part: {part}"
                
            # Create mapping between parts_info and filename_parts
            parts_mapping = {}
            for i, part in enumerate(self.parts_info):  
                parts_mapping[part] = filename_parts[i]
                
            # Parse name info
            parsed_parts = {}
            for code_type in ['Network', 'Station', 'Location', 'Channel']:
                if code_type in self.name_info:
                    # The codes of Network, Station, Location, and Channel.
                    # Configured in the segments control by user.
                    value = self.name_info[code_type]
                    if code_type == "Channel":
                        if value and value.strip():
                            channel_existed = True
                   
                    found = False
                    for part_name, filename_part in parts_mapping.items():
                        if part_name == value:
                            # If found, use the filename part as the value
                            parsed_parts[code_type] = filename_part
                            found = True
                            break
                    if not found:
                        # If not found, use the value directly
                        parsed_parts[code_type] = value
                            
            return True, parsed_parts, channel_existed, ""
            
        except Exception as e:
            logger.error(f"Error parsing filename: {e}")
            return False, {}, False, str(e)
            
    def get_folder_architecture(self, parsed_parts: Dict[str, str]) -> str:
        """Get folder architecture string from parsed parts.
        
        Args:
            parsed_parts: Dictionary of parsed parts from parse_filename
            
        Returns:
            Folder architecture string (e.g., "Network/Station/Location/Channel")
        """
        folder_parts = "/"
        
        # Add network if present
        if 'Network' in parsed_parts :
            network_part = parsed_parts['Network']
            if network_part and network_part.strip():
                folder_parts =folder_parts+network_part+"/"
        if 'Station' in parsed_parts :
            station_part = parsed_parts['Station']
            if station_part and station_part.strip():
                folder_parts =folder_parts+station_part+"/"
        if 'Location' in parsed_parts :
            location_part = parsed_parts['Location']
            if location_part and location_part.strip():
                folder_parts =folder_parts+location_part+"/"
            
        # Add channel if present
        if 'Channel' in parsed_parts :
            channel_part = parsed_parts['Channel']
            if channel_part and channel_part.strip():
                folder_parts=folder_parts+channel_part
            else:
                folder_parts=folder_parts+"[NEZ]"
            
            #channel_part = parsed_parts['Channel']
            
        return folder_parts
        
    def get_name_info_string(self, parsed_parts: Dict[str, str]) -> str:
        """Get name info string from parsed parts.
        
        Args:
            parsed_parts: Dictionary of parsed parts from parse_filename
            
        Returns:
            Name info string (e.g., "Network:NET;Station:STA;Location:LOC;Channel:CHN")
        """
        parts = []
        for code_type in ['Network', 'Station', 'Location', 'Channel']:
            if code_type in parsed_parts and parsed_parts[code_type]:
                parts.append(f"{code_type}:{parsed_parts[code_type]}")
        return ';'.join(parts)
        
    def validate_filename(self, filename: str) -> Tuple[bool, str]:
        """Validate if a filename matches the project pattern.
        
        Args:
            filename: Name of the file to validate
            
        Returns:
            Tuple containing:
            - Success flag (bool)
            - Error message if any (str)
        """
        success, _, _, error = self.parse_filename(filename)
        return success, error 
    def _has_special_characters(self,s):
        for char in s:
            if not char.isalnum():  
                return True
        return False