# Building Windows Installer for HDLE Premium

## Overview

This guide describes how to build a standalone Windows installer for HDLE Premium. The installer bundles the application into a single `.exe` file that can be distributed and installed on any Windows 10/11 machine without requiring Python or dependencies.

## Prerequisites

### 1. Development Environment

**Required:**
- Windows 10 or Windows 11
- Python 3.11 or higher
- Git (for version control)

**Recommended:**
- Clean Windows VM for testing (no Python installed)
- At least 2 GB free disk space

### 2. Python Dependencies

All Python dependencies should be installed in the virtual environment:

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies (if not already installed)
pip install -e .
```

**Key dependencies for building:**
- `PyInstaller` - Bundles Python app into standalone executable
- `psutil` - Required by process lock system

### 3. PyInstaller

**Status:** ✅ Already installed (version 6.18.0)

If not installed:
```powershell
pip install pyinstaller
```

### 4. Inno Setup

**Status:** ❌ NOT in PATH on current machine

**Download:** https://jrsoftware.org/isdl.php

**Installation:**
1. Download Inno Setup (version 6.x or higher)
2. Run installer
3. During installation, select "Add to PATH" (recommended)
4. Default install location: `C:\Program Files (x86)\Inno Setup 6\`

**Verify installation:**
```powershell
ISCC.exe /?
```

If not in PATH, you can compile manually:
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss
```

### 5. sqlite3 CLI for baseline DB recovery

If prebuild/release work requires recovering a corrupted baseline DB with
`scripts/repair_db_corruption.py`, use the known-good sqlite3 CLI:

- `C:\msys64\ucrt64\bin\sqlite3.exe`

Verified on `2026-03-08`:

- version `3.51.2`
- supports `.recover`

Do not use an arbitrary older `sqlite3.exe` just because it is first in `PATH`.
Some binaries fail the recovery pipeline because `.recover` is missing.

Recommended verification:

```powershell
& "C:\msys64\ucrt64\bin\sqlite3.exe" -version
cmd /c "echo .help | C:\msys64\ucrt64\bin\sqlite3.exe"
```

---

## Build Process

### Step 1: Build Standalone Executable

The standalone executable is built using PyInstaller with a custom spec file.

**Command:**
```powershell
.\scripts\build_windows.ps1
```

**What this does:**
1. Activates virtual environment
2. Generates build traceability metadata (`scripts/generate_build_meta.py`)
3. Checks/installs PyInstaller
4. Cleans previous build artifacts
5. Runs `pyinstaller build/v_book.spec` (onedir mode)
6. Verifies output: `dist\HDLE_Premium\HDLE_Premium.exe`

**Expected output:**
```
============================================
   HDLE Premium - Windows Build Script
============================================

[1/5] Activating virtual environment...
✓ Virtual environment activated

[2/5] Checking PyInstaller...
PyInstaller 6.18.0
✓ PyInstaller ready

[3/5] Cleaning previous build...
✓ Build directory cleaned

[4/5] Building executable...
This may take several minutes...

[... PyInstaller output ...]

✓ Executable built successfully

[5/5] Verifying build...
✓ Executable verified: dist\HDLE_Premium\HDLE_Premium.exe
✓ Distribution folder: dist\HDLE_Premium\ (total size)

============================================
           BUILD SUCCESSFUL
============================================
```

**Build time:** 2-5 minutes (depending on hardware)

