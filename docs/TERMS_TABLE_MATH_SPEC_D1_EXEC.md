# D1: Executable Mathematical Specification

**Purpose:** D1 (`verify_terms_math.py`) is an executable specification that verifies the mathematical correctness of the Terms table extraction pipeline.

**Status:** Implemented (2026-02-02)

---

## What D1 Verifies

### 1. Schema Compatibility
- All required tables exist (`lemma`, `ngram`, `term_cluster`, etc.)
- All required columns exist (with fallback name resolution)
- Fails-fast with actionable error messages if schema is incompatible

### 2. Mathematical Invariants (ALL clusters)

For every extracted cluster, D1 asserts:

```python
# Basic bounds
freq_abs >= 0
doc_freq >= 0
members_count >= 1

# Metric bounds
0 <= dice <= 1
llr >= 0

# Logical constraints
doc_freq <= total_documents_in_project
freq_abs >= doc_freq  # Term appears at least as many times as documents

# Aggregation correctness
cluster.freq_abs == sum(member.freq_abs)
cluster.doc_freq == max(member.doc_freq)  # Current implementation
```

**Implementation:** `check_invariants()` function checks all clusters, collects failures.

### 3. Independent Metric Recomputation

For target clusters ("בית הספר", "הספר החדש"):

D1 independently recomputes PMI, LLR, Dice using **pure math** (not production functions):

#### PMI (Pointwise Mutual Information)
```python
PMI = log2( (c_xy * N) / (c_x * c_y) )
```

**Inputs:**
- `c_xy`: Bigram count (from `ngram_project_stat.freq_abs`)
- `c_x`, `c_y`: Unigram lemma counts (from `lemma_project_stat.freq_abs`)
- `N`: Total token count (from `SUM(document_text.token_count)`)

**Comparison:**
- Tolerance: `1e-5`
- Compared against `ngram_project_stat.pmi_cache`

#### Dice Coefficient
```python
Dice = 2 * c_xy / (c_x + c_y)
```

**Inputs:** Same as PMI (except N not needed)

**Comparison:**
- Tolerance: `1e-6`
- Compared against `ngram_project_stat.dice_cache`

#### LLR (Log-Likelihood Ratio)
```python
LLR = 2 * Σ O_ij * ln(O_ij / E_ij)
```

**Contingency Table (2×2):**
```
        | y        | ¬y       | total
--------|----------|----------|-------
x       | O11=c_xy | O12=c_x-c_xy | c_x
¬x      | O21=c_y-c_xy | O22=N-c_x-c_y+c_xy | N-c_x
--------|----------|----------|-------
total   | c_y      | N-c_y    | N
```

**Expected values:**
```
E_ij = (row_total * col_total) / N
```

**Comparison:**
- Tolerance: `1e-5`
- Compared against `ngram_project_stat.llr_cache`
- Uses **natural log (ln)** to match production code

---

## What D1 Does NOT Verify

1. **Termhood metrics** (weirdness, keyness) - not in scope
2. **NP chunk extraction** - disabled in D1 (only n-grams)
3. **Trigram metrics** - controlled dataset uses only bigrams
4. **UI projection** - tests DB layer only
5. **Concordance/FTS** - separate concern
6. **Hebrew normalization completeness** - only uses artifacts present in dataset ("ה ספר")

---

## Controlled Dataset

D1 uses exactly 3 documents:

**Document A (5 sentences):**
```
בית הספר גדול.
בית הספר גדול.
בבית הספר יש ספר חדש.
הספר החדש טוב.
הספר החדש טוב.
```

**Document B (4 sentences):**
```
בית ספר גדול ליד בית הספר.
בית הספר גדול.
הספר בבית הספר חדש וטוב.
בבית הספר יש ספר חדש.
```

**Document C (2 sentences, includes artifact):**
```
ה ספר הזה טוב.
בית הספר החדש טוב.
```

**Why this dataset:**
- 3 documents → DocFreq meaningful (can be 1, 2, or 3)
- Repetitions → Freq > 1, metrics not N/A
- Artifact case → Validates "ה ספר" merge normalization
- Deterministic → Repeated runs produce same results

---

## Expected Output

### PASS (all checks)

```
======================================================================
D1: EXECUTABLE SPECIFICATION - Terms Table Mathematics
======================================================================

[SCHEMA INTROSPECTION]
  ✅ Schema validated: 8 tables
     ngram_project_stat: {'pmi': 'pmi_cache', 'llr': 'llr_cache', 'dice': 'dice_cache'}
     term_cluster: {'pmi': 'best_pmi', 'llr': 'best_llr', 'dice': 'best_dice'}
     lemma: {'text': 'lemma_text'}

[1/5] Creating controlled dataset...
  Documents: 3
  Document A: 5 sentences
  Document B: 4 sentences
  Document C: 2 sentences
  ✅ Project ID: 1, Corpus ID: 1

[2/5] Importing and processing documents...
  ✅ Document A: ID=1, sentences=5
  ✅ Document B: ID=2, sentences=4
  ✅ Document C: ID=3, sentences=2

[3/5] Extracting terms...
  ✅ N-grams extracted: 5
  ✅ Clusters created: 4

[4/5] Checking invariants for all clusters...
  Retrieved 4 clusters
  ✅ All invariants passed for 4 clusters

[5/5] Independent metric verification...

  📊 Verifying: בית הספר
     Cluster ID: 1
     ✅ Freq aggregation: 8 = sum(members)
     ✅ DocFreq aggregation: 3 = max(members)

     Counts for 'בית הספר' (lemma: 'בית ספר'):
       C(בית) = 9
       C(ספר) = 15
       C(בית,ספר) = 5
       N = 44

     PMI:
       Calculated: 0.704544
       Stored:     0.704544
       Diff:       1.110223e-16
       ✅ PASS

     Dice:
       Calculated: 0.416667
       Stored:     0.416667
       Diff:       0.000000e+00
       ✅ PASS

     LLR (2×2 contingency table):
       O11 (x,y):        5
       O12 (x,¬y):       4
       O21 (¬x,y):      10
       O22 (¬x,¬y):     25
       Calculated:   10.606378
       Stored:       10.606378
       Diff:         8.881784e-15
       ✅ PASS

  📊 Verifying: הספר החדש
     ... (similar output)

======================================================================
VERIFICATION SUMMARY
======================================================================
✅ PASS: All invariants and metric checks passed
   - Dataset: 3 documents
   - Clusters verified: 4
   - Metrics independently recomputed and matched

📁 Database saved: verify_terms_math.db
```

