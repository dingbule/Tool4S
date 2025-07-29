"""
Main application window.
"""

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                           QAction, QMessageBox, QFileDialog, QSplitter, QMenu,  QTreeView,
                            QFileSystemModel, QCheckBox, QLabel, QGroupBox)
from PyQt5.QtCore import Qt, QDir
import logging
import os
from pathlib import Path
import json
from core.plugin_manager import PluginManager
from gui.plot_widget import PlotWidget
from gui.dialogs.psd_calculation_dialog import PSDCalculationDialog
from gui.dialogs.format_change_dialog import FormatChangeDialog
from gui.dialogs.file_cut_dialog import FileCutDialog
from gui.dialogs.create_file_dialog import CreateFileDialog
from gui.dialogs.psd_parameter_test_dialog import PSDParameterTestDialog
from gui.dialogs.psd_pdf_dialog import PSDPDFDialog
from utils.config import config
from gui.dialogs.project_parameters_dialog import ProjectParametersDialog
from gui.dialogs.merge_files_dialog import MergeFilesDialog
from utils.window_utils import set_window_size, center_window, set_window_title
from utils.constants import (DEFAULT_OUTPUT_FOLDER, PSD_FOLDER_NAME, 
                           PSD_FILE_EXTENSION, APP_FULL_NAME)

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        """Initialize main window."""
        super().__init__()
        
        # Initialize components
        self.plugin_manager = PluginManager()
        self.project_dir = None
        self.output_folders = set()  # Track output folders
        
        # Load plugins at startup
        self.plugin_manager.reload_plugins()
        self.readers = self.plugin_manager.get_available_readers()
       
        # Initialize UI
        self._init_ui()
        
        # Load initial state from config
        self._load_initial_state()
        
    def _init_ui(self):
        """Initialize UI components."""
        set_window_title(self,APP_FULL_NAME)
        
        # Set window size to 80% of screen size
        set_window_size(self, 0.8, 0.8)
        center_window(self)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QHBoxLayout(central_widget)
        
        # Create splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Create left panel for file tree and filter
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Create file system models
        self.file_model = self._create_file_model()
        self.external_model = self._create_file_model()
        
        # Create project files group
        project_group = QGroupBox("Project Files")
        project_layout = QVBoxLayout()
        
        # Create filter checkbox
        self.filter_checkbox = QCheckBox("Data File Filter")
        self.filter_checkbox.setChecked(False)
        self.filter_checkbox.stateChanged.connect(self._on_filter_changed)
        self.filter_checkbox.setEnabled(False)  # Initially disabled
        
        # Create file tree
        self.file_tree = self._create_tree_view(self.file_model)
        
        # Add filter checkbox and tree view to project group
        project_layout.addWidget(self.filter_checkbox)
        project_layout.addWidget(self.file_tree)
        project_group.setLayout(project_layout)

        # Create output files group
        external_group = QGroupBox("Output Files")
        external_layout = QVBoxLayout()

        # Add the hint label
        self.external_hint_label = QLabel(
            "You haven't set the output folder in the project parameters setting dialog!"
        )
        self.external_hint_label.setWordWrap(True)
        external_layout.addWidget(self.external_hint_label)

        # Create external tree view
        self.external_tree = self._create_tree_view(self.external_model)
        
        # Add tree view to external group
        external_layout.addWidget(self.external_tree)
        external_group.setLayout(external_layout)
        
        # Add groups to left panel
        left_layout.addWidget(project_group)
        left_layout.addWidget(external_group)
        
        # Create plot widget
        self.plot_widget = PlotWidget()
        self.plot_widget.loading_started.connect(self._on_loading_started)
        self.plot_widget.loading_finished.connect(self._on_loading_finished)
        self.plot_widget.loading_error.connect(self._on_loading_error)
        self.plot_widget.progress_updated.connect(self._on_progress_updated)
        
        # Add widgets to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(self.plot_widget)
        
        # Set splitter sizes (20% for tree, 80% for plot)
        splitter.setSizes([200, 800])
        
        layout.addWidget(splitter)
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create status bar
        self.statusBar().showMessage("Ready")
        
    def _create_file_model(self):
        """Create a file system model with standard settings.
        
        Returns:
            QFileSystemModel: Configured file model
        """
        model = QFileSystemModel()
        model.setRootPath("")
        model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
        return model
        
    def _create_tree_view(self, model):
        """Create a tree view with standard settings.
        
        Args:
            model: The model to use for the tree view
            
        Returns:
            QTreeView: Configured tree view
        """
        tree = QTreeView()
        tree.setModel(model)
        tree.setRootIndex(model.index(""))
        tree.setAnimated(False)
        tree.setIndentation(20)
        tree.setSortingEnabled(True)
        tree.sortByColumn(0, Qt.AscendingOrder)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.doubleClicked.connect(self._on_file_selected)
        
        # Enable horizontal scrolling and adjust column behavior
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tree.setWordWrap(False)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, tree.header().Interactive)
        tree.setColumnWidth(0, tree.width())
        
        # Hide size and date columns
        tree.setColumnHidden(1, True)
        tree.setColumnHidden(2, True)
        tree.setColumnHidden(3, True)
        
        return tree

    def _create_menu_bar(self):
        """Create menu bar."""
        menubar = self.menuBar()
        
        # Project menu
        project_menu = menubar.addMenu("Project")
        project_actions = [
            ("Open Project Directory", "Ctrl+O", self._open_project_directory),
            ("Project Parameters...", "Ctrl+P", self._show_project_parameters),
            (None, None, None),  # Separator
            ("Exit", "Ctrl+Q", self.close)
        ]
        self._add_menu_actions(project_menu, project_actions)
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        tools_actions = [
            ("Cut Files...", None, self._show_cut_dialog),
            ("Merge Files...", None, self._show_merge_dialog),
            ("Change Format...", None, self._show_format_dialog)
        ]
        self._add_menu_actions(tools_menu, tools_actions)
        
        # PSD menu
        psd_menu = menubar.addMenu("PSD")
        psd_actions = [
            ("Overlapped Files Creation", None, self._show_create_dialog),
            ("PSD Parameter Test", None, self._show_psd_parameter_test_dialog),
            ("PSD Calculation", None, self._show_psd_calculation_dialog)
        ]
        self._add_menu_actions(psd_menu, psd_actions)
        
        # Analysis menu
        analysis_menu = menubar.addMenu("Analysis")
        analysis_actions = [
            ("PSD Analysis", None, self._show_psd_pdf_dialog)
        ]
        self._add_menu_actions(analysis_menu, analysis_actions)
        
        # Plugins menu
        plugins_menu = menubar.addMenu("Plugins")
        readers_menu = plugins_menu.addMenu("Data Readers")
        readers_menu.setObjectName("readers_menu")
        
        # Add current formats
        for format_name in self.plugin_manager.get_supported_formats():
            action = QAction(format_name.upper(), self)
            action.setEnabled(False)  # These are just for display
            readers_menu.addAction(action)

        # Reload action
        reload_action = QAction("Reload Plugins", self)
        reload_action.triggered.connect(self._reload_plugins)
        plugins_menu.addAction(reload_action)
            
    def _add_menu_actions(self, menu, actions):
        """Add actions to a menu.
        
        Args:
            menu: The menu to add actions to
            actions: List of (text, shortcut, slot) tuples. Use None for separator
        """
        for text, shortcut, slot in actions:
            if text is None:
                menu.addSeparator()
            else:
                action = QAction(text, self)
                if shortcut:
                    action.setShortcut(shortcut)
                if slot:
                    action.triggered.connect(slot)
                menu.addAction(action)

    def _on_loading_started(self):
        """Handle loading started signal."""
        self.setEnabled(False)
        self.statusBar().showMessage("Loading file...")
        
    def _on_loading_finished(self):
        """Handle loading finished signal."""
        self.setEnabled(True)
        
    def _on_loading_error(self, error_msg: str):
        """Handle loading error signal."""
        QMessageBox.critical(self, "Error", f"Failed to load data: {error_msg}")
        self.statusBar().showMessage("Load error")
        self.setEnabled(True)
        
    def _on_progress_updated(self, message: str):
        """Handle progress update signal."""
        self.statusBar().showMessage(message)
        

    def _is_file_item(self, index):
        """Check if tree item represents a file."""
        if not index.isValid():
            return False
        model = index.model()
        return not model.isDir(index)

    def _get_item_path(self, index):
        """Get full path for a tree item."""
        if not index.isValid():
            return None
        model = index.model()
        return model.filePath(index)

    def _on_filter_changed(self, state):
        """Filter to show only data files."""
        if not self.project_dir:
            logger.warning("No project directory set for filtering")
            return
            
        try:
            data_file = Path(self.project_dir) / 'data.json'
            if not data_file.exists():
                logger.warning(f"Data.json file not found: {data_file}")
                return
                
            with open(data_file, 'r', encoding='utf-8') as f:
                datainfo = json.load(f)
                
            # Get all possible file formats
            formats = set()
            
            # Add output format if specified
            output_format = datainfo.get('data_params', {}).get('outputFormat', '').lower()
            if output_format:
                formats.add(output_format)
                
            # Add raw data format from parts_info
            parts_info = datainfo.get('name_parser', {}).get('parts_info', "")
            if parts_info:
                suffix = parts_info.split()[-1]
                formats.add(suffix)
                
            # Add PSD formats
            formats.update(['psd', 'npz'])
            
            if state == Qt.Checked:
                # Create name filters for all formats
                name_filters = [f"*.{fmt}" for fmt in formats]
                self.file_model.setNameFilters(name_filters)
                self.file_model.setNameFilterDisables(False)
            else:
                # Clear name filters
                self.file_model.setNameFilters([])
                self.file_model.setNameFilterDisables(True)
                
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in data file: {data_file}")
            QMessageBox.warning(
                self,
                "Warning",
                "Invalid data.json format. Cannot apply filter."
            )
        except FileNotFoundError:
            logger.error(f"Data Info file not found: {data_file}")
        except Exception as e:
            logger.error(f"Error updating file filters: {e}")
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to update file filters: {str(e)}"
            )

    def _check_data_json(self):
        """Check if data.json exists and has delimiters info."""
        if not self.project_dir:
            return False
            
        data_json_path = Path(self.project_dir) / 'data.json'
        if not data_json_path.exists():
            return False
            
        try:
            with open(data_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Check if delimiters exist in the name_parser object
                return 'name_parser' in data and 'delimiters' in data['name_parser']
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            logger.error(f"Error checking data.json: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking data.json: {e}")
            return False

    def _load_directory(self, directory: str):
        """Load directory contents into tree."""
        self.project_dir = directory
        
        try:
            # Save project directory to config
            config.set('Project', 'ProDir', directory)
            config.save()
            
            # Set root path for the model
            root_index = self.file_model.index(directory)
            self.file_tree.setRootIndex(root_index)
            
            # Expand the root item
            self.file_tree.expand(root_index)
            
            # Update filter checkbox state
            has_data_json = self._check_data_json()
            self.filter_checkbox.setEnabled(has_data_json)
            self.filter_checkbox.setChecked(False)  # Start with no filtering
            
        except Exception as e:
            logger.error(f"Error loading directory: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load directory: {str(e)}")

    def _update_output_folders(self):
        """Update the list of output folders based on data.json."""
        if not self.project_dir:
            # No project dir: show label, hide tree
            self.external_hint_label.setVisible(True)
            self.external_tree.setVisible(False)
            return

        try:
            data_json_path = Path(self.project_dir) / 'data.json'
            if not data_json_path.exists():
                self.external_tree.setRootIndex(self.external_model.index(""))
                self.external_hint_label.setVisible(True)
                self.external_tree.setVisible(False)
                return
                
            with open(data_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            output_folder = data.get('data_params', {}).get('outputFolder', str(Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER))
            output_format = data.get('data_params', {}).get('outputFormat', '').lower()
            
            # If output_folder is not set or empty, show label, hide tree
            if not output_folder or output_folder.strip() == "":
                self.external_hint_label.setVisible(True)
                self.external_tree.setVisible(False)
                return

            # Add to set of output folders
            self.output_folders.clear()
            self.output_folders.add(output_folder)
            
            for output_folder in self.output_folders:
                output_path = Path(output_folder)
                if output_path.exists():
                    index = self.external_model.setRootPath(str(output_path))
                    self.external_tree.setRootIndex(index)
                    self.external_tree.expand(index)
                    
                    # Set name filters based on output format
                    if output_format:
                        name_filters = [f"*.{output_format}", f"*{PSD_FOLDER_NAME}*{PSD_FILE_EXTENSION}"]
                        self.external_model.setNameFilters(name_filters)
                        self.external_model.setNameFilterDisables(False)
                        self.external_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)
                    else:
                        self.external_model.setNameFilters([])
                        self.external_model.setNameFilterDisables(True)

                    # Output folder is set: hide label, show tree
                    self.external_hint_label.setVisible(False)
                    self.external_tree.setVisible(True)
                    return

            # If output folder path does not exist
            self.external_hint_label.setText(
                f"Output folder {output_folder} does not exist, "
                "This default output folder will be created automatically once "
                "you use tools to generate output files."
                )
            self.external_hint_label.setVisible(True)
            self.external_tree.setVisible(False)

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in data.json file: {data_json_path}")
            self.external_hint_label.setText("Invalid data.json file format")
            self.external_hint_label.setVisible(True)
            self.external_tree.setVisible(False)
        except FileNotFoundError:
            logger.error(f"Data.json file not found: {data_json_path}")
            self.external_hint_label.setText("Project parameters not set")
            self.external_hint_label.setVisible(True)
            self.external_tree.setVisible(False)
        except Exception as e:
            logger.error(f"Error updating output folders: {e}")
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to update output folders: {str(e)}"
            )
            self.external_hint_label.setVisible(True)
            self.external_tree.setVisible(False)

    def _on_output_folder_created(self, folder_path):
        """Handle output folder creation.
        
        Args:
            folder_path: Path of created folder
        """
        logger.info(f"Output folder created: {folder_path}")
        self.output_folders.add(folder_path)
        self._update_output_folders()

    def _on_file_selected(self, index):
        """Handle file selection."""
        if self.plot_widget.is_loading_data():
            return
            
        # Determine which model the index belongs to
        model = index.model()
        if not (model in (self.file_model, self.external_model) and self._is_file_item(index)):
            return
            
        file_path = model.filePath(index)
        if not file_path:
            return

        # Check if data.json exists and has delimiters
        if not self._check_data_json():
            QMessageBox.warning(
                self,
                "Warning",
                "Please set up project parameters first by editing project parameters in the menu."
            )
            return

        try:
            # Get output folder and formats from data.json
            data_json_path = Path(self.project_dir) / 'data.json'
            with open(data_json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                output_folder = data.get('data_params', {}).get('outputFolder', str(Path(self.project_dir) / DEFAULT_OUTPUT_FOLDER))
                output_format = data.get('data_params', {}).get('outputFormat', '').lower()
                parts_info = data.get('name_parser', {}).get('parts_info', "")

            # Get supported formats
            supported_formats = set()
            if output_format:
                supported_formats.add(output_format)
            if parts_info:
                suffix = parts_info.split()[-1]
                supported_formats.add(suffix)

            # Check if file is in output folder or PSD folder
            file_path_obj = Path(file_path)
            is_in_psd = PSD_FOLDER_NAME in file_path_obj.parts
            file_suffix = file_path_obj.suffix.lower().lstrip('.')

            # Handle file loading based on type
            if is_in_psd and file_path_obj.suffix.lower() == PSD_FILE_EXTENSION:
                self._load_psd_file(str(file_path_obj))
            elif file_suffix in supported_formats:
                self._load_data_file(str(file_path_obj))
            else:
                QMessageBox.warning(
                    self,
                    "Warning",
                    f"Unsupported file format: {file_suffix}. Only data formats in readers are supported."
                )

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in data.json file")
            QMessageBox.critical(
                self,
                "Error",
                "Invalid data.json format. Please check the project parameters."
            )
        except FileNotFoundError:
            logger.error(f"Data.json file not found")
            QMessageBox.critical(
                self,
                "Error",
                "Project parameters file not found."
            )
        except Exception as e:
            logger.error(f"Error handling file selection: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to handle file selection: {str(e)}"
            )

    def _load_psd_file(self, file_path):
        """Load and display a PSD file.
        
        Args:
            file_path: Path to the PSD file
        """
        file_path_obj = Path(file_path)
        try:
            if not file_path_obj.exists():
                raise FileNotFoundError(f"PSD file not found: {file_path}")
                
            self.plot_widget.load_psd_file(str(file_path_obj))
            self.statusBar().showMessage(f"Loaded PSD: {file_path}")
        except FileNotFoundError as e:
            logger.error(f"PSD file not found: {e}")
            QMessageBox.critical(
                self,
                "Error",
                str(e)
            )
        except Exception as e:
            logger.error(f"Error loading PSD file: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load PSD file: {str(e)}"
            )

    def _load_data_file(self, file_path):
        """Load and display a data file.
        
        Args:
            file_path: Path to the data file
        """
        file_path_obj = Path(file_path)
        try:
            if not file_path_obj.exists():
                raise FileNotFoundError(f"Data file not found: {file_path}")
                
            if not self.project_dir:
                raise ValueError("No project directory set")
                
            self.plot_widget.load_file(str(file_path_obj), self.project_dir)
            self.statusBar().showMessage(f"Loaded: {file_path}")
        except FileNotFoundError as e:
            logger.error(f"Data file not found: {e}")
            QMessageBox.critical(
                self,
                "Error",
                str(e)
            )
        except ValueError as e:
            logger.error(f"Invalid project state: {e}")
            QMessageBox.critical(
                self,
                "Error",
                str(e)
            )
        except Exception as e:
            logger.error(f"Error loading file: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load file: {str(e)}"
            )

    def _open_project_directory(self):
        """Open project directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Project Directory",
            "",
            QFileDialog.ShowDirsOnly
        )
        
        if directory:
            self._load_directory(directory)
            self._update_output_folders()
            self._clear_plot_widget()

    def _clear_plot_widget(self):
        """Clear the plotting area."""
        if hasattr(self, 'plot_widget') and self.plot_widget:
            self.plot_widget.ax.clear()
            self.plot_widget.canvas.draw()

    def _show_psd_calculation_dialog(self):
        """Show PSD calculation dialog."""
        if not self._check_project_directory():
            return
            
        dialog = PSDCalculationDialog(self.project_dir, self)
        dialog.exec_()
        
    def _show_format_dialog(self):
        """Show the format change dialog."""
        if not self._check_project_directory():
            return
            
        if not self._check_test_result():
            return
            
        dialog = FormatChangeDialog(self.project_dir, self)
        # Connect output folder created signal
        dialog.output_folder_created.connect(self._on_output_folder_created)
        dialog.exec_()
        
        # Update output folders
        self._update_output_folders()
        
    def _check_project_directory(self):
        """Check if project directory exists and is valid."""
        if not self.project_dir:
            QMessageBox.warning(self, "Warning", "Please open a project first")
            return False
            
        project_path = Path(self.project_dir)
        if not project_path.exists():
            QMessageBox.warning(self, "Warning", "Project directory not found")
            return False
            
        data_json = project_path / 'data.json'
        if not data_json.exists():
            QMessageBox.warning(
                self,
                "Warning",
                "Project parameters not set. Please set project parameters first."
            )
            return False
            
        return True
        
    def _check_test_result(self):
        """Check if test result exists and is true in data.json."""
        try:
            data_json = Path(self.project_dir) / 'data.json'
            with open(data_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if not data.get('test_result', False):
                QMessageBox.warning(
                    self,
                    "Warning",
                    "Please test project parameters first before using this tool."
                )
                return False
            return True
        except Exception as e:
            logger.error(f"Error checking test result: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to check test result: {str(e)}"
            )
            return False

    def _show_cut_dialog(self):
        """Show the file cut dialog."""
        if not self._check_project_directory():
            return
            
        if not self._check_test_result():
            return
            
        dialog = FileCutDialog(self.project_dir, self)
        # Connect output folder created signal
        dialog.output_folder_created.connect(self._on_output_folder_created)
        dialog.exec_()
        
        # Update output folders
        self._update_output_folders()
        
    def _show_project_parameters(self):
        """Show the project parameters dialog."""
        if not self.project_dir:
            QMessageBox.warning(self, "Warning", "Please open a project first")
            return
            
        dialog = ProjectParametersDialog(self.project_dir, self)
        # Connect to the parameters_saved signal
        dialog.parameters_saved.connect(self._on_parameters_saved)
        dialog.exec_()
        
        # Update filter checkbox state after dialog closes
        has_data_json = self._check_data_json()
        self.filter_checkbox.setEnabled(has_data_json)
        self.filter_checkbox.setChecked(False)  # Reset filter state

    def _on_parameters_saved(self, output_folder: str):
        """Handle parameters saved signal from ProjectParametersDialog.
        
        Args:
            output_folder: The new output folder path
        """
        if not output_folder:
            logger.warning("Empty output folder path received")
            return
            
        try:
            # Add to set of output folders
            self.output_folders.clear()
            self.output_folders.add(output_folder)
            self._update_output_folders()
        except Exception as e:
            logger.error(f"Error updating output folder tree: {e}")
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to update output folder tree: {str(e)}"
            )
            
    
        
    def _show_create_dialog(self):
        """Show create files dialog."""
        if not self._check_project_directory():
            return
            
        if not self._check_test_result():
            return
            
        dialog = CreateFileDialog(self.project_dir, self)
        dialog.exec_()
        
    def _show_psd_parameter_test_dialog(self):
        """Show the PSD parameter test dialog."""
        if not self._check_project_directory():
            return
            
        dialog = PSDParameterTestDialog(self.project_dir, self)
        dialog.exec_()
        
    def _show_psd_pdf_dialog(self):
        """Show PSD PDF viewer dialog."""
        if not self._check_project_directory():
            return
            
        dialog = PSDPDFDialog(self.project_dir, self)
        dialog.exec_()
        
        
    def _show_merge_dialog(self):
        """Show the merge files dialog."""
        if not self._check_project_directory():
            return
            
        if not self._check_test_result():
            return
            
        dialog = MergeFilesDialog(self.project_dir, self)
        # Connect output folder created signal
        dialog.output_folder_created.connect(self._on_output_folder_created)
        dialog.exec_()
        
        # Update output folders
        self._update_output_folders()

    def _reload_plugins(self):
        """Reload plugins."""
        try:
            self.plugin_manager.reload_plugins()
            self.readers = self.plugin_manager.get_available_readers()
            
            # Update readers menu
            readers_menu = self.findChild(QMenu, "readers_menu")
            if readers_menu:
                readers_menu.clear()
                for format_name in self.plugin_manager.get_supported_formats():
                    action = QAction(format_name.upper(), self)
                    action.setEnabled(False)
                    readers_menu.addAction(action)
         
                    
            QMessageBox.information(self, "Success", "Plugins reloaded successfully, \
check the new reader list and restart this application.")
            
        except Exception as e:
            logger.error(f"Failed to reload plugins: {e}")
            QMessageBox.critical(self, "Error", f"Failed to reload plugins: {str(e)}")
            
    def _load_initial_state(self):
        """Load initial state from config."""
        try:
            # Load last project directory
            last_directory = config.get('Project', 'ProDir', fallback='')
            logger.info(f"Last directory: {last_directory}")
            if last_directory and Path(last_directory).exists():
                self._load_directory(last_directory)
                self._update_output_folders()
                self.statusBar().showMessage(f"Current project: {last_directory}")
        except Exception as e:
            logger.error(f"Failed to load initial state: {e}")
            
    def closeEvent(self, event):
        """Handle window close event."""
        try:
            # Save current project directory
            if self.project_dir:
                config.set('Project', 'ProDir', self.project_dir)
                config.save()
        except Exception as e:
            logger.error(f"Failed to save state on close: {e}")
            
        event.accept()