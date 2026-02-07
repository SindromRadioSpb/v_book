# WikiExtractor-V2 Patches

This document records patches applied to `tools/Wikiextractor-V2/` to fix bugs encountered during Hebrew Wikipedia extraction.

**Source**: WikiExtractor-V2 is an external tool located in `tools/Wikiextractor-V2/` (not tracked by git).

---

## PATCH 1: UTF-8 Encoding for Config Files (2026-02-07)

**Issue**: `UnicodeDecodeError: 'charmap' codec can't decode byte 0x98` when running on Windows systems with cp1251/cp1252 default encoding.

**Root Cause**: WikiExtractor's internal config file reads (discard_templates, ignore_templates, discard_sections) used `open(..., "r")` without `encoding='utf-8'`, causing Python to use system default encoding (cp1251 on Russian Windows).

**Fix**: Added `encoding='utf-8'` to 3 file open() calls in `WikiExtractor.py`:

### File: `tools/Wikiextractor-V2/wikiextractor/WikiExtractor.py`

**Line 442** (discard_templates):
```python
# BEFORE:
with open( path_to_discard_templates , "r") as f:

# AFTER:
with open( path_to_discard_templates , "r", encoding='utf-8') as f:
```

**Line 468** (ignore_templates):
```python
# BEFORE:
with open( path_to_ignore_templates , "r") as f:

# AFTER:
with open( path_to_ignore_templates , "r", encoding='utf-8') as f:
```

**Line 496** (discard_sections):
```python
# BEFORE:
with open( path_to_discard_sections , "r") as f:

# AFTER:
with open( path_to_discard_sections , "r", encoding='utf-8') as f:
```

---

## PATCH 2: Initialize Class Variables When expand_templates=False (2026-02-07)

**Issue**: `TypeError: argument of type 'NoneType' is not iterable` at line 1433 in `extract/extract.py`:
```python
elif(title.lower() in self.ignoreTemplates):
```

**Root Cause**: The Extractor class variables `discardTemplates` and `ignoreTemplates` are initialized to `set()` ONLY inside the `if expand_templates:` block in `preprocess_dump()` (lines 414-487). When WikiExtractor is called without template expansion (`--templates` not provided), `expand_templates=False`, the initialization is skipped, and these variables remain `None`.

**Fix**: Added `else` clause after the `if expand_templates:` block to initialize class variables when template expansion is disabled.

### File: `tools/Wikiextractor-V2/wikiextractor/WikiExtractor.py`

**After line 487** (end of ignoreTemplates initialization):
```python
        else:
            Extractor.ignoreTemplates = set()
    else:
        # expand_templates is False - initialize to empty sets
        Extractor.discardTemplates = set()
        Extractor.ignoreTemplates = set()
```

**Context**: This ensures that even when `expand_templates=False`, the Extractor class variables are properly initialized to empty sets instead of remaining `None`.

---

## Application

These patches are required for:
1. Running WikiExtractor on Windows systems with non-UTF-8 system encodings
2. Running WikiExtractor in generator mode (`--generator`) without template expansion (`--templates` not provided)

Both scenarios apply to our Hebrew Wikipedia extraction pipeline (`scripts/ref_corpora/extract_hewiki_to_jsonl.py`).

---

## Verification

After applying patches, extraction test passed:
```bash
python scripts/ref_corpora/extract_hewiki_to_jsonl.py \
    --dump "J:\Project_Vibe\V_book\ref_corpora\hewiki\raw\hewiki-20260201-pages-articles.xml.bz2" \
    --out_dir "J:\Project_Vibe\V_book\ref_corpora\hewiki\jsonl" \
    --limit_docs 200 \
    --overwrite
```

**Result**: Successfully extracted 200 Hebrew Wikipedia articles to JSONL with manifest and SHA256 verification.
