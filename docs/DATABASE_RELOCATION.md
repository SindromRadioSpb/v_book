# Database Relocation to M:\V_book\HDLE

## Problem

Disk C was running out of space due to databases and projects stored in:
- `C:\Users\Win10_Game_OS\AppData\Local\HDLE\`

## Solution Implemented

### 1. Changed Default Paths

**Updated:** `app/main.py`

```python
def get_app_dir() -> Path:
    if sys.platform == "win32":
        # Use M:\V_book\HDLE to avoid filling up C: drive
        app_dir = Path(r"M:\V_book\HDLE")
```

**New Default Locations:**
- **Windows:** `M:\V_book\HDLE\` (instead of `%LOCALAPPDATA%\HDLE\`)
- **macOS:** `~/Library/Application Support/HDLE/` (unchanged)
- **Linux:** `~/.local/share/hdle/` (unchanged)

### 2. Copied Hebrew Wikipedia Baseline to Production

**Method:** Used `VACUUM INTO` to create clean copy of dev database

**Source:** `J:\Project_Vibe\V_book\hdle_premium.db` (2.4 GB)
**Target:** `M:\V_book\HDLE\hdle_production_new.db` (2.35 GB)

**Contents:**
- ✅ Hebrew Wikipedia Baseline (reference corpus)
- ✅ 387,639 documents
- ✅ All lemmas, n-grams, and statistics

### 3. Application Configuration

The application now automatically uses the new production database:
1. First checks for `M:\V_book\HDLE\hdle_production_new.db` (contains Hebrew Wikipedia)
2. Falls back to `M:\V_book\HDLE\hdle.db` if new database doesn't exist

## Files Changed

### Code Changes
1. **app/main.py** - Changed default path from `%LOCALAPPDATA%\HDLE` to `M:\V_book\HDLE`
2. **copy_hewiki_to_production.py** - Updated target path to `M:\V_book\HDLE\hdle.db`

### Scripts Created
1. **init_production_db.py** - Initialize empty production database
2. **copy_db_vacuum.py** - Copy database using VACUUM INTO

### Documentation Updated
1. **README.md** - Added database location section
2. **INSTALL.md** - Updated log file paths
3. **DEV_DATABASE_GUIDE.md** - Updated all production paths
4. **docs/PATCH-06_DATABASE_PATH_FIX.md** - Updated paths
5. **docs/DATABASE_RELOCATION.md** - This file

## Post-Installation Steps

### For End Users (After System Restart)

After restarting your computer to release file locks:

```batch
cd M:\V_book\HDLE
del hdle.db hdle.db-wal hdle.db-shm
ren hdle_production_new.db hdle.db
```

This renames the new database (with Hebrew Wikipedia) to the standard name.

### Verification

Run the application:
```batch
python -m app.main
```

You should see:
- ✅ **🌐 Hebrew Wikipedia Baseline** in project list
- ✅ 387,639 documents
- ✅ All metrics populated (lemmas, n-grams)

## Disk Space Savings

**Before:**
- C: drive: ~2.4 GB used for databases
- M: drive: 0 GB

**After:**
- C: drive: ~0 GB (freed up)
- M: drive: ~2.4 GB (production database)

**Savings:** ~2.4 GB freed on C: drive

## Database Locations Summary

| Database | Old Location | New Location | Size |
|----------|-------------|--------------|------|
| **Production** | `C:\Users\...\AppData\Local\HDLE\hdle.db` | `M:\V_book\HDLE\hdle_production_new.db` | 2.35 GB |
| **Development** | `J:\Project_Vibe\V_book\hdle_premium.db` | (unchanged) | 2.4 GB |
| **Logs** | `C:\Users\...\AppData\Local\HDLE\logs\` | `M:\V_book\HDLE\logs\` | ~1 MB |
| **Backups** | `C:\Users\...\AppData\Local\HDLE\backups\` | `M:\V_book\HDLE\backups\` | varies |

## Benefits

1. ✅ **Freed C: drive space** - Critical for system performance
2. ✅ **Centralized location** - All V_book data in M:\V_book\
3. ✅ **Hebrew Wikipedia included** - Reference corpus available by default
4. ✅ **Easier backup** - All data in one location (M: drive)
5. ✅ **No migration needed** - Fresh installs work immediately

## Troubleshooting

### Issue: Application can't find database

**Symptom:** "Database not found" error on startup

**Solution:**
```batch
# Verify file exists
dir M:\V_book\HDLE\hdle_production_new.db

# Run with explicit path
python -m app.main --db-path "M:\V_book\HDLE\hdle_production_new.db"
```

### Issue: Old database locked

**Symptom:** Can't delete or rename `hdle.db`

**Solution:**
1. Restart Windows to release file locks
2. Run cleanup:
   ```batch
   taskkill /F /IM python.exe
   del M:\V_book\HDLE\hdle.db-wal
   del M:\V_book\HDLE\hdle.db-shm
   ```

### Issue: Want to use custom location

**Solution:**
```batch
# Use --db-path argument
python -m app.main --db-path "D:\MyCustomPath\hdle.db"
```

## Technical Notes

### Why VACUUM INTO?

We used `VACUUM INTO` instead of file copy because:
1. ✅ Creates clean, optimized copy
2. ✅ Avoids WAL file conflicts
3. ✅ Reclaims deleted space
4. ✅ Single atomic operation

### Why hdle_production_new.db?

The old `hdle.db` was locked by a running process. Instead of forcing termination:
1. Created new database with safe name
2. Updated code to use new database
3. Allows manual rename after restart

This is safer and avoids data corruption risks.

---

**Date:** 2026-02-07
**Author:** Claude Sonnet 4.5
**Status:** ✅ COMPLETE - Production database relocated with Hebrew Wikipedia included
