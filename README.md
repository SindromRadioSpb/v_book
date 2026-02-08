# HDLE Premium - Hebraic Dynamic Lexicon Engine

Premium desktop application for Hebrew lexicography and terminology extraction.

## Status

- ✅ **M1-M11: Core Milestones** - COMPLETE
- ✅ **M11: Batch Translation** - Dictionary & Terms (Google Translate integrated)
- ✅ **P0: Security Hardening** - COMPLETE
- ✅ **Database Relocation** - M:\V_book\HDLE (saves C: drive space)
- ✅ **Hebrew Wikipedia Baseline** - Included as reference corpus (387k documents)
- ⏳ **M12: Reference Corpus Integration** - IN PROGRESS

## Features

### Core Features (M1-M11)
- ✅ **Offline-first**: All processing happens locally, no network required
- ✅ **Multi-format ingestion**: TXT, DOCX, PDF (text + OCR)
- ✅ **Drag-drop import**: Import files by dragging into the window
- ✅ **Duplicate detection**: SHA256-based to prevent re-imports
- ✅ **Project management**: Create/open projects with corpora
- ✅ **Reference corpora**: Hebrew Wikipedia Baseline (387k documents) included
- ✅ **Advanced NLP**: Lemmatization, POS tagging (Stanza Hebrew)
- ✅ **MWE extraction**: Multi-word expressions with PMI/T-score
- ✅ **Live updates**: Incremental document processing
- ✅ **FTS5 search**: Fast concordance and KWIC display
- ✅ **Translation memory**: Offline dictionary + MT integration
- ✅ **Batch translation (M11)**: Automated translation for Dictionary & Terms
  - Google Translate integration (free, no API key)
  - Force provider mode (direct provider selection)
  - Chain mode (fallback to multiple providers)
  - Progress tracking with real-time updates
- ✅ **Term curation**: Review workflow with approval states
- ✅ **Export Center**: Excel, CSV, JSONL, TBX, TMX with real project data
- ✅ **Security**: FTS5/CSV/log injection prevention, credential encryption, audit logging
- ✅ **Database layer**: SQLite with WAL mode, FTS5, schema versioning

## Requirements

- Python 3.11+
- Windows/Linux/macOS

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -e .

# Download Stanza Hebrew model
python -c "import stanza; stanza.download('he')"
```

## Usage

```bash
python -m app.main
```

**Database Location:**
- **Windows:** `M:\V_book\HDLE\hdle_production_new.db` (saves C: drive space, includes Hebrew Wikipedia)
- **macOS:** `~/Library/Application Support/HDLE/hdle.db`
- **Linux:** `~/.local/share/hdle/hdle.db`

**Custom Database Path:**
```bash
python -m app.main --db-path "path/to/custom.db"
```

**Note:** On Windows, after system restart, rename `hdle_production_new.db` to `hdle.db`. See [DATABASE_RELOCATION.md](docs/DATABASE_RELOCATION.md) for details.

## Architecture

- **UI Layer**: PyQt6
- **Business Logic**: Services + Domain
- **Data Layer**: SQLAlchemy 2.x + SQLite WAL + FTS5
- **NLP**: Stanza (pluggable engine architecture)

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/
```

## License

Proprietary - Premium Edition