**Output (onedir mode):**
- `dist\HDLE_Premium\` - Distribution folder containing:
  - `HDLE_Premium.exe` - Main executable
  - Qt6 plugins, PyTorch libraries, SQLAlchemy, etc.
  - All dependencies in-place (no extraction at runtime)

**Note:** Using onedir (not onefile) to avoid `torch_cpu.dll` extraction failures on startup.

### Step 2: Test Standalone Executable (Optional but Recommended)

Before creating the installer, test the executable on the development machine:

```powershell
.\dist\HDLE_Premium\HDLE_Premium.exe
```

Or run automated smoke test:

```powershell
.\scripts\run_packaged_smoke.ps1
```

**Expected behavior:**
1. App launches without errors
2. Database created at `%LOCALAPPDATA%\HDLE\hdle.db`
3. Logs created at `%LOCALAPPDATA%\HDLE\logs\`
4. UI displays correctly
5. Build metadata is available in Help -> About HDLE Premium (version/commit/dirty/built_at)

**Build traceability check (required before release):**

```powershell
python scripts/generate_build_meta.py
powershell -ExecutionPolicy Bypass -File scripts\verify_frozen_health.ps1
```

Expected:
- `build\verify\import_dist.json`, `build\verify\health_dist.json`, and `build\verify\db_open_dist.json` contain `build.version`, `build.commit`, `build.dirty`, `build.built_at_utc`
- `build\verify\frozen_health_summary.json` exists as the canonical frozen self-check summary artifact
- `build\verify\build_meta_dist.txt` exists and matches the expected commit for the release candidate

**Frozen runtime gates (required before release):**

Run these exact checks on the built `dist` payload:

```powershell
.\dist\HDLE_Premium\HDLE_Premium.exe --self-check import --self-check-out "J:\Project_Vibe\V_book\build\verify_dist\import_dist.json"
.\dist\HDLE_Premium\HDLE_Premium.exe --self-check health --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" --self-check-out "J:\Project_Vibe\V_book\build\verify_dist\health_dist.json"
.\dist\HDLE_Premium\HDLE_Premium.exe --self-check db_open --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" --self-check-out "J:\Project_Vibe\V_book\build\verify_dist\db_open_dist.json"
.\dist\HDLE_Premium\HDLE_ONNX_Probe.exe --mode import --out "J:\Project_Vibe\V_book\build\verify_dist\probe_import_dist.json"
```

Required pass criteria:

- `onnxruntime_import.ok = true`
- `checks.onnxruntime_import.helper_path` points to `HDLE_ONNX_Probe.exe`
- `frozen_onnx_probe.status = ok`
- `bootstrap:pronunciation.status = ok`
- `bootstrap:sentence_niqqud.status = ok`
- `db_open_dist.json` reports:
  - `ok = true`
  - `schema_version` present
  - `supported_schema_version` present
  - `db_profile` present
- `frozen_health_summary.json` exists and summarizes probe/import/health/db_open

This is mandatory after any change touching:

- `app/infra/pronunciation/phonikud_adapter.py`
- `app/main.py`
- `app/tools/onnx_probe.py`
- `hdle_premium_installer.spec`

Reason:

- the frozen runtime can pass in dev but still fail in the installer if:
  - bundled helper path resolution is wrong,
  - `huggingface_hub` is missing from packaging,
  - ONNX helper/runtime contract drifts from self-check expectations.

Current verified frozen-layout expectation for fresh `dist` builds:

- staged phonikud model is bundled under:
  - `dist\HDLE_Premium\_internal\resources\models\phonikud\phonikud-1.0.int8.onnx`
- `HDLE_ONNX_Probe.exe` must discover that bundled model without requiring a
  user-configured `pronunciation/phonikud/model_path`

Manual confirmation command:

```powershell
.\dist\HDLE_Premium\HDLE_ONNX_Probe.exe --out "J:\Project_Vibe\V_book\build\verify_dist\probe_dist_manual.json"
```

Pass criteria:

- `ok = true`
- `details = real_inference`
- `model_path` points to `_internal\resources\models\phonikud\...`

**Windows console encoding gate (required before release):**

`--self-check` output must remain ASCII-safe on Windows consoles with `cp1251`.

Pass criteria:

- `HDLE_Premium.exe --self-check import ...`
- `HDLE_Premium.exe --self-check health ...`

must not crash with:

- `UnicodeEncodeError: 'charmap' codec can't encode characters ...`

Contract:

- JSON written to output files stays UTF-8
- console output must remain ASCII-safe

