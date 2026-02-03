# M7 Translation Memory - Normalization Contract

**Version:** 1.0
**Date:** 2026-02-03
**Status:** APPROVED

---

## 1. Core Principles

1. **Determinism**: Same input → same output (always)
2. **M5 Compatibility**: `src_norm` for lemma/term_cluster MUST match M5 `canonical_key`
3. **Content Preservation**: NEVER remove numbers, Latin letters, or meaningful content
4. **Mode Separation**: `strict` for storage keys, `compat` for user matching

---

## 2. NormalizedText DTO

```python
@dataclass
class NormalizedText:
    raw: str           # Original input
    clean: str         # UI-friendly (nikud removed, space joiner, no stripping)
    norm: str          # DB lookup key (deterministic, mode/kind-dependent)
    mode: str          # "strict" or "compat"
    canonical_key: str # M5 canonical_key (for term_cluster compat)
    warnings: List[str]
```

---

## 3. Normalization Matrix (Hebrew)

### 3.1 STRICT Mode (для ключей БД / UNIQUE / src_norm)

| kind          | prefix_strip | joiner | example input   | norm          | canonical_key |
|---------------|--------------|--------|-----------------|---------------|---------------|
| **lemma**     | ✅ YES       | `_`    | `בית ספר`       | `בית_ספר`     | `בית_ספר`     |
| **lemma**     | ✅ YES       | `_`    | `הבית הספר`     | `בית_ספר`     | `בית_ספר`     |
| **term_cluster** | ✅ YES    | `_`    | `בבית ספר`      | `בית_ספר`     | `בית_ספר`     |
| **ngram**     | ❌ NO        | `_`    | `הבית הגדול`    | `הבית_הגדול`  | `בית_גדול`    |
| **surface**   | ❌ NO        | `_`    | `לבית`          | `לבית`        | `בית`         |

**Rules:**
- Prefix stripping ONLY for `lemma` and `term_cluster`
- All use `_` joiner for deterministic keys
- Numbers and Latin preserved: `דף 123` → `דף_123`

### 3.2 COMPAT Mode (для user input / import / recall)

| kind          | prefix_strip | joiner | example input   | norm          | canonical_key |
|---------------|--------------|--------|-----------------|---------------|---------------|
| **lemma**     | ✅ YES       | `_`    | `בית ספר`       | `בית_ספר`     | `בית_ספר`     |
| **term_cluster** | ✅ YES    | `_`    | `והבית`         | `בית`         | `בית`         |
| **ngram**     | ❌ NO        | ` `    | `הבית הגדול`    | `הבית הגדול`  | `בית_גדול`    |
| **surface**   | ❌ NO        | ` `    | `לבית`          | `לבית`        | `בית`         |

**Rules:**
- `ngram/surface` use **space** joiner (user-friendly matching)
- `lemma/term_cluster` still use M5 canonical format
- Numbers and Latin preserved: `דף 123` → `דף 123`

### 3.3 Clean (UI Display)

- **Always** space joiner
- **Never** strip prefixes
- **Always** preserve numbers/Latin
- Example: `בבית ספר` → `clean="בבית ספר"`

---

## 4. Processing Pipeline

```
Input: "בְּבֵית הַסֵּפֶר" (kind=lemma, mode=strict)
  ↓
1. Strip nikud/cantillation → "בבית הספר"
  ↓
2. Normalize whitespace → "בבית הספר"
  ↓
3. Split tokens → ["בבית", "הספר"]
  ↓
4. Filter standalone prefixes → ["בבית", "הספר"]
  ↓
5. Strip prefixes (if kind=lemma/term_cluster) → ["בית", "ספר"]
  ↓
6. Join with joiner (strict="_", compat=" " for ngram) → "בית_ספר"
  ↓
7. Lowercase → "בית_ספר"
  ↓
8. Remove punctuation (KEEP numbers/Latin/Hebrew) → "בית_ספר"
  ↓
Output: NormalizedText(
    raw="בְּבֵית הַסֵּפֶר",
    clean="בבית הספר",
    norm="בית_ספר",
    mode="strict",
    canonical_key="בית_ספר"
)
```

