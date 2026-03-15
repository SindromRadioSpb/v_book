# Windows Release Checklist

This checklist ensures that the Windows installer works correctly on clean systems and that user data survives upgrades.

---

## Prerequisites

- [ ] Clean Windows VM (Windows 10/11)
- [ ] No Python installed (simulating end-user environment)
- [ ] Internet connection (for Stanza models first-run download)
- [ ] ~1 GB free disk space

---

## Build Steps

### 0. Recovery Tooling Precheck

- [ ] If release baseline DB recovery is needed, use:
  - `C:\msys64\ucrt64\bin\sqlite3.exe`
- [ ] Verify selected sqlite3 supports `.recover`:
  ```powershell
  & "C:\msys64\ucrt64\bin\sqlite3.exe" -version
  cmd /c "echo .help | C:\msys64\ucrt64\bin\sqlite3.exe"
  ```
- [ ] Do not use older sqlite3 binaries that fail with:
  - `unknown command or invalid arguments: "recover"`
- [ ] `python scripts/prebuild_validate.py --db-path "<release-candidate-db>"` does not fail on the new corruption probe
- [ ] `python scripts/prebuild_validate.py --db-path "<release-candidate-db>" --report-json-out "build\\verify\\prebuild_validate.json"` writes a JSON release-evidence artifact
- [ ] If prebuild validation stops on corruption probe, repair first:
  - `python scripts/repair_db_corruption.py --db-path "<release-candidate-db>"`

### 1. Build Standalone Executable

```powershell
cd J:\Project_Vibe\V_book
.\scripts\build_windows.ps1
```

**Verify:**
- [ ] Build completes without errors
- [ ] `dist\HDLE_Premium\HDLE_Premium.exe` exists
- [ ] Distribution folder `dist\HDLE_Premium\` contains all dependencies
- [ ] Run smoke test: `.\scripts\run_packaged_smoke.ps1`
- [ ] Build metadata generated (commit/dirty/built_at)
- [ ] `powershell -ExecutionPolicy Bypass -File scripts\verify_frozen_health.ps1` passes
- [ ] `build\verify\build_meta_dist.txt` exists and commit matches target release SHA

**Required model staging gate:**
- [ ] Required offline niqqud model exists at:
  - `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\models\phonikud\phonikud-1.0.int8.onnx`
- [ ] `rebuild.ps1` stages it into:
  - `installer\resources\local_models\phonikud\phonikud-1.0.int8.onnx`
- [ ] Staged model path remains git-ignored and is not committed to the repo

**Additional frozen runtime gates:**
- [ ] `.\dist\HDLE_Premium\HDLE_ONNX_Probe.exe --mode import --out "build\verify_dist\probe_import_dist.json"` passes
- [ ] `build\verify_dist\import_dist.json` confirms `checks.onnxruntime_import.helper_path` points to `HDLE_ONNX_Probe.exe`
- [ ] `build\verify_dist\health_dist.json` reports:
  - `frozen_onnx_probe.status = ok`
  - `bootstrap:pronunciation.status = ok`
  - `bootstrap:sentence_niqqud.status = ok`
- [ ] `--self-check import` and `--self-check health` do not crash with `UnicodeEncodeError`

### 2. Build Installer

```powershell
# If ISCC in PATH:
ISCC.exe installer\installer.iss

