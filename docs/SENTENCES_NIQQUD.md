# Sentence Niqqud Layer — Design Contract & Requirements

> Status: **Approved** — 2026-02-22
> Scope: `sentence_pronunciation` dedicated layer (Task 24)
> Does NOT replace `pronunciation_entry` (lexical layer for Terms/Lemmas/UD).

---

## 1. Problem Statement

The Sentences tab shows ~0% niqqud coverage because `COL_NIQQUD` was reading
from the **lexical** `PronunciationEntry` table (keyed by `src_norm` of a
lemma/term), not from a sentence-level store.  A normalized sentence string
almost never matches a lemma `src_norm`, so all lookups return empty.

Root causes:
1. No dedicated sentence-level table (sentence_id → niqqud_text).
2. No `src_hash` idempotency key for sentences (preventing safe re-runs).
3. No guards / skip-reason tracking (skipped == opaque).
4. No sentence-specific bootstrap dialog or context-menu actions.

---

## 2. Architecture

```
┌────────────────────────────────────────┐
│  Sentences tab (SentencesView)          │
│  + Niqqud column (sentence layer)       │
│  + QC badge column                      │
│  + Bootstrap button / context menu      │
└──────────────┬─────────────────────────┘
               │ sentence_id
               ▼
┌──────────────────────────────────────────┐
│  sentence_pronunciation table (NEW)       │
│  PK: sentence_id (FK document_sentence)   │
│  Key: src_hash (sha256, idempotency)      │
│  Stores: niqqud_text, qc_status, source  │
│  Override wins: is_override=1 immutable  │
└──────────────┬───────────────────────────┘
               │ SentencePronunciationService
               ▼
┌───────────────────────────────────────────┐
│  Phonikud adapter / PronunciationQuality  │
│  (reused: sanitize, has_hebrew_nikud,     │
│   coverage, QC tiers)                     │
└───────────────────────────────────────────┘
```

The **lexical** `PronunciationEntry` table is NOT touched by this feature.

---

## 3. DB Schema — `sentence_pronunciation`

```sql
CREATE TABLE sentence_pronunciation (
    sentence_id       INTEGER PRIMARY KEY,   -- FK document_sentence.sentence_id CASCADE
    lang              TEXT    NOT NULL DEFAULT 'he',
    src_hash          TEXT    NOT NULL,       -- sha256(lang|preprocessed_text|phonikud_version|sanitizer_version)
    src_preprocessed  TEXT,                  -- cleaned sentence text used for hash + generation
    niqqud_text       TEXT,                  -- NULL = not yet generated or rejected
    source            TEXT    NOT NULL DEFAULT 'auto_phonikud',
                                             -- auto_phonikud | manual | import_csv
    is_override       INTEGER NOT NULL DEFAULT 0,  -- 1 = manual override (never auto-overwritten)
    confidence        REAL,
    qc_status         TEXT    NOT NULL DEFAULT 'ok',
                                             -- ok | auto_fixed | partial | rejected | failed | pending
    qc_reason         TEXT,                  -- human-readable explanation
    niqqud_coverage   REAL,                  -- 0.0–1.0: fraction of He words with nikud
    phonikud_version  TEXT,                  -- model version used (for lifecycle management)
    sanitizer_version TEXT    NOT NULL DEFAULT '1',
    error_kind        TEXT,                  -- classification of failure
    error_details     TEXT,
    review_status     TEXT    NOT NULL DEFAULT 'auto',
                                             -- auto | pending_review | approved | rejected_by_user
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    FOREIGN KEY (sentence_id) REFERENCES document_sentence(sentence_id) ON DELETE CASCADE,
    CHECK(source IN ('auto_phonikud','manual','import_csv')),
    CHECK(is_override IN (0,1)),
    CHECK(qc_status IN ('ok','auto_fixed','partial','rejected','failed','pending')),
    CHECK(review_status IN ('auto','pending_review','approved','rejected_by_user')),
    CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CHECK(niqqud_coverage IS NULL OR (niqqud_coverage >= 0 AND niqqud_coverage <= 1))
);

-- Indexes
CREATE INDEX idx_sp_lang_hash        ON sentence_pronunciation(lang, src_hash);
CREATE INDEX idx_sp_is_override      ON sentence_pronunciation(is_override);
CREATE INDEX idx_sp_qc_status        ON sentence_pronunciation(qc_status);
CREATE INDEX idx_sp_review_status    ON sentence_pronunciation(review_status);
CREATE INDEX idx_sp_source           ON sentence_pronunciation(source);
```

