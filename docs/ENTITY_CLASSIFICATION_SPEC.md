# Entity Classification Specification

**Version**: 1.0
**Date**: 2026-02-11
**Status**: Approved

## Purpose

Classify lemmas and term clusters into distinct entity types to enable intelligent noise filtering in UI, export, and analysis workflows. Every string gets a deterministic classification with an explainable reason code if marked as noise.

---

## Pipeline Map

### Lemma Creation Path

```
Raw text (file import)
  ↓
app/domain/preprocessing.py:8-31 (preprocess_text)
  - Strip nikud/cantillation (Unicode 0591-05C7)
  - Normalize quotes/whitespace
  ↓
app/domain/sentence_splitter.py:108-119 (split_into_sentences)
  ↓
DocumentSentence rows (DB)
  ↓
app/infra/nlp_engines/stanza_engine.py:76-118 (Stanza pipeline)
  - processors='tokenize,pos,lemma'
  - Returns Token(text, lemma, pos, morph)
  ↓
app/services/process_service.py:266-309 (_create_or_get_lemmas)
  - NO FILTERING (before this patch)
  - Every unique lemma_text → lemma row
  - POS: First encountered POS wins
  ↓
lemma table (app/infra/sa_models.py:218-231)
  - UNIQUE(project_id, lemma_text)
  ↓
app/ui/dictionary_view.py:143-169 (UI display)
  - POS filter dropdown only
  - NO noise exclusion (before this patch)
```

### Term Cluster Creation Path

```
app/services/term_extraction_service.py:238 (_extract_ngrams)
  ↓
app/domain/term_extraction/ngram_extractor.py:39
  - POS pattern filtering (NOUN+NOUN, etc.)
  ↓
ngram table (app/infra/sa_models.py:271-292)
  ↓
app/services/term_extraction_service.py:527 (_cluster_terms)
  - Groups by he_canonical key
  - NO noise filtering (before this patch)
  ↓
term_cluster table (app/infra/sa_models.py:487-527)
  ↓
app/ui/terms_view.py:91-127 (UI display)
  - Source/Preset/Search filters only
  - NO noise exclusion (before this patch)
```

### Export Paths

```
app/ui/export_view.py (user triggers export)
  ↓
app/services/export_service.py
  - export_xlsx() (line 273): TM + Lemmas (limit 100!) + Stats
  - export_tm_csv() (line 35): TM entries only
  - export_tm_json() (line 126): TM entries only
  - export_tbx() (line 542): Term clusters (approved_only option)
  - export_tmx() (line 629): TM + pinned translations
  - NO noise filtering anywhere (before this patch)
  ↓
CSV/XLSX/JSON/TBX/TMX files
```

**Project Exchange** (.hdleproj):
- `app/services/project_exchange/export_engine.py`
- Exports ALL data (no filtering)
- Classification columns transferred as regular columns

---

## Classification Taxonomy

### Entity Classes (9 types)

| Class | Definition | Examples | Default is_noise |
|-------|------------|----------|------------------|
| `WORD_HE` | Pure Hebrew letters + geresh (`'`) / gershayim (`"`) / maqaf (`-`) as word-internal markers | `שלום`, `כוח`, `ק"מ`, `ת"א` | **No** |
| `WORD_LATIN` | Pure Latin letters (A-Z, a-z) | `hello`, `force`, `cos`, `energy` | **No** |
| `NUMBER` | Pure numeric: integers, decimals, fractions | `42`, `0.1`, `3.14`, `1/2` | **Yes** |
| `QUANTITY_UNIT` | Number + unit word (detected as separate tokens or fused) | `1.2kg`, `10kN`, `0.6 מטר`, `5 ק"מ` | **Yes** |
| `MIXED_ALPHA_NUM` | Letters mixed with digits (not cleanly separated) | `0.5W1`, `B-40kg`, `A1`, `3x` | **Yes** |
| `MATH_EXPR` | Math operators, Greek letters, superscripts, formulas | `*ΔL^2/2`, `∑F`, `cos30°)`, `μ_k`, `c·h^2/2` | **Yes** |
| `SYMBOL` | Single or few symbol characters (not part of word/number) | `μ`, `θ`, `–`, `§`, `©` | **Yes** |
| `PUNCT` | Punctuation marks only | `!`, `%`, `(`, `)`, `,`, `.`, `'`, `"` | **Yes** |
| `OTHER` | Unclassified / mixed garbage | Rare edge cases | **Yes** |

### Noise Reason Codes (8 codes)

| Reason Code | Trigger | Examples |
|-------------|---------|----------|
| `NOISE_PUNCT_ONLY` | `entity_class == PUNCT` | `!`, `%`, `(` |
| `NOISE_SYMBOL_ONLY` | `entity_class == SYMBOL` | `μ`, `–`, `§` |
| `NOISE_NUMERIC_ONLY` | `entity_class == NUMBER or QUANTITY_UNIT` | `0.1`, `1.2kg`, `10kN` |
| `NOISE_MATH_EXPR` | `entity_class == MATH_EXPR` | `*ΔL^2/2`, `∑F`, `cos30°)` |
| `NOISE_MIXED_GARBAGE` | `entity_class == MIXED_ALPHA_NUM or OTHER` | `0.5W1`, `B-40kg` |
| `NOISE_TOO_SHORT` | len(stripped) <= 1 and not a meaningful letter | Single punctuation/symbol | `!`, `%` |
| `NOISE_RATIO_NON_LETTER_HIGH` | For multi-char strings: (punct + symbol + digit) / total > 0.6 | `*ΔL^2/2` (high non-letter ratio) |
| `NOISE_LEADING_TRAILING_PUNCT_HEAVY` | Starts or ends with 2+ punctuation chars | `))x`, `--abc` |

