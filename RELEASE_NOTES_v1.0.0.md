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
4. **Audit Logging** - All security events → `security_audit_log` table
5. **Cryptography** - AES-256-GCM authenticated encryption
6. **Database** - Encrypted credentials storage
7. **OS Keyring** - Master key protection (Windows Credential Manager)

**Attack Surface Mitigations:**
- ✅ FTS5 injection prevention (query sanitization, operator blocking)
- ✅ CSV formula injection neutralization (`=+-@` prefix escaping)
- ✅ Log injection prevention (CRLF replacement)
- ✅ Path traversal protection (UNC blocking, system dir exclusion)
- ✅ File size DoS prevention (100 MB documents, 10 MB dictionaries)
- ✅ Credential exposure protection (AES-256-GCM encryption at rest)

## 📊 Database

- **Schema Version:** v8
- **Total Tables:** 47
- **Migrations:** 001-008 (including security tables: `security_audit_log`, `credentials`)

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
- ✅ Security tables: `security_audit_log` + `credentials`
- ✅ Defense-in-depth: 7 layers operational

## 💾 Requirements

- **OS:** Windows 10/11 (64-bit)
- **Disk Space:** ~5 GB
- **Internet:** Required on first run only (for Stanza Hebrew models ~300 MB)
- **Permissions:** Standard user (no admin required)

## 📥 Installation

1. Download `HDLE_Premium.zip` from Assets below
2. Extract to desired location (e.g., `C:\Program Files\HDLE\`)
3. Run `HDLE_Premium.exe`
4. **First run:** Application will:
   - Create `%LOCALAPPDATA%\HDLE\` directory
   - Initialize database (`hdle.db`) with schema v8
   - Download Stanza Hebrew models (~300 MB, requires internet)
   - Create `logs/`, `backups/`, `snapshots/` subdirectories

## 🔄 Upgrading from Previous Versions

**User data is preserved automatically:**
- Database: `%LOCALAPPDATA%\HDLE\hdle.db` (upgraded via migrations)
- Backups: `%LOCALAPPDATA%\HDLE\backups\` (kept intact)
- Logs: `%LOCALAPPDATA%\HDLE\logs\` (kept intact)

**To upgrade:**
1. Close running application
2. Extract new version over old installation
3. Launch `HDLE_Premium.exe`
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
- **Documentation:** See `docs/` folder in repository

---

**Note:** This is a development baseline build. User data location: `%LOCALAPPDATA%\HDLE\`. Executable is NOT signed (you may see "Unknown Publisher" warning on first run).

🤖 *Built with [Claude Code](https://claude.com/claude-code)*
