# PATCH-06: Pre-Process Reference Database on Dev Machine

**Status:** 📋 READY TO EXECUTE (Manual Process)
**Date:** 2026-02-07

---

## Overview

This document provides step-by-step instructions for pre-processing the Hebrew Wikipedia reference database on a development machine with GPU (RTX 3070).

**Goal:** Create a fully processed database file that can be distributed to end users, bypassing the 12-21 hour processing time.

---

## Prerequisites

- ✅ RTX 3070 GPU (or equivalent CUDA-capable GPU)
- ✅ Python 3.11-3.13 (NOT 3.14 - Stanza/PyTorch incompatible)
- ✅ 50+ GB free disk space
- ✅ Stable internet connection (for initial download)

---

## Step-by-Step Process

### 1. Setup Environment

```bash
# Use Python 3.11-3.13 (create separate venv if needed)
python3.11 -m venv venv_process
source venv_process/bin/activate  # Windows: venv_process\Scripts\activate

# Install dependencies
pip install -e .
pip install stanza torch --index-url https://download.pytorch.org/whl/cu118

# Download Stanza Hebrew model
python -c "import stanza; stanza.download('he')"
```

### 2. Verify GPU Availability

```python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
```

**Expected Output:**
```
CUDA available: True
CUDA device: NVIDIA GeForce RTX 3070
```

### 3. Download Wikipedia Dump

```bash
# Create working directory
mkdir -p M:/V_book/HDLE_Processing
cd M:/V_book/HDLE_Processing

# Download Hebrew Wikipedia dump (20260201)
wget https://dumps.wikimedia.org/hewiki/20260201/hewiki-20260201-pages-articles.xml.bz2

# Verify download (optional)
md5sum hewiki-20260201-pages-articles.xml.bz2
```

### 4. Extract to JSONL

```bash
# Extract Wikipedia XML to JSONL shards
python scripts/ref_corpora/extract_hewiki_to_jsonl.py \
    --dump M:/V_book/HDLE_Processing/hewiki-20260201-pages-articles.xml.bz2 \
    --out_dir M:/V_book/HDLE_Processing/jsonl \
    --overwrite

# Expected: ~387,639 documents in multiple JSONL shards
```

**Duration:** ~2-5 minutes

### 5. Create Fresh Database

```bash
# Initialize fresh production database
python init_production_db.py

# This creates: M:\V_book\HDLE\hdle.db (empty, schema v7)
```

### 6. Import JSONL to Database

```bash
# Import all JSONL shards
python scripts/ref_corpora/import_ref_jsonl_to_project.py \
    --jsonl_files "M:/V_book/HDLE_Processing/jsonl/*.jsonl" \
    --project_name "Hebrew Wikipedia Baseline" \
    --corpus_name "HEWiki-20260207" \
    --source_key "hewiki" \
    --db_path "M:/V_book/HDLE/hdle.db"

# Expected: 387,639 documents imported, ~0 duplicates
```

**Duration:** ~5-10 minutes

### 7. Mark as Reference Corpus

```bash
# Set is_general_corpus=1
python scripts/ref_corpora/setup_hewiki_as_default_reference.py \
    --db-path "M:/V_book/HDLE/hdle.db" \
    --assign-existing
```

### 8. Process with NLP (GPU) ⏰ LONG OPERATION

**IMPORTANT:** This is the longest step (~12-21 hours with GPU)

```bash
# Run NLP processing with GPU
python scripts/process_reference_corpus.py \
    --db-path "M:/V_book/HDLE/hdle.db" \
    --project-name "Hebrew Wikipedia Baseline" \
    --use-gpu \
    --batch-size 100

# Monitor progress (another terminal)
tail -f M:/V_book/HDLE/logs/hdle.log
```

**Create this script** (`scripts/process_reference_corpus.py`):

```python
#!/usr/bin/env python3
"""Process reference corpus with NLP pipeline."""

import argparse
import logging
from pathlib import Path

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.process_service import ProcessService
from app.infra.sa_models import SourceDocument, SourceCorpus, DictProject
from sqlalchemy import select

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Process reference corpus with NLP")
    parser.add_argument("--db-path", type=str, required=True)
    parser.add_argument("--project-name", type=str, required=True)
    parser.add_argument("--use-gpu", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    db_path = Path(args.db_path)
    setup_logging(db_path.parent / "logs", level=logging.INFO)

    DBService.initialize(db_path)
    db_service = DBService.get_instance()
    process_service = ProcessService()

    try:
        with db_service.get_session() as session:
            # Get project
            project = session.execute(
                select(DictProject).where(DictProject.name == args.project_name)
            ).scalar_one()

            # Get all documents
            docs = session.execute(
                select(SourceDocument.doc_id)
                .join(SourceCorpus)
                .where(SourceCorpus.project_id == project.project_id)
                .order_by(SourceDocument.doc_id)
            ).scalars().all()

            total = len(docs)
            logger.info(f"Processing {total:,} documents (GPU={args.use_gpu})")

            for i, doc_id in enumerate(docs, 1):
                try:
                    process_service.process_document(
                        session, doc_id, use_gpu=args.use_gpu
                    )
                    session.commit()

                    if i % args.batch_size == 0:
                        logger.info(f"Progress: {i:,}/{total:,} ({i/total*100:.1f}%)")

                except Exception as e:
                    logger.error(f"Error processing doc {doc_id}: {e}")
                    session.rollback()

            logger.info(f"NLP processing complete: {total:,} documents")

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    main()
```

**Duration:** ~12-21 hours (GPU RTX 3070)

### 9. Extract Terms ⏰ MODERATE OPERATION

