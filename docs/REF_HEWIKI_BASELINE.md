# Hebrew Wikipedia Baseline Corpus (REF_HE_WIKI)

Extraction and import pipeline for building a Hebrew Wikipedia reference corpus in HDLE Premium.

## Overview

This pipeline provides two-stage processing:
1. **Extraction**: Convert Wikipedia XML dumps to sharded JSONL files with metadata manifests
2. **Import**: Load JSONL shards into HDLE project database as source documents

**Key Features:**
- Automatic JSONL sharding (200K lines or 512MB per shard)
- SHA256 verification for data integrity
- Idempotent imports (safe to re-run)
- Comprehensive manifests with extraction metadata
- UTF-8 safety on Windows systems
- Progress tracking and error reporting

---

## Prerequisites

### 1. Wikipedia Dump File

Download Hebrew Wikipedia dump from https://dumps.wikimedia.org/hewiki/

```bash
# Example: Latest pages-articles dump
wget https://dumps.wikimedia.org/hewiki/latest/hewiki-latest-pages-articles.xml.bz2
```

Place in: `ref_corpora/hewiki/raw/`

### 2. WikiExtractor-V2

Already included at `tools/Wikiextractor-V2/`

**Important**: Two patches have been applied to WikiExtractor (see `docs/WIKIEXTRACTOR_V2_PATCHES.md`):
- UTF-8 encoding fix for Windows systems
- Class variable initialization fix for non-template mode

### 3. Python Environment

Standard HDLE Premium environment (no additional dependencies required).

---

## Pipeline Usage

### Stage 1: Extract Wikipedia Dump to JSONL

```bash
python scripts/ref_corpora/extract_hewiki_to_jsonl.py \
    --dump ref_corpora/hewiki/raw/hewiki-20260201-pages-articles.xml.bz2 \
    --out_dir ref_corpora/hewiki/jsonl \
    --shard_max_lines 200000 \
    --shard_max_bytes 536870912 \
    --overwrite
```

**Parameters:**
- `--dump`: Path to Wikipedia XML.bz2 dump file (required)
- `--out_dir`: Output directory for JSONL shards (default: `ref_corpora/hewiki/jsonl`)
- `--limit_docs`: Limit extraction to N documents (0 = unlimited, default)
- `--shard_max_lines`: Max lines per shard (default: 200,000)
- `--shard_max_bytes`: Max bytes per shard (default: 512 MB)
- `--overwrite`: Overwrite existing shards (without this, extraction fails if output exists)

**Output:**
- JSONL shards: `hewiki-20260201-pages-articles_articles_00000.jsonl`, `_00001.jsonl`, etc.
- Manifest: `manifests/extract_run_TIMESTAMP.json`

**Example Output:**
```
[2026-02-07 05:13:25][INFO] Starting extraction...
[2026-02-07 05:13:25][INFO] Dump: hewiki-20260201-pages-articles.xml.bz2
[2026-02-07 05:13:25][INFO] Output: ref_corpora/hewiki/jsonl
[2026-02-07 05:13:27][INFO] Extraction complete: 200 documents in 1 shards
[2026-02-07 05:13:27][INFO] Manifest saved: extract_run_20260207T051327Z.json
✓ Total documents: 200
✓ Total shards: 1
✓ Manifest: manifests/extract_run_20260207T051327Z.json
```

### Stage 2: Import JSONL into HDLE Project

```bash
python scripts/ref_corpora/import_ref_jsonl_to_project.py \
    --jsonl_files ref_corpora/hewiki/jsonl/*.jsonl \
    --project_name "Hebrew Wikipedia Baseline" \
    --corpus_name "HEWiki-20260201" \
    --source_key "hewiki" \
    --report_path ref_corpora/hewiki/manifests/import_report.json
```

**Parameters:**
- `--jsonl_files`: JSONL shard file(s) to import (supports glob patterns, required)
- `--project_name`: Project name to create or use (mutually exclusive with --project_id)
- `--project_id`: Existing project ID (mutually exclusive with --project_name)
- `--corpus_name`: Corpus name for imported documents (required)
- `--source_key`: Source identifier for deduplication (e.g., "hewiki", required)
- `--db_path`: Path to HDLE database (defaults to `hdle_premium.db`)
- `--dry_run`: Preview import without committing
- `--commit_every`: Commit frequency for large imports (default: 100)
- `--report_path`: Save import report to JSON file

