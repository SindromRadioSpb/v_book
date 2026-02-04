# Hotfix: M8 Migration Schema Issue

**Date:** 2026-02-04
**Issue:** Missing M8 curation fields in production database
**Status:** ✅ RESOLVED

---

## Problem Description

User reported errors when opening project "Тест M8,M9":

```
Failed to load terms: (sqlite3.OperationalError) no such column: term_cluster.curation_status
Failed to load review queue: (sqlite3.OperationalError) no such column: term_cluster.curation_status
```

### Root Cause

The production database at `%LOCALAPPDATA%\HDLE\hdle.db` had:
- Schema version = 5 (indicating migration 005 was "applied")
- But term_cluster table was missing M8 columns:
  - curation_status
  - pinned_translation
  - pinned_translation_lang
  - pinned_example_sent_id
  - curation_notes
  - curated_at
  - curated_by

**Hypothesis:** Migration 005 was marked as applied (schema_version=5) but ALTER TABLE commands failed silently or database was restored from an older backup.

---

## Solution

### 1. Backup Creation

```bash
cp hdle.db hdle.db.backup_20260204_214357
```

### 2. Manual Migration Application

Applied migration 005_m8_term_curation.sql manually:

```sql
-- Add M8 curation columns
ALTER TABLE term_cluster ADD COLUMN curation_status TEXT DEFAULT 'auto'
  CHECK(curation_status IN ('auto', 'needs_review', 'approved', 'rejected'));

ALTER TABLE term_cluster ADD COLUMN pinned_translation TEXT;
ALTER TABLE term_cluster ADD COLUMN pinned_translation_lang TEXT DEFAULT 'ru';
ALTER TABLE term_cluster ADD COLUMN pinned_example_sent_id INTEGER
  REFERENCES document_sentence(sentence_id) ON DELETE SET NULL;

ALTER TABLE term_cluster ADD COLUMN curation_notes TEXT;
ALTER TABLE term_cluster ADD COLUMN curated_at TEXT;
ALTER TABLE term_cluster ADD COLUMN curated_by TEXT;

-- Add M8 indexes
CREATE INDEX IF NOT EXISTS idx_cluster_curation_status
  ON term_cluster(project_id, curation_status);

CREATE INDEX IF NOT EXISTS idx_cluster_needs_review
  ON term_cluster(project_id, curation_status, freq_abs DESC)
  WHERE curation_status = 'needs_review';

CREATE INDEX IF NOT EXISTS idx_cluster_approved
  ON term_cluster(project_id, curation_status, freq_abs DESC)
  WHERE curation_status = 'approved';
```

### 3. Verification

```sql
-- Schema version: 5 ✅
-- Total projects: 5 ✅
-- Total term_clusters: 1356 ✅
-- All clusters have curation_status='auto' (default) ✅
```

**Result:** All M8 columns and indexes successfully added.

---

## Testing

**Required:** User should:
1. Restart the application
2. Open project "Тест M8,M9"
3. Verify Terms tab loads without errors
4. Verify Review queue tab loads without errors
5. Test M8 features:
   - Change curation status (auto → needs_review → approved)
   - Pin translation for a term
   - Add/remove aliases
   - Mark term as stopword

**Expected:** No errors, all M8 features functional.

---

## Prevention (M10)

**Issue:** Migration system marked migration as applied but columns were missing.

**M10 Solution (PATCH 9):**
- Implement automatic database backup before migrations
- Add migration verification (check expected columns exist after migration)
- Implement rollback mechanism on migration failure
- Add migration health check on startup

**Related Milestones:**
- PATCH 9: M10 auto-backup before migrations
- PATCH 10: M10 crash recovery + SnapshotService

---

## Files Modified

**Database:**
- `%LOCALAPPDATA%\HDLE\hdle.db` - Production database (schema fixed)
- `%LOCALAPPDATA%\HDLE\hdle.db.backup_20260204_214357` - Pre-fix backup

**Documentation:**
- `docs/HOTFIX_M8_MIGRATION.md` (this file)

---

## Status

✅ **RESOLVED**

User should restart application and verify M8 features work correctly.

---

**Applied:** 2026-02-04 21:43
**Verified:** Schema version 5, all M8 columns present
**Action Required:** User restart + testing