```bash
# Extract terms and create clusters
python scripts/extract_reference_terms.py \
    --db-path "M:/V_book/HDLE/hdle.db" \
    --project-name "Hebrew Wikipedia Baseline"
```

**Create this script** (`scripts/extract_reference_terms.py`):

```python
#!/usr/bin/env python3
"""Extract terms from reference corpus."""

import argparse
import logging
from pathlib import Path

from app.infra.util.logging import setup_logging
from app.services.db_service import DBService
from app.services.term_extraction_service import TermExtractionService
from app.infra.sa_models import DictProject
from sqlalchemy import select

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Extract terms from reference corpus")
    parser.add_argument("--db-path", type=str, required=True)
    parser.add_argument("--project-name", type=str, required=True)
    args = parser.parse_args()

    db_path = Path(args.db_path)
    setup_logging(db_path.parent / "logs", level=logging.INFO)

    DBService.initialize(db_path)
    db_service = DBService.get_instance()
    term_service = TermExtractionService()

    try:
        with db_service.get_session() as session:
            # Get project
            project = session.execute(
                select(DictProject).where(DictProject.name == args.project_name)
            ).scalar_one()

            logger.info(f"Extracting terms for project: {project.name}")

            # Extract terms
            report = term_service.extract_terms_for_project(session, project.project_id)

            logger.info(f"Term extraction complete:")
            logger.info(f"  N-grams: {report.ngrams_extracted:,}")
            logger.info(f"  Clusters: {report.clusters_created:,}")

    finally:
        DBService.shutdown()


if __name__ == "__main__":
    main()
```

**Duration:** ~3-5 hours

### 10. Verify Database

```bash
# Verify completeness
python verify_reference_corpus.py --db-path "M:/V_book/HDLE/hdle.db"
```

**Expected Output:**
```
[OK] Project: Hebrew Wikipedia Baseline (ID: 1)
[OK] is_general_corpus: 1
[OK] Total documents: 387,639
[OK] Processed documents: 387,639 (100%)
[OK] Total lemmas: ~45,000-50,000
[OK] Total n-grams: ~10,000-15,000
[OK] Database size: ~2.3-2.5 GB
[OK] All checks passed!
```

### 11. Prepare for Distribution

```bash
# Copy to distribution directory
cp "M:/V_book/HDLE/hdle.db" "M:/V_book/HDLE_Processing/hewiki_ref_processed_v20260207.db"

# Calculate SHA256
sha256sum hewiki_ref_processed_v20260207.db > hewiki_ref_processed_v20260207.db.sha256

# Get file size
ls -lh hewiki_ref_processed_v20260207.db
```

### 12. Upload to GitHub Release

```bash
# Create GitHub release
gh release create v1.1.0 \
    --title "HDLE Premium v1.1.0 - Hebrew Wikipedia Reference Corpus" \
    --notes "Includes pre-processed Hebrew Wikipedia Baseline (387,639 documents)" \
    hewiki_ref_processed_v20260207.db

# Note the download URL
gh release view v1.1.0 --json assets
```

### 13. Update Manifest

Update `app/services/reference_setup/manifest.py`:

```python
EMBEDDED_MANIFEST.entries = {
    "hewiki_ref_baseline": ManifestEntry(
        name="hewiki_ref_baseline",
        version="20260207",
        url="https://github.com/SindromRadioSpb/v_book/releases/download/v1.1.0/hewiki_ref_processed_v20260207.db",
        sha256="<ACTUAL_SHA256_HERE>",  # From step 11
        size_bytes=<ACTUAL_SIZE_HERE>,  # From step 11
        compression="none",
        created_at="2026-02-07T00:00:00Z",
        description="Hebrew Wikipedia Baseline (387,639 documents, fully processed)",
    )
}
```

---

## Troubleshooting

### GPU Out of Memory

**Symptom:** `CUDA out of memory` error during NLP processing

**Solution:** Reduce batch size or use CPU
```bash
python scripts/process_reference_corpus.py --batch-size 50  # or 25
```

### Stanza Not Using GPU

**Symptom:** Slow processing (~1-2 docs/sec instead of 10-20 docs/sec)

**Verify:**
```python
import torch
import stanza

nlp = stanza.Pipeline('he', use_gpu=True)
print(f"Using GPU: {next(nlp.processors['tokenize'].model.parameters()).is_cuda}")
```

### Processing Interrupted

**Resume:**
- Script automatically skips already-processed documents
- Safe to re-run from any point

---

## Timeline Estimate (RTX 3070)

| Step | Duration | Cumulative |
|------|----------|------------|
| 1-2. Setup | 10 min | 10 min |
| 3. Download XML | 5-10 min | 20 min |
| 4. Extract JSONL | 3 min | 23 min |
| 5-7. Import + Setup | 10 min | 33 min |
| 8. NLP Processing | **12-21 hours** | **12.5-21.5 hours** |
| 9. Term Extraction | 3-5 hours | **15.5-26.5 hours** |
| 10-13. Verify + Upload | 30 min | **16-27 hours** |

**Total: ~16-27 hours** (mostly unattended)

---

## Post-Processing Checklist

- [ ] Database file created and verified
- [ ] SHA256 checksum calculated
- [ ] File uploaded to GitHub Release
- [ ] Manifest updated with real URL and checksum
- [ ] Test download on clean machine
- [ ] Verify import into fresh HDLE installation

---

**Status:** Ready to execute when GPU machine is available
**Author:** Claude Sonnet 4.5
**Co-Authored-By:** Claude Sonnet 4.5 <noreply@anthropic.com>