**Output:**
```
[2026-02-07 05:28:43][INFO] Created project: Hebrew Wikipedia Baseline (ID: 2)
[2026-02-07 05:28:43][INFO] Created corpus: HEWiki-20260201 (ID: 3)
[2026-02-07 05:28:43][INFO] Processing: hewiki_articles_00000.jsonl
[2026-02-07 05:28:43][INFO] Progress: 100 added, 0 duplicates, 0 errors
============================================================
IMPORT COMPLETE
============================================================
Project: Hebrew Wikipedia Baseline (ID: 2)
Corpus: HEWiki-20260201
Duration: 0.49s
------------------------------------------------------------
✓ Added: 200
○ Skipped (duplicate): 0
○ Skipped (empty): 0
✗ Errors: 0
```

---

## Data Formats

### JSONL Record Format

Each line in JSONL shards is a JSON object:

```json
{
  "doc_id": "מתמטיקה",
  "title": "מתמטיקה",
  "url": "https://he.wikipedia.org/wiki?curid=7",
  "language": "he",
  "text": "מָתֵמָטִיקָה היא תחום דעת...",
  "source": "hewiki",
  "dump": "hewiki-20260201-pages-articles.xml.bz2",
  "extracted_at": "2026-02-07T05:13:25Z"
}
```

**Fields:**
- `doc_id`: Wikipedia page title (used for deduplication)
- `title`: Article title
- `url`: Wikipedia URL with curid
- `language`: Language code (e.g., "he")
- `text`: Cleaned article text (with templates expanded)
- `source`: Source identifier ("hewiki")
- `dump`: Original dump filename
- `extracted_at`: Extraction timestamp (ISO 8601 UTC)

### Extraction Manifest Format

```json
{
  "started_at": "2026-02-07T05:13:25Z",
  "ended_at": "2026-02-07T05:13:27Z",
  "duration_ms": 1237,
  "dump_file": "hewiki-20260201-pages-articles.xml.bz2",
  "dump_path": "J:\\...\\hewiki-20260201-pages-articles.xml.bz2",
  "wikiextractor_path": "J:\\...\\WikiExtractor.py",
  "wikiextractor_commit": null,
  "args": {
    "namespaces": "0",
    "limit_docs": 200,
    "shard_max_lines": 200000,
    "shard_max_bytes": 536870912
  },
  "output": {
    "directory": "J:\\...\\hewiki\\jsonl",
    "shards": [
      {
        "filename": "hewiki_articles_00000.jsonl",
        "lines": 200,
        "bytes": 5142371,
        "sha256": "0a22c6ec728593e7dda1b9f480a5228aaadf58504807c5e6c6d0abcc280298b3"
      }
    ],
    "total_docs": 200,
    "total_bytes": 5142171,
    "num_shards": 1
  }
}
```

### Import Report Format

```json
{
  "started_at": "2026-02-07T05:28:43Z",
  "ended_at": "2026-02-07T05:28:43Z",
  "duration_ms": 493,
  "source": {
    "source_key": "hewiki",
    "corpus_name": "HEWiki-20260201",
    "project_name": "Hebrew Wikipedia Baseline",
    "project_id": 2
  },
  "input": {
    "jsonl_files": ["hewiki_articles_00000.jsonl"],
    "total_records": 200
  },
  "results": {
    "added": 200,
    "skipped_duplicate": 0,
    "skipped_empty": 0,
    "errors": 0
  },
  "error_details": []
}
```

---

## Database Schema

### Virtual Document Model

Wikipedia articles are stored as `SourceDocument` records with virtual file paths:

```sql
INSERT INTO source_document (
  corpus_id,
  file_path,      -- "hewiki:מתמטיקה" (source:doc_id format)
  file_name,      -- "מתמטיקה"
  file_ext,       -- ".wiki"
  file_size_bytes,-- Length of text in bytes
  sha256,         -- SHA256("hewiki:מתמטיקה") for deduplication
  status          -- "imported"
) VALUES (...);

INSERT INTO document_text (
  doc_id,
  raw_text,       -- Full Wikipedia article text
  ocr_used        -- 0 (not applicable)
) VALUES (...);
```

**Deduplication Strategy:**
- SHA256 hash = `SHA256(source_key:doc_id)` (e.g., `SHA256("hewiki:מתמטיקה")`)
- Unique constraint: `UNIQUE(corpus_id, sha256)`
- Re-importing same JSONL → all duplicates skipped

---

## Idempotency

Both stages are **fully idempotent**:

### Extraction Idempotency

