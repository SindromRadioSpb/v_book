# Migration Notes: Schema v8 → v9

**Migration Date:** 2026-02-08
**New Schema Version:** 9
**Migration File:** `app/infra/migrations/009_mt_usage_tracking.sql`

---

## Overview

Schema version 9 adds usage tracking for MT providers, enabling budget guard enforcement and cost monitoring.

**What's new:**
- `mt_usage` table - Track character and request counts
- Atomic counters - Prevent race conditions in concurrent batch translate
- Period-based tracking - Per-minute, per-day, per-month granularity

---

## Automatic Migration

### On First Launch

When you launch HDLE Premium after update, migration 009 applies automatically:

```
2026-02-08 22:10:00 - app.infra.db - INFO - Applying migration: 009_mt_usage_tracking.sql
2026-02-08 22:10:00 - app.infra.db - INFO - Migration 009 applied successfully
2026-02-08 22:10:00 - app.infra.db - INFO - Current schema version: 9
```

**No action required** - migration is fully automated.

### Migration Process

1. **Backup created** (automatic):
   - Location: `M:\V_book\HDLE\backups\hdle_backup_<timestamp>.db`
   - Original database preserved

2. **Process lock** (prevents concurrent migrations):
   - Lock file: `M:\V_book\HDLE\migrate.lock`
   - Auto-cleanup on completion

3. **Schema changes applied**:
   - Create `mt_usage` table
   - Create index `idx_mt_usage_lookup`
   - Update `schema_meta` to version 9

4. **Verification**:
   - Schema version checked
   - Table existence verified
   - Indexes validated

**Duration:** <1 second (empty table creation)

---

## Schema Changes

### New Table: mt_usage

```sql
CREATE TABLE mt_usage (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,           -- e.g., 'google_cloud_translate'
    period_type TEXT NOT NULL,           -- 'minute', 'day', 'month'
    period_key TEXT NOT NULL,            -- '2026-02-08T15:30', '2026-02-08', '2026-02'
    char_count INTEGER NOT NULL DEFAULT 0,
    request_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(provider_id, period_type, period_key)
);
```

**Purpose:**
- Track MT provider usage for budget enforcement
- Prevent overspending with real-time limits
- Monitor translation costs

**Columns:**
- `usage_id` - Primary key (auto-increment)
- `provider_id` - Provider identifier (e.g., "google_cloud_translate")
- `period_type` - Granularity: "minute", "day", "month"
- `period_key` - Period identifier:
  - Minute: "2026-02-08T15:30"
  - Day: "2026-02-08"
  - Month: "2026-02"
- `char_count` - Total characters translated in period
- `request_count` - Total API requests in period
- `created_at` - First usage timestamp
- `updated_at` - Last update timestamp

**Unique Constraint:**
- `(provider_id, period_type, period_key)` - One row per provider per period
- Enables atomic updates with `INSERT ... ON CONFLICT DO UPDATE`

### New Index: idx_mt_usage_lookup

```sql
CREATE INDEX idx_mt_usage_lookup
ON mt_usage(provider_id, period_type, period_key);
```

**Purpose:**
- Fast lookups during budget guard checks
- Efficient queries by provider and period

**Performance:**
- Lookup time: O(log n) instead of O(n)
- Critical for real-time budget enforcement

---

## Backward Compatibility

### ✅ Fully Backward Compatible

**Existing functionality unchanged:**
- All existing providers work (Google Translate Free, Local MT)
- Existing translations preserved
- Existing caches intact
- Existing settings unchanged

**New table empty on migration:**
- Usage tracking starts after migration
- No historical data migrated (none exists)
- Future usage tracked automatically

**Optional feature:**
- Google Cloud Translate provider disabled by default
- Requires manual setup (Service Account JSON)
- Existing providers unaffected

---

## Verification

### Check Migration Success

**Method 1: Application Logs**

Check `M:\V_book\HDLE\logs\hdle.log` for:
```
app.infra.db - INFO - Current schema version: 9
```

**Method 2: SQL Query**

```sql
SELECT value FROM schema_meta WHERE key = 'schema_version';
```

Expected result: `9`

**Method 3: Table Existence**

```sql
SELECT name FROM sqlite_master WHERE type='table' AND name='mt_usage';
```

Expected result: `mt_usage`

### Rollback (If Needed)

If migration fails, HDLE automatically:
1. Restores from backup
2. Logs error details
3. Exits safely

