# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

project_root = Path('.')



a = Analysis(
    ['__main__.py'],
    pathex=[project_root],
    binaries=[],
    datas=[
        (str(project_root / 'plugins'), 'plugins'),  
        (str(project_root / 'core/data/noise_models.npz'), 'core/data'),
    ],
    hiddenimports=[],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['rthooks/obspy.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='tool4s',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
