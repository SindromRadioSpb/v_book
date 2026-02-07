# HDLE Premium - Installer Location Guide

**Last Updated:** 2026-02-07
**Version:** 1.0.0 (P0 Security Hardening Baseline)

---

## Quick Reference - Where to Find Files

### 📦 Production Installer (Single-File Setup.exe)

**Location:**
```
installer/output/HDLE_Premium_Setup.exe
```

**Type:** Inno Setup installer (self-extracting)
**Size:** ~1.5-2 GB (compressed)
**Distribution:** Upload to GitHub Releases or distribute directly

**Build Command:**
```powershell
# From project root
& "C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\installer.iss
```

**Automated Build:**
```powershell
.\scripts\build_windows.ps1          # Build onedir executable first
.\scripts\build_installer.ps1        # Build installer (TBD - create this script)
```

---

### 🗂️ Development Executable (Onedir Distribution)

**Location:**
```
dist/HDLE_Premium/
├── HDLE_Premium.exe          (44 MB)
└── _internal/                 (4.5 GB dependencies)
```

**Type:** Standalone executable (requires entire folder)
**Size:** ~4.5-5 GB (uncompressed)
**Distribution:** Compress to ZIP for sharing

**Build Command:**
```powershell
# From project root
.\scripts\build_windows.ps1

# Or manually:
pyinstaller build\v_book.spec --clean --noconfirm
```

**Deployed Copy (for local use):**
```
M:\Soft\V_book\HDLE_Premium\
```

---

## Installation Types Comparison

| Aspect | **Installer (Setup.exe)** | **Onedir (Folder)** |
|--------|--------------------------|---------------------|
| **File** | Single .exe file | Entire HDLE_Premium/ folder |
| **Size** | ~1.5-2 GB (compressed) | ~4.5-5 GB (uncompressed) |
| **Installation** | Wizard-based, installs to Program Files | Manual copy to any location |
| **Shortcuts** | Auto-creates (Start Menu, Desktop) | Manual creation required |
| **Uninstall** | Via Control Panel | Manual folder deletion |
| **Upgrades** | Automated (preserves user data) | Manual (overwrite folder) |
| **User Data** | Preserved in %LOCALAPPDATA%\HDLE\ | Same |
| **Distribution** | ✅ End users, releases | ✅ Testing, portable deployment |

---

## Build Workflow

### Standard Release Build Process

```powershell
# Step 1: Build onedir executable
cd J:\Project_Vibe\V_book
.\scripts\build_windows.ps1

# Expected output:
# dist/HDLE_Premium/HDLE_Premium.exe (44 MB + 4.5 GB dependencies)

# Step 2: Build installer
& "C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\installer.iss

# Expected output:
# installer/output/HDLE_Premium_Setup.exe (~1.5-2 GB)

# Step 3: Test installer
.\installer\output\HDLE_Premium_Setup.exe

# Step 4: Upload to GitHub Release
# See RELEASE_NOTES_v1.0.0.md for instructions
```

---

## Installer Configuration

### Inno Setup Script
**File:** `installer/installer.iss`

**Key Settings:**
```ini
[Setup]
AppName=HDLE Premium
AppVersion=1.0.0
OutputDir=installer\output
OutputBaseFilename=HDLE_Premium_Setup

[Files]
; Bundles entire onedir distribution
Source: "..\dist\HDLE_Premium\*"
DestDir: "{app}"
Flags: ignoreversion recursesubdirs createallsubdirs
```

**Installation Paths:**
- **Application Files:** `C:\Program Files\HDLE\` (managed by installer)
- **User Data:** `%LOCALAPPDATA%\HDLE\` (NOT managed, survives uninstall)

**User Data Includes:**
- `hdle.db` (database with migrations)
- `logs/` (application logs)
- `backups/` (migration backups)
- `snapshots/` (test snapshots)
- `models/` (Stanza Hebrew models, downloaded on first run)

---

## Tools Required

### For Building Onedir Executable

**Required:**
- Python 3.11+ (currently 3.13.2)
- Virtual environment (`.venv`)
- PyInstaller 6.18.0+ (installed in venv)

**Install:**
```powershell
pip install pyinstaller
```

### For Building Installer

**Required:**
- Inno Setup 6.7.0+

**Install:**
```powershell
# Via winget (recommended)
winget install --id JRSoftware.InnoSetup

