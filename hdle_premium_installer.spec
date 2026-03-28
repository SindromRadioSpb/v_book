# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for HDLE Premium
#
# РђРљРўРЈРђР›Р¬РќРђРЇ Р’Р•Р РЎРРЇ: 2026-03-22 (РІРєР»СЋС‡Р°РµС‚ Task 9 - Project Exchange, Task 11 - Entity Classification)
#
# Р­С‚РѕС‚ spec С„Р°Р№Р» СЃРѕР·РґР°РµС‚ standalone Windows executable СЃ:
# - РџРѕР»РЅС‹РјРё hiddenimports (PyQt6, SQLAlchemy, psutil, Google Cloud Translate)
# - Р’СЃС‚СЂРѕРµРЅРЅС‹РјРё SQL РјРёРіСЂР°С†РёСЏРјРё
# - РњРѕРґСѓР»РµРј project_exchange (Task 9)
# - Р‘Р•Р— UPX compression (РёР·Р±РµРіР°РµС‚ false positives Р°РЅС‚РёРІРёСЂСѓСЃРѕРІ)
# - РСЃРєР»СЋС‡РµРЅРЅС‹РјРё РЅРµРёСЃРїРѕР»СЊР·СѓРµРјС‹РјРё Р·Р°РІРёСЃРёРјРѕСЃС‚СЏРјРё (stanza_resources, tkinter, matplotlib)
#
# Р Р•Р–РРњ: onedir (РЅРµ onefile) - РєСЂРёС‚РёС‡РЅРѕ РґР»СЏ torch_cpu.dll
# Р’Р«РҐРћР”: dist/HDLE_Premium/ (РїР°РїРєР° СЃ exe + Р·Р°РІРёСЃРёРјРѕСЃС‚СЏРјРё)

import sys
from pathlib import Path

# Project root
project_root = Path.cwd()


def _collect_tree_datas(source_root: Path, target_root: str):
    items = []
    if not source_root.exists():
        return items
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        relative_parent = path.relative_to(source_root).parent.as_posix()
        target_dir = target_root if relative_parent == "." else f"{target_root}/{relative_parent}"
        items.append((str(path), target_dir))
    return items

block_cipher = None