# If not in PATH:
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\installer.iss
```

**Verify:**
- [ ] Build completes without errors
- [ ] `installer\output\HDLE_Premium_Setup.exe` exists
- [ ] File size ~46 MB

---

## Testing on Clean VM

### 1. Fresh Installation

**Copy installer to VM:**
- [ ] Transfer `HDLE_Premium_Setup.exe` to VM

**Run installer:**
- [ ] Double-click `HDLE_Premium_Setup.exe`
- [ ] Follow wizard (accept defaults)
- [ ] Installation completes successfully

**Installed binary freshness gate:**
- [ ] Installed `HDLE_Premium.exe` timestamp matches the latest build
- [ ] Installed `HDLE_ONNX_Probe.exe` timestamp matches the latest build

**Verify installation:**
- [ ] Installed to `C:\Program Files\HDLE\`
- [ ] Start menu shortcut: Start → HDLE Premium
- [ ] Desktop shortcut (if selected during install)

### 2. First Run

**Launch app:**
- [ ] Start → HDLE Premium
- [ ] App launches (may take 10-20s on first run)
- [ ] Help → About HDLE Premium shows version + commit + dirty + built_at

**Installed self-check gates:**
- [ ] `HDLE_Premium.exe --self-check import --self-check-out ...` succeeds
- [ ] `HDLE_Premium.exe --self-check health --db-path "<known-good migrated db>" --self-check-out ...` succeeds
- [ ] No `UnicodeEncodeError` window/dialog appears during self-check
- [ ] Installed health JSON reports:
  - `frozen_onnx_probe.status = ok`
  - `bootstrap:pronunciation.status = ok`
  - `bootstrap:sentence_niqqud.status = ok`
  - `report.overall = ok`

**Stanza models download (if internet available):**
- [ ] Check logs for model download messages
- [ ] Models stored in: `%LOCALAPPDATA%\HDLE\models\`
- [ ] Download completes successfully (~300 MB)

**Database initialization:**
- [ ] DB created at `%LOCALAPPDATA%\HDLE\hdle.db`
- [ ] Logs created at `%LOCALAPPDATA%\HDLE\logs\`
- [ ] No errors in logs
- [ ] First launch reaches the main window without auto-attaching a stale heavy settings DB before UI appears
- [ ] If a large legacy settings DB is deferred, startup still opens on the local default DB and explains that explicit reconnect is available
- [ ] If the heavy runtime DB is already migrated and healthy, opening it from settings does not block the window from appearing in a reasonable time

**Active runtime DB gate:**
- [ ] Log confirms the actual active DB path
- [ ] Log confirms `Database source`
- [ ] Log confirms current schema version
- [ ] If startup is slow, distinguish packaged-app failure from long first-run migration/backup of an existing large DB

### 2A. Runtime DB Readiness Gate

Before final sign-off, inspect the DB that the installed app opens without CLI overrides.

Commands:

```powershell
Get-Content "$env:LOCALAPPDATA\HDLE\logs\hdle.log" -Tail 80
```

If this deployment uses a custom app root, inspect that concrete log path instead.

Required:
- [ ] log shows `Database: ...`
- [ ] log shows `Database source: ...`
- [ ] log shows current schema version
- [ ] no stale `app_instance.lock` / `migrate.lock` loop remains

Decision rule:
- [ ] if startup delay is caused by first-run migration of a huge existing DB, treat it as runtime DB readiness work, not as proof that the packaged binaries are broken
- [ ] for deterministic install smoke, launch once with explicit `--db-path` to a known-good migrated DB
- [ ] premium sign-off requires one successful launch without CLI overrides and without implicit startup migration of a stale heavy settings DB

Known-good reconnect target for release smoke:

- [ ] `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
- [ ] Verify before reconnect:
  - `schema_version = 35`
  - `PRAGMA quick_check = ok`

### 3. Basic Functionality Test

**Create library:**
- [ ] Click "Create Library"
- [ ] Enter name: "Test Library"
- [ ] Library created successfully

**Create project:**
- [ ] Click "Create Project"
- [ ] Enter name: "Test Project"
- [ ] Source: Hebrew, Target: Russian
- [ ] Project created successfully

**Import document:**
- [ ] Import → Add DOCX file
- [ ] File appears in corpus list
- [ ] Document count increments

**Export test:**
- [ ] Export → XLSX
- [ ] Select save location
- [ ] Export completes
- [ ] Open XLSX in Excel
- [ ] Verify sheets: Dictionary, Statistics

**Pronunciation smoke:**
- [ ] Open Health Check
- [ ] Verify `Pronunciation Bootstrap` is `ok`
- [ ] Verify `Sentence Niqqud Bootstrap` is `ok`

