# M10 Backup Policy

## Overview

HDLE Premium automatically creates backups before applying database migrations to protect against data loss. This document describes the backup system, retention policy, and recovery procedures.

## Backup Location

**Windows:** `%LOCALAPPDATA%\HDLE\backups\`
**Typical Path:** `C:\Users\<username>\AppData\Local\HDLE\backups\`

Backups are stored alongside your main database in the application data directory.

## When Backups Are Created

Automatic backups are created in the following scenarios:

1. **Before Database Migrations** - Every time the application upgrades the database schema
2. **Backup Naming Format:** `backup_YYYYMMDD_HHMMSS_pre_migration_X_to_Y.db`

Example: `backup_20260205_143022_pre_migration_004_to_005.db`

## Backup Method

HDLE uses **WAL-safe backup** via SQLite's native `backup()` API, which:

- ✅ Handles Write-Ahead Log (WAL) files automatically
- ✅ Creates atomic, consistent snapshots
- ✅ Works even while the database is in use
- ✅ No need to manually copy `*.db-wal` or `*.db-shm` files

**Technical Detail:** The backup system uses `sqlite3.Connection.backup()` API, which properly handles databases in WAL journal mode. This is superior to simple file copying (e.g., `shutil.copy2()`), which can create corrupted backups if WAL files are active.

## Retention Policy

**Default Policy:**
- Keep last **10 backups**, OR
- Keep backups from last **30 days**

Whichever is more permissive applies.

**Example Scenarios:**

1. **Frequent Migrations:**
   - If you have 15 backups, the 5 oldest will be deleted **only if** they are older than 30 days.

2. **Infrequent Use:**
   - If you have 3 backups from the last 6 months, all are kept (under the 10-backup limit).

**Cleanup Trigger:** Old backups are automatically cleaned up **after** each successful migration.

## Concurrency Protection

### Migration Lock

A file-based lock prevents concurrent migrations:

- **Lock File:** `%LOCALAPPDATA%\HDLE\migrate.lock`
- **Timeout:** 30 seconds
- **Behavior:** If another instance is running migrations, subsequent instances will wait up to 30 seconds, then fail with an error.

**Error Message:**
```
Could not acquire lock within 30s - migration already in progress or app already running
```

### Stale Lock Detection

The lock system uses **PID-based stale detection**:

1. When acquiring the lock, the process ID (PID) is written to the lock file.
2. If a lock file exists, the system checks if that PID is still running.
3. If the process is dead (e.g., from a crash), the stale lock is removed automatically.

**Requirement:** This feature requires the `psutil` Python package (automatically installed).

## Manual Backup Recovery

If you need to restore from a backup:

### Step 1: Locate Your Backup

1. Navigate to: `%LOCALAPPDATA%\HDLE\backups\`
2. Find the backup file (e.g., `backup_20260205_143022_pre_migration_004_to_005.db`)

### Step 2: Close the Application

Ensure HDLE Premium is completely closed.

### Step 3: Replace the Database

1. Navigate to: `%LOCALAPPDATA%\HDLE\`
2. **Backup Current Database** (optional safety step):
   - Rename `hdle.db` to `hdle.db.broken`
3. **Restore Backup:**
   - Copy your chosen backup file from `backups/` directory
   - Rename it to `hdle.db`

**Example (PowerShell):**
```powershell
cd $env:LOCALAPPDATA\HDLE
# Backup current (potentially broken) database
mv hdle.db hdle.db.broken

# Restore from backup
cp backups\backup_20260205_143022_pre_migration_004_to_005.db hdle.db
```

### Step 4: Restart Application

Launch HDLE Premium. The database will now be at the state of the backup.

**Important:** If you restore an older backup, you may need to re-apply migrations. The application will detect this and prompt you.

## Verifying Backup Integrity

Each backup includes a SHA256 hash for integrity verification. To verify a backup:

```python
from app.services.backup_service import BackupService
from pathlib import Path

backup_path = Path(r"C:\Users\<username>\AppData\Local\HDLE\backups\backup_20260205_143022_pre_migration_004_to_005.db")