- Requires `--overwrite` flag to replace existing shards
- Without `--overwrite`, fails if output directory contains existing shards
- SHA256 verification ensures data integrity

### Import Idempotency

- Uses `SHA256(source_key:doc_id)` for deduplication
- Re-importing same JSONL → 0 added, N skipped duplicates
- Safe to re-run without data duplication

**Example:**
```bash
# First import
$ python scripts/ref_corpora/import_ref_jsonl_to_project.py ...
✓ Added: 200

# Second import (same JSONL)
$ python scripts/ref_corpora/import_ref_jsonl_to_project.py ...
✓ Added: 0
○ Skipped (duplicate): 200  ← All duplicates detected
```

---

## Workflow Examples

### Full Pipeline (Extract + Import)

```bash
# 1. Extract Wikipedia dump to JSONL
python scripts/ref_corpora/extract_hewiki_to_jsonl.py \
    --dump ref_corpora/hewiki/raw/hewiki-20260201-pages-articles.xml.bz2 \
    --out_dir ref_corpora/hewiki/jsonl \
    --overwrite

# 2. Import JSONL into new project
python scripts/ref_corpora/import_ref_jsonl_to_project.py \
    --jsonl_files ref_corpora/hewiki/jsonl/*.jsonl \
    --project_name "Hebrew Wikipedia 2026-02" \
    --corpus_name "HEWiki-20260201" \
    --source_key "hewiki" \
    --report_path ref_corpora/hewiki/manifests/import_report_full.json

# 3. Verify import
sqlite3 hdle_premium.db "
  SELECT COUNT(*) FROM source_document
  WHERE corpus_id = (
    SELECT corpus_id FROM source_corpus WHERE name = 'HEWiki-20260201'
  );
"
```

### Test Subset (200 docs)

```bash
# Extract limited subset for testing
python scripts/ref_corpora/extract_hewiki_to_jsonl.py \
    --dump ref_corpora/hewiki/raw/hewiki-20260201-pages-articles.xml.bz2 \
    --out_dir ref_corpora/hewiki/jsonl_test \
    --limit_docs 200 \
    --overwrite

# Dry-run import to preview
python scripts/ref_corpora/import_ref_jsonl_to_project.py \
    --jsonl_files ref_corpora/hewiki/jsonl_test/*.jsonl \
    --project_name "HEWiki Test" \
    --corpus_name "Test-200" \
    --source_key "hewiki" \
    --dry_run

# Actual import
python scripts/ref_corpora/import_ref_jsonl_to_project.py \
    --jsonl_files ref_corpora/hewiki/jsonl_test/*.jsonl \
    --project_name "HEWiki Test" \
    --corpus_name "Test-200" \
    --source_key "hewiki"
```

### Import into Existing Project

```bash
# Get project ID
sqlite3 hdle_premium.db "SELECT project_id, name FROM dict_project;"

# Import using project ID
python scripts/ref_corpora/import_ref_jsonl_to_project.py \
    --jsonl_files ref_corpora/hewiki/jsonl/*.jsonl \
    --project_id 5 \
    --corpus_name "HEWiki-Additional" \
    --source_key "hewiki"
```

---

## Troubleshooting

### Extraction Issues

**Problem**: `UnicodeDecodeError: 'charmap' codec can't decode...`
- **Cause**: WikiExtractor not using UTF-8 encoding
- **Fix**: Verify `docs/WIKIEXTRACTOR_V2_PATCHES.md` patches are applied

**Problem**: `TypeError: argument of type 'NoneType' is not iterable`
- **Cause**: WikiExtractor class variables not initialized when `--templates` not provided
- **Fix**: Apply PATCH-02 from `docs/WIKIEXTRACTOR_V2_PATCHES.md`

**Problem**: Extraction very slow (>1 hour for 200 docs)
- **Cause**: Large dump file with template expansion overhead
- **Tip**: Use `--limit_docs 200` for testing first
- **Tip**: Extract without templates for faster processing (less clean text)

### Import Issues

**Problem**: `RuntimeError: DBService not initialized`
- **Cause**: Database not initialized before import
- **Fix**: Automatic - script initializes with default `hdle_premium.db`
- **Tip**: Use `--db_path` to specify custom database

**Problem**: All records skipped as duplicates
- **Status**: This is **expected behavior** on re-import!
- **Verification**: Check import report shows `skipped_duplicate: N`
- **Explanation**: SHA256 deduplication working correctly

