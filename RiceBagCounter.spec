# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

block_cipher = None

# Get all required hidden imports
hidden_imports = [
    'cv2',
    'numpy',
    'torch',
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'reportlab.graphics.barcode',
    'reportlab.rl_config',
    'reportlab.pdfbase.ttfonts',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PIL',
    'yaml'  # Required for ultralytics config
]

# Add all ultralytics submodules
hidden_imports.extend(collect_submodules('ultralytics'))

# Collect data files
datas = [
    ('resources', 'resources'),  # Include all resources
]

# Add PyQt5 and matplotlib data files
datas += collect_data_files('PyQt5')
datas += collect_data_files('matplotlib')

# Add ultralytics data files and metadata
datas += collect_data_files('ultralytics')
datas += copy_metadata('ultralytics')

a = Analysis(
    ['master_app.py'],  # Your main script
    pathex=[os.path.abspath(SPECPATH)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Remove duplicate binaries and data files
def remove_duplicates(list_of_tuples):
    seen = set()
    return [x for x in list_of_tuples if not (x[0] in seen or seen.add(x[0]))]

a.binaries = remove_duplicates(a.binaries)
a.datas = remove_duplicates(a.datas)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RiceBagCounter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # Keep True for debugging until everything works
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources/rice.ico']
)

# Create a directory containing everything
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RiceBagCounter'
)