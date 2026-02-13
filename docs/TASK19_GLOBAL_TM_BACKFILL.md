# Task 19: Global TM Backfill Guide

## Overview

The backfill process migrates existing `tm_entry` data into the `tm_global` canonical layer. This is a one-time migration that runs automatically on first startup after migration 015, but can also be run manually.

## Automatic Backfill

**When**: On first startup after migration 015 is applied

**Trigger**: `db.py` checks if:
- `tm_global` table exists AND
- `tm_global` has 0 rows AND
- `tm_entry` has >0 rows

**Process**: Automatically calls `TMGlobalService.backfill()` with default settings (chunk_size=500).

**Logging**: Check application logs for backfill progress:
```
INFO - Starting automatic tm_global backfill
INFO - Backfill complete: 3,245 groups created, 9,876 entries linked
```

---

## Manual Backfill

### Using the CLI Script

**Location**: `scripts/backfill_tm_global.py`

**Basic usage**:
```bash
# Dry-run (no changes, shows what would happen)
python scripts/backfill_tm_global.py --dry-run

# Execute backfill (default production DB)
python scripts/backfill_tm_global.py

# Execute with custom DB path
python scripts/backfill_tm_global.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db"

# Execute with custom chunk size
python scripts/backfill_tm_global.py --chunk-size 1000
```

**Options**:
- `--dry-run`: Show statistics without making changes
- `--db-path PATH`: Override default database path
- `--chunk-size N`: Number of keys per commit (default: 500)

### Using Python API

```python
from app.infra.db import DBService
from app.services.tm_global_service import TMGlobalService

# Initialize database
db_service = DBService(db_path="hdle.db")
session = db_service.get_session()

# Run backfill
service = TMGlobalService()
stats = service.backfill(session, chunk_size=500, dry_run=False)

print(f"Groups created: {stats['groups_created']}")
print(f"Entries linked: {stats['entries_linked']}")
print(f"Entries skipped: {stats['entries_skipped']}")

session.close()
```

---

## What Backfill Does

### Algorithm

1. **Group**: SELECT all `tm_entry` rows, group by canonical key `(src_lang, tgt_lang, kind, src_norm)`

2. **Score**: For each group, score all entries using scoring algorithm:
   - Has translation > empty
   - Status: approved (4) > draft (3) > deprecated (2) > rejected (1)
   - Origin: user_edit (5) > import (4) > mt_accept (3) > merge (2) > mt_auto (1) > revert (0)
   - Updated timestamp DESC
   - tm_id ASC (lowest = canonical tiebreaker)

3. **Select best**: Pick entry with highest score

4. **Determine noise**: Global is noise ONLY if ALL entries in group are noise

5. **Upsert**: INSERT or UPDATE `tm_global` with best entry's fields

6. **Link**: Set `tm_entry.tm_global_id` for ALL entries in group

7. **Commit**: Commit in chunks (default 500 keys per chunk)

### Example

**Before backfill**:
```
tm_entry:
- tm_id=1, project_id=4, src_norm="שווה_norm", translation="стоит", status="approved", origin="user_edit"
- tm_id=2, project_id=7, src_norm="שווה_norm", translation="", status="draft", origin="mt_auto"
- tm_id=3, project_id=8, src_norm="שווה_norm", translation="равен", status="draft", origin="mt_auto"

tm_global: (empty)
```

**After backfill**:
```
tm_entry:
- tm_id=1, tm_global_id=101
- tm_id=2, tm_global_id=101
- tm_id=3, tm_global_id=101

tm_global:
- tm_global_id=101, src_norm="שווה_norm", translation="стоит", status="approved", origin="user_edit", source_tm_id=1
```

**Winner**: Entry 1 (approved+user_edit beats draft+mt_auto)

---

## Output

### Dry-Run Output

```
=== DRY RUN - NO CHANGES WILL BE MADE ===
Database: M:\V_book\HDLE\hdle.db

Analyzing tm_entry data...

Canonical key groups found: 3,245
Total tm_entry records: 9,876
Average entries per key: 3.04

Sample groups:
  Key: (he, ru, lemma, "שווה_norm") - 4 entries
    Best: tm_id=1234, status=approved, origin=user_edit, translation="стоит"
  Key: (he, ru, lemma, "אבל_norm") - 2 entries
    Best: tm_id=5678, status=draft, origin=mt_auto, translation="но"

=== END DRY RUN ===
```

### Execution Output

```
Starting backfill...
Database: M:\V_book\HDLE\hdle.db

Processing 3,245 canonical key groups...
Chunk 1/7 (500 keys): 1,487 entries linked
Chunk 2/7 (500 keys): 1,523 entries linked
Chunk 3/7 (500 keys): 1,498 entries linked
Chunk 4/7 (500 keys): 1,512 entries linked
Chunk 5/7 (500 keys): 1,501 entries linked
Chunk 6/7 (500 keys): 1,489 entries linked
Chunk 7/7 (245 keys): 866 entries linked

Backfill complete!
Groups created: 3,245
Entries linked: 9,876
Entries skipped: 0
Time elapsed: 12.3s
```

---

## Idempotency

**Safe to run multiple times**: Backfill is idempotent.

