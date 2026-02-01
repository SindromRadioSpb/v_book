# M5 Term Extraction - Fixes Applied

**Date:** 2026-02-01
**Status:** ✅ ALL TESTS PASSING (M1-M5)

## Issues Fixed

### 1. AttributeError: 'DocumentSentence' has no attribute 'tokens_json'
**Problem:**
Term extraction service tried to access `sent.tokens_json` which doesn't exist in the DocumentSentence model. Tokens are not stored in the database.

**Fix:**
- Added NLP engine to TermExtractionService
- Re-parse sentences with NLP engine during term extraction
- Convert NLP tokens to dict format for n-gram extractor

**Files Modified:**
- `app/services/term_extraction_service.py` (lines 1-35, 159-215)

---

### 2. TypeError: 'he_canonical' is an invalid keyword argument for Ngram
**Problem:**
Migration 002 added new columns to ngram table, but ORM models weren't updated.

**Fix:**
Updated ORM models to match migration schema:
- `Ngram`: Added `he_canonical`, `lemma_phrase`, `source_kind` columns
- `NgramProjectStat`: Added `llr_cache`, `dice_cache`, `tfidf`, `weirdness` columns
- `DictProject`: Added `is_general_corpus`, `general_corpus_id` columns

**Files Modified:**
- `app/infra/sa_models.py` (lines 47-75, 261-285, 308-327)

---

### 3. Canonicalization Over-Stripping
**Problem:**
`strip_prefixes()` was too aggressive, stripping "ב" from "בית" → "ית" even though "בית" is a real word.

**Fix:**
Modified `strip_prefixes()` to only strip if at least 3 characters remain after stripping.

**Files Modified:**
- `app/domain/term_extraction/canonicalizer.py` (lines 46-73)

---

### 4. NLP Engine Mismatch
**Problem:**
Documents processed with Mock engine, but term extraction used Stanza, causing inconsistent lemmas.

**Fix:**
- ProcessService now updates `project.nlp_engine` field when processing
- TermExtractionService reads `project.nlp_engine` to use same engine
- Fixed case-insensitive comparison ("mock" vs "Mock")

**Files Modified:**
- `app/services/process_service.py` (lines 106-120)
- `app/services/term_extraction_service.py` (line 189)

---

### 5. Test Formatting Error
**Problem:**
Invalid f-string format specifier with conditional inside.

**Fix:**
Pre-compute formatted string before using in f-string.

**Files Modified:**
- `test_m5.py` (lines 104-110)

---

## Test Results

```
✅ M1 (Database initialization) - PASSED
✅ M2 (Document ingestion) - PASSED
✅ M3 (NLP pipeline) - PASSED
✅ M4 (Delta statistics + Project deletion) - PASSED
✅ M5 (Term extraction + clustering) - PASSED
```

### M5 Test Output:
- N-grams extracted: 3
- Clusters created: 2
- "בית ספר" cluster found with canonical key "בית_ספר"
- 2 surface variants: "לבית הספר", "בית הספר"
- Determinism verified ✅

---

## Files Changed (Total: 6)

**Modified:**
1. `app/services/term_extraction_service.py` - Re-parse sentences with NLP
2. `app/infra/sa_models.py` - Updated ORM models for M5 schema
3. `app/domain/term_extraction/canonicalizer.py` - Fixed over-stripping
4. `app/services/process_service.py` - Record NLP engine in project
5. `test_m5.py` - Fixed f-string formatting
6. `M5_FIXES.md` - This file

---

## Production Ready

✅ M5 Base + M5.1 (Clustering) fully functional
✅ All integration tests passing
✅ Hebrew term canonicalization working correctly
✅ Deterministic extraction (re-runs produce same results)
✅ No regressions in M1-M4

**Next:** Commit changes and update M5_PLUS_COMPLETE.md
