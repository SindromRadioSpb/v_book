# HDLE Premium - Hebraic Dynamic Lexicon Engine

Premium desktop application for Hebrew lexicography and terminology extraction.

## Status

- ✅ **M1: Foundation & Storage** - COMPLETE
- ✅ **M2: Document Ingestion** - COMPLETE
- 🚧 **M3: NLP Pipeline** - Ready to implement

## Features

### Implemented (M1-M2)
- ✅ **Offline-first**: All processing happens locally, no network required
- ✅ **Multi-format ingestion**: TXT, DOCX, PDF (text + OCR)
- ✅ **Drag-drop import**: Import files by dragging into the window
- ✅ **Duplicate detection**: SHA256-based to prevent re-imports
- ✅ **Project management**: Create/open projects with corpora
- ✅ **Document viewer**: View extracted text
- ✅ **Database layer**: SQLite with WAL mode, FTS5 ready

### Planned (M3-M10)
- 🚧 **Advanced NLP**: Lemmatization, POS tagging (Stanza Hebrew)
- 🚧 **MWE extraction**: Multi-word expressions with PMI/T-score
- 🚧 **Live updates**: Incremental document processing
- 🚧 **FTS5 search**: Fast concordance and KWIC display
- 🚧 **Translation memory**: Offline dictionary + user overrides
- 🚧 **Term curation**: Review workflow with approval states
- 🚧 **Export**: Excel, CSV, JSONL, TBX, TMX
- 🚧 **Snapshots**: Project versioning

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