---

## 5. Edge Cases

### 5.1 Numbers
- **Input:** `דף 123`
- **Output (strict/lemma):** `דף_123`
- **Output (compat/ngram):** `דף 123`
- **Rule:** NEVER remove numbers

### 5.2 Mixed Scripts
- **Input:** `דבר word`
- **Output (strict/lemma):** `דבר_word`
- **Output (compat/ngram):** `דבר word`
- **Rule:** NEVER remove Latin letters

### 5.3 Whitespace Variations
- **Input:** `דבר   אחר` (multiple spaces)
- **Output (strict/lemma):** `דבר_אחר`
- **Output (compat/ngram):** `דבר אחר`
- **Rule:** Normalize to single space, then apply joiner

### 5.4 Newlines/Tabs
- **Input:** `דבר\nאחר`
- **Output (strict/lemma):** `דבר_אחר`
- **Output (compat/ngram):** `דבר אחר`
- **Rule:** Convert to space first, then apply joiner

### 5.5 Standalone Prefixes
- **Input:** `ה ספר` (tokenizer separated article)
- **Output (strict/lemma):** `ספר`
- **Rule:** Filter single-char prefix tokens, then strip remaining

---

## 6. M5 Compatibility Guarantees

### 6.1 Term Cluster Keys
```python
# M5 canonical_key
canonical = canonicalize_hebrew_term("בבית ספר")  # → "בית_ספר"

# M7 TM src_norm (MUST match)
tm_entry.src_norm = normalize_for_tm("he", "בבית ספר", "term_cluster").norm
assert tm_entry.src_norm == canonical  # ✅ MUST pass
```

### 6.2 Lemma Keys
```python
# M5 lemma canonical
lemma.canonical_key = canonicalize_hebrew_term(lemma.lemma_text)

# M7 TM src_norm (MUST match for lemma kind)
tm_entry.src_norm = normalize_for_tm("he", lemma.lemma_text, "lemma").norm
assert tm_entry.src_norm == lemma.canonical_key  # ✅ MUST pass
```

---

## 7. Non-Hebrew Languages

| Language | Processing                        | Example           | norm     |
|----------|-----------------------------------|-------------------|----------|
| Russian  | Lowercase, preserve spaces        | `Дом школа`       | `дом школа` |
| English  | Lowercase, preserve spaces        | `School House`    | `school house` |
| Mixed    | Preserve all, lowercase Latin     | `Test 123`        | `test 123` |

**Rule:** Non-Hebrew uses simple lowercase normalization, no stripping.

---

## 8. Validation Rules

1. **Idempotence:** `normalize(normalize(x)) == normalize(x)`
2. **Determinism:** Same input → same output (always)
3. **Content Preservation:** Numbers/Latin never removed
4. **M5 Sync:** `canonical_key` for lemma/term_cluster matches M5

---

## 9. Implementation Checklist

- [x] `NormalizedText` includes `mode` field
- [x] `canonicalize_hebrew_term()` preserves numbers/Latin
- [x] `canonicalize_hebrew_term()` has `strip_prefixes_enabled` param
- [x] `canonicalize_hebrew_term()` has `joiner` param
- [ ] `_normalize_hebrew()` implements strict/compat matrix correctly
- [ ] All 60 normalization tests pass
- [ ] M5 canonical_key compatibility verified

---

## 10. Test Coverage Requirements

- ✅ Strict mode: prefix stripping for lemma/term_cluster only
- ✅ Compat mode: no prefix stripping for ngram/surface
- ✅ Numbers preserved in all modes
- ✅ Latin letters preserved in all modes
- ✅ Whitespace normalized (space → joiner)
- ✅ Newlines/tabs normalized
- ✅ M5 canonical_key compatibility
- ✅ Idempotence tests
- ✅ Real-world Hebrew examples

---

**Approved by:** Staff Engineer (Claude Sonnet 4.5)
**Review Required:** Before merging to main
