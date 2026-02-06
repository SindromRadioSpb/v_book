# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for HDLE Premium
#
# This spec builds a standalone Windows executable with:
# - Complete hiddenimports (PyQt6, SQLAlchemy, psutil)
# - Bundled SQL migrations
# - No UPX compression (avoids antivirus false positives)
# - Excluded unused dependencies (stanza_resources, tkinter, matplotlib)

import sys
from pathlib import Path

# Project root
project_root = Path.cwd()

block_cipher = None

a = Analysis(
    [str(project_root / 'app' / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Bundle SQL migrations (required for DB initialization)
        (str(project_root / 'app' / 'infra' / 'migrations' / '*.sql'), 'app/infra/migrations/'),
    ],
    hiddenimports=[
        # PyQt6
        'PyQt6.sip',
        # SQLAlchemy
        'sqlalchemy.dialects.sqlite',
        'app.infra.sa_models',
        # Process lock
        'psutil',
        # Services (explicit to ensure bundling)
        'app.services.backup_service',
        'app.services.snapshot_service',
        'app.services.db_service',
        'app.services.processor_service',
        'app.services.export_service',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'stanza_resources',  # Stanza models (downloaded on first run)
        'tkinter',           # Not used
        'matplotlib',        # Not used
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='HDLE_Premium',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # DISABLED: UPX can trigger antivirus false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app (no console window)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Add icon if available
)