### Hash Function

```python
import hashlib, json

SANITIZER_VERSION = "1"

def compute_src_hash(lang: str, preprocessed_text: str,
                     phonikud_version: str) -> str:
    payload = json.dumps({
        "lang": lang,
        "text": preprocessed_text,
        "pv": phonikud_version,
        "sv": SANITIZER_VERSION,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]
```

---

## 4. Merge Semantics

| Condition | Fill-only (rebuild_auto=False) | Rebuild (rebuild_auto=True) |
|---|---|---|
| `is_override=1` | **SKIP** — manual wins | **SKIP** — manual wins always |
| `src_hash == new_hash` AND `niqqud_text` non-empty | **SKIP** (same_hash) | **SKIP** (same_hash) |
| `src_hash == new_hash` AND `niqqud_text` NULL/empty | **PROCESS** (fill missing) | **PROCESS** |
| `src_hash != new_hash` AND `is_override=0` | **SKIP** (fill-only skips changed) | **PROCESS** (update) |
| No existing row | **PROCESS** (insert new) | **PROCESS** (insert new) |

---

## 5. Guards & Skip Reasons

All guards checked in `SentencePronunciationService.should_process()`:

| Skip Reason Key | Condition | Default Threshold |
|---|---|---|
| `skipped_too_short` | `len(preprocessed_text) < MIN_LEN` | MIN_LEN = 5 chars |
| `skipped_too_long` | `len(preprocessed_text) > MAX_LEN` | MAX_LEN = 2000 chars |
| `skipped_non_hebrew_ratio` | Hebrew letter fraction < MIN_HE_RATIO | MIN_HE_RATIO = 0.10 |
| `skipped_same_hash` | hash unchanged AND niqqud non-empty | — |
| `skipped_has_override` | `is_override=1` | — |
| `skipped_invalid_after_qc` | QC tier = `rejected` | niqqud_coverage < 0.40 |

Skip reason counts are accumulated and shown in the bootstrap summary dialog.

---

## 6. QC Tiers

After generation, `niqqud_coverage` is measured as:

```
coverage = (words_with_any_nikud_mark) / (total_he_words)
```

| Tier | Condition | `qc_status` |
|---|---|---|
| ok | coverage ≥ 0.75 | `ok` |
| partial | 0.40 ≤ coverage < 0.75 | `partial` |
| rejected | coverage < 0.40 | `rejected` |
| failed | Exception during generation | `failed` |

Records with `qc_status = rejected` or `failed` still get stored (for diagnostics),
but `niqqud_text` may be set to NULL if rejected.

---

## 7. Sentence Segmentation (Long Sentences)

Phonikud models have a token limit (~400 chars).  Long sentences are split
before generation and the results are concatenated:

```
SentenceSegmenter.split(text, max_chars=380)
  → segments list
  → generate each segment
  → join niqqud segments with space
  → QC on final result
```

Segmentation splits on clause boundaries: `[.,;:!?]\s+` or newlines.
If a single "word" exceeds `max_chars`, it passes through unsplit.

---

## 8. Bootstrap Modes & Scopes

### Scopes
| Scope Key | Description |
|---|---|
| `selected` | Sentence IDs from current table selection |
| `current_page` | All IDs on current page |
| `all_filtered` | All IDs matching current doc/search filter |