**Note**: `WORD_HE` and `WORD_LATIN` have `is_noise=False` and `noise_reason=None` by default.

---

## Classification Algorithm (Pseudocode)

### For Single Lemma (`classify_text`)

```python
1. norm_text = normalize_text(raw)  # NFKC, unify dashes/quotes, strip whitespace
2. if norm_text is empty: return PUNCT / NOISE_PUNCT_ONLY

3. Compute character-class ratios:
   - he_ratio = count(Hebrew Unicode 0590-05FF) / len(norm_text)
   - latin_ratio = count(A-Z, a-z) / len(norm_text)
   - digit_ratio = count(0-9) / len(norm_text)
   - punct_ratio = count(punctuation) / len(norm_text)
   - symbol_ratio = count(math/Greek symbols) / len(norm_text)

4. Decision tree (in order):
   a. If punct_ratio == 1.0 → PUNCT
   b. If digit_ratio >= 0.9 and only digits/decimal/fraction chars → NUMBER
   c. If contains Greek letters (Α-Ω, α-ω) or math operators (∑, Δ, ∫, ·, ^) → MATH_EXPR
   d. If len <= 2 and symbol_ratio > 0.5 → SYMBOL
   e. If pattern: digits + whitespace? + unit_word (Hebrew/Latin) → QUANTITY_UNIT
   f. If he_ratio >= 0.9 and only Hebrew + geresh/gershayim/maqaf → WORD_HE
   g. If latin_ratio >= 0.9 → WORD_LATIN
   h. If (latin_ratio + he_ratio) > 0.3 and digit_ratio > 0.1 → MIXED_ALPHA_NUM
   i. Else → OTHER

5. Apply noise mapping:
   - PUNCT → is_noise=True, noise_reason=NOISE_PUNCT_ONLY
   - SYMBOL → is_noise=True, noise_reason=NOISE_SYMBOL_ONLY
   - NUMBER, QUANTITY_UNIT → is_noise=True, noise_reason=NOISE_NUMERIC_ONLY
   - MATH_EXPR → is_noise=True, noise_reason=NOISE_MATH_EXPR
   - MIXED_ALPHA_NUM, OTHER → is_noise=True, noise_reason=NOISE_MIXED_GARBAGE
   - WORD_HE, WORD_LATIN → is_noise=False, noise_reason=None

6. Additional heuristics (override if needed):
   - If len(norm_text.strip()) <= 1 and not Hebrew/Latin letter → NOISE_TOO_SHORT
   - If (punct + symbol + digit) / total > 0.6 → NOISE_RATIO_NON_LETTER_HIGH
   - If norm_text starts/ends with 2+ punct chars → NOISE_LEADING_TRAILING_PUNCT_HEAVY
```

### For Phrase (`classify_phrase`)

```python
1. Split norm_text on whitespace → tokens
2. Classify each token independently → token_classes[]
3. Aggregate:
   - noise_count = count(token where token.is_noise == True)
   - If noise_count / len(tokens) >= 0.5 → phrase is_noise=True
   - Dominant noise reason = most frequent noise_reason from noise tokens
4. Special case: First token is NUMBER, remaining are WORD_HE → QUANTITY_UNIT phrase (still noise)
5. Return ClassificationResult(entity_class=dominant, is_noise=aggregate, noise_reason=dominant_reason, norm_text)
```

---

## Golden Test Vectors

### Lemma Test Cases (Single Tokens)

| Input | entity_class | is_noise | noise_reason |
|-------|--------------|----------|--------------|
| `!` | PUNCT | True | NOISE_PUNCT_ONLY |
| `%` | PUNCT | True | NOISE_PUNCT_ONLY |
| `'` | PUNCT | True | NOISE_PUNCT_ONLY |
| `(` | PUNCT | True | NOISE_PUNCT_ONLY |
| `)` | PUNCT | True | NOISE_PUNCT_ONLY |
| `*ΔL^2/2` | MATH_EXPR | True | NOISE_MATH_EXPR |
| `/שנייה` | OTHER | True | NOISE_LEADING_TRAILING_PUNCT_HEAVY |
| `0.1` | NUMBER | True | NOISE_NUMERIC_ONLY |
| `0.5W1` | MIXED_ALPHA_NUM | True | NOISE_MIXED_GARBAGE |
| `0.5_m` | MIXED_ALPHA_NUM | True | NOISE_MIXED_GARBAGE |
| `1.2kg` | QUANTITY_UNIT | True | NOISE_NUMERIC_ONLY |
| `B-40kg` | MIXED_ALPHA_NUM | True | NOISE_MIXED_GARBAGE |
| `V_A)_x` | MATH_EXPR | True | NOISE_MATH_EXPR |
| `cos30°)` | MATH_EXPR | True | NOISE_MATH_EXPR |
| `c·h^2/2` | MATH_EXPR | True | NOISE_MATH_EXPR |
| `μ` | SYMBOL | True | NOISE_SYMBOL_ONLY |
| `μ_k` | MATH_EXPR | True | NOISE_MATH_EXPR |
| `–` | SYMBOL | True | NOISE_SYMBOL_ONLY |
| `∑F` | MATH_EXPR | True | NOISE_MATH_EXPR |
| `שלום` | WORD_HE | False | None |
| `כוח` | WORD_HE | False | None |
| `אנרגיה` | WORD_HE | False | None |
| `ק"מ` | WORD_HE | False | None (gershayim part of Hebrew abbreviation) |
| `hello` | WORD_LATIN | False | None |
| `force` | WORD_LATIN | False | None |
| `energy` | WORD_LATIN | False | None |

