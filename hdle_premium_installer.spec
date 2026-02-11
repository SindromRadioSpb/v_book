# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for HDLE Premium
#
# АКТУАЛЬНАЯ ВЕРСИЯ: 2026-02-11 (включает Task 9 - Project Exchange)
#
# Этот spec файл создает standalone Windows executable с:
# - Полными hiddenimports (PyQt6, SQLAlchemy, psutil, Google Cloud Translate)
# - Встроенными SQL миграциями
# - Модулем project_exchange (Task 9)
# - БЕЗ UPX compression (избегает false positives антивирусов)
# - Исключенными неиспользуемыми зависимостями (stanza_resources, tkinter, matplotlib)
#
# РЕЖИМ: onedir (не onefile) - критично для torch_cpu.dll
# ВЫХОД: dist/HDLE_Premium/ (папка с exe + зависимостями)

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
        # SQL migrations (обязательно для инициализации БД)
        (str(project_root / 'app' / 'infra' / 'migrations' / '*.sql'), 'app/infra/migrations/'),
        # dialogs.py модуль (конфликт имен с dialogs/ папкой)
        (str(project_root / 'app' / 'ui' / 'dialogs.py'), 'app/ui/'),
    ],
    hiddenimports=[
        # PyQt6 core
        'PyQt6.sip',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',

        # SQLAlchemy
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.sql.default_comparator',
        'app.infra.sa_models',

        # Process lock
        'psutil',

        # Security module (P0)
        'app.infra.security',
        'app.infra.security.sanitizer',
        'app.infra.security.validator',
        'app.infra.security.crypto',
        'app.infra.security.credentials',
        'app.infra.security.audit',

        # MT Providers
        'deep_translator',
        'deep_translator.google',
        'app.infra.translators.providers.google_translate_provider',

        # Google Cloud Translate (Official API)
        'google.cloud.translate_v3',
        'google.cloud.translate',
        'google.auth',
        'google.oauth2.service_account',
        'google.api_core',
        'google.api_core.gapic_v1',
        'grpc',
        'grpc._cython.cygrpc',

        # Services (явно для гарантии bundling)
        'app.services.backup_service',
        'app.services.snapshot_service',
        'app.services.db_service',
        'app.services.processor_service',
        'app.services.export_service',
        'app.services.batch_mt_translate_service',
        'app.services.ingest_service',
        'app.services.project_service',
        'app.services.translation_service',
        'app.services.concordance_service',
        'app.services.stats_service',
        'app.services.term_extraction_service',
        'app.services.coverage_service',
        'app.services.dictionary_import_service',

        # Project Exchange (Task 9) - НОВОЕ
        'app.services.project_exchange',
        'app.services.project_exchange.export_engine',
        'app.services.project_exchange.import_engine',
        'app.services.project_exchange.bundle_format',
        'app.services.project_exchange.worker',
        'app.services.project_exchange.constants',
        'app.services.project_exchange.dto',

        # UI dialogs - КРИТИЧНО: и файл dialogs.py, и папка dialogs/
        'app.ui.dialogs',  # Это импортирует app/ui/dialogs.py (файл с CreateProjectDialog и т.д.)
        'app.ui.dialogs.batch_translate_dialog',
        'app.ui.dialogs.batch_progress_dialog',
        'app.ui.dialogs.batch_progress_dialog_v2',
        'app.ui.dialogs.project_exchange_dialogs',

        # Encryption/credentials
        'keyring',
        'keyring.backends',
        'keyring.backends.Windows',
        'cryptography',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.ciphers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'stanza_resources',  # Stanza models (скачиваются при первом запуске)
        'tkinter',           # Не используется
        'matplotlib',        # Не используется
        'PIL',               # Не используется (если нет OCR)
        'numpy.distutils',   # Не нужно для runtime
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
    [],
    exclude_binaries=True,  # КРИТИЧНО: Режим onedir (не onefile) для избежания ошибки извлечения torch_cpu.dll
    name='HDLE_Premium',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # ОТКЛЮЧЕНО: UPX может вызвать false positives антивирусов
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI приложение (без консольного окна)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Добавить иконку если доступна
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='HDLE_Premium',
)
