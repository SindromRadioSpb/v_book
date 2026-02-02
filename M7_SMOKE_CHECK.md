# M7 Translation Memory - Smoke Check

**Purpose:** Manual verification that M7 core functionality works correctly.

**Prerequisites:**
- M1-M6 working
- Schema migrated to version 5 (004_m7_translation_memory.sql applied)
- Test project with some processed documents

---

## Test Scenarios

### 1. Schema Migration

```bash
# Check schema version
sqlite3 your_db.db "SELECT * FROM schema_meta WHERE key = 'schema_version'"
# Expected: value = '5'

# Verify M7 tables exist
sqlite3 your_db.db "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'tm_%' OR name LIKE 'dict_%' OR name = 'mt_cache'"
# Expected: tm_entry, tm_entry_history, tm_alias, dict_source, dict_entry, mt_cache
```

**✅ Pass criteria:** Schema version = 5, all M7 tables present

---

### 2. Normalization Compatibility

```python
# In Python console
from app.domain.normalization import normalize_text
from app.domain.term_extraction.canonicalizer import canonicalize_hebrew_term

# Test that M7 norm matches M5 canonical_key
test_cases = [
    "בית הספר",
    "בבית הספר",
    "ה ספר",
    "בית ספר",
]

for text in test_cases:
    m5_key = canonicalize_hebrew_term(text)
    m7_result = normalize_text("he", text, "surface", "strict")
    print(f"{text:20} → M5: {m5_key:15} | M7: {m7_result.norm:15} | Match: {m5_key == m7_result.norm}")

# Expected: All Match = True
```

**✅ Pass criteria:** M5 and M7 normalization produce identical keys

---

### 3. Translation Service Lookup

```python
from app.services.db_service import DBService
from app.services.translation_service import TranslationService
from app.infra.sa_models import TMEntry

# Initialize
DBService.initialize("your_db.db")
db = DBService.get_instance()
tm_service = TranslationService()

with db.get_session() as session:
    # Create test TM entry
    entry = TMEntry(
        project_id=None,  # Global
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="בית",
        src_norm="בית",
        translation="дом",
        status="approved",
        origin="user_edit",
    )
    session.add(entry)
    session.commit()

    # Lookup
    result = tm_service.resolve_translation(
        session,
        src_text="בית",
        kind="lemma",
        project_id=None,
    )

    print(f"Translation: {result.translation}")
    print(f"Source: {result.source}")
    print(f"Status: {result.status}")

    # Expected: Translation="дом", Source="tm", Status="approved"
```

**✅ Pass criteria:** TM entry retrieved correctly

---

### 4. Precedence Order (TM > Dict)

```python
from app.infra.sa_models import DictSource, DictEntry

with db.get_session() as session:
    # Create dict source
    dict_src = DictSource(
        project_id=None,
        name="Test Dict",
        format="csv",
        sha256="test_hash",
        row_count=1,
    )
    session.add(dict_src)
    session.flush()

    # Add dict entry for same word (different translation)
    dict_entry = DictEntry(
        dict_source_id=dict_src.dict_source_id,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="בית",
        src_norm="בית",
        translation="здание",  # Different from TM
        status="approved",
    )
    session.add(dict_entry)
    session.commit()

    # Lookup (should return TM, not dict)
    result = tm_service.resolve_translation(
        session,
        src_text="בית",
        kind="lemma",
    )

    print(f"Translation: {result.translation}")
    print(f"Source: {result.source}")

    # Expected: Translation="дом" (TM), Source="tm" (NOT dict)
```

**✅ Pass criteria:** TM wins over dict in precedence

---

### 5. Bulk Resolve Performance

```python
with db.get_session() as session:
    # Create multiple TM entries
    test_words = ["ספר", "גדול", "חדש", "טוב", "יש"]
    translations = ["книга", "большой", "новый", "хороший", "есть"]

    for word, trans in zip(test_words, translations):
        entry = TMEntry(
            project_id=None,
            kind="lemma",
            src_lang="he",
            tgt_lang="ru",
            src_text=word,
            src_norm=word,
            translation=trans,
            status="approved",
            origin="user_edit",
        )
        session.add(entry)
    session.commit()

    # Bulk lookup
    items = [(word, "lemma") for word in test_words]

    import time
    start = time.time()
    results = tm_service.bulk_resolve(session, items)
    elapsed = time.time() - start

    print(f"Bulk resolve {len(items)} items in {elapsed*1000:.2f}ms")

    # Verify all found
    for item, result in results.items():
        print(f"{item[0]:10} → {result.translation:15} ({result.source})")

    # Expected: All items have translations, <50ms total
```

**✅ Pass criteria:** All lookups succeed, time <50ms (indicates batching, not N+1 queries)

---

### 6. TM Override Persistence

