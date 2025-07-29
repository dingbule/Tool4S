import sys
import os
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, copy_metadata, collect_submodules
import obspy
obspy_root=os.path.dirname(obspy.__file__)
binaries = collect_dynamic_libs('obspy')

datas = [
    (os.path.join(obspy_root, "*.txt"), os.path.join('obspy', 'core', 'util')),
    (os.path.join(obspy_root, "imaging", "data"), os.path.join('obspy', 'imaging', 'data')),
    (os.path.join(obspy_root, "signal", "data"), os.path.join('obspy', 'signal', 'data')),
    (os.path.join(obspy_root, "taup", "data"), os.path.join('obspy', 'taup', 'data')),
    (os.path.join(obspy_root, "geodetics", "data"), os.path.join('obspy', 'geodetics', 'data')),
]


metadata = copy_metadata('obspy')
datas += metadata

hiddenimports = collect_submodules('obspy')   