**Exit code: 0**

### FAIL (example)

```
[4/5] Checking invariants for all clusters...
  Retrieved 4 clusters
  ❌ Invariant failures: 2

[5/5] Independent metric verification...
  ... (metric checks)

  PMI:
    Calculated: 0.704544
    Stored:     0.820123
    Diff:       1.155790e-01
    ❌ FAIL

======================================================================
VERIFICATION SUMMARY
======================================================================
❌ FAIL: 3 verification failure(s)

Failures:
  1. Cluster 2 (ליד בית): dice=1.2 not in [0,1]
  2. Cluster 3 (טוב חדש): freq_abs=2 < doc_freq=3
  3. בית הספר (בית הספר): PMI diff=1.155790e-01 > tolerance

📁 Database saved for inspection: verify_terms_math.db
```

**Exit code: 1**

---

## How to Run

```bash
# Preconditions first
python verify_preconditions.py

# Then D1 executable spec
python verify_terms_math.py

# Check exit code
echo $?  # 0 = pass, 1 = fail
```

---

## How to Interpret Failures

### Schema Error
```
❌ SCHEMA ERROR: Table 'ngram_project_stat' missing column for 'pmi'.
   Tried: ['pmi_cache', 'pmi']
   Actual columns: ['cluster_id', 'freq_abs', 'pmi_score']
```

**Fix:** Update schema introspection candidates in D1, OR rename DB column.

### Invariant Failure
```
Cluster 5 (בית גדול): doc_freq=4 > num_docs=3
```

**Fix:** Bug in DocFreq calculation (production code).

### Metric Mismatch
```
בית הספר (בית הספר): PMI diff=1.155790e-01 > tolerance
  Calculated: 0.704544
  Stored:     0.820123
```

**Fix:** Either:
1. Production formula incorrect (check `association_measures.py`)
2. D1 formula incorrect (check `compute_pmi_independent()`)
3. Different N definitions (check how production counts tokens)

**Debug:**
- Inspect `verify_terms_math.db` with SQLite viewer
- Check `document_text.token_count` values
- Verify unigram counts in `lemma_project_stat`

---

## Metric Definitions Used

### N (Total Token Count)

```sql
SELECT SUM(freq_abs)
FROM lemma_project_stat
WHERE project_id = :project_id
```

**Note:** N = sum of all unigram lemma frequencies in the project. This matches production implementation `_get_total_tokens()`. This is the total number of lemma occurrences, used as denominator for probabilities in PMI/LLR calculations.

### Unigram Counts (c_x, c_y)

```sql
SELECT l.lemma_text, lps.freq_abs
FROM lemma l
JOIN lemma_project_stat lps ON lps.lemma_id = l.lemma_id
WHERE lps.project_id = :project_id
  AND l.lemma_text IN (:lemma1, :lemma2)
```

**Note:** Uses **lemma** text, not surface forms. PMI/LLR/Dice compare lemmatized bigrams.

### Bigram Count (c_xy)

```sql
SELECT st.freq_abs
FROM ngram_project_stat st
WHERE st.ngram_id = :ngram_id
  AND st.project_id = :project_id
```

**Note:** Frequency of the bigram occurrence in corpus.

---

## Performance

**Target:** <5 seconds on controlled dataset

**Actual:** ~2-3 seconds (on typical hardware)

**Optimizations:**
- Schema introspection cached in dict
- SQL queries use indexes
- Only verifies 2 target clusters for metrics (not all)
- Invariants checked for all (fast, no DB queries per cluster)

---

## Maintenance

**When to update D1:**

1. **Schema changes:** Update `required_tables` dict in `get_schema_info()`
2. **New metrics added:** Add to invariant checks and/or independent computation
3. **Formula changes:** Update `compute_*_independent()` functions
4. **DocFreq definition changes:** Update comment and verification logic

**Test after:**
- Schema migrations
- Changes to `association_measures.py`
- Changes to `term_extraction_service.py` clustering logic
- Hebrew normalization changes (if affecting the controlled dataset)

---

## Related Documentation

- `verify_preconditions.py` (D0) - Environment setup verification
- `docs/TERMS_TABLE_MATH_SPEC.md` - Complete mathematical specification
- `app/domain/term_extraction/association_measures.py` - Production formulas
- `VERIFICATION_FINDINGS.md` - Bug fixes and historical issues
