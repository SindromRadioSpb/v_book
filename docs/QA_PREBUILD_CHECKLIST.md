# QA Prebuild Validation Checklist

## Overview

Before building the HDLE Premium installer, run comprehensive validation to ensure all critical features work correctly.

## Automated Validation

### Option 1: Full Validation (Recommended)

```bash
python scripts/prebuild_validate.py
```

Current ship-gate note:

- prebuild validation now runs a bounded DB corruption probe before the
  write-heavy checks
- if the selected DB is unhealthy, validation stops early and points to:
  - `python scripts/repair_db_corruption.py --db-path "<db-path>"`

This runs:
1. ✅ FTS table presence and consistency
2. ✅ Project lifecycle (create/delete)
3. ✅ Export/import bundle roundtrip
4. ✅ Database integrity (quick check)

**Expected output:**
```
======================================================================
SUMMARY
======================================================================
  FTS Presence.............................. [OK] PASSED
  Project Lifecycle......................... [OK] PASSED
  Export/Import............................. [OK] PASSED
  Database Integrity........................ [OK] PASSED
======================================================================

[OK] ALL CHECKS PASSED - Ready for build
```

### Option 2: Fast Validation (Skip Export/Import)

```bash
python scripts/prebuild_validate.py --skip-export-import
```

Use this for quick checks during development.

## Regression Tests

Run full pytest suite:

```bash
pytest tests/test_fts_self_healing.py -v
pytest tests/test_project_exchange.py -v
```

**Expected:**
- All 6 FTS self-healing tests pass
- All 10 project exchange tests pass (includes document_sentence regression test)

## Manual Smoke Tests (UI)

After automated validation, perform these manual UI checks:

### 1. Project Management
- [ ] Create new project → Success
- [ ] Delete project → Success, no "no such table: sentence_fts" error
- [ ] Process documents with NLP → No crashes

### 2. Project Exchange
- [ ] Tools → Export Project Bundle → Success
- [ ] Tools → Import Project Bundle → Success
- [ ] Import creates new project with correct data

### 3. Database Health
- [ ] Application starts without errors
- [ ] No FTS-related errors in logs

## Diagnostic Tools

### Check FTS Presence

```bash
python scripts/diag_fts_presence.py
```

**Expected output:**
```
======================================================================
FTS Diagnostic Report
======================================================================
Database: J:\Project_Vibe\V_book\hdle_premium.db
Schema: main
Schema Version: 9

FTS Tables:
  sentence_fts: [OK] EXISTS
  term_fts:     [OK] EXISTS

Triggers:
  sentence: trg_sentence_ai, trg_sentence_ad, trg_sentence_au
  term:     trg_term_search_ai, trg_term_search_ad, trg_term_search_au

======================================================================
[OK] No issues found. FTS configuration is healthy.
======================================================================
```

### Repair Missing FTS

If FTS tables are missing:

```bash
python app/infra/fts_manager.py --rebuild
```

This creates missing FTS tables and rebuilds data from base tables.

## Common Issues

### Issue: "no such table: main.sentence_fts"

**Root Cause:** FTS virtual tables were deleted or migrations failed.

**Fix:**
1. Run `python app/infra/fts_manager.py --rebuild`
2. Verify: `python scripts/diag_fts_presence.py`

### Issue: Export/Import crashes

**Root Cause:** FTS tables missing in host or payload DB.

**Fix:**
The fix is already applied:
- Export creates FTS in payload before copying data
- Import ensures FTS exists in host before inserting

### Issue: Prebuild validation fails on corruption probe

**Root Cause:** The selected DB is already unhealthy enough that release
validation should stop before project lifecycle or export/import writes.

**Fix:**
1. Run `python scripts/repair_db_corruption.py --db-path "<db-path>"`
2. Rerun `python scripts/prebuild_validate.py --db-path "<db-path>"`

### Issue: "no such table: main.document_sentence" during export

**Root Cause:** PyInstaller builds couldn't find migrations due to relative path resolution.

**Symptoms:**
```
Error: no such table: main.document_sentence
```

**Fix (2026-02-11):**
The fix is already applied in `export_engine.py`:
- Added `_get_migrations_dir()` helper function
- Uses `sys._MEIPASS` for PyInstaller builds
- Uses relative path `app/infra/migrations` for development
- Ensures payload DB schema is created before data export

**Verification:**
- New regression test: `test_export_creates_payload_schema_including_document_sentence`
- Verifies document_sentence table exists in payload
- Verifies exported sentence count matches source

### Issue: Project delete fails

**Root Cause:** DELETE triggers reference missing sentence_fts.

**Fix:**
The fix is already applied:
- `project_service.py` ensures FTS exists before deletion

## Architecture Notes

### Self-Healing FTS

The application now automatically creates missing FTS tables:

1. **At startup:** After migrations (`db.py:apply_migrations`)
2. **Before export:** In payload DB (`export_engine.py`)
3. **Before import:** In host DB (`import_engine.py`)
4. **Before delete:** In main DB (`project_service.py`)

This prevents "no such table" errors caused by:
- Manual FTS deletion
- Failed migrations
- Old databases
- Corrupted schema

### FTS Architecture

```
document_sentence (base table)
    ├── trg_sentence_ai (AFTER INSERT) → sentence_fts
    ├── trg_sentence_ad (AFTER DELETE) → sentence_fts
    └── trg_sentence_au (AFTER UPDATE) → sentence_fts

term_search (base table)
    ├── trg_term_search_ai (AFTER INSERT) → term_fts
    ├── trg_term_search_ad (AFTER DELETE) → term_fts
    └── trg_term_search_au (AFTER UPDATE) → term_fts
```

Triggers require FTS tables to exist. If missing, all INSERTs/DELETEs/UPDATEs fail.

## Files Added/Modified

### New Files
- `app/infra/fts_manager.py` - FTS self-healing utilities
- `scripts/diag_fts_presence.py` - FTS diagnostic tool
- `scripts/prebuild_validate.py` - Automated validation suite
- `tests/test_fts_self_healing.py` - FTS regression tests
- `docs/QA_PREBUILD_CHECKLIST.md` - This document

### Modified Files
- `app/infra/db.py` - Ensure FTS after migrations
- `app/services/project_service.py` - Ensure FTS before delete
- `app/services/project_exchange/export_engine.py` - Ensure FTS in payload + PyInstaller path resolution (2026-02-11)
- `app/services/project_exchange/import_engine.py` - Ensure FTS in host
- `tests/test_project_exchange.py` - Added document_sentence regression test (2026-02-11)

## DoD (Definition of Done)

Before releasing a build, verify:

✅ `python scripts/prebuild_validate.py` passes all checks
✅ `pytest tests/test_fts_self_healing.py` - all 6 tests pass
✅ `pytest tests/test_project_exchange.py` - all 10 tests pass
✅ Manual smoke tests (create/delete/export/import) work in UI
✅ No FTS errors in logs
✅ Git status clean, all changes committed

## Next Steps

After validation passes:

1. ✅ Run prebuild validation → All passed
2. ⏭️ Build installer (PyInstaller)
3. ⏭️ Test installer on clean machine
4. ⏭️ Release
