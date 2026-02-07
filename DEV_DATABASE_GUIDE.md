# HDLE Premium - Development Database Guide

## Problem: Reference Project Not Visible in UI

When you run HDLE Premium normally, it uses the **production database** located at:
- **Windows:** `%LOCALAPPDATA%\HDLE\hdle.db`
- **macOS:** `~/Library/Application Support/HDLE/hdle.db`
- **Linux:** `~/.local/share/hdle/hdle.db`

However, the **Hebrew Wikipedia Baseline** reference corpus was imported into the **development database** at:
- `J:\Project_Vibe\V_book\hdle_premium.db`

This is why you don't see the reference project when launching the application normally.

---

## Solution: Use Development Database

### Option 1: Run with Batch Script (Recommended)

Double-click the batch script:
```
J:\Project_Vibe\V_book\run_dev.bat
```

This automatically launches the application with the development database.

---

### Option 2: Command-Line Launch

Open terminal in `J:\Project_Vibe\V_book` and run:

```batch
python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"
```

---

### Option 3: Import Hebrew Wikipedia into Production Database

If you want the reference corpus available in the production database:

1. Use the import script from `ref_corpora/hewiki/`:
   ```batch
   cd J:\Project_Vibe\V_book
   python -m scripts.ref_corpora.import_hewiki_jsonl --target-db "%LOCALAPPDATA%\HDLE\hdle.db" --jsonl-dir "ref_corpora\hewiki\data"
   ```

2. Set as reference corpus:
   ```batch
   python scripts\ref_corpora\setup_hewiki_as_default_reference.py --db-path "%LOCALAPPDATA%\HDLE\hdle.db" --assign-existing
   ```

---

## Verification

After launching with the development database, you should see:

**Project Dashboard:**
- ✅ `🌐 Hebrew Wikipedia Baseline` visible in project list
- ✅ Real metrics displayed: 387,639 documents, lemmas, n-grams
- ✅ Status bar shows: "Total projects: X (My Projects: Y | Reference Corpora: 1)"

**Inside Reference Project:**
- ✅ All 6 tabs accessible: Documents, Dictionary, Terms, Concordance, Term Cards, Export
- ✅ Documents tab shows 387k+ documents with read-only protection
- ✅ Dictionary, Terms, and other tabs fully functional

---

## Command-Line Help

To see all available options:
```batch
python -m app.main --help
```

Output:
```
usage: main.py [-h] [--db-path DB_PATH]

HDLE Premium - Terminology Extraction Tool

options:
  -h, --help         show this help message and exit
  --db-path DB_PATH  Path to database file (default: %LOCALAPPDATA%/HDLE/hdle.db)
```

---

## Database Locations Summary

| Database | Location | Purpose | Contains HEWiki? |
|----------|----------|---------|------------------|
| **Production** | `%LOCALAPPDATA%\HDLE\hdle.db` | Default for end users | ❌ No (only test projects) |
| **Development** | `J:\Project_Vibe\V_book\hdle_premium.db` | Development/testing | ✅ Yes (387k documents) |

---

## FAQ

**Q: Why are there two databases?**
A: The production database is for end users (clean, AppData location). The development database is for testing features and contains pre-imported reference corpora like Hebrew Wikipedia.

**Q: Can I delete the production database?**
A: Yes, if you only use the development database. The production database will be recreated automatically when you launch the app normally.

**Q: How do I switch back to production database?**
A: Simply run `python -m app.main` without the `--db-path` argument.

---

**Created:** 2026-02-07
**Author:** Claude Sonnet 4.5 (QA Engineer)