### Modes
| Mode Key | Behavior |
|---|---|
| `dry_run` | No DB writes; returns what *would* be processed |
| `fill_only` | Insert/update only where hash changed or niqqud empty; skip same-hash |
| `rebuild` | Re-generate all non-override rows; update even if hash unchanged |

### Bootstrap Result Counters
```python
@dataclass
class SentenceBootstrapResult:
    total_candidates: int
    processed: int
    inserted: int
    updated: int
    skipped_same_hash: int
    skipped_has_override: int
    skipped_too_short: int
    skipped_too_long: int
    skipped_non_hebrew_ratio: int
    skipped_invalid_after_qc: int
    failed: int
    rejected_qc: int
    partial_qc: int
    dry_run: bool = False
```

---

## 9. Service API

### `SentencePronunciationService`

```python
class SentencePronunciationService:
    SANITIZER_VERSION = "1"
    MIN_LEN   = 5     # chars
    MAX_LEN   = 2000  # chars
    MIN_HE_RATIO = 0.10  # fraction of Hebrew letter chars

    def compute_src_hash(lang, preprocessed_text, phonikud_version) -> str
    def preprocess_text(text: str) -> str
        # strip bidi/joiners, normalize whitespace, keep punctuation
    def should_process(text: str) -> tuple[bool, str]
        # returns (should_process, skip_reason)
    def get_effective_niqqud(session, sentence_id) -> SentenceNiqqudOverlay | None
    def upsert_auto(session, sentence_id, lang, src_hash, src_preprocessed,
                    niqqud_text, confidence, qc_status, qc_reason,
                    niqqud_coverage, phonikud_version) -> str  # "inserted"|"updated"|"skipped"
    def upsert_manual(session, sentence_id, niqqud_text, notes=None) -> None
    def clear(session, sentence_id) -> bool
    def bulk_get_niqqud(session, sentence_ids) -> dict[int, SentenceNiqqudOverlay]
```

### `SentencePronunciationBootstrapService`

```python
class SentencePronunciationBootstrapService:
    def run(
        session,
        sentence_ids: list[int],
        *,
        lang: str,
        mode: Literal["dry_run", "fill_only", "rebuild"],
        phonikud_adapter,
        guard_params: GuardParams | None = None,
        progress_callback: Callable | None = None,
        cancel_check: Callable[[], bool] | None = None,
        pause_check: Callable[[], bool] | None = None,
        chunk_size: int = 200,
    ) -> SentenceBootstrapResult
```

---

## 10. DTO & Overlay

```python
@dataclass
class SentenceNiqqudOverlay:
    sentence_id: int
    niqqud_text: Optional[str]
    qc_status: str         # ok | partial | rejected | failed | pending
    qc_reason: Optional[str]
    source: str            # auto_phonikud | manual | import_csv
    confidence: Optional[float]
    niqqud_coverage: Optional[float]
    is_override: bool
    review_status: str
```

`SentenceDTO` gains new fields:
```python
niqqud_qc:         Optional[str]   # short qc_status badge
niqqud_source:     Optional[str]
niqqud_confidence: Optional[float]
niqqud_coverage:   Optional[float]
niqqud_is_override: bool
niqqud_review:     Optional[str]
```

---

## 11. UI Requirements

### Column Layout (8 columns)
| Index | Name | Width |
|---|---|---|
| 0 | ID | 70 |
| 1 | Document | 180 |
| 2 | # | 50 |
| 3 | Sentence Text | 400 |
| 4 | Translation | 280 |
| 5 | Niqqud | 200 |
| 6 | QC | 60 |
| 7 | Audio | 90 |

### Niqqud Column Tooltip
```
Source: auto_phonikud
Confidence: 0.82
Coverage: 87%
QC: ok
Reason: —
```

### QC Column Badges
| qc_status | Badge | Color |
|---|---|---|
| ok | ✓ | green |
| partial | ~ | orange |
| rejected | ✗ | red |
| failed | ! | red |
| pending | … | gray |
| (empty) | — | gray |