**Problem**: Hebrew text garbled in database
- **Cause**: Incorrect encoding when reading JSONL
- **Fix**: Verify files are UTF-8 encoded (extraction script uses `ensure_ascii=False`)

### Performance Issues

**Problem**: Import too slow (< 100 docs/sec)
- **Tip**: Increase `--commit_every` to 500 or 1000 for large imports
- **Tip**: Use SSD storage for database

**Problem**: Out of memory during extraction
- **Cause**: Very large Wikipedia articles or complex templates
- **Tip**: Reduce `--shard_max_lines` to 100,000
- **Tip**: Use `--limit_docs` to process in batches

---

## Verification Commands

### Check Extraction Output

```bash
# Count JSONL lines (should match manifest total_docs)
wc -l ref_corpora/hewiki/jsonl/*.jsonl

# Verify SHA256 of first shard
sha256sum ref_corpora/hewiki/jsonl/hewiki_articles_00000.jsonl

# Sample first 5 articles
head -n 5 ref_corpora/hewiki/jsonl/hewiki_articles_00000.jsonl | python -m json.tool

# Check manifest
cat ref_corpora/hewiki/manifests/extract_run_*.json | python -m json.tool
```

### Check Import Results

```bash
# Count imported documents
sqlite3 hdle_premium.db "
  SELECT
    c.name AS corpus,
    COUNT(d.doc_id) AS doc_count
  FROM source_corpus c
  JOIN source_document d ON c.corpus_id = d.corpus_id
  GROUP BY c.corpus_id;
"

# Sample imported documents
sqlite3 hdle_premium.db "
  SELECT
    file_name,
    file_path,
    file_size_bytes,
    SUBSTR(sha256, 1, 16) AS sha_prefix
  FROM source_document
  WHERE corpus_id = 3
  LIMIT 10;
"

# Check document text
sqlite3 hdle_premium.db "
  SELECT
    sd.file_name,
    LENGTH(dt.raw_text) AS text_length,
    SUBSTR(dt.raw_text, 1, 100) AS text_preview
  FROM source_document sd
  JOIN document_text dt ON sd.doc_id = dt.doc_id
  WHERE sd.corpus_id = 3
  LIMIT 3;
"

# Verify no duplicates (all sha256 unique within corpus)
sqlite3 hdle_premium.db "
  SELECT
    corpus_id,
    COUNT(*) AS total,
    COUNT(DISTINCT sha256) AS unique_hashes
  FROM source_document
  GROUP BY corpus_id;
"
```

---

## Performance Benchmarks

Based on test runs with `hewiki-20260201-pages-articles.xml.bz2`:

### Extraction Performance
- **Test**: 200 articles (limited subset)
- **Duration**: 1.2 seconds
- **Rate**: ~167 articles/sec
- **Output**: 1 shard (5.1 MB, 200 lines)
- **Manifest**: 1.1 KB JSON

### Import Performance
- **Test**: 200 articles (1 JSONL shard)
- **Duration**: 0.49 seconds
- **Rate**: ~406 docs/sec
- **Database**: SQLite with WAL mode
- **Storage**: ~5.2 MB (documents + text)

### Full Pipeline Estimate
- **1M articles**: ~90 minutes extraction + ~40 minutes import
- **Shards**: ~5 shards (200K lines each)
- **Storage**: ~26 GB JSONL + ~26 GB database

---

## Future Enhancements

Potential improvements (not yet implemented):

1. **Parallel Extraction**: Use WikiExtractor's multiprocessing mode for faster extraction
2. **Sentence Splitting**: Pre-split articles into sentences during import for NLP readiness
3. **Multiple Languages**: Extend to support enwiki, frwiki, etc. with language detection
4. **Incremental Updates**: Import only new articles from monthly Wikipedia dumps
5. **Compression**: GZIP JSONL shards to save disk space
6. **Statistics**: Extract metadata (word count, link count, categories) during extraction
7. **Quality Filtering**: Skip stub articles or redirect pages

---

## References

- **Wikipedia Dumps**: https://dumps.wikimedia.org/hewiki/
- **WikiExtractor-V2**: https://github.com/adrianrb469/Wikiextractor-V2
- **WikiExtractor Patches**: `docs/WIKIEXTRACTOR_V2_PATCHES.md`
- **HDLE Database Schema**: `app/infra/migrations/001_init.sql`

---

## Credits

Pipeline developed for HDLE Premium (Hebrew Dictionary Learning Environment).

**Co-Authored-By**: Claude Sonnet 4.5 <noreply@anthropic.com>
