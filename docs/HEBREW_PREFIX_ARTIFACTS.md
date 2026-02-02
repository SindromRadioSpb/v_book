# Hebrew Prefix Artifacts: Standalone Article "ה" with Space

## Overview

This document explains the root cause, impact, and solution for Hebrew definite article ("ה") appearing as a standalone token with a space in extracted terms (e.g., "ה תנועה" instead of "התנועה").

## The Issue

### Symptom
Users see terms in the Terms table that contain standalone single-letter Hebrew prefixes separated by spaces:
- "ה ספר" (should be "הספר" - "the book")
- "ה תנועה" (should be "התנועה" - "the movement")
- "ב בית" (should be "בבית" - "in house")

### Impact
- Pollutes extracted term clusters with malformed entries
- Confuses users who expect normalized Hebrew text
- Reduces quality of term frequency analysis
- Makes concordance search less effective (searches for "הספר" won't find "ה ספר")

## Root Cause

The standalone space is introduced through a **multi-stage pipeline issue**:

### 1. Stanza Tokenization (Primary Cause)

**File**: `app/infra/nlp_engines/stanza_engine.py`
**Function**: `StanzaEngine.process()` (line 76-122)

Stanza's Hebrew tokenizer sometimes separates articles/prefixes from their base words:
- Input sentence: "התנועה החדשה" or "הספר הזה"
- Stanza tokens: `["ה", "תנועה", "ה", "חדשה"]` OR `["ה", "ספר", "ה", "זה"]`

This is **linguistically correct** for Stanza's analysis purposes (the article is a separate morpheme), but causes issues when we join tokens back into surface forms.

### 2. Token Joining with Spaces

**File**: `app/domain/term_extraction/ngram_extractor.py`
**Critical line**: Line 76

```python
surface_tokens = [tok['text'] for tok in window]
surface_text = ' '.join(surface_tokens)  # ← SPACE INTRODUCED HERE
```

When n-grams are extracted, tokens are joined with spaces:
- Token window: `[{"text": "ה", ...}, {"text": "ספר", ...}]`
- Result: `"ה ספר"` ← space between article and noun

**File**: `app/domain/term_extraction/np_extractor.py`
**Critical line**: Line 122

```python
surface_tokens = [tok['text'] for tok in span_tokens]
surface_text = ' '.join(surface_tokens)  # ← SAME ISSUE
```

NP chunks have the same problem.

### 3. Database Storage

**File**: `app/infra/sa_models.py`

The malformed surface text is stored as-is in:
- `Ngram.surface_text` (line 271-292)
- `TermCluster.representative_he` (line 487-517)

### 4. Partial Mitigation (Current State)

**File**: `app/domain/term_extraction/canonicalizer.py`

Two functions attempt to handle this:

**Function**: `canonicalize_hebrew_term()` (line 78-147)
- Removes standalone prefixes for the **canonical key** (used for clustering)
- Does NOT fix `surface_text` (what users see)

**Function**: `has_standalone_function_tokens()` (line 171-197)
- Detects terms with standalone prefixes: `"ה ספר"` → `True`

**Function**: `choose_representative_term()` (line 200-239)
- Tries to filter out terms with standalone tokens when choosing cluster representative
- **BUT**: Has fallback (line 231) - if ALL terms in cluster have standalone prefixes, it shows one anyway

```python
# Line 223-231
valid_terms = [
    t for t in terms
    if not has_standalone_function_tokens(t['surface_text'])
]

# FALLBACK: If all invalid, show anyway
candidates = valid_terms if valid_terms else terms
```

## Why the Fallback Fails

If Stanza **consistently** tokenizes a word with its article as two tokens, then:
- All n-gram variants for that word will have "ה " in them
- `valid_terms` will be empty
- Fallback kicks in → user sees "ה ספר"

## Edge Cases We Must Preserve

Not all standalone "ה" should be merged. Legitimate cases:

### 1. Enumerations
```
סעיף ה.    (section ה.)
סעיף ה:    (section ה:)
סעיף ה)    (section ה))
```
Here "ה" is a letter used for enumeration (like "e." in English).

### 2. Variables in Math/Technical Contexts
```
ה = 5      (h = 5)
ה = k      (h = k)
```
Here "ה" is a variable name.

### 3. Article Already Attached
```
הספר       (already attached, no space)
בבית       (already attached, no space)
```
Should not be modified.

### 4. Genuine Separation by Punctuation
```
ספר, ה...  (book, the...)
```
If punctuation separates the article, it may be intentional.

## Solution Strategy

### Approach: Post-Tokenization Normalization

Merge standalone article tokens **before** joining into n-grams/NP chunks.

**Where**: New function in `app/domain/hebrew_utils.py`

**Function**: `merge_standalone_articles(tokens: List[dict]) -> List[dict]`

**Logic**:
1. Iterate through token list
2. When we find standalone prefix token (len=1, in HEBREW_PREFIXES):
   - Check next token context
   - If next token is NOT punctuation/equals/etc. → MERGE
   - If next token IS punctuation/equals → KEEP SEPARATE
3. Return modified token list

**Integration points**:
- `app/domain/term_extraction/ngram_extractor.py` (before line 76)
- `app/domain/term_extraction/np_extractor.py` (before line 122)

### Minimal Diff

Only two files need modification:
1. `hebrew_utils.py` - add new function
2. `ngram_extractor.py` - call function before joining
3. `np_extractor.py` - call function before joining

No changes to:
- Database schema
- Tokenization engines
- Canonicalization logic (already handles this for canonical_key)

## Verification

### Automated Tests
See `test_hebrew_article_merge.py`:
- Positive merge cases
- Negative preservation cases
- Integration test with term extraction

### Manual Verification
1. Process document with text: "הספר הזה" or "בית הספר"
2. Extract terms
3. Check Terms table
4. Verify: No "ה <word>" entries (except legitimate enumerations/variables)

## Database Cleanup (If Needed)

If existing databases have stored "ה " artifacts:

### Option 1: Re-extract Terms
```bash
# Delete old terms
DELETE FROM ngram WHERE project_id = ?;
DELETE FROM term_cluster WHERE project_id = ?;

# Re-run extraction (new code will merge correctly)
```

### Option 2: Migration Script
Create migration to:
1. Identify all `Ngram` rows with standalone prefixes in `surface_text`
2. Merge tokens in `surface_text` column
3. Update `TermCluster.representative_he` if needed
4. Rebuild FTS index if concordance search affected

**Recommendation**: Re-extraction is cleaner and safer.

## Related Files

| Component | File | Line |
|-----------|------|------|
| **Tokenization** | `app/infra/nlp_engines/stanza_engine.py` | 76-122 |
| **N-gram extraction** | `app/domain/term_extraction/ngram_extractor.py` | 76 |
| **NP extraction** | `app/domain/term_extraction/np_extractor.py` | 122 |
| **Canonicalization** | `app/domain/term_extraction/canonicalizer.py` | 171-239 |
| **Hebrew utils** | `app/domain/hebrew_utils.py` | (new function) |
| **DB Models** | `app/infra/sa_models.py` | 271-292, 487-517 |

## Status

- **Root cause**: Identified ✅
- **Solution**: Designed ✅
- **Implementation**: In progress
- **Tests**: Pending
- **Documentation**: This file ✅

---

**Last updated**: 2026-02-02
**Related issues**: Terms table showing "ה ספר", "ב בית" artifacts
**Solution**: Post-tokenization normalization before n-gram/NP extraction