**Manual rollback:**
1. Stop HDLE Premium
2. Replace database with backup:
   ```batch
   copy "M:\V_book\HDLE\backups\hdle_backup_<timestamp>.db" "M:\V_book\HDLE\hdle.db"
   ```
3. Restart HDLE Premium
4. Report issue: https://github.com/SindromRadioSpb/v_book/issues

---

## Common Issues

### Issue 1: "Permission denied on migrate.lock"

**Symptom:**
```
PermissionError: [Errno 13] Permission denied
ERROR: Migration aborted: Could not acquire lock within 30s
```

**Cause:**
- Another HDLE instance running
- Antivirus blocking lock file
- Previous migration didn't clean up

**Solution:**
1. Close all HDLE instances
2. Delete lock file manually:
   ```batch
   del "M:\V_book\HDLE\migrate.lock"
   ```
3. Restart HDLE Premium

---

### Issue 2: "Database or disk is full"

**Symptom:**
```
sqlite3.OperationalError: database or disk is full
ERROR: Backup creation failed
```

**Cause:**
- Insufficient disk space for backup
- C: drive full (SQLite temp files)

**Solution:**
1. Free up disk space (delete temp files, empty recycle bin)
2. Move database to drive with more space:
   ```batch
   python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"
   ```
3. Restart HDLE Premium

---

### Issue 3: "table mt_usage already exists"

**Symptom:**
```
sqlite3.OperationalError: table mt_usage already exists
```

**Cause:**
- Migration 009 partially applied (table created but schema version not updated)

**Solution:**
Fixed in commit `f36a30a`. Update to latest version:
```batch
git pull origin main
```

If already on latest version, manually update schema version:
```sql
UPDATE schema_meta SET value = '9' WHERE key = 'schema_version';
```

---

## Data Migration

### No Data Migration Required

Migration 009 creates an empty `mt_usage` table. No existing data is migrated because:

1. **No historical usage data exists** - Usage tracking is a new feature
2. **Fresh start preferred** - Clean baseline for budget enforcement
3. **No performance impact** - Empty table, instant creation

**Future usage tracked automatically** after migration.

---

## Testing

### Pre-Migration Testing

Before deploying to production:

1. **Test on development database:**
   ```batch
   python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_test.db"
   ```

2. **Verify migration success:**
   - Check logs: `Current schema version: 9`
   - Query: `SELECT * FROM mt_usage;` (should be empty)

3. **Test rollback:**
   - Restore from backup
   - Verify schema version reverted

### Post-Migration Verification

After production migration:

1. **Schema version check:**
   ```sql
   SELECT value FROM schema_meta WHERE key = 'schema_version';
   ```
   Expected: `9`

2. **Table existence check:**
   ```sql
   SELECT name FROM sqlite_master WHERE type='table' AND name='mt_usage';
   ```
   Expected: `mt_usage`

3. **Index check:**
   ```sql
   SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mt_usage_lookup';
   ```
   Expected: `idx_mt_usage_lookup`

4. **Usage tracking test:**
   - Use Google Cloud Translate provider
   - Translate a few documents
   - Query: `SELECT * FROM mt_usage;`
   - Verify rows inserted

---

## Performance Impact

### Migration Performance

- **Duration:** <1 second (empty table creation)
- **Downtime:** None (single-user application)
- **Disk space:** Minimal (~1 KB for empty table)
- **CPU impact:** Negligible

### Runtime Performance

**Usage tracking overhead:**
- Per translation: +1ms (single INSERT/UPDATE)
- Budget check: +2ms (SELECT + SUM)
- Total overhead: ~3ms per translation

**Acceptable because:**
- Translation API latency: 200-500ms
- Tracking overhead: <1% of total time
- Atomic operations prevent concurrency issues

**Index performance:**
- Lookup time: O(log n)
- Memory: Minimal (few KB for typical usage)
- Update time: O(log n) per insert

---

## Security Considerations

### New Security Features

**Credential encryption (schema v8, prerequisite for v9):**
- Service Account JSON encrypted with AES-256-GCM
- Master key in Windows Credential Manager
- Required for Google Cloud Translate provider

**Usage tracking security:**
- No sensitive data in `mt_usage` table (only counts)
- Atomic operations prevent race conditions
- No injection vulnerabilities (parameterized queries)

### Audit Logging

Usage tracking events logged in `security_audit_log`:
```sql
SELECT * FROM security_audit_log
WHERE event_type LIKE 'mt_usage_%'
ORDER BY timestamp DESC;
```

