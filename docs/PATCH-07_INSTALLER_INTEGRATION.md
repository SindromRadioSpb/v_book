# PATCH-07: Installer Integration and Release

**Status:** ✅ READY FOR INTEGRATION
**Date:** 2026-02-07

---

## Overview

Final integration of Hebrew Wikipedia auto-setup into installer and creation of v1.1.0 release.

---

## Changes to Main Application

### 1. Show Setup Wizard on First Launch

**File:** `app/main.py`

**Add after database initialization:**

```python
def check_first_run_setup(app_dir: Path, db_path: Path):
    """Check if first-run setup is needed."""
    from sqlalchemy import select
    from app.infra.sa_models import DictProject

    # Check if Hebrew Wikipedia reference corpus exists
    db_service = DBService.get_instance()
    with db_service.get_session() as session:
        ref_project = session.execute(
            select(DictProject).where(DictProject.is_general_corpus == 1)
        ).scalar_one_or_none()

        if not ref_project:
            logger.info("No reference corpus found - showing setup wizard")
            return True

    return False


def main():
    # ... existing code ...

    # Initialize database
    DBService.initialize(db_path)
    logger.info("Database initialized")

    # NEW: Check if first-run setup needed
    if check_first_run_setup(app_dir, db_path):
        from app.ui.reference_setup_wizard import ReferenceSetupWizard

        # Show setup wizard BEFORE main window
        wizard = ReferenceSetupWizard(
            work_dir=app_dir / "downloads",
            db_path=db_path,
        )

        if wizard.exec() != QDialog.DialogCode.Accepted:
            logger.info("Setup wizard cancelled - exiting")
            return 1

        logger.info("Setup wizard completed")

    # ... rest of existing code ...
```

---

## Updated Installer Configuration

**File:** `installer/installer.iss`

**No changes needed** - setup wizard runs on first launch automatically.

---

## Release Notes Template

**File:** `docs/RELEASE_NOTES_v1.1.0.md`

```markdown
# HDLE Premium v1.1.0 - Hebrew Wikipedia Auto-Setup

**Release Date:** 2026-02-07

---

## 🆕 New Features

### Hebrew Wikipedia Reference Corpus - Auto-Setup

HDLE Premium now includes automatic setup for the Hebrew Wikipedia Baseline reference corpus (387,639 documents)!

**Two Setup Modes:**

1. **Download Pre-Processed Database (Recommended)**
   - ⚡ Fast: 5-15 minutes
   - 📦 Size: ~2.5 GB download
   - ✅ Ready to use immediately
   - All NLP processing complete

2. **Process Locally (Advanced/Offline)**
   - 🔧 Full control over processing
   - 📦 Size: ~1.5 GB XML download
   - ⏰ Processing time: 12-21 hours (GPU required for reasonable speed)
   - Works offline after initial download

**Features:**
- Background processing with progress tracking
- Pause/Resume support
- Cancellable at any time
- Automatic resume after restart
- Safe error handling

---

## 🔧 Improvements

- **Database Relocation:** Default location moved to `M:\V_book\HDLE\` (Windows) to save C: drive space
- **Real Metrics:** Project dashboard now shows actual document/lemma/ngram counts
- **Service Guards:** Reference corpus protected from accidental modification

---

## 📊 Technical Details

### Benchmark Results

Full processing time on different hardware:
- **CPU only:** ~84 hours (not recommended)
- **RTX 3070 GPU:** ~12-21 hours
- **Pre-processed download:** 5-15 minutes ⚡

### Database Specifications

- **Documents:** 387,639 Wikipedia articles
- **Lemmas:** ~45,000-50,000 unique
- **N-grams:** ~10,000-15,000 term clusters
- **Database size:** ~2.3-2.5 GB
- **Schema version:** v7 (includes security audit log)

---

## 🐛 Bug Fixes

- Fixed: Download service resume on network interruption
- Fixed: State persistence across application restarts
- Fixed: Progress bar accuracy during long operations

---

## 📦 Installation

### New Installation

1. Download `HDLE_Premium_Setup.exe` from [Releases](https://github.com/SindromRadioSpb/v_book/releases/tag/v1.1.0)
2. Run installer
3. Launch HDLE Premium
4. Follow Setup Wizard prompts
5. Choose download mode (recommended) or local processing
6. Wait for setup to complete
7. Start using Hebrew Wikipedia as reference corpus!

### Upgrade from v1.0.0

1. Download new installer
2. Run installer (preserves existing data)
3. On first launch, Setup Wizard will offer to add Hebrew Wikipedia
4. Complete setup
5. Existing projects remain intact

---

## ⚙️ System Requirements

- **OS:** Windows 10/11 (64-bit)
- **RAM:** 8 GB minimum, 16 GB recommended
- **Disk Space:**
  - Download mode: 3 GB free (database + download)
  - Local processing mode: 10 GB free (temporary files)
- **GPU (optional):** CUDA-capable GPU for faster local processing
- **Internet:** Required for initial setup (download mode or XML download)

---

## 📝 Notes

- **Python 3.14 Compatibility:** Some features require Python 3.11-3.13 (zstandard compression, cryptography). This doesn't affect end users who install via installer.
- **Default Database Path:** Changed from `%LOCALAPPDATA%\HDLE\` to `M:\V_book\HDLE\` on Windows to save C: drive space
- **First-Run Time:** Allow 5-30 minutes for first launch depending on mode selected

---

## 🔗 Links

- **Download:** [HDLE_Premium_Setup.exe](https://github.com/SindromRadioSpb/v_book/releases/download/v1.1.0/HDLE_Premium_Setup.exe)
- **Pre-Processed Database:** [hewiki_ref_processed_v20260207.db](https://github.com/SindromRadioSpb/v_book/releases/download/v1.1.0/hewiki_ref_processed_v20260207.db)
- **Documentation:** [GitHub Wiki](https://github.com/SindromRadioSpb/v_book/wiki)
- **Issues:** [Bug Reports](https://github.com/SindromRadioSpb/v_book/issues)

---

**Checksums:**

```
SHA256(HDLE_Premium_Setup.exe) = <TBD>
SHA256(hewiki_ref_processed_v20260207.db) = <TBD>
```

---

**Co-Authored-By:** Claude Sonnet 4.5 <noreply@anthropic.com>
```