# Default installation path:
# C:\Users\<username>\AppData\Local\Programs\Inno Setup 6\ISCC.exe
```

**Verify Installation:**
```powershell
& "C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6\ISCC.exe" /?
```

---

## Version Management

### Incrementing Version for New Release

**1. Update Installer Script (`installer/installer.iss`):**
```ini
[Setup]
AppVersion=1.0.1                    ; <-- Change here
VersionInfoVersion=1.0.1.0          ; <-- And here
```

**2. Update Project Metadata (`pyproject.toml`):**
```toml
[project]
version = "1.0.1"                   ; <-- Change here
```

**3. Rebuild Both Artifacts:**
```powershell
.\scripts\build_windows.ps1                          # Rebuild executable
& "C:\Users\...\ISCC.exe" installer\installer.iss    # Rebuild installer
```

**4. Tag in Git:**
```powershell
git tag v1.0.1
git push origin v1.0.1
```

---

## Distribution Checklist

### For GitHub Releases

- [ ] Build onedir executable (`dist/HDLE_Premium/`)
- [ ] Build installer (`installer/output/HDLE_Premium_Setup.exe`)
- [ ] Test installer on clean Windows VM
- [ ] Verify migrations apply to schema v8
- [ ] Verify security tables exist (audit_log, credentials)
- [ ] Create ZIP of onedir (optional, for advanced users)
- [ ] Upload installer to GitHub Release
- [ ] Update release notes with install instructions
- [ ] Tag commit (`git tag v1.0.0`)

### For Local Deployment

- [ ] Build onedir executable
- [ ] Copy to `M:\Soft\V_book\HDLE_Premium\`
- [ ] Test executable launches
- [ ] Verify user data in `%LOCALAPPDATA%\HDLE\`

---

## Troubleshooting

### Installer Build Fails

**Error:** `No files found matching "dist\HDLE_Premium\*"`

**Solution:** Build onedir executable first:
```powershell
.\scripts\build_windows.ps1
```

---

**Error:** `Could not read "compiler:WizModernImage-IS.bmp"`

**Solution:** Already fixed in `installer/installer.iss` (wizard images commented out)

---

### ISCC.exe Not Found in PATH

**Solution:** Use full path:
```powershell
& "C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\installer.iss
```

Or add to PATH:
```powershell
$env:PATH += ";C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6"
```

---

### Installer Size Too Large

**Expected:** ~1.5-2 GB (compressed)
**Reason:** Includes PyTorch (~2 GB) and all dependencies

**Options to Reduce Size:**
1. Exclude CUDA libraries (if CPU-only deployment)
2. Use separate package for Stanza models (download on first run)
3. Consider installer variants (Full vs Lite)

**Current Strategy:** Single full installer with all dependencies (easiest for end users)

---

## File Paths Summary

```
J:\Project_Vibe\V_book\
│
├── installer/
│   ├── installer.iss                    # Inno Setup script
│   └── output/
│       └── HDLE_Premium_Setup.exe       # ✅ PRODUCTION INSTALLER (distribute this)
│
├── dist/
│   └── HDLE_Premium/
│       ├── HDLE_Premium.exe             # Main executable
│       └── _internal/                    # Dependencies (4.5 GB)
│
├── build/
│   └── v_book.spec                      # PyInstaller configuration
│
└── scripts/
    ├── build_windows.ps1                # Build onedir executable
    └── find_inno.ps1                    # Locate Inno Setup installation
```

**Deployed Copy (local use):**
```
M:\Soft\V_book\HDLE_Premium\             # Deployed onedir for testing
```

---

## Best Practices

### Always Test Both Artifacts

**1. Onedir Executable:**
```powershell
.\dist\HDLE_Premium\HDLE_Premium.exe
```

**2. Installer:**
```powershell
.\installer\output\HDLE_Premium_Setup.exe
```

**3. Test on Clean VM** (critical before release):
- No Python installed
- Fresh Windows 10/11 installation
- Internet connection (for Stanza models)

### Keep Installer and Executable in Sync

**After any code changes:**
```powershell
# Rebuild both
.\scripts\build_windows.ps1           # Updates dist/
& "...\ISCC.exe" installer\installer.iss  # Updates installer/output/
```

### Version Control

**Commit installer script changes:**
```powershell
git add installer/installer.iss
git commit -m "chore(installer): bump version to 1.0.1"
```

**Do NOT commit build artifacts:**
- `dist/` (in .gitignore)
- `installer/output/` (in .gitignore)
- `build/` (in .gitignore, except v_book.spec)

---

## Related Documentation

- **BUILD_WINDOWS_INSTALLER.md** - Complete installer guide with Inno Setup details
- **BUILD_REPORT_P0_BASELINE_EXE.md** - Latest build report (v1.0.0)
- **RELEASE_NOTES_v1.0.0.md** - Release notes for GitHub
- **GATE_REPORT.md** - Pre-push verification report

---

**Maintained by:** Release Engineering
**For Questions:** See [BUILD_WINDOWS_INSTALLER.md](BUILD_WINDOWS_INSTALLER.md) for detailed instructions