### 4. Crash Recovery Test

**Trigger crash:**
- [ ] Start NLP processing (if available)
- [ ] Force-quit app via Task Manager (End Task)

**Restart app:**
- [ ] Launch app again
- [ ] Check logs: `%LOCALAPPDATA%\HDLE\logs\`
- [ ] Search for: "Crash recovery" or "unfinished runs"

**Expected log entry:**
```
WARNING: Found X unfinished runs - recovering...
INFO: Recovered X runs
```

- [ ] Crash recovery message appears in logs
- [ ] Verify runs marked as failed in UI (if processing history visible)
- [ ] App continues to work normally

### 5. Upgrade Installation Test

**Build new version:**
- [ ] Increment version in `installer.iss` (e.g., 1.0.0 → 1.0.1)
- [ ] Rebuild installer
- [ ] Transfer new installer to VM

**Before upgrade - record data:**
- [ ] Count projects in current installation
- [ ] Note database size: `ls $env:LOCALAPPDATA\HDLE\hdle.db`
- [ ] Note backup count: `ls $env:LOCALAPPDATA\HDLE\backups\`

**Run upgrade installer:**
- [ ] Double-click `HDLE_Premium_Setup.exe` (version 1.0.1)
- [ ] Installer detects previous version
- [ ] Upgrade completes

**After upgrade - verify preservation:**
- [ ] Application files in `C:\Program Files\HDLE\` updated
- [ ] Database in `%LOCALAPPDATA%\HDLE\hdle.db` unchanged
- [ ] Project count matches pre-upgrade
- [ ] Backups in `%LOCALAPPDATA%\HDLE\backups\` preserved
- [ ] Logs in `%LOCALAPPDATA%\HDLE\logs\` preserved
- [ ] Stanza models in `%LOCALAPPDATA%\HDLE\models\` preserved

**Launch upgraded app:**
- [ ] App launches successfully
- [ ] All data intact (projects, libraries visible)
- [ ] No errors in logs

### 6. Uninstall Test

**Uninstall via Control Panel:**
- [ ] Control Panel → Programs → Uninstall a program
- [ ] Select "HDLE Premium"
- [ ] Click Uninstall
- [ ] Uninstaller displays data preservation message
- [ ] Uninstall completes

**Verify cleanup:**
- [ ] Application removed from `C:\Program Files\HDLE\`
- [ ] Start menu shortcuts removed
- [ ] Desktop shortcut removed (if created)

**Verify data preservation:**
- [ ] Database **STILL EXISTS**: `%LOCALAPPDATA%\HDLE\hdle.db`
- [ ] Backups **STILL EXIST**: `%LOCALAPPDATA%\HDLE\backups\`
- [ ] Logs **STILL EXIST**: `%LOCALAPPDATA%\HDLE\logs\`
- [ ] Stanza models **STILL EXIST**: `%LOCALAPPDATA%\HDLE\models\`

**Message box:**
- [ ] Uninstaller shows message: "Your user data has been preserved at: C:\Users\<username>\AppData\Local\HDLE"

### 7. Clean Uninstall (Optional)

**Manual data cleanup:**
```powershell
Remove-Item -Recurse -Force $env:LOCALAPPDATA\HDLE
```

- [ ] All user data removed
- [ ] No traces of HDLE Premium remain

---

## Performance Checks

### Startup Time

- [ ] First run: < 30s (includes model download)
- [ ] Subsequent runs: < 5s

### Memory Usage

- [ ] Idle: < 200 MB
- [ ] During NLP processing: < 1 GB

### Database Size

- [ ] Empty project: ~350 KB
- [ ] With 100 documents: < 50 MB (varies by content)

---

## Error Scenarios

### 1. Insufficient Disk Space

**Test:**
- [ ] Limit VM disk space to < 500 MB
- [ ] Attempt installation

**Expected:**
- [ ] Installer warns about disk space
- [ ] OR installation fails gracefully with error message

### 2. No Internet (First Run)

**Test:**
- [ ] Disconnect VM from internet
- [ ] Launch app (first run)

**Expected:**
- [ ] App launches successfully
- [ ] Warning about Stanza models not available
- [ ] App continues to function (without NLP)
- [ ] OR app provides clear instructions to download models manually

### 3. Corrupted Database

**Test:**
- [ ] Delete lines from `hdle.db` (simulate corruption)
- [ ] Launch app

**Expected:**
- [ ] App detects corruption
- [ ] Offers to restore from backup
- [ ] OR prompts user to delete database and start fresh

### 4. Missing Backups Directory

**Test:**
- [ ] Delete `%LOCALAPPDATA%\HDLE\backups\` directory
- [ ] Trigger migration (upgrade to new version)

**Expected:**
- [ ] App creates `backups/` directory automatically
- [ ] Migration proceeds normally

---

## Known Issues & Workarounds

### 1. Antivirus False Positives

**Issue:** Some antivirus software may flag `HDLE_Premium.exe` as suspicious

**Workaround:**
- Add exception in antivirus settings
- Submit to antivirus vendor for whitelisting

**Future:** Code signing certificate will eliminate this issue

### 2. Unicode Font Issues

**Issue:** Hebrew characters may not render correctly on clean VM

**Cause:** Missing Hebrew fonts

**Workaround:**
- Install language pack for Hebrew
- Windows Update should provide fonts automatically

### 3. Slow First-Run Stanza Download

**Issue:** First run may take 5-10 minutes if downloading Stanza models

**Workaround:**
- Document expected delay in README
- Provide progress indicator in app (future enhancement)

---

## Sign-Off

**Tested by:** ________________

**Date:** ________________

**VM OS:** Windows _____ (10/11)

**Build Version:** ________________

**Build SHA:** ________________ (git commit hash)

**Build Dirty:** ________________ (0/1)

**Build UTC Timestamp:** ________________

**Test Results:**

- [ ] Fresh installation: PASS
- [ ] First run: PASS
- [ ] Basic functionality: PASS
- [ ] Crash recovery: PASS
- [ ] Upgrade installation: PASS
- [ ] Uninstall: PASS

**Overall Status:** ☐ PASS  ☐ FAIL

**Notes:**
_________________________________________________
_________________________________________________
_________________________________________________

---

## Troubleshooting

### Installer Won't Run

**Symptoms:** Double-click installer, nothing happens

**Check:**
1. User has Administrator privileges
2. Installer file is not corrupted (check file size)
3. Antivirus is not blocking installer

### App Crashes on Startup

**Symptoms:** App launches and immediately closes

**Check:**
1. `%LOCALAPPDATA%\HDLE\logs\` for error messages
2. Missing DLLs (unlikely with PyInstaller bundle)
3. Corrupted database (delete `hdle.db` and restart)

### Database Errors

**Symptoms:** "Database is locked" or "Database disk image is malformed"

**Check:**
1. Close all instances of HDLE Premium
2. Delete WAL files: `hdle.db-wal`, `hdle.db-shm`
3. Restore from backup (see `M10_BACKUP_POLICY.md`)

### Stanza Models Won't Download

**Symptoms:** "Failed to download language model"

**Check:**
1. Internet connection active
2. Firewall not blocking app
3. Sufficient disk space

---

## Appendix: Test Data

### Sample DOCX Files

**Minimal test document:**
- File size: < 10 KB
- Content: 2-3 paragraphs of Hebrew text
- Purpose: Quick smoke test

**Medium test document:**
- File size: ~100 KB
- Content: 10-20 paragraphs
- Purpose: Performance test

**Large test document:**
- File size: ~1 MB
- Content: Full article or book chapter
- Purpose: Stress test

### Expected Metrics

**Empty project:**
- Documents: 0
- Lemmas: 0
- Terms: 0
- TM Entries: 0

**After importing medium doc:**
- Documents: 1
- Lemmas: ~200-500 (varies by content)
- Terms: ~50-100 (varies)
- TM Entries: 0 (until translated)

---

**Last Updated:** 2026-02-05