a = Analysis(
    [str(project_root / 'app' / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # SQL migrations (РѕР±СЏР·Р°С‚РµР»СЊРЅРѕ РґР»СЏ РёРЅРёС†РёР°Р»РёР·Р°С†РёРё Р‘Р”)
        (str(project_root / 'app' / 'infra' / 'migrations' / '*.sql'), 'app/infra/migrations/'),
        # dialogs.py РјРѕРґСѓР»СЊ (РєРѕРЅС„Р»РёРєС‚ РёРјРµРЅ СЃ dialogs/ РїР°РїРєРѕР№)
        (str(project_root / 'app' / 'ui' / 'dialogs.py'), 'app/ui/'),
        # Resource manifest for Resources Manager / Health checks
        (str(project_root / 'app' / 'resources' / '*.json'), 'app/resources/'),
        # Bundled local pronunciation model for frozen ONNX probe / bootstrap
        (str(project_root / 'installer' / 'resources' / 'local_models' / 'phonikud' / '*.onnx'), 'resources/models/phonikud/'),
    ] + _collect_tree_datas(
        project_root / 'installer' / 'resources' / 'local_models' / 'stanza_hebrew',
        'resources/nlp_runtime/stanza_payload',
    ),
    hiddenimports=[
        # PyQt6 core
        'PyQt6.sip',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtMultimedia',

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

        # Services (СЏРІРЅРѕ РґР»СЏ РіР°СЂР°РЅС‚РёРё bundling)
        'app.services.backup_service',
        'app.services.snapshot_service',
        'app.services.db_service',
        # 'app.services.processor_service',  # REMOVED: module does not exist
        'app.services.export_service',
        'app.services.batch_mt_translate_service',
        'app.services.ingest_service',
        'app.services.project_service',
        'app.services.translation_service',
        'app.services.concordance_service',
        'app.services.stats_service',
        'app.services.term_extraction_service',
        'app.services.translation_admin_service',  # all import sites are lazy — must be explicit
        'app.services.coverage_service',
        'app.services.dictionary_import_service',
        'app.services.entity_classifier',  # Task 11: Entity Classification
        'app.services.pronunciation_service',
        'app.services.pronunciation_bootstrap_service',
        'app.services.pronunciation_import_export_service',
        'app.infra.pronunciation.phonikud_adapter',
        'phonikud',
        'phonikud_onnx',
        'huggingface_hub',
        'onnxruntime.capi.onnxruntime_pybind11_state',
        'app.services.audio_usage_tracker',

        # Project Exchange (Task 9) - РќРћР’РћР•
        'app.services.project_exchange',
        'app.services.project_exchange.export_engine',
        'app.services.project_exchange.import_engine',
        'app.services.project_exchange.bundle_format',
        'app.services.project_exchange.worker',
        'app.services.project_exchange.constants',
        'app.services.project_exchange.dto',

        # UI dialogs - РљР РРўРР§РќРћ: Рё С„Р°Р№Р» dialogs.py, Рё РїР°РїРєР° dialogs/
        'app.ui.dialogs',  # Р­С‚Рѕ РёРјРїРѕСЂС‚РёСЂСѓРµС‚ app/ui/dialogs.py (С„Р°Р№Р» СЃ CreateProjectDialog Рё С‚.Рґ.)
        'app.ui.dialogs.batch_translate_dialog',
        'app.ui.dialogs.batch_audio_dialog',
        'app.ui.dialogs.mms_license_gate_dialog',
        'app.ui.dialogs.batch_progress_dialog',
        'app.ui.dialogs.batch_progress_dialog_v2',
        'app.ui.dialogs.project_exchange_dialogs',
        'app.ui.dialogs.pronunciation_bootstrap_dialog',
        'app.ui.database_switch_dialog',
        'app.ui.resources_manager_dialog',
        'app.ui.first_run_wizard',
        'app.ui.audio_provider_settings_dialog',
        'app.ui.delegates.audio_play_delegate',
        'app.ui.widgets.audio_player_panel',
        'app.services.resources.resource_registry',
        'app.services.health_check_service',

        # Internal playback
        'app.services.audio_player_service',

        # Audio providers
        'app.infra.audio.providers.google_cloud_tts_provider',
        'app.infra.audio.providers.azure_speech_tts_provider',
        'app.infra.audio.providers.mms_tts_local_provider',

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
        'stanza_resources',  # Stanza models (СЃРєР°С‡РёРІР°СЋС‚СЃСЏ РїСЂРё РїРµСЂРІРѕРј Р·Р°РїСѓСЃРєРµ)
        'tkinter',           # РќРµ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ
        'matplotlib',        # РќРµ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ
        'PIL',               # РќРµ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ (РµСЃР»Рё РЅРµС‚ OCR)
        'numpy.distutils',   # РќРµ РЅСѓР¶РЅРѕ РґР»СЏ runtime
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    module_collection_mode={
        'onnxruntime': 'py',
    },
    noarchive=False,
)

probe_a = Analysis(
    [str(project_root / 'app' / 'tools' / 'onnx_probe.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[
        'phonikud_onnx',
        'huggingface_hub',
        'onnxruntime',
        'onnxruntime.capi.onnxruntime_pybind11_state',
        'app.infra.resource_paths',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'stanza_resources',
        'tkinter',
        'matplotlib',
        'PIL',
        'numpy.distutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    module_collection_mode={
        'onnxruntime': 'py',
    },
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
probe_pyz = PYZ(probe_a.pure, probe_a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # РљР РРўРР§РќРћ: Р РµР¶РёРј onedir (РЅРµ onefile) РґР»СЏ РёР·Р±РµР¶Р°РЅРёСЏ РѕС€РёР±РєРё РёР·РІР»РµС‡РµРЅРёСЏ torch_cpu.dll
    name='HDLE_Premium',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # РћРўРљР›Р®Р§Р•РќРћ: UPX РјРѕР¶РµС‚ РІС‹Р·РІР°С‚СЊ false positives Р°РЅС‚РёРІРёСЂСѓСЃРѕРІ
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI РїСЂРёР»РѕР¶РµРЅРёРµ (Р±РµР· РєРѕРЅСЃРѕР»СЊРЅРѕРіРѕ РѕРєРЅР°)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: Р”РѕР±Р°РІРёС‚СЊ РёРєРѕРЅРєСѓ РµСЃР»Рё РґРѕСЃС‚СѓРїРЅР°
)

onnx_probe_exe = EXE(
    probe_pyz,
    probe_a.scripts,
    [],
    exclude_binaries=True,
    name='HDLE_ONNX_Probe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    onnx_probe_exe,
    a.binaries,
    probe_a.binaries,
    a.zipfiles,
    probe_a.zipfiles,
    a.datas,
    probe_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='HDLE_Premium',
)
