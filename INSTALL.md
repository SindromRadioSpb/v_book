# HDLE Premium - Installation Guide

## System Requirements

- Python 3.11 or higher
- Windows/Linux/macOS
- 500 MB free disk space minimum
- For GUI: Qt development tools (optional for M1)

## Quick Start (M1 - Foundation)

### 1. Clone/Extract Repository

```bash
cd J:\Project_Vibe\V_book
```

### 2. Create Virtual Environment

```bash
python -m venv venv
```

### 3. Activate Virtual Environment

Windows (Git Bash/MSYS):
```bash
source venv/bin/activate
```

Windows (CMD):
```cmd
venv\Scripts\activate
```

Linux/macOS:
```bash
source venv/bin/activate
```

### 4. Install Dependencies

**Core dependencies (no GUI):**
```bash
pip install SQLAlchemy python-docx PyPDF2 openpyxl pandas
```

**Full dependencies (with GUI):**
```bash
pip install -e .
```

Note: PyQt6 requires Qt development tools (qmake). If installation fails, install Qt Creator first or use pre-built wheels.

### 5. Test M1 (Foundation)

```bash
python test_m1.py
```

Expected output:
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

## Running the Application

### With GUI (requires PyQt6):

```bash
python -m app.main
```

### Without GUI (API/Testing only):

Use the services programmatically:

```python
from pathlib import Path
from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.project_service import ProjectService

# Initialize
setup_logging(Path("logs"))
DBService.initialize(Path("data/hdle.db"))

# Use services
project_service = ProjectService()
with project_service.db_service.get_session() as session:
    projects = project_service.list_projects(session)
    print(f"Projects: {len(projects)}")

# Cleanup
DBService.shutdown()
```

## Troubleshooting

### PyQt6 Installation Fails

**Error:** `qmake not found`

**Solution:** Install Qt development tools first:
- Windows: Download Qt Creator from qt.io
- Linux: `sudo apt-get install qt6-base-dev` (Ubuntu/Debian)
- macOS: `brew install qt6`

Or use pre-compiled wheels:
```bash
pip install PyQt6 --only-binary :all:
```

### Import Errors

**Error:** `ModuleNotFoundError`

**Solution:** Ensure virtual environment is activated and dependencies installed:
```bash
pip install typing_extensions greenlet
```

### Database Locked

**Error:** `database is locked`

**Solution:** Close all other connections to the database and ensure WAL mode is enabled (handled automatically).

## Development Setup

### Install Development Dependencies

```bash
pip install -e ".[dev]"
```

### Run Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black app/ tests/
```

## Next Steps After M1

1. **M2 - Document Ingestion:** Implement file extractors and drag-drop UI
2. **M3 - NLP Pipeline:** Integrate Stanza Hebrew for lemmatization
3. **M4 - Live Updates:** Implement incremental document processing
4. **M5 - MWE Extraction:** Add multi-word expression detection
5. **M6 - Concordance:** Implement FTS5 search and KWIC display
6. **M7 - Translation Memory:** Add offline dictionary and TM
7. **M8 - Term Cards:** Implement curation workflow
8. **M9 - Export Center:** Add export to Excel/CSV/TBX/TMX
9. **M10 - Packaging:** Create installer and final QA

## Support

For issues, refer to the log files:
- Application logs: `<app_dir>/logs/hdle.log`
- Test logs: `test_data/logs/hdle.log`

Where `<app_dir>` is:
- **Windows: `M:\V_book\HDLE`** (to avoid filling up C: drive)
- macOS: `~/Library/Application Support/HDLE`
- Linux: `~/.local/share/hdle`