**Troubleshooting:**
- If app crashes immediately, check `%LOCALAPPDATA%\HDLE\logs\` for error messages
- If DLL errors appear, rebuild with `--clean` flag

### Step 2A: Stage Required Phonikud ONNX Model

Premium installer builds must bundle the required offline niqqud model.
Do not commit the binary into git. Treat it as a staged build input.

`rebuild.ps1` stages the required model automatically before the build:

- preferred override: `HDLE_REQUIRED_PHONIKUD_MODEL_PATH`
- default known-good source:
  - `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\models\phonikud\phonikud-1.0.int8.onnx`

Staging target:

- `installer\resources\local_models\phonikud\phonikud-1.0.int8.onnx`

That staging path is intentionally git-ignored. It is a release artifact, not a source-controlled asset.

Required verification:

```powershell
Test-Path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\models\phonikud\phonikud-1.0.int8.onnx"
Get-ChildItem installer\resources\local_models\phonikud
```

### Step 2B: Stage Bundled Hebrew Payload for Managed Stanza Runtime

Packaged releases must now carry the bundled Hebrew payload for the product-owned
managed Stanza runtime. This payload is directory-based and is staged before the
PyInstaller build.

`rebuild.ps1` stages the payload automatically before the build:

- preferred override: `HDLE_REQUIRED_STANZA_HEBREW_SOURCE`
- fallback sources:
  - `%LOCALAPPDATA%\StanfordNLP\stanza\Cache\<version>\resources`
  - `%USERPROFILE%\stanza_resources`
  - previously staged `installer\resources\local_models\stanza_hebrew\stanza_resources`

Canonical staging target:

- `installer\resources\local_models\stanza_hebrew\payload_manifest.json`
- `installer\resources\local_models\stanza_hebrew\stanza_resources\resources.json`
- `installer\resources\local_models\stanza_hebrew\stanza_resources\he\...`

PyInstaller bundles this staged payload into the frozen app under:

- `dist\HDLE_Premium\_internal\resources\nlp_runtime\stanza_payload\...`

This is the canonical packaged source for the managed Hebrew payload. The app
must not depend on a legacy local Stanza cache when this bundled payload is present.

Required verification:

```powershell
Get-ChildItem installer\resources\local_models\stanza_hebrew -Recurse
Get-ChildItem dist\HDLE_Premium\_internal\resources\nlp_runtime\stanza_payload -Recurse
```

### Step 3: Build Installer with Inno Setup

Once the standalone executable is verified, create the installer.

**Command (if ISCC in PATH):**
```powershell
ISCC.exe installer\installer.iss
```

**Command (if ISCC NOT in PATH):**
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss
```

**Expected output:**
```
Inno Setup 6.x Compiler
Copyright (C) 1997-2024 Jordan Russell. All rights reserved.

Compiling installer\installer.iss...
Preprocessor: Preprocessed
Compiler: Processing [Setup] section...
Compiler: Processing [Languages] section...
Compiler: Processing [Tasks] section...
Compiler: Processing [Files] section...
Compiler: Processing [Icons] section...
Compiler: Processing [Run] section...
Compiler: Processing [Code] section...
Compiler: Finished compiling.

Successful compile (X.XXX sec). Resulting Setup program filename is:
installer\output\HDLE_Premium_Setup.exe
```

**Output:**
- `installer\output\HDLE_Premium_Setup.exe` - Windows installer (~46 MB)

**Build time:** 10-30 seconds

---

## Testing the Installer

### Test on Development Machine (Quick Test)

1. **Uninstall previous version (if any):**
   - Control Panel → Programs → Uninstall
   - OR: `installer\output\HDLE_Premium_Setup.exe /SILENT /UNINSTALL`

2. **Run installer:**
   ```powershell
   .\installer\output\HDLE_Premium_Setup.exe
   ```

