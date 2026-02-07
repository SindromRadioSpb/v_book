# Create GitHub Release for v1.0.0-p0-baseline
#
# This script creates a GitHub Release using GitHub CLI (gh).
# If gh is not installed, it will provide instructions for manual creation.

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  GitHub Release Creator" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if gh CLI is installed
$ghVersion = gh --version 2>$null

if (-not $ghVersion) {
    Write-Host "GitHub CLI (gh) not found." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Option 1: Install GitHub CLI and run this script again" -ForegroundColor White
    Write-Host "  winget install --id GitHub.cli" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Option 2: Create release manually via web interface" -ForegroundColor White
    Write-Host "  1. Go to: https://github.com/SindromRadioSpb/v_book/releases/new" -ForegroundColor Gray
    Write-Host "  2. Select tag: v1.0.0-p0-baseline" -ForegroundColor Gray
    Write-Host "  3. Title: HDLE Premium v1.0.0 - P0 Security Hardening Baseline" -ForegroundColor Gray
    Write-Host "  4. Copy release notes from below" -ForegroundColor Gray
    Write-Host ""
    Write-Host "--- RELEASE NOTES (copy this) ---" -ForegroundColor Cyan
    Write-Host ""

    $releaseNotes = @"
# HDLE Premium v1.0.0 - P0 Security Hardening Baseline

First production release after comprehensive P0 Security Hardening implementation.

## 🎯 Features

### Core Functionality
- **M7: Translation Memory** - Offline dictionary + user overrides + MT cache
- **M8: Term Curation** - Review workflow with approval states
- **M9: Export Center** - XLSX, TBX, TMX, CSV, JSON exports with statistics
- **M10: Backup & Recovery** - Auto-backup before migrations, crash recovery

### 🔒 P0 Security Hardening (NEW)
**Defense-in-Depth Architecture (7 Layers):**
1. **UI Validation** - Query complexity limits before search
2. **Service Validation** - FTS5 sanitization, path security checks
3. **Rate Limiting** - Token bucket algorithm (60/min imports, 30/min exports)
4. **Audit Logging** - All security events → ``security_audit_log`` table
5. **Cryptography** - AES-256-GCM authenticated encryption
6. **Database** - Encrypted credentials storage
7. **OS Keyring** - Master key protection (Windows Credential Manager)

**Attack Surface Mitigations:**
- ✅ FTS5 injection prevention (query sanitization, operator blocking)
- ✅ CSV formula injection neutralization (``=+-@`` prefix escaping)
- ✅ Log injection prevention (CRLF replacement)
- ✅ Path traversal protection (UNC blocking, system dir exclusion)
- ✅ File size DoS prevention (100 MB documents, 10 MB dictionaries)
- ✅ Credential exposure protection (AES-256-GCM encryption at rest)

## 📊 Database

- **Schema Version:** v8
- **Total Tables:** 47
- **Migrations:** 001-008 (including security tables: ``security_audit_log``, ``credentials``)

## 🛠️ Technical Details

### Build
- **Commit:** 9e7ffe7
- **Build Date:** 2026-02-07
- **Build Tool:** PyInstaller 6.18.0 (onedir mode)
- **Executable Size:** 44 MB
- **Total Package Size:** ~4.5 GB (includes PyTorch, PyQt6, all dependencies)

### Dependencies
- **Python:** 3.13.2
- **PyQt6:** 6.10.2 (UI framework)
- **cryptography:** 46.0.4 (AES-256-GCM encryption)
- **keyring:** 25.7.0 (OS credential storage)
- **SQLAlchemy:** 2.0.36 (ORM + migrations)
- **torch:** 2.6.0+cpu (Stanza NLP backend)

### Verification
- ✅ Runtime tests: 3/3 PASS
- ✅ PATCH-06 smoke tests: 6/6 PASS
- ✅ Security tables: ``security_audit_log`` + ``credentials``
- ✅ Defense-in-depth: 7 layers operational

## 💾 Requirements

- **OS:** Windows 10/11 (64-bit)
- **Disk Space:** ~5 GB
- **Internet:** Required on first run only (for Stanza Hebrew models ~300 MB)
- **Permissions:** Standard user (no admin required)

## 📥 Installation

1. Download ``HDLE_Premium.zip`` from Assets below
2. Extract to desired location (e.g., ``C:\Program Files\HDLE\``)
3. Run ``HDLE_Premium.exe``
4. **First run:** Application will:
   - Create ``%LOCALAPPDATA%\HDLE\`` directory
   - Initialize database (``hdle.db``) with schema v8
   - Download Stanza Hebrew models (~300 MB, requires internet)
   - Create ``logs/``, ``backups/``, ``snapshots/`` subdirectories

## 🔄 Upgrading from Previous Versions

**User data is preserved automatically:**
- Database: ``%LOCALAPPDATA%\HDLE\hdle.db`` (upgraded via migrations)
- Backups: ``%LOCALAPPDATA%\HDLE\backups\`` (kept intact)
- Logs: ``%LOCALAPPDATA%\HDLE\logs\`` (kept intact)

**To upgrade:**
1. Close running application
2. Extract new version over old installation
3. Launch ``HDLE_Premium.exe``
4. Migrations apply automatically

## 📚 Documentation

- [BUILD_REPORT_P0_BASELINE_EXE.md](docs/BUILD_REPORT_P0_BASELINE_EXE.md) - Full build documentation
- [SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md) - Security threat model and mitigations
- [BUILD_WINDOWS_INSTALLER.md](docs/BUILD_WINDOWS_INSTALLER.md) - Installer creation guide
- [GATE_REPORT.md](GATE_REPORT.md) - Pre-push verification report

## 🐛 Known Issues

None critical. See [BUILD_REPORT_P0_BASELINE_EXE.md](docs/BUILD_REPORT_P0_BASELINE_EXE.md) for non-critical warnings.

## 🙏 Support

- **Issues:** https://github.com/SindromRadioSpb/v_book/issues
- **Documentation:** See ``docs/`` folder in repository

---

**Note:** This is a development baseline build. User data location: ``%LOCALAPPDATA%\HDLE\``. Executable is NOT signed (you may see "Unknown Publisher" warning on first run).

🤖 *Built with [Claude Code](https://claude.com/claude-code)*
"@

    Write-Host $releaseNotes
    Write-Host ""
    Write-Host "--- END RELEASE NOTES ---" -ForegroundColor Cyan
    Write-Host ""

    exit 0
}

# GitHub CLI is available - create release automatically
Write-Host "GitHub CLI found: $ghVersion" -ForegroundColor Green
Write-Host ""

Write-Host "Creating GitHub Release for v1.0.0-p0-baseline..." -ForegroundColor Yellow

$releaseNotes = @"
# HDLE Premium v1.0.0 - P0 Security Hardening Baseline

First production release after comprehensive P0 Security Hardening implementation.

## 🎯 Features

### Core Functionality
- **M7: Translation Memory** - Offline dictionary + user overrides + MT cache
- **M8: Term Curation** - Review workflow with approval states
- **M9: Export Center** - XLSX, TBX, TMX, CSV, JSON exports with statistics
- **M10: Backup & Recovery** - Auto-backup before migrations, crash recovery

### 🔒 P0 Security Hardening (NEW)
**Defense-in-Depth Architecture (7 Layers):**
1. **UI Validation** - Query complexity limits before search
2. **Service Validation** - FTS5 sanitization, path security checks
3. **Rate Limiting** - Token bucket algorithm (60/min imports, 30/min exports)
4. **Audit Logging** - All security events → security_audit_log table
5. **Cryptography** - AES-256-GCM authenticated encryption
6. **Database** - Encrypted credentials storage
7. **OS Keyring** - Master key protection (Windows Credential Manager)

**Attack Surface Mitigations:**
- ✅ FTS5 injection prevention (query sanitization, operator blocking)
- ✅ CSV formula injection neutralization (=+-@ prefix escaping)
- ✅ Log injection prevention (CRLF replacement)
- ✅ Path traversal protection (UNC blocking, system dir exclusion)
- ✅ File size DoS prevention (100 MB documents, 10 MB dictionaries)
- ✅ Credential exposure protection (AES-256-GCM encryption at rest)

## 📊 Database

- **Schema Version:** v8
- **Total Tables:** 47
- **Migrations:** 001-008 (including security tables: security_audit_log, credentials)

## 🛠️ Technical Details

### Build
- **Commit:** 9e7ffe7
- **Build Date:** 2026-02-07
- **Build Tool:** PyInstaller 6.18.0 (onedir mode)
- **Executable Size:** 44 MB
- **Total Package Size:** ~4.5 GB (includes PyTorch, PyQt6, all dependencies)

### Dependencies
- **Python:** 3.13.2
- **PyQt6:** 6.10.2 (UI framework)
- **cryptography:** 46.0.4 (AES-256-GCM encryption)
- **keyring:** 25.7.0 (OS credential storage)
- **SQLAlchemy:** 2.0.36 (ORM + migrations)
- **torch:** 2.6.0+cpu (Stanza NLP backend)

### Verification
- ✅ Runtime tests: 3/3 PASS
- ✅ PATCH-06 smoke tests: 6/6 PASS
- ✅ Security tables: security_audit_log + credentials
- ✅ Defense-in-depth: 7 layers operational

## 💾 Requirements

- **OS:** Windows 10/11 (64-bit)
- **Disk Space:** ~5 GB
- **Internet:** Required on first run only (for Stanza Hebrew models ~300 MB)
- **Permissions:** Standard user (no admin required)

## 📥 Installation

1. Download HDLE_Premium.zip from Assets below
2. Extract to desired location (e.g., C:\Program Files\HDLE\)
3. Run HDLE_Premium.exe
4. **First run:** Application will:
   - Create %LOCALAPPDATA%\HDLE\ directory
   - Initialize database (hdle.db) with schema v8
   - Download Stanza Hebrew models (~300 MB, requires internet)
   - Create logs/, backups/, snapshots/ subdirectories

## 🔄 Upgrading from Previous Versions

**User data is preserved automatically:**
- Database: %LOCALAPPDATA%\HDLE\hdle.db (upgraded via migrations)
- Backups: %LOCALAPPDATA%\HDLE\backups\ (kept intact)
- Logs: %LOCALAPPDATA%\HDLE\logs\ (kept intact)

**To upgrade:**
1. Close running application
2. Extract new version over old installation
3. Launch HDLE_Premium.exe
4. Migrations apply automatically

## 📚 Documentation

- BUILD_REPORT_P0_BASELINE_EXE.md - Full build documentation
- SECURITY_AUDIT.md - Security threat model and mitigations
- BUILD_WINDOWS_INSTALLER.md - Installer creation guide
- GATE_REPORT.md - Pre-push verification report

## 🐛 Known Issues

None critical. See BUILD_REPORT_P0_BASELINE_EXE.md for non-critical warnings.

## 🙏 Support

- **Issues:** https://github.com/SindromRadioSpb/v_book/issues
- **Documentation:** See docs/ folder in repository

---

**Note:** This is a development baseline build. User data location: %LOCALAPPDATA%\HDLE\. Executable is NOT signed (you may see "Unknown Publisher" warning on first run).

🤖 Built with Claude Code (https://claude.com/claude-code)
"@

# Create release
gh release create v1.0.0-p0-baseline `
    --title "HDLE Premium v1.0.0 - P0 Security Hardening Baseline" `
    --notes $releaseNotes `
    --target main

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Release Created Successfully!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "View release at:" -ForegroundColor White
    Write-Host "  https://github.com/SindromRadioSpb/v_book/releases/tag/v1.0.0-p0-baseline" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor White
    Write-Host "  1. Upload build artifact (HDLE_Premium.zip) to release" -ForegroundColor Gray
    Write-Host "  2. Edit release notes if needed" -ForegroundColor Gray
    Write-Host "  3. Mark as latest release" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "ERROR: Failed to create release" -ForegroundColor Red
    Write-Host "Please create manually at:" -ForegroundColor Yellow
    Write-Host "  https://github.com/SindromRadioSpb/v_book/releases/new?tag=v1.0.0-p0-baseline" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}