---

## Build and Release Checklist

### Pre-Release

- [ ] All PATCH-00 through PATCH-06 completed
- [ ] Pre-processed database created and uploaded
- [ ] Manifest updated with real URL and SHA256
- [ ] Tests passing (reference corpus guards verified)
- [ ] Documentation complete

### Build Installer

```bash
# 1. Update version in installer.iss
#    AppVersion=1.1.0

# 2. Build onedir executable
.\scripts\build_windows.ps1

# 3. Build installer
& "C:\Users\Win10_Game_OS\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer\installer.iss

# Output: installer/output/HDLE_Premium_Setup.exe
```

### Test Installation

- [ ] Test on clean Windows VM (no HDLE installed)
- [ ] Verify Setup Wizard appears on first launch
- [ ] Test download mode (confirm 5-15 min)
- [ ] Verify Hebrew Wikipedia appears in project list
- [ ] Verify metrics populated (387k docs, lemmas, ngrams)
- [ ] Test all tabs (Documents, Dictionary, Terms, etc.)
- [ ] Verify read-only protection works

### Create GitHub Release

```bash
# Tag release
git tag v1.1.0
git push origin v1.1.0

# Create release with assets
gh release create v1.1.0 \
    --title "HDLE Premium v1.1.0 - Hebrew Wikipedia Auto-Setup" \
    --notes-file docs/RELEASE_NOTES_v1.1.0.md \
    installer/output/HDLE_Premium_Setup.exe \
    M:/V_book/HDLE_Processing/hewiki_ref_processed_v20260207.db
```

### Post-Release

- [ ] Update README.md with v1.1.0 links
- [ ] Update installer location docs
- [ ] Announce release
- [ ] Monitor for issues

---

## Rollback Plan

If issues discovered post-release:

1. Mark release as "Pre-release" on GitHub
2. Create hotfix branch
3. Fix issue
4. Create v1.1.1 patch release
5. Update documentation

---

**Status:** Ready for integration and release
**Author:** Claude Sonnet 4.5
**Co-Authored-By:** Claude Sonnet 4.5 <noreply@anthropic.com>