3. **Follow wizard:**
   - Accept defaults (install to `C:\Program Files\HDLE\`)
   - Optionally create desktop shortcut
   - Launch app after installation

4. **Verify installation:**
   - App installed to: `C:\Program Files\HDLE\` (folder with all dependencies)
   - Main executable: `C:\Program Files\HDLE\HDLE_Premium.exe`
   - Start menu shortcut: Start → HDLE Premium
   - Desktop shortcut (if selected)

5. **Verify data separation:**
   - User data NOT in `C:\Program Files\HDLE\`
   - User data in: `%LOCALAPPDATA%\HDLE\`
   - Database: `%LOCALAPPDATA%\HDLE\hdle.db`
   - Logs: `%LOCALAPPDATA%\HDLE\logs\`
   - Backups: `%LOCALAPPDATA%\HDLE\backups\`

6. **Verify installed runtime is actually updated:**
   - Do not assume silent reinstall replaced the binaries.
   - Compare installed timestamps against the freshly built artifacts:

   ```powershell
   Get-Item .\dist\HDLE_Premium\HDLE_Premium.exe | Select-Object FullName,Length,LastWriteTime
   Get-Item "M:\Soft\HDLE\HDLE_Premium.exe" | Select-Object FullName,Length,LastWriteTime
   Get-Item "M:\Soft\HDLE\HDLE_ONNX_Probe.exe" | Select-Object FullName,Length,LastWriteTime
   ```

   Required:
   - installed `HDLE_Premium.exe` timestamp matches the latest build wave
   - installed `HDLE_ONNX_Probe.exe` timestamp matches the latest build wave

7. **Verify installed self-check on the real installation path:**

   ```powershell
   M:\Soft\HDLE\HDLE_Premium.exe --self-check import --self-check-out "J:\Project_Vibe\V_book\build\verify_installed\import_installed.json"
   M:\Soft\HDLE\HDLE_Premium.exe --self-check health --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" --self-check-out "J:\Project_Vibe\V_book\build\verify_installed\health_installed.json"
   M:\Soft\HDLE\HDLE_Premium.exe --self-check db_open --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" --self-check-out "J:\Project_Vibe\V_book\build\verify_installed\db_open_installed.json"
   M:\Soft\HDLE\HDLE_ONNX_Probe.exe --mode import --out "J:\Project_Vibe\V_book\build\verify_installed\probe_import_installed.json"
   ```

   Required:
   - no `UnicodeEncodeError` dialog/window
   - `import_installed.json` exists and contains current `build.built_at_utc`
   - `health_installed.json` reports:
     - `frozen_onnx_probe.status = ok`
     - `bootstrap:pronunciation.status = ok`
     - `bootstrap:sentence_niqqud.status = ok`
   - `db_open_installed.json` exists and reports:
     - `ok = true`
     - current `schema_version`
     - current `supported_schema_version`
     - `db_profile`

8. **Verify installer really deployed the latest binaries:**

   If tests still show old behavior, do not assume the code fix failed. First verify
   that the install directory actually updated.

   ```powershell
   Get-Item .\dist\HDLE_Premium\HDLE_Premium.exe | Select-Object FullName,Length,LastWriteTime
   Get-Item "M:\Soft\HDLE\HDLE_Premium.exe" | Select-Object FullName,Length,LastWriteTime
   Get-Item "M:\Soft\HDLE\HDLE_ONNX_Probe.exe" | Select-Object FullName,Length,LastWriteTime
   ```

   If installed timestamps do not match the latest build wave:

   ```powershell
   .\installer\output\HDLE_Premium_Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="M:\Soft\HDLE" /LOG="J:\Project_Vibe\V_book\build\logs\installer_reinstall.log"
   Get-Content "J:\Project_Vibe\V_book\build\logs\installer_reinstall.log" -Tail 200
   ```

   Release rule:

   - do not debug stale installed binaries as if they were current
   - first confirm installer deployment actually replaced `HDLE_Premium.exe` and `HDLE_ONNX_Probe.exe`

### Step 2A: Runtime DB Readiness Gate

Before treating installer smoke as passed, verify which DB the installed app will open by default.

Important:

- the installed app may open a large runtime DB from settings instead of the release baseline DB
- in this cycle the active installed DB was:
  - `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`
- that DB was still on `schema_version = 32`, so normal startup entered a long migration path before the UI appeared

Required checks:

```powershell
Get-Content "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\logs\hdle.log" -Tail 80
```

Look for:

- `Database: ...`
- `Database source: ...`
- `Current schema version: ...`

Release rule:

- if installed startup uses an old large DB that still needs migration, do not classify "app does not open" as a packaging regression until that migration path is resolved
- first distinguish:
  - frozen packaging/runtime failure
  - versus long first-run migration/backup of the active runtime DB

Operational recommendation:

- for deterministic install smoke, launch the installed app at least once with explicit `--db-path` to a known-good migrated DB
- if the default runtime DB is large and behind on schema, migrate it offline before final installer sign-off

Premium startup recommendation for heavy DB deployments:

- the installed app should reach the main window on a light local DB first
- it must not silently auto-attach a stale heavy settings DB before the UI appears
- if startup detects a large legacy settings DB behind current schema, defer it and fall back to the local default DB
- after the UI is visible, offer explicit reconnect/switch instead of blocking startup on backup+migration

Recommended reconnect target for release smoke:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

Required validation before reconnecting a heavy/baseline DB:

```powershell
python -c "import sqlite3; p=r'J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db'; c=sqlite3.connect(p); print({'schema_version': c.execute(\"SELECT value FROM schema_meta WHERE key='schema_version'\").fetchone()[0], 'quick_check': c.execute('PRAGMA quick_check').fetchone()[0]})"
```

Pass criteria:

- `schema_version = 42`
- `python scripts/repair_fts_schema.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" --dry-run` returns `status = OK`

Separate ongoing development target after the release cut:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`

This second DB is retained for:

- ongoing operator-style testing during the next development stage
- post-release regression work
- reproducing heavy-project issues without using the release reconnect target

It is not the primary release sign-off DB.

### Test on Clean Windows VM (Critical)

**Why:** Ensures app works without Python/dependencies installed.

**Setup:**
1. Create Windows 10/11 VM (VirtualBox, VMware, Hyper-V)
2. **Do NOT install Python** (simulates end-user environment)
3. Ensure internet connection (for Stanza model download)

**Test Procedure:**
1. Copy `HDLE_Premium_Setup.exe` to VM
2. Run installer
3. Launch app
4. **First-run Stanza download:**
   - App may download Stanza models (~300 MB)
   - This is expected behavior
   - Models stored in: `%LOCALAPPDATA%\HDLE\models\`
5. Create test project
6. Import sample document
7. Run NLP processing
8. Export to XLSX
9. Verify no errors in logs

**Expected result:** App works identically to development machine.

### Test Upgrade Installation

**Purpose:** Verify user data survives upgrades.

**Procedure:**
1. Install version 1.0.0
2. Create project, import data
3. Build version 1.0.1 (increment version in `installer.iss`)
4. Run new installer
5. Verify:
   - App files in `C:\Program Files\HDLE\` are updated
   - User data in `%LOCALAPPDATA%\HDLE\` is **UNCHANGED**
   - Old database, backups, logs are intact

### Test Uninstallation

**Procedure:**
1. Uninstall via Control Panel
2. Check `C:\Program Files\HDLE\` → Should be **DELETED**
3. Check `%LOCALAPPDATA%\HDLE\` → Should be **INTACT**
4. Uninstall shows message:
   ```
   Your user data has been preserved at:
   C:\Users\<username>\AppData\Local\HDLE
   ```

---

## File Structure

### Build Artifacts

```
J:\Project_Vibe\V_book\
├── build/
│   ├── v_book.spec              # PyInstaller spec file (onedir mode)
│   └── HDLE_Premium/            # PyInstaller build cache (auto-generated)
├── dist/
│   └── HDLE_Premium/            # Distribution folder (onedir mode)
│       ├── HDLE_Premium.exe     # Main executable
│       ├── Qt6/                 # Qt plugins and libraries
│       ├── torch/               # PyTorch libraries (torch_cpu.dll, etc.)
│       ├── sqlalchemy/          # SQLAlchemy and dependencies
│       └── ... (all dependencies in-place)
├── installer/
│   ├── installer.iss            # Inno Setup script
│   └── output/
│       └── HDLE_Premium_Setup.exe  # Windows installer (46 MB)
└── scripts/
    └── build_windows.ps1        # Build automation script
```

### User Data (Survives Upgrades/Uninstalls)

```
%LOCALAPPDATA%\HDLE\              # C:\Users\<username>\AppData\Local\HDLE\
├── hdle.db                       # Main database
├── hdle.db-wal                   # SQLite WAL journal
├── hdle.db-shm                   # SQLite shared memory
├── backups/                      # Migration backups
│   └── backup_YYYYMMDD_HHMMSS_*.db
├── snapshots/                    # Test snapshots
│   └── snapshot_YYYYMMDD_HHMMSS_*.db
├── logs/                         # Application logs
│   └── hdle_YYYYMMDD.log
└── models/                       # Stanza models (downloaded on first run)
    └── he/
        └── ...
```

---

## PyInstaller Spec File Details

### Included Files

**Migrations:**
- Source: `app/infra/migrations/*.sql`
- Target: `app/infra/migrations/` (inside .exe)
- Why: Required for database schema initialization

### Hidden Imports

**Critical imports** that PyInstaller may miss:

```python
hiddenimports=[
    'PyQt6.sip',                        # PyQt6 binding layer
    'sqlalchemy.dialects.sqlite',       # SQLite dialect
    'app.infra.sa_models',              # ORM models
    'psutil',                           # Process lock detection
]
```

**All services** are explicitly listed to ensure they're bundled.

### Excluded Files

```python
excludes=[
    'stanza_resources',  # Stanza models (100s of MB)
    'tkinter',           # Not used
    'matplotlib',        # Not used
]
```

**Bundled Hebrew payload** is staged into the release artifact for the managed
Stanza runtime. The managed runtime then copies it into `%LOCALAPPDATA%\HDLE\nlp_runtime\stanza_resources\`.

### UPX Compression

**Disabled:** `upx=False`

**Reason:** UPX can trigger antivirus false positives.

---

## Inno Setup Installer Details

### Installation Paths

| Component         | Path                                |
|-------------------|-------------------------------------|
| Application files | `C:\Program Files\HDLE\`            |
| User database     | `%LOCALAPPDATA%\HDLE\hdle.db`       |
| Logs              | `%LOCALAPPDATA%\HDLE\logs\`         |
| Backups           | `%LOCALAPPDATA%\HDLE\backups\`      |
| Snapshots         | `%LOCALAPPDATA%\HDLE\snapshots\`    |
| Stanza models     | `%LOCALAPPDATA%\HDLE\models\`       |

### Upgrade Behavior

**What gets replaced:**
- ✅ Application folder: `C:\Program Files\HDLE\` (entire folder)

**What survives:**
- ✅ Database: `%LOCALAPPDATA%\HDLE\hdle.db`
- ✅ Backups: `%LOCALAPPDATA%\HDLE\backups\`
- ✅ Logs: `%LOCALAPPDATA%\HDLE\logs\`
- ✅ Stanza models: `%LOCALAPPDATA%\HDLE\models\`

**How it works:** User data is in `%LOCALAPPDATA%`, which is NOT managed by the installer.

### Uninstall Behavior

**Deleted:**
- ✅ `C:\Program Files\HDLE\` (application files)
- ✅ Start menu shortcuts
- ✅ Desktop shortcut (if created)

**NOT deleted:**
- ✅ `%LOCALAPPDATA%\HDLE\` (user data)

**User notification:** Uninstaller shows a message box explaining that user data was preserved and how to manually delete it.

---

## Troubleshooting

### PyInstaller Build Fails

**Error:** `ModuleNotFoundError: No module named 'xyz'`

**Solution:** Add missing module to `hiddenimports` in `build/v_book.spec`.

**Error:** `FileNotFoundError: app/infra/migrations`

**Solution:** Ensure migrations directory exists and is committed to git.

### Installer Build Fails

**Error:** `ISCC.exe : The term 'ISCC.exe' is not recognized...`

**Solution:** Inno Setup not in PATH. Use full path:
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss
```

**Error:** `Unable to open file "dist\HDLE_Premium\HDLE_Premium.exe"`

**Solution:** Run PyInstaller build first (`.\scripts\build_windows.ps1`).

### App Crashes on Launch

**Error:** `Failed to extract torch\lib\torch_cpu.dll: decompression resulted in return code -1`

**Root cause:** PyInstaller onefile mode fails to decompress large PyTorch DLL files at runtime.

**Solution:** Already implemented - using onedir mode (`exclude_binaries=True` in spec). This keeps all files extracted on disk, avoiding runtime decompression.

**Error:** DLL load failures

**Solution:**
1. Rebuild with `--clean` flag
2. Check that all PyQt6 dependencies are installed
3. Test on development machine first
4. Verify using onedir mode (not onefile)

**Error:** `sqlite3.OperationalError: unable to open database file`

**Solution:** Insufficient permissions to `%LOCALAPPDATA%`. Run as administrator.

### Stanza Models Not Downloading

**Error:** `ConnectionError` or `TimeoutError`

**Solution:**
1. Ensure internet connection
2. Check firewall settings
3. For offline installations, see "Offline Installer" section below

---

## Advanced Topics

### Offline Installer (Optional)

If you need to create an installer that works without internet:

1. **Download Stanza models manually:**
   ```python
   import stanza
   stanza.download('he')
   ```

2. **Locate models:**
   - Default location: `%USERPROFILE%\stanza_resources\he\`

3. **Modify installer.iss:**
   ```ini
   [Files]
   Source: "dist\HDLE_Premium.exe"; DestDir: "{app}"; Flags: ignoreversion
   Source: "stanza_models\he\*"; DestDir: "{localappdata}\HDLE\models\he"; Flags: recursesubdirs
   ```

4. **Rebuild installer:**
   ```powershell
   ISCC.exe installer\installer.iss
   ```

**Result:** Installer is ~350 MB (includes Stanza models).

### Code Signing (Optional)

To avoid "Unknown Publisher" warnings:

1. **Obtain code signing certificate** (from CA like DigiCert, Sectigo)
2. **Sign executable:**
   ```powershell
   signtool sign /f cert.pfx /p password /t http://timestamp.digicert.com dist\HDLE_Premium.exe
   ```
3. **Sign installer:**
   ```powershell
   signtool sign /f cert.pfx /p password /t http://timestamp.digicert.com installer\output\HDLE_Premium_Setup.exe
   ```

### Custom Icon (Optional)

If you have a custom icon file:

1. **Create icon file:**
   - Format: `.ico`
   - Sizes: 16x16, 32x32, 48x48, 256x256
   - Location: `resources/icon.ico`

2. **Update spec file:**
   ```python
   exe = EXE(
       ...
       icon='resources/icon.ico'
   )
   ```

3. **Update installer.iss:**
   ```ini
   [Setup]
   SetupIconFile=resources\icon.ico
   ```

4. **Rebuild:**
   ```powershell
   .\scripts\build_windows.ps1
   ISCC.exe installer\installer.iss
   ```

---

## Version Management

### Incrementing Version Number

To release a new version (e.g., 1.0.0 → 1.0.1):

1. **Update installer.iss:**
   ```ini
   [Setup]
   AppVersion=1.0.1
   VersionInfoVersion=1.0.1.0
   ```

2. **Update pyproject.toml:**
   ```toml
   [project]
   version = "1.0.1"
   ```

3. **Rebuild:**
   ```powershell
   .\scripts\build_windows.ps1
   ISCC.exe installer\installer.iss
   ```

4. **Tag in git:**
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```

---

## Distribution

### Release Checklist

- [ ] Build standalone executable
- [ ] Test on development machine
- [ ] Test on clean Windows VM
- [ ] Build installer
- [ ] Test installer on clean VM
- [ ] Test upgrade installation
- [ ] Verify user data preservation
- [ ] Create release notes
- [ ] Upload to GitHub Releases
- [ ] Tag git commit

### GitHub Release

1. **Create release on GitHub:**
   - Go to Releases → Draft a new release
   - Tag: `v1.0.0`
   - Title: `HDLE Premium v1.0.0`
   - Upload: `HDLE_Premium_Setup.exe`

2. **Release notes template:**
   ```markdown
   # HDLE Premium v1.0.0

   ## Features
   - Translation Memory (M7)
   - Term Curation (M8)
   - Export Center (M9): XLSX, TBX, TMX, CSV, JSON
   - Auto-backup before migrations (M10)
   - Crash recovery (M10)

   ## Installation
   Download and run `HDLE_Premium_Setup.exe`

   ## Requirements
   - Windows 10/11 (64-bit)
   - ~500 MB disk space
   - Internet connection (first run only, for Stanza models)

   ## Upgrading
   Run the new installer. Your data will be preserved automatically.

   ## Known Issues
   None

   ## Support
   Report issues: https://github.com/yourusername/v_book/issues
   ```

---

## Summary

**Build commands:**
```powershell
# 1. Build standalone executable
.\scripts\build_windows.ps1

# 2. Build installer
ISCC.exe installer\installer.iss

# 3. Output
# - Executable: dist\HDLE_Premium.exe
# - Installer: installer\output\HDLE_Premium_Setup.exe
```

**Key points:**
- User data in `%LOCALAPPDATA%\HDLE\` survives upgrades/uninstalls
- Stanza models downloaded on first run
- Test on clean VM before release
- Increment version in `installer.iss` for each release

---

## Related Documentation

- **Backup Policy:** `M10_BACKUP_POLICY.md`
- **Crash Recovery:** `M10_CRASH_RECOVERY.md`
- **Release Checklist:** `RELEASE_CHECKLIST_WINDOWS.md`
