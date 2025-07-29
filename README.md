# Tool4S

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](https://github.com/dingbule/tool4s)
[![Python](https://img.shields.io/badge/python-3.8-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

A GUI-based software for seismic site station selection data processing and analyzing based on Python.

## Features

- **Multi-format Data Support**: Plugin architecture for various seismic formats (MSEED, SAC, SEGY, ..., and proprietary formats)
- **Advanced PSD Analysis**: Power Spectral Density calculation with noise model comparison
- **Data Processing Tools**: File cutting, merging, and format conversion
- **Parameter Testing**: PSD parameter optimization and batch processing
- **Interactive Visualization**: Real-time plotting and comprehensive reporting

## Examples & Screenshots

Example data files and a simple how-to are provided in `example_data` folder.

## Installation

We have tested the installation on Windows 10 and Ubuntu 18.04.

### Using Conda (Recommended)

```bash
# Clone repository
git clone https://github.com/dingbule/tool4s.git
cd tool4s

# Create and activate conda environment with Python 3.8
conda create -n tool4s python=3.8
conda activate tool4s

# Install dependencies
pip install -r requirements.txt

# Run application
python __main__.py
```

### Using Pip

```bash
# Clone repository
git clone https://github.com/dingbule/tool4s.git
cd tool4s

# Install dependencies
pip install -r requirements.txt

# Run application
python __main__.py
```

## Executable Application  (Windows)

We provide a pre-built executable for Windows 10 in `Application`, unzip the 'tool4s.zip' to get the executable and put it under `Application` folder.

### Building Your Own Executable

```bash
# Build executable (Windows)
pyinstaller main.spec
```

The executable will be created in the `dist` folder. If you build your own executable, you should put it in the `Application` folder where several necessary DLL files are alreadly located.

> **Note**: The executable build has only been tested on Windows 10. The `hooks` and `rthooks` folders are required for the PyInstaller build process.

## Project Structure

```
tool4s/
├── core/           # Core processing modules
│   ├── psd.py      # Power Spectral Density calculator
│   └── data/       # Reference data including noise models
├── gui/            # User interface components
│   ├── dialogs/    # Application dialog windows
│   └── plot_widget.py # Visualization components
├── plugins/        # Data format readers
│   ├── mseed_reader.py
│   ├── sac_reader.py
│   └── ...
├── utils/          # Utility functions and helpers
├── __main__.py     # Application entry point
├── requirements.txt # Dependencies

*Used to built your own executables
├── Application     # pre-built executable
├── rthooks         # Used by pyinstaller
├── hooks           # Used by pyinstaller
├── main.spec       # Used by pyinstaller
├── build           # Created by pyinstaller
└── dist            # Created by pyinstaller

*Folder and file created while Tool4S starts up once
├── logs            # logs 
└── config.ini      # config for Tool4S
*Documents
├── docs            # screenshots
└── README.md       # introduction


```


## Dependencies

- **Python**: 3.8
- **Scientific**: numpy, scipy, matplotlib, obspy
- **GUI**: PyQt5
- **Build(optional)**: pyinstaller

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**Tool4S** - Making seismic analysis accessible and efficient. 