```python
# This test requires processing pipeline
from app.services.term_extraction_service import TermExtractionService

term_service = TermExtractionService()

with db.get_session() as session:
    # Assume project_id=1 exists with processed documents
    project_id = 1

    # Extract terms
    report = term_service.extract_terms_for_project(
        session, project_id,
        enable_ngrams=True,
        ngram_ns=(2,),
        overwrite=True
    )
    print(f"Clusters created: {report.clusters_created}")

    # Get a cluster
    clusters = term_service.list_term_clusters(session, project_id, top_n=5)
    if clusters:
        cluster = clusters[0]
        print(f"Testing cluster: {cluster.representative_he}")

        # Create TM override for this cluster
        entry = TMEntry(
            project_id=project_id,
            kind="term_cluster",
            src_lang="he",
            tgt_lang="ru",
            src_text=cluster.representative_he,
            src_norm=cluster.canonical_key,  # CRITICAL: Use existing canonical_key
            translation="ТЕСТОВЫЙ ПЕРЕВОД",
            status="approved",
            origin="user_edit",
        )
        session.add(entry)
        session.commit()
        tm_id = entry.tm_id

        # Re-extract terms (simulate reindex)
        report2 = term_service.extract_terms_for_project(
            session, project_id,
            enable_ngrams=True,
            ngram_ns=(2,),
            overwrite=True
        )
        print(f"Re-extraction done: {report2.clusters_created} clusters")

        # Verify TM still exists
        tm_check = session.get(TMEntry, tm_id)
        print(f"TM entry after re-extraction: {tm_check.translation if tm_check else 'NOT FOUND'}")

        # Lookup translation
        result = tm_service.resolve_translation(
            session,
            src_text=cluster.representative_he,
            kind="term_cluster",
            project_id=project_id,
        )
        print(f"Translation lookup: {result.translation} (source: {result.source})")

        # Expected: TM survives re-extraction, lookup returns TM translation
```

**✅ Pass criteria:** TM override persists after re-extraction, lookup returns TM translation

---

### 7. Status Workflow

```python
with db.get_session() as session:
    # Create draft entry
    draft_entry = TMEntry(
        project_id=None,
        kind="lemma",
        src_lang="he",
        tgt_lang="ru",
        src_text="חדש_test",
        src_norm="חדש_test",
        translation="новый (черновик)",
        status="draft",
        origin="user_edit",
    )
    session.add(draft_entry)
    session.commit()
    entry_id = draft_entry.tm_id

    # Lookup without allow_draft (should NOT find)
    result = tm_service.resolve_translation(
        session,
        src_text="חדש_test",
        kind="lemma",
        allow_draft=False,
    )
    print(f"Without allow_draft: {result.translation}")
    # Expected: None

    # Lookup with allow_draft (should find)
    result = tm_service.resolve_translation(
        session,
        src_text="חדש_test",
        kind="lemma",
        allow_draft=True,
    )
    print(f"With allow_draft: {result.translation}")
    # Expected: "новый (черновик)"

    # Approve entry
    entry = session.get(TMEntry, entry_id)
    entry.status = "approved"
    entry.approved_at = "2026-02-02T12:00:00.000Z"
    session.commit()

    # Lookup now finds it without allow_draft
    result = tm_service.resolve_translation(
        session,
        src_text="חדש_test",
        kind="lemma",
        allow_draft=False,
    )
    print(f"After approve: {result.translation}")
    # Expected: "новый (черновик)"
```

**✅ Pass criteria:** Draft status respected, approval workflow works

---

## Summary Checklist

- [ ] Schema migration to v5 successful
- [ ] Normalization matches M5 canonical_key
- [ ] TM lookup works (single item)
- [ ] Precedence order correct (TM > Dict > MT)
- [ ] Bulk resolve performs well (<50ms for 5 items)
- [ ] TM override persists after re-extraction
- [ ] Status workflow (draft/approved) works

**Result:** ___ / 7 tests passed

---

## Troubleshooting

### "Normalization produces different key than M5"
- Check that `normalize_text()` calls `canonicalize_hebrew_term()` from M5
- Verify import path in `app/domain/normalization/normalizer.py`

### "TM lookup returns None but entry exists"
- Check `src_norm` matches between TM entry and lookup
- Verify status is "approved" (or `allow_draft=True`)
- Check project_id scope (project vs global)

### "Bulk resolve is slow"
- Verify `_batch_lookup_tm` uses `.in_()` clause (not N+1 queries)
- Check SQLite indexes on `src_norm` columns
- Profile with `logging.debug()` to see query counts

### "TM disappears after re-extraction"
- This should NOT happen - check tm_entry CASCADE rules
- Verify re-extraction doesn't DELETE from tm_entry table
- TM table is independent of term_cluster table
