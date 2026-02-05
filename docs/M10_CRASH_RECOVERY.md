# M10 Crash Recovery

## Overview

HDLE Premium automatically detects and recovers from unclean shutdowns (crashes, force-quits, power outages). This document describes the crash recovery system and what users should know.

## What Happens on Unclean Shutdown

### Normal Shutdown

During normal shutdown:
1. All processing jobs complete or are cancelled gracefully
2. ProcessorRun status is set to `'ok'` or `'failed'`
3. `finished_at` timestamp is recorded
4. Database connections are closed cleanly

### Unclean Shutdown (Crash)

During an unclean shutdown (crash, force-quit, power loss):
1. ProcessorRun status may remain `'running'`
2. `finished_at` is not set
3. Database connections are terminated abruptly
4. **SQLite WAL journal ensures database integrity** (no corruption)

## Automatic Recovery on Startup

When HDLE Premium starts, it performs the following recovery steps:

### Step 1: Database Initialization

The database is initialized and migrations are applied (with automatic backup).

### Step 2: Crash Detection

The system queries for all `ProcessorRun` records with `status='running'`:

```sql
SELECT * FROM processor_run
WHERE status = 'running'
ORDER BY run_id;
```

**Deterministic ordering** (by `run_id`) ensures consistent recovery in tests and logs.

### Step 3: Mark Runs as Failed

For each unfinished run:
1. **Update status:** `'running'` → `'failed'`
2. **Set finished_at:** Current timestamp (ISO 8601 format with timezone)
3. **Create RunError record:**
   - `error_type`: `'crash_recovery'`
   - `error_message`: `'Process terminated unexpectedly - recovered on restart'`
   - `severity`: `'warning'`
   - `context`: `None`

### Step 4: Log Recovery

The recovery operation is logged:

```
WARNING: Found 2 unfinished runs - recovering...
INFO: Recovered 2 runs
```

**Log Location:** `%LOCALAPPDATA%\HDLE\logs\`

## What Users Should Do

### Most Cases: Nothing

Crash recovery is **fully automatic**. Users do not need to take any action.

**Behavior:**
- App starts normally
- A warning message may appear in logs (if runs were recovered)
- No data loss (SQLite WAL ensures integrity)
- No corrupted database

### Checking Recovery Logs

To verify recovery happened:

1. Navigate to: `%LOCALAPPDATA%\HDLE\logs\`
2. Open the most recent log file (e.g., `hdle_20260205.log`)
3. Search for: `"Crash recovery"` or `"unfinished runs"`

**Example Log Entries:**
```
2026-02-05 14:35:12 WARNING Found 1 unfinished runs - recovering...
2026-02-05 14:35:12 INFO Recovered 1 runs
```

### Manual Intervention (Advanced Users)

In rare cases, users may want to manually inspect recovered runs:

**SQL Query (using SQLite browser):**
```sql
SELECT run_id, processor_name, status, started_at, finished_at
FROM processor_run
WHERE run_id IN (
    SELECT run_id FROM run_error WHERE error_type = 'crash_recovery'
);
```

**Re-running Failed Jobs:**
Users can manually re-trigger processing in the UI (the failed runs will not block new runs).

## Technical Details

### Integration Point

Crash recovery is called in `app/main.py`, immediately after database initialization:

```python
# Initialize database
DBService.initialize(db_path)

# Crash recovery
db_service = DBService.get_instance()
recovered_count = db_service.recover_from_crash()
if recovered_count > 0:
    logger.warning(f"Crash recovery: marked {recovered_count} runs as failed")
```

**Critical:** Recovery happens **after** migrations, ensuring the schema is up-to-date before querying `processor_run`.

### Method Signature

```python
def recover_from_crash(self) -> int:
    """
    Detect and recover from unclean shutdown.

    Returns:
        Number of runs recovered (0 if no recovery needed)
    """