service = BackupService()
computed_hash = service._compute_sha256(backup_path)
print(f"SHA256: {computed_hash}")
```

Compare the computed hash with the hash logged during backup creation (check application logs).

## Disk Space Management

### Pre-Flight Check

Before creating a backup, the system checks for available disk space:

- **Requirement:** 3× the current database size
- **Failure Behavior:** If insufficient space, migration is aborted with an error

### Manual Cleanup

If you need to free space, you can manually delete old backups:

1. Navigate to `%LOCALAPPDATA%\HDLE\backups\`
2. Delete backup files you no longer need
3. **Caution:** Keep at least 2-3 recent backups for safety

**Automated cleanup** runs after each migration, so manual intervention is rarely needed.

## Backup Logs

Backup creation is logged in the application logs:

**Log Location:** `%LOCALAPPDATA%\HDLE\logs\`

**Log Entry Example:**
```
2026-02-05 14:30:22 INFO Migration backup created: C:\Users\...\backups\backup_20260205_143022_pre_migration_004_to_005.db
2026-02-05 14:30:22 INFO Backup created successfully: ... (442368 bytes, SHA256: a3f2...)
2026-02-05 14:30:25 INFO Cleaned up 2 old backups
```

## Installer Behavior

### Fresh Installation

On first install, the `backups/` directory does not exist. It is created automatically on the first migration.

**Installation Paths:**
- **Application:** `C:\Program Files\HDLE\HDLE_Premium.exe`
- **User Data:** `%LOCALAPPDATA%\HDLE\` (database, backups, logs)

The installer **only** manages the application directory. User data is in a separate location and is never touched by the installer.

### Upgrade Installation

**User data is preserved during upgrades:**

| Component             | Location                        | Behavior During Upgrade |
|-----------------------|---------------------------------|-------------------------|
| Application files     | `C:\Program Files\HDLE\`        | ✅ REPLACED             |
| Database              | `%LOCALAPPDATA%\HDLE\hdle.db`   | ✅ PRESERVED            |
| Backups               | `%LOCALAPPDATA%\HDLE\backups\`  | ✅ PRESERVED            |
| Snapshots             | `%LOCALAPPDATA%\HDLE\snapshots\`| ✅ PRESERVED            |
| Logs                  | `%LOCALAPPDATA%\HDLE\logs\`     | ✅ PRESERVED            |
| Stanza models         | `%LOCALAPPDATA%\HDLE\models\`   | ✅ PRESERVED            |

**Result:** All your backups survive application upgrades. You can upgrade without losing any data.

**How it works:** The installer only manages `C:\Program Files\HDLE\`. User data in `%LOCALAPPDATA%` is completely separate and untouched by the installer.

### Uninstallation

**User data is NOT deleted on uninstall:**

**Deleted:**
- ✅ Application files: `C:\Program Files\HDLE\`
- ✅ Start menu shortcuts
- ✅ Desktop shortcut (if created)

**PRESERVED:**
- ✅ Database: `%LOCALAPPDATA%\HDLE\hdle.db`
- ✅ Backups: `%LOCALAPPDATA%\HDLE\backups\`
- ✅ Snapshots: `%LOCALAPPDATA%\HDLE\snapshots\`
- ✅ Logs: `%LOCALAPPDATA%\HDLE\logs\`
- ✅ Stanza models: `%LOCALAPPDATA%\HDLE\models\`

**User Notification:** The uninstaller displays a message box informing you that user data was preserved and provides the path to manually delete it if desired.

**Manual Cleanup (Optional):** If you want to completely remove all data, manually delete:
```powershell
Remove-Item -Recurse -Force $env:LOCALAPPDATA\HDLE
```

## Troubleshooting

### "Backup failed: Insufficient disk space"

**Cause:** Less than 3× database size available on disk.

**Solution:**
1. Free up disk space (at least 2 GB recommended)
2. Delete old backups manually from `%LOCALAPPDATA%\HDLE\backups\`
3. Retry the operation

### "Could not acquire lock within 30s"

**Cause:** Another instance is running migrations, or a stale lock exists.

**Solution:**
1. Close all instances of HDLE Premium
2. Wait 30 seconds
3. If problem persists, manually delete the lock file:
   ```
   %LOCALAPPDATA%\HDLE\migrate.lock
   ```
4. Restart the application

### "Migration aborted: backup failed"

**Cause:** Backup creation failed (disk space, permissions, or I/O error).

**Solution:**
1. Check disk space (`%LOCALAPPDATA%` drive)
2. Ensure you have write permissions to `%LOCALAPPDATA%\HDLE\`
3. Check application logs for detailed error message
4. Contact support if issue persists

## Technical Architecture

### Shared Base Class

The backup system shares code with the snapshot system via `DBSnapshotBase`:

- **Location:** `app/services/db_snapshot_base.py`
- **Shared Methods:**
  - `_create_snapshot_copy()` - WAL-safe SQLite backup
  - `_compute_sha256()` - File hash computation
  - `_ensure_directory()` - Directory creation

**Benefits:**
- DRY (Don't Repeat Yourself) principle
- Consistent behavior across backup and snapshot features
- Reduced maintenance burden (single WAL-safe implementation)

### Integration Point

Backups are triggered in `app/infra/db.py`, method `DatabaseManager.apply_migrations()`:

1. Detect pending migrations
2. Acquire migration lock
3. **Create backup** ← Before any schema changes
4. Apply migrations
5. Cleanup old backups
6. Release lock

**Critical Property:** Backup always happens **before** schema changes, ensuring a valid rollback point.

## Best Practices

1. **Don't disable backups** - They take minimal time and disk space
2. **Monitor backup logs** - Ensure backups succeed after each upgrade
3. **Keep 2-3 recent backups** - Even if you manually clean up old ones
4. **Test recovery once** - Practice restoring from a backup in a test environment
5. **Backup before manual DB edits** - If you manually modify the database (advanced users), create a backup first

## Related Documentation

- **Crash Recovery:** See `M10_CRASH_RECOVERY.md` for startup recovery procedures
- **Snapshots:** See `SnapshotService` documentation for test/verification snapshots
- **Build & Install:** See `BUILD_WINDOWS_INSTALLER.md` for installer behavior

## Version History

- **1.0.0** (2026-02-05) - Initial M10 implementation
  - WAL-safe backup using `sqlite3.backup()` API
  - PID-based stale lock detection
  - Retention policy (10 backups / 30 days)
  - Automatic cleanup after migrations