### Phrase Test Cases (Term Clusters)

| Input | entity_class | is_noise | noise_reason |
|-------|--------------|----------|--------------|
| `0.2 BD` | MIXED_ALPHA_NUM | True | NOISE_MIXED_GARBAGE |
| `0.25 הערה` | QUANTITY_UNIT | True | NOISE_NUMERIC_ONLY |
| `0.25 מ'` | QUANTITY_UNIT | True | NOISE_NUMERIC_ONLY |
| `0.6 מטר` | QUANTITY_UNIT | True | NOISE_NUMERIC_ONLY |
| `0.8 ק"מ` | QUANTITY_UNIT | True | NOISE_NUMERIC_ONLY |
| `10 m/sec א` | MIXED_ALPHA_NUM | True | NOISE_MIXED_GARBAGE |
| `10 מ'` | QUANTITY_UNIT | True | NOISE_NUMERIC_ONLY |
| `10kN שאלה` | MIXED_ALPHA_NUM | True | NOISE_MIXED_GARBAGE |
| `10kN שאלה 6.8` | MIXED_ALPHA_NUM | True | NOISE_MIXED_GARBAGE |
| `θ שווה 40` | MIXED (SYMBOL+WORD_HE+NUMBER) | True | NOISE_MIXED_GARBAGE |
| `בית ספר` | WORD_HE | False | None (valid Hebrew phrase) |
| `כוח חיכוך` | WORD_HE | False | None |

---

## Normalization Rules

Implemented in `normalize_text()`:

1. **Unicode normalization**: NFKC (compatibility decomposition + canonical composition)
2. **Dash unification**: Em dash (`—`), en dash (`–`), minus (`−`) → ASCII hyphen (`-`)
3. **Quote unification**: Curly quotes (`'`, `'`, `"`, `"`) → ASCII (`'`, `"`)
4. **Whitespace**: Multiple spaces/tabs/newlines → single space, strip leading/trailing
5. **Preserve**: Hebrew letters (0590-05FF), Latin (A-Z, a-z), digits (0-9), geresh/gershayim as Hebrew markers

**Note**: Nikud and cantillation are already stripped in `preprocess_text()` (preprocessing.py:8-31) before text reaches the classifier.

---

## Implementation Notes

### Performance Requirements

- Classification must be **< 1ms per call** (pure regex/character iteration)
- Backfill 300k lemmas: target < 10 minutes total
- No external dependencies beyond Python stdlib (`re`, `unicodedata`)

### Backward Compatibility

- All new DB columns are **nullable with defaults**
- `is_noise` defaults to `0` (not noise)
- Unclassified rows (entity_class=NULL) treated as non-noise until backfill runs
- UI filters use `(is_noise = 0 OR is_noise IS NULL)` to handle transition period

### Hebrew-Specific Handling

- **Geresh** (`'`, U+05F3): Used in Hebrew abbreviations like `ק"מ`, `ת"א`
- **Gershayim** (`"`, U+05F4): Used similarly
- **Maqaf** (`-`, U+05BE): Hebrew hyphen
- These are considered **part of Hebrew words**, not punctuation, when adjacent to Hebrew letters

### Edge Cases

1. **Empty strings**: After normalization → PUNCT, NOISE_PUNCT_ONLY
2. **Whitespace-only**: Same as empty
3. **Single character**: Classify normally (could be WORD_HE like `א` or PUNCT like `!`)
4. **Mixed scripts**: If contains Cyrillic/Arabic/etc. + Hebrew/Latin → OTHER
5. **URLs/emails**: Typically classified as MIXED_ALPHA_NUM or OTHER (noise)

---

## References

- **DB models**: `app/infra/sa_models.py` lines 218-231 (Lemma), 487-527 (TermCluster)
- **Migration**: `app/infra/migrations/010_entity_classification.sql`
- **Classifier**: `app/services/entity_classifier.py`
- **Tests**: `tests/test_entity_classifier.py`

---

**Authors**: Claude Sonnet 4.5 + User
**Review Status**: Approved for implementation
**Last Updated**: 2026-02-11