```

### Error Records

Crash recovery creates `RunError` records:

| Field          | Value                                                      |
|----------------|------------------------------------------------------------|
| `run_id`       | ID of recovered run                                        |
| `error_type`   | `'crash_recovery'`                                         |
| `error_message`| `'Process terminated unexpectedly - recovered on restart'` |
| `severity`     | `'warning'`                                                |
| `context`      | `None`                                                     |

**Purpose:** Allows users/admins to distinguish crash-recovered runs from normal failures.

### Timestamp Format

`finished_at` is set using UTC timezone:

```python
from datetime import datetime, timezone

finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
```

**Format:** ISO 8601 with microseconds and 'Z' suffix (e.g., `2026-02-05T14:35:12.123456Z`)

## Known Limitations

### Concurrent Instances

**Limitation:** If two app instances are running, crash recovery may mark active runs as failed.

**Reason:** There is no global "single-instance lock" (only migration lock).

**Mitigation:** Users should not run multiple instances simultaneously. Future versions may add single-instance enforcement.

### Lock File

**File:** `%LOCALAPPDATA%\HDLE\app.lock`

**Status:** Not currently implemented (future enhancement).

**Workaround:** Crash recovery is safe to run even if false positives occur (users can re-run jobs).

### SQLite WAL Integrity

**Critical Assumption:** SQLite's Write-Ahead Log (WAL) ensures database integrity even after unclean shutdown.

**Verification:**
- SQLite 3.51.2+ with WAL mode enabled
- `PRAGMA journal_mode=WAL` set on connection

**If WAL fails:** Database may be corrupted. Users should restore from backup (see `M10_BACKUP_POLICY.md`).

## Testing Crash Recovery

### Manual Test Procedure

1. **Start app and begin processing:**
   - Create a project
   - Import a document
   - Start NLP processing

2. **Force-quit app mid-process:**
   - Windows: Task Manager → End Task
   - Linux/macOS: `kill -9 <pid>`

3. **Restart app:**
   - Launch HDLE Premium normally

4. **Verify recovery:**
   - Check logs: `%LOCALAPPDATA%\HDLE\logs\`
   - Search for: `"Crash recovery"` or `"unfinished runs"`
   - Verify run marked as failed in UI (Processing History)

### Automated Test

See `test_m10.py::test_03_crash_recovery_marks_running_as_failed` for automated crash recovery test.

**Test Strategy:**
- Create `ProcessorRun` with `status='running'`
- Shutdown DBService (simulate restart)
- Re-initialize DBService
- Call `recover_from_crash()`
- Verify run marked as `'failed'`
- Verify `RunError` created

## Troubleshooting

### "No crash recovery needed" (Expected)

**Log Entry:**
```
DEBUG: No crash recovery needed
```

**Meaning:** No unfinished runs found. This is normal during routine app starts.

### "Found N unfinished runs - recovering..."

**Log Entry:**
```
WARNING: Found 2 unfinished runs - recovering...
INFO: Recovered 2 runs
```

**Meaning:** App crashed previously, and 2 runs were left in `'running'` state. They have now been marked as failed.

**Action:** No user action required. Check recovered runs in Processing History if needed.

### Database Corruption After Crash

**Symptoms:**
- App fails to start
- Error: `"database disk image is malformed"`

**Cause:** SQLite WAL journal failure (rare).

**Solution:**
1. Close app
2. Navigate to: `%LOCALAPPDATA%\HDLE\`
3. Restore from backup (see `M10_BACKUP_POLICY.md`)

**Example (PowerShell):**
```powershell
cd $env:LOCALAPPDATA\HDLE
mv hdle.db hdle.db.corrupt
cp backups\backup_20260205_143022_pre_migration_004_to_005.db hdle.db
```

## Related Documentation

- **Backup Policy:** See `M10_BACKUP_POLICY.md` for automatic backups before migrations
- **Snapshots:** See `SnapshotService` documentation for test snapshots
- **Build & Install:** See `BUILD_WINDOWS_INSTALLER.md` for deployment

## Version History

- **1.0.0** (2026-02-05) - Initial M10 implementation
  - Automatic crash detection on startup
  - Mark unfinished runs as failed
  - Create `RunError` records with `crash_recovery` type
  - Deterministic ordering (ORDER BY run_id)
  - UTC timestamps with microseconds
