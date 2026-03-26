# Algorithm Profiles — NLP Extraction Configurations

> Three named profiles for balancing precision vs recall in Hebrew term extraction.
> Use these as starting points; tune per corpus type.

---

## Overview

| Profile | Goal | Typical Use Case |
|---------|------|-----------------|
| **precise** | Maximum precision; minimal false positives | Legal/medical terminology; expert review |
| **balanced** | Standard product profile | General encyclopaedic corpus (default) |
| **recall** | Maximum coverage; accepts more noise | Exploratory analysis; building seed lexicons |

---

## Profile Definitions

### `precise`

Extracts only the highest-confidence multi-word terms.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Include N-grams | Yes | |
| Include NP chunks | Yes | |
| Bigrams | Yes | |
| Trigrams | No | Trigrams have higher false-positive rate |
| Max NP length | 3 | Longer spans are less likely to be fixed terms |
| Min freq | 5 | Require strong evidence |
| Min doc freq | 3 | Must appear in multiple documents |
| Store hapax | Off | Single-occurrence terms excluded |
| Noise filter | Conservative | PUNCT, SYMBOL, MATH_EXPR, NOISE_TOO_SHORT only |

**Association measure thresholds:**
- PMI ≥ 3.0 (strong log-odds)
- Dice ≥ 0.3 (moderate co-occurrence stability)
- LLR ≥ 10.83 (significant at p < 0.001)

---

### `balanced` (default)

The standard profile shipped with HDLE Premium.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Include N-grams | Yes | |
| Include NP chunks | Yes | |
| Bigrams | Yes | |
| Trigrams | Yes | |
| Max NP length | 5 | |
| Min freq | 2 | |
| Min doc freq | 1 | |
| Store hapax | Off | Reduces noise in term list |
| Noise filter | Balanced | All auto-classified noise classes |

**Association measure thresholds:**
- PMI ≥ 1.0
- Dice ≥ 0.1
- LLR ≥ 3.84 (p < 0.05)

---

### `recall`

Captures all candidate terms for downstream review.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Include N-grams | Yes | |
| Include NP chunks | Yes | |
| Bigrams | Yes | |
| Trigrams | Yes | |
| Max NP length | 5 | |
| Min freq | 1 | Include hapax for seeding |
| Min doc freq | 1 | |
| Store hapax | **On** | All single-occurrence terms stored |
| Noise filter | None | No automatic noise exclusion |

**Association measure thresholds:**
- No PMI threshold (accept all)
- Dice ≥ 0.0 (any co-occurrence)

---

## Noise Classification Profiles

Three noise classifier profiles correspond to the extraction profiles:

### `conservative` (→ precise extraction)
Marks as noise only:
- `PUNCT`, `SYMBOL`, `MATH_EXPR` entity classes
- `NOISE_PUNCT_ONLY`, `NOISE_SYMBOL_ONLY`, `NOISE_MATH_EXPR`, `NOISE_TOO_SHORT` reasons

### `balanced` (→ balanced extraction)
Marks as noise:
- All auto-classified classes: `PUNCT`, `SYMBOL`, `NUMBER`, `QUANTITY_UNIT`,
  `MATH_EXPR`, `MIXED_ALPHA_NUM`, `OTHER`
- All `NoiseReason` codes

### `aggressive` (→ recall extraction with cleanup)
Additionally marks:
- `WORD_HE` with len ≤ 2
- Any token with non-letter ratio > 0.4

---

## Validation Test Mapping

Each profile should be validated with the C08 noise corpus using the corresponding profile:

```python
# Example: run balanced profile validation
cases = gold_data("c08_noise_classification")["classify_text_cases"]
for case in cases:
    result = validate_classify_text(case, profile="balanced")
    assert result.match
```

The `noise_profiles` key in `c08_noise_classification.json` documents which
entity classes and reason codes each profile treats as noise.

---

## Choosing a Profile

```
                   Fewer terms (higher precision)
                             ▲
                             │
                         precise
                             │
                         balanced  ◄── default
                             │
                          recall
                             │
                             ▼
                   More terms (higher recall)
```

Start with `balanced`. Switch to `precise` if the term list contains too many
non-terminological fragments. Switch to `recall` when building a seed lexicon
for a new domain.