- `tm_global` rows have UNIQUE constraint on `(src_lang, tgt_lang, kind, src_norm)`
- Upsert will UPDATE existing row if new entry has higher score
- Entries already linked (`tm_global_id IS NOT NULL`) are skipped

**Re-running after data changes**: If new `tm_entry` rows were added or translations updated, re-running backfill will:
- Update `tm_global` if new entries have higher scores
- Link any new entries to existing `tm_global` rows

---

## When to Run Manual Backfill

### Scenario 1: Recovery After Desync

**Symptom**: `tm_entry.translation` differs from `tm_global.translation` for linked entries

**Fix**: Re-run backfill to re-score and update global:
```bash
python scripts/backfill_tm_global.py
```

### Scenario 2: After Bulk Import

**Symptom**: Imported `tm_entry` rows have `tm_global_id IS NULL`

**Fix**: Run backfill to link imports:
```bash
python scripts/backfill_tm_global.py --db-path "path/to/db"
```

### Scenario 3: Testing Changes

**Symptom**: Need to verify backfill behavior before applying to production

**Fix**: Use dry-run mode:
```bash
python scripts/backfill_tm_global.py --dry-run --db-path "dev.db"
```

---

## Performance

### Typical Scale

- **10,000 tm_entry rows** → ~3,000 tm_global rows (3:1 ratio)
- **Backfill time**: 5-15 seconds (500 keys/chunk)
- **Startup impact**: Auto-backfill only runs ONCE (on first startup after migration 015)

### Large Databases

For databases with >100,000 tm_entry rows:
- Consider increasing chunk size: `--chunk-size 1000`
- Monitor memory usage (grouping queries load all entries per key)
- Expect 1-2 minutes for backfill completion

---

## Troubleshooting

### Problem: Backfill skips all entries

**Cause**: All entries already linked (`tm_global_id IS NOT NULL`)

**Solution**: Normal behavior if backfill already ran. Check `tm_global` row count:
```sql
SELECT COUNT(*) FROM tm_global;
```

### Problem: UNIQUE constraint error

**Cause**: Duplicate `tm_global` rows exist (should be impossible if backfill runs correctly)

**Solution**: Find duplicates and delete manually:
```sql
-- Find duplicates
SELECT src_lang, tgt_lang, kind, src_norm, COUNT(*)
FROM tm_global
GROUP BY src_lang, tgt_lang, kind, src_norm
HAVING COUNT(*) > 1;

-- Delete lower-scored duplicate (manual SQL), then re-run backfill
```

### Problem: Backfill takes too long

**Cause**: Very large database or slow disk

**Solution**:
- Increase chunk size: `--chunk-size 2000`
- Run on SSD if possible
- Close other database connections during backfill

### Problem: tm_global has fewer rows than expected

**Cause**: Many `tm_entry` rows share the same canonical key (expected behavior)

**Solution**: This is normal. Check average entries per key:
```sql
SELECT
  (SELECT COUNT(*) FROM tm_entry) AS total_entries,
  (SELECT COUNT(*) FROM tm_global) AS total_keys,
  CAST((SELECT COUNT(*) FROM tm_entry) AS REAL) / (SELECT COUNT(*) FROM tm_global) AS avg_per_key;
```

Typical ratio: 2-5 entries per key (cross-project duplicates).

---

## Verification

After backfill, verify correctness:

### Check 1: All entries linked

```sql
-- Should return 0
SELECT COUNT(*) FROM tm_entry WHERE tm_global_id IS NULL;
```

### Check 2: Global count reasonable

```sql
-- Compare to tm_entry count
SELECT
  (SELECT COUNT(*) FROM tm_entry) AS entries,
  (SELECT COUNT(*) FROM tm_global) AS keys,
  CAST((SELECT COUNT(*) FROM tm_entry) AS REAL) / (SELECT COUNT(*) FROM tm_global) AS ratio;
```

Expected ratio: 2-5 (if multiple projects exist).

### Check 3: Best translation won

```sql
-- Example: Check specific lemma
SELECT e.tm_id, e.project_id, e.translation, e.status, e.origin, e.updated_at
FROM tm_entry e
JOIN tm_global g ON e.tm_global_id = g.tm_global_id
WHERE g.src_norm = 'שווה_norm'
ORDER BY e.status DESC, e.origin DESC, e.updated_at DESC;

-- Compare to tm_global.translation (should match highest-scored entry)
SELECT translation, status, origin, source_tm_id
FROM tm_global
WHERE src_norm = 'שווה_norm';
```

### Check 4: Noise policy correct

```sql
-- If ANY entry is not noise, global should be not noise
SELECT g.tm_global_id, g.is_noise, COUNT(DISTINCT e.is_noise) AS noise_variety
FROM tm_global g
JOIN tm_entry e ON e.tm_global_id = g.tm_global_id
GROUP BY g.tm_global_id
HAVING noise_variety > 1 AND g.is_noise = 1;

-- Should return 0 rows (global cannot be noise if entries disagree)
```

---

## Next Steps

After successful backfill:
- **New projects**: Will automatically inherit translations via read-path fallback
- **Editing translations**: Changes propagate to all projects via tm_global
- **Monitoring**: Check `tm_global` row count grows as new terms are translated
- **Maintenance**: No further manual backfill needed (write-path integration handles incremental updates)