### Action Buttons (toolbar)
- `Niqqud Bootstrap…` (all filtered) — always enabled
- `Niqqud Selected…` (selection) — enabled only when rows selected
- Existing: Translate Selected, Generate Audio, Play

### Context Menu
```
Translate Selected (N)...
Generate Audio (N)...
──────────────────────
▶ Play Audio Selected (N)
Pronunciation Bootstrap Selected (N)...   ← lexical bootstrap (existing)
──────────────────────
Niqqud Selected (N)...                    ← sentence niqqud bootstrap
Edit Niqqud...                            ← manual override dialog (first row)
Clear Niqqud...                           ← nullify niqqud_text for selection
──────────────────────
Mispronounced -> Add Pronunciation...     ← lexical edit (existing)
```

### Bootstrap Dialog — `SentenceNiqqudBootstrapDialog`
Fields:
- Scope: Current Page | Selected (N) | All Filtered
- Mode: Fill-only (recommended) | Rebuild | Dry-run
- Phonikud gate status badge: real | fallback | error (with warning on fallback/error)
- Advanced (collapsible):
  - Min length (default 5)
  - Max length (default 2000)
  - Min Hebrew ratio (default 0.10)
  - Chunk size (default 200)

### Edit Niqqud Dialog — `EditSentenceNiqqudDialog`
- Shows sentence text (read-only)
- Hebrew text edit for niqqud_text (manual override)
- Preview: renders the niqqud text with `QLabel` (RTL)
- Sets `is_override=1`, `source='manual'`

---

## 12. TTS Priority Chain

When generating audio for a sentence:
```
1. IF sentence_pronunciation row exists
   AND qc_status NOT IN ('rejected', 'failed')
   AND niqqud_text is not NULL/empty:
       use niqqud_text (TTS sanitize first)
2. ELSE: use sanitized sentence text
```

---

## 13. WAL Safety & Performance

- All writes via `SentencePronunciationBootstrapService.run()` only.
- Chunks of 200 sentences per transaction (`session.commit()` per chunk).
- `@retry_on_db_locked` decorator on write methods.
- Worker thread emits signals only; no DB access in UI thread.
- Progress updates throttled to max 10/sec via signal batching.

---

## 14. Test Coverage (Required)

| Test File | Cases |
|---|---|
| `test_sentence_pronunciation_hash_idempotency.py` | same text → same hash; changed text → different hash; fill_only skips same_hash |
| `test_sentence_pronunciation_guards.py` | too_short, too_long, non_hebrew, happy path |
| `test_sentence_pronunciation_manual_wins.py` | manual override not overwritten by auto; rebuild skips is_override=1 |
| `test_sentence_bootstrap_skip_reasons.py` | all skip reason buckets populated; dry_run no DB write |
| `test_sentence_bootstrap_worker_v3.py` | cancel stops mid-batch; pause/resume produces same result |
| `test_sentences_view_niqqud_column.py` | QC badge color; tooltip data from overlay; column count=8 |

---

## 15. Smoke Evidence Matrix

| Scenario | Expected |
|---|---|
| Bootstrap All Filtered (fill_only) | First run: inserted>0; second run: skipped_same_hash≈N, updated≈0 |
| Bootstrap rebuild | Re-processes all non-override; updated>0 |
| Manual override | Edit Niqqud dialog → saves is_override=1; subsequent bootstrap skips |
| Clear Niqqud | Sets niqqud_text=NULL, is_override=0, qc_status='pending' |
| Dry run | Result shows what would be processed; DB unchanged |
| Long sentence (>380 chars) | Segmented → generated → joined → QC pass |
| Short sentence (<5 chars) | skipped_too_short counter increments |
| Non-Hebrew sentence | skipped_non_hebrew_ratio counter increments |

---

## 16. Out of Scope (this task)

- Flashcard / study integration with sentence niqqud.
- Bulk CSV export/import of sentence niqqud (deferred to future task).
- Review approval workflow UI (review_status column stored but no dedicated UI).
- Phonikud model version management UI (phonikud_version stored but no version switcher).