**Logged events:**
- `mt_usage_check` - Budget guard check
- `mt_usage_record` - Usage recorded
- `mt_usage_limit_exceeded` - Budget limit exceeded

---

## FAQ

### Q: Do I need to update existing translations?

**A:** No. Migration only adds usage tracking table. Existing translations in `mt_cache` are unchanged.

---

### Q: Will this affect my Google Translate Free provider?

**A:** No. Usage tracking applies to all providers but Google Translate Free has no budget limits (free service).

---

### Q: Can I disable usage tracking?

**A:** No. Usage tracking is mandatory for budget enforcement. However, if you don't configure budget limits, tracking has no functional impact (only monitoring).

---

### Q: What happens to usage data over time?

**A:** Usage data accumulates indefinitely. For cleanup:

```sql
-- Delete usage older than 1 year
DELETE FROM mt_usage
WHERE created_at < date('now', '-1 year');

-- Vacuum to reclaim space
VACUUM;
```

**Recommendation:** Clean up annually.

---

### Q: How much disk space will mt_usage consume?

**A:** Very little. Example estimates:

| Usage | Rows | Disk Space |
|-------|------|------------|
| 1 provider, 1 month | ~90 | <10 KB |
| 5 providers, 1 year | ~5,400 | ~500 KB |
| Heavy use, 5 years | ~27,000 | ~2.5 MB |

**Negligible** compared to typical database size (2+ GB).

---

### Q: Can I import historical usage data?

**A:** Yes, manually insert into `mt_usage` table:

```sql
INSERT INTO mt_usage (provider_id, period_type, period_key, char_count, request_count)
VALUES ('google_cloud_translate', 'month', '2026-01', 500000, 100);
```

**Note:** Historical data doesn't affect budget guards (only current period counts).

---

## Rollout Plan

### Recommended Rollout

**Phase 1: Development (Done)**
- Test on development database
- Verify migration success
- Test Google Cloud Translate provider

**Phase 2: Staging (If applicable)**
- Test on staging database
- Verify backward compatibility
- Load test with concurrent batch translate

**Phase 3: Production**
- **Backup first:** Manual backup before migration
- Deploy to production
- Monitor logs during first launch
- Verify schema version 9
- Test existing providers still work
- Test new Google Cloud Translate provider

### Emergency Rollback

If critical issue discovered after production migration:

1. **Stop HDLE Premium immediately**
2. **Restore from backup:**
   ```batch
   copy "M:\V_book\HDLE\backups\hdle_backup_<timestamp>.db" "M:\V_book\HDLE\hdle.db"
   ```
3. **Verify restoration:**
   ```sql
   SELECT value FROM schema_meta WHERE key = 'schema_version';
   ```
   Should be: `8`
4. **Restart HDLE Premium on v8**
5. **Report issue:** https://github.com/SindromRadioSpb/v_book/issues
6. **Wait for fix before re-attempting migration**

---

## Support

### Getting Help

**Documentation:**
- [Release Notes](RELEASE_NOTES_GOOGLE_CLOUD_TRANSLATE.md)
- [Integration Guide](INTEGRATION_GOOGLE_CLOUD_TRANSLATE.md)

**Logs:**
- Application: `M:\V_book\HDLE\logs\hdle.log`
- Migration: Search for "migration" in logs

**Bug Reports:**
- GitHub Issues: https://github.com/SindromRadioSpb/v_book/issues
- Include:
  - Error message
  - Log file (last 100 lines)
  - Schema version before/after
  - Database size

---

## Checklist

### Pre-Migration

- [ ] Backup database manually (extra safety)
- [ ] Check disk space (need 2x database size free)
- [ ] Close all HDLE instances
- [ ] Test on development database first

### During Migration

- [ ] Monitor logs for errors
- [ ] Verify schema version updated to 9
- [ ] Check `mt_usage` table created

### Post-Migration

- [ ] Verify schema version: `SELECT value FROM schema_meta WHERE key='schema_version'`
- [ ] Test existing providers (Google Translate Free, Local MT)
- [ ] Test new provider (Google Cloud Translate)
- [ ] Verify usage tracking: Translate something, check `mt_usage` table
- [ ] Keep backup for 30 days

---

**Migration Version:** v8 → v9
**Migration File:** `009_mt_usage_tracking.sql`
**Last Updated:** 2026-02-08
**Author:** HDLE Premium Development Team
