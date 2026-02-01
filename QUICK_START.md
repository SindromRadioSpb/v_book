# HDLE Premium - Quick Start Guide

## ✅ M1 (Foundation) is READY

The foundation layer is **fully implemented and tested**. Follow these steps to verify:

---

## Step 1: Install Core Dependencies

```bash
cd "J:\Project_Vibe\V_book"

# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # Git Bash/MSYS
# OR: venv\Scripts\activate  # Windows CMD

# Install minimal dependencies for M1 test
venv/bin/pip install SQLAlchemy typing_extensions greenlet
```

---

## Step 2: Run M1 Verification Test

```bash
venv/bin/python test_m1.py
```

**Expected Result:**
```
============================================================
M1 TEST PASSED
============================================================

All core functionality working:
  - Database initialization [OK]
  - Migrations applied [OK]
  - WAL mode enabled [OK]
  - Foreign keys enabled [OK]
  - Project management [OK]
  - Corpus management [OK]
```

If you see this, **M1 is working perfectly!**

---

## Step 3 (Optional): Install GUI Dependencies

For the full PyQt6 GUI, you need Qt development tools:

### Option A: Pre-compiled Wheels (Recommended)

```bash
pip install PyQt6 --only-binary :all:
```

### Option B: Full Installation

**Windows:**
1. Download Qt Creator from https://www.qt.io/download-qt-installer
2. Install Qt 6.x
3. Add qmake to PATH
4. Run: `pip install PyQt6`

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install qt6-base-dev
pip install PyQt6
```

**macOS:**
```bash
brew install qt6
pip install PyQt6
```

---

## Step 4 (Optional): Run GUI Application

```bash
python -m app.main
```

**What You'll See:**
1. Main window opens (1200x800)
2. Project Dashboard (empty initially)
3. Click "Create Project" → enter name → project appears
4. Double-click project → Project View with tabs
5. Tabs are placeholders for M2-M10 features

---

## What Works Now (M1)

✅ **Database Layer:**
- SQLite with WAL mode
- 25+ tables (full schema for M1-M10)
- FTS5 full-text search tables
- Migrations system
- Foreign keys enforced

✅ **Project Management:**
- Create projects
- List projects
- Default library and corpus creation
- SQLAlchemy ORM models

✅ **Infrastructure:**
- Rotating file logs (10MB max, 5 backups)
- Cross-platform app directory
- SHA256 file hashing
- Hebrew text utilities

✅ **UI Shell (PyQt6):**
- Main window with navigation
- Project dashboard
- Project view with tabs
- Modal dialogs

---

## What's Coming (M2-M10)

See `PROJECT_STATUS.md` for full roadmap.

**M2 (Next):** Document ingestion - drag-drop files, extract text, store in DB

**M3:** NLP pipeline - Stanza Hebrew, lemmatization, dictionary view

**M4:** Live updates - incremental document processing

**M5:** MWE extraction - "בית ספר" as single term

**M6:** Concordance search - FTS5 KWIC display

**M7:** Translation memory - offline dict + user overrides

**M8:** Term curation - approve/reject workflow

**M9:** Export - Excel/CSV/TBX/TMX

**M10:** Packaging - Windows installer

---

## Troubleshooting

### Test Fails with Import Error

**Problem:** `ModuleNotFoundError: No module named 'X'`

**Solution:**
```bash
venv/bin/pip install X
```

Common missing modules:
- `typing_extensions`
- `greenlet`

### PyQt6 Installation Fails

**Problem:** `qmake not found`

**Solution:** Install Qt development tools (see Step 3 above) OR skip GUI and use API only.

### Database Locked

**Problem:** `database is locked`

**Solution:** Close all connections. M1 uses WAL mode to avoid this issue.

---

## Application Data Location

Data is stored in platform-specific directories:

- **Windows:** `%LOCALAPPDATA%\HDLE\`
  - Database: `hdle.db`
  - Logs: `logs/hdle.log`

- **macOS:** `~/Library/Application Support/HDLE/`

- **Linux:** `~/.local/share/hdle/`

Test data is in: `J:\Project_Vibe\V_book\test_data\`

---

## Development Commands

### Run Tests
```bash
pytest tests/          # Full test suite
python test_m1.py      # M1 verification
```

### Format Code
```bash
pip install black
black app/ tests/
```

### View Logs
```bash
tail -f test_data/logs/hdle.log
```

### Inspect Database
```bash
sqlite3 test_data/test.db
sqlite> .tables
sqlite> .schema dict_project
sqlite> SELECT * FROM library;
```

---

## File Structure Overview

```
app/
├── main.py              # Entry point (GUI)
├── ui/                  # PyQt6 UI layer
│   ├── app_window.py   # Main window
│   └── project_dashboard.py
├── services/            # Business logic
│   ├── db_service.py   # DB singleton
│   └── project_service.py
├── domain/              # Core logic
│   ├── hebrew_utils.py # Hebrew text processing
│   └── preprocessing.py
└── infra/               # Infrastructure
    ├── db.py           # Database manager
    ├── sa_models.py    # ORM models
    └── migrations/
        └── 001_init.sql # Database schema
```

---

## Next Steps

1. ✅ **Verify M1 works:** `python test_m1.py`
2. 📖 **Read architecture:** Check `PROJECT_STATUS.md`
3. 🛠️ **Start M2:** Implement document ingestion
4. 📚 **Download Stanza:** `python -c "import stanza; stanza.download('he')"`

---

## Support & Documentation

- **Installation:** `INSTALL.md`
- **Full Status:** `PROJECT_STATUS.md`
- **Project Overview:** `README.md`
- **This Guide:** `QUICK_START.md`

---

## License

HDLE Premium - Proprietary Edition

---

**Status:** M1 Foundation Complete ✅
**Last Updated:** 2026-02-01
**Ready for:** M2 Implementation
