"""
Plugin manager for loading and managing data reader plugins.
"""

import os
import sys
import importlib.util
from typing import Dict, Type
from pathlib import Path
from plugins.base_reader import DataReader

class PluginManager:
    """Manager for loading and managing data reader plugins."""
    
    def __init__(self):
        """Initialize the plugin manager."""
        self.plugins: Dict[str, Type[DataReader]] = {}
        self.plugins_dir = self._get_plugins_dir()
        self._load_plugins()
        
    def _get_plugins_dir(self) -> str:
        """Get the plugins directory path.
        
        Returns:
            Path to plugins directory
        """
        # If running from frozen executable
        if getattr(sys, 'frozen', False):
            # Get path relative to executable
            base_path = Path(sys.executable).parent
        else:
            # Get path relative to script
            base_path = Path(__file__).parent.parent
            
        return base_path / 'plugins'
        
    def _load_plugins(self):
        """Load all plugins from the plugins directory."""
        # Create plugins directory if it doesn't exist
        self.plugins_dir.mkdir(exist_ok=True)
        # Get all Python files in plugins directory
        for plugin_path in self.plugins_dir.glob('*.py'):
            if plugin_path.name.startswith('__'):
                continue
                
            try:
                module_name = plugin_path.stem  
                spec = importlib.util.spec_from_file_location(module_name, str(plugin_path))  # 注意转换为str
                if spec is None or spec.loader is None:
                    continue
                    
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                
                for item in dir(module):
                    obj = getattr(module, item)
                    if (isinstance(obj, type) and 
                        issubclass(obj, DataReader) and 
                        obj != DataReader):
                        reader = obj()
                        format_name = reader.get_format_name().lower()
                        self.plugins[format_name] = obj
                        ext = f".{format_name}"
                        if ext not in self.plugins:
                            self.plugins[ext] = obj
                            
            except Exception as e:
                print(f"Failed to load plugin {plugin_path.name}: {e}")

                    
    def get_reader(self, format_name: str) -> Type[DataReader]:
        """Get reader for specified format.
        
        Args:
            format_name: Name of data format
            
        Returns:
            DataReader class for format
        """
        return self.plugins.get(format_name.lower())
        
    def get_supported_formats(self) -> list:
        """Get list of supported data formats.
        
        Returns:
            List of format names
        """
        return sorted(set(name for name in self.plugins.keys() if not name.startswith('.')))
        
    def get_available_readers(self) -> Dict[str, Type[DataReader]]:
        """Get dictionary of available readers.
        
        Returns:
            Dictionary mapping file extensions to reader classes
        """
        return {ext: cls for ext, cls in self.plugins.items() if ext.startswith('.')}
        
    def reload_plugins(self):
        """Reload all plugins."""
        self.plugins.clear()
        self._load_plugins() 