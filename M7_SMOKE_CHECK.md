# M7 Translation Memory - Smoke Check

## Automated Gate (обязательно перед ручными сценариями)

Выполни эти автопроверки **перед** разделом «Test Scenarios». Они должны завершиться успешно (exit code 0).

### Windows PowerShell
```powershell
# из корня репозитория
.\.venv\Scripts\Activate.ps1

python test_m7_ui_integration.py
python test_m7_normalization.py
python smoke_check_m7.py
python test_m7.py
```

### Bash (macOS/Linux/Git-Bash)
```bash
source .venv/bin/activate
python test_m7_ui_integration.py
python test_m7_normalization.py
python smoke_check_m7.py
python test_m7.py
```

**✅ Pass criteria:**
- `test_m7_ui_integration.py`: все тесты PASS (unittest выводит `OK`)
- `test_m7_normalization.py`: все тесты PASS (unittest выводит `OK`)
- `smoke_check_m7.py`: общий итог PASSED и exit code 0
- `test_m7.py`: общий итог PASSED и exit code 0

Если любой из шагов падает — **остановись** и исправь проблему перед ручным smoke-check.

---

## P1 Premium: Automated Scenario 7 Verification

**Purpose:** Automated verification that TM entries persist through re-extraction and database restarts (Scenario 7).

**What it does:**
1. Creates a snapshot copy of your database (never modifies production DB)
2. Selects 3 test items (term_cluster, multiword lemma, single lemma)
3. Seeds TM entries with strict normalization
4. Verifies TM entries resolve correctly pre-extraction
5. Simulates re-extraction/reindex
6. Verifies TM entries still resolve post-extraction
7. Simulates database restart
8. Verifies TM entries still resolve post-restart
9. Generates MD + JSON reports

### P1.1 UI Panel (Premium - Recommended for Non-Technical Users)

**How to access:**
1. Launch HDLE application
2. Click menu: **Tools → Verification (P1 Scenario 7)**
3. Select database (or use current production DB)
4. Select project (or "Global" for all projects)
5. Click "▶ Run P1 Scenario 7"

**Features:**
- ✅ Non-blocking UI (uses background worker)
- ✅ Real-time progress bar and log output
- ✅ Cancel button (can stop mid-run)
- ✅ Open Report button (opens report directory)
- ✅ Copy Summary button (copies results to clipboard)
- ✅ Status badges: PASS / PARTIAL / SKIPPED / FAIL

**Screenshot guide:**
1. DB section shows production DB path (read-only)
2. Project dropdown lists all available projects
3. Run button starts verification (green)
4. Progress bar shows 0-100% with phase updates
5. Log output shows real-time messages
6. Status badge updates with final result

**Note:** UI always runs on snapshot - your production DB is never modified.

### P1.2 Headless CLI (Automation/CI)

```bash
# Activate environment
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Run verification
python -m app.tools.p1_verify --db your_db.db
python -m app.tools.p1_verify --db your_db.db --project-id 1
python -m app.tools.p1_verify --db your_db.db --out-dir ./my_reports
```

**Exit codes:**
- `0` = PASS or PARTIAL (all or some tests passed)
- `1` = FAIL (critical failure)
- `2` = SKIPPED (no processed data found)

### P1.3 Unit Tests

```bash
# P1 service unit tests (6 tests)
python test_p1_verification.py

# Expected: 6/6 PASS
```

### P1.4 E2E Test with Real Term Clusters

```bash
# E2E test using real term extraction pipeline
python test_p1_e2e_termclusters.py

# Expected: 3/3 PASS
# - Fixture has term clusters (not empty)
# - P1 verification NOT SKIPPED
# - Full report generated with PASS status
```

**What E2E test does:**
1. Builds fixture DB with real Hebrew text
2. Runs term extraction pipeline (same as production)
3. Verifies term_clusters created (≥1)
4. Runs P1 verification on fixture
5. Asserts PASS (not SKIPPED)
6. Generates report in `runtime/fixtures/termcluster/<timestamp>/`

### P1.5 CI Gate (Automated Testing)

**Running all tests locally:**

```powershell
# Windows PowerShell
.\scripts\ci_run_tests.ps1

# Linux/macOS/Git Bash
./scripts/ci_run_tests.sh
```

**What CI runs:**
1. `test_m7.py` - M7 core functionality
2. `test_m7_ui_integration.py` - M7 UI integration (13 tests)
3. `test_m7_normalization.py` - M7 normalization contract (60 tests)
4. `test_p1_verification.py` - P1 unit tests (6 tests)
5. `test_p1_e2e_termclusters.py` - P1 E2E with real pipeline (3 tests)

**CI configuration:**
- GitHub Actions: `.github/workflows/ci.yml`
- Runs on push to `main` or `develop`
- Runs on pull requests to `main`
- Tests on Ubuntu + Windows, Python 3.11 + 3.12
- Uses headless mode: `QT_QPA_PLATFORM=offscreen`

**✅ Pass criteria (CI gate):**
- All tests PASS
- Exit code 0
- No SKIPPED tests in E2E

### P1.6 Reports

**Report locations:**
- UI runs: `runtime/verifications/p1/<timestamp>/`
- CLI runs: `runtime/verifications/p1/<timestamp>/` or custom `--out-dir`
- E2E tests: `runtime/fixtures/termcluster/<timestamp>/`

**Report files:**
- `P1_SCENARIO_7_REPORT.md` - Human-readable Markdown
- `P1_SCENARIO_7_REPORT.json` - Machine-readable JSON

**Report contents:**
- Environment (source DB, snapshot path, SHA256, project ID)
- Test items (kind, src_text, src_norm)
- Seeded TM entries (tm_id, translation, src_norm)
- Phase results (pre/post-extraction, post-restart)
- Failures (if any) with expected vs actual
- Summary (status, duration, final verdict)

---

## P3 Premium: Dictionary Import + Export

**Purpose:** Automated and manual verification of dictionary import wizard, conflict policies, and CSV injection protection.

### P3.1 Automated Gate Tests

**Run before manual testing:**

```bash
# Activate environment
source .venv/bin/activate  # or .venv\Scripts\activate.ps1 on Windows

# P3 test suite (all must PASS)
python test_p3_dictionary_import_csv.py       # 6 tests: CSV import
python test_p3_dictionary_import_xlsx.py      # 3 tests: XLSX import (if openpyxl available)
python test_p3_conflict_policies.py           # 5 tests: skip/overwrite/keep_both
python test_p3_export_csv_injection.py        # 3 tests: CSV injection protection
python test_p3_scenario7_gate.py              # 2 tests: Automated Scenario 7 gate
python test_p3_import_wizard_smoke.py         # 3 tests: Wizard UI instantiation

# Regression tests (verify P3 didn't break P1/M7)
python test_m7_normalization.py               # 60 tests: Normalization contract
python test_m7.py                             # M7 core functionality
python test_p1_verification.py                # 6 tests: P1 verification service
```

**✅ Pass criteria:**
- All P3 tests PASS (unittest outputs `OK`)
- All regression tests still PASS
- No runtime files committed to git
- Exit code 0 for all tests

**What each test verifies:**

- **test_p3_dictionary_import_csv.py:**
  - 2-column CSV format (he, ru)
  - Full CSV format with headers (kind, src_lang, tgt_lang, etc.)
  - Aliases handling (creates separate dict_entry rows)
  - SHA256 deduplication (same file not re-imported)
  - Cancel flag (cooperative cancellation + rollback)
  - Chunk commit (commits every 200 rows)

- **test_p3_dictionary_import_xlsx.py:**
  - 2-column XLSX format
  - Full XLSX format with headers
  - SHA256 deduplication for XLSX
  - (Skipped if openpyxl not installed)

- **test_p3_conflict_policies.py:**
  - skip: Duplicate entries skipped
  - overwrite: Existing entries updated
  - keep_both_as_variants: Both entries kept as separate rows
  - Duplicate with same translation always skipped

- **test_p3_export_csv_injection.py:**
  - CSV export sanitizes dangerous prefixes (= + - @) with ' prefix
  - JSON export does NOT sanitize (not needed)
  - sanitize_csv_cell unit test

- **test_p3_scenario7_gate.py:**
  - Creates fixture DB with term_clusters
  - Runs P1 verification service
  - Asserts PASS/PARTIAL with all phases passing
  - Verifies P3 import creates valid data for P1 verification

- **test_p3_import_wizard_smoke.py:**
  - Headless UI instantiation (no crashes)
  - All wizard components initialized
  - Scope toggle works (global/project)
  - Back button signal emitted

### P3.2 Manual Import Wizard Test

**Prerequisites:**
- P3.1 automated tests PASS
- Test database with at least one project

**How to test:**

1. **Launch Application:**
   ```bash
   python -m app.main
   ```

2. **Open Import Wizard:**
   - Menu: **Tools → Import Dictionary...**
   - Shortcut: `Ctrl+Shift+I`

3. **Test 2-Column CSV Import:**
   - Create test CSV:
     ```csv
     בית,дом
     ספר,книга
     שולחן,стол
     ```
   - Click "Browse" and select CSV file
   - Scope: **Global**
   - Conflict Policy: **skip**
   - Normalize Mode: **strict**
   - Click "▶ Run Import"
   - **Expected:** Progress bar 0→100%, log shows "Added 3 entries", green status badge "✓ Completed"

4. **Test Re-Import (SHA256 Dedup):**
   - Click "Browse" and select same CSV file
   - Click "▶ Run Import"
   - **Expected:** Log shows "File already imported (SHA256 match), skipping", status "✓ Completed", 0 entries added

5. **Test Full Format CSV:**
   - Create test CSV:
     ```csv
     kind,src_lang,tgt_lang,src_text,translation,pos,domain,status
     lemma,he,ru,בית,дом,NOUN,general,approved
     term_cluster,he,ru,בית הספר,школа,,education,approved
     ```
   - Import with same settings
   - **Expected:** 2 entries added, log shows details

6. **Test Conflict Policies:**
   - Create CSV with duplicate:
     ```csv
     בית,здание
     ```
   - Test each policy:
     - **skip:** Entry skipped, log shows conflict
     - **overwrite:** Entry updated with new translation
     - **keep_both_as_variants:** Both entries kept as separate rows

7. **Test Cancel:**
   - Create large CSV (500+ rows)
   - Click "▶ Run Import"
   - Click "✕ Cancel" mid-import
   - **Expected:** Import stops, log shows "Cancelled", no entries committed (rollback)

8. **Test CSV Export with Injection Protection:**
   - Create TM entry with dangerous value:
     ```python
     # In Python console
     from app.infra.sa_models import TMEntry
     entry = TMEntry(
         project_id=None, kind="lemma", src_lang="he", tgt_lang="ru",
         src_text="=2+2", src_norm="=2+2", translation="+危险",
         status="approved", origin="user_edit"
     )
     session.add(entry)
     session.commit()
     ```
   - Export TM to CSV (use export service or future UI)
   - Open CSV in Excel/LibreOffice
   - **Expected:** Values prefixed with ' (e.g., `'=2+2`, `'+危险`), no formula execution

**✅ Pass criteria (manual):**
- Import wizard opens without errors
- 2-column and full format CSV both import
- SHA256 dedup prevents re-import
- All conflict policies work correctly
- Cancel stops import and rolls back
- Exported CSV neutralizes injection attempts

### P3.3 Troubleshooting

**"ImportWizard crashes on startup"**
- Check QT_QPA_PLATFORM environment variable (set to 'offscreen' for headless)
- Verify PyQt6 installed: `pip show PyQt6`
- Check logs for missing database initialization

**"CSV import fails with 'Invalid format'"**
- Verify CSV is UTF-8 encoded
- Check for correct number of columns (2 for simple, 8+ for full format)
- Ensure no empty required fields (src_text, translation)

**"SHA256 dedup not working"**
- Check dict_source table has sha256 column
- Verify force_reimport=False (default)
- Different scope (global vs project) allows re-import

**"Conflict policy 'keep_both' creates only one entry"**
- Check that translations are different (same translation always skipped)
- Verify UNIQUE constraint: (dict_source_id, kind, src_lang, tgt_lang, src_norm, translation)

**"Cancel doesn't stop import"**
- Verify cancel_flag is cooperative (not terminate())
- Check chunk size (200 rows) - cancel happens between chunks
- Ensure worker.cancel() sets flag correctly

**"Excel executes formulas from exported CSV"**
- Check that sanitize_csv_cell() prefixes dangerous chars (= + - @) with '
- Verify export service uses sanitization on all text fields
- Note: JSON export should NOT sanitize

---

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

---

## P3 Automated Verification Gate

**Purpose:** Production-safe automated verification of P3 import/export/conflict functionality.

**What it does:**
1. Creates a snapshot copy of your database (never modifies production DB)
2. Runs 8 comprehensive verification steps:
   - CSV Import (2-column format)
   - CSV Import (full format with headers)
   - XLSX Import
   - Conflict Policies (skip, overwrite)
   - Chunk Commit + Cancel behavior
   - SHA256 Deduplication
   - CSV Injection Protection
   - Resolve Sanity (dict → TM override precedence)
3. Generates JSON + Markdown reports
4. Returns correct exit codes (0=PASS, 1=FAIL, 2=SKIPPED)

### Windows PowerShell

```powershell
# Run P3 verification test suite
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe test_p3_verification.py

# Run all P3 tests including regression
powershell.exe -ExecutionPolicy Bypass -File scripts\run_p3_verify.ps1
```

### Bash (macOS/Linux/Git-Bash)

```bash
# Run P3 verification test suite
export QT_QPA_PLATFORM=offscreen
source .venv/bin/activate
python test_p3_verification.py

# Run all P3 tests including regression
bash scripts/run_p3_verify.sh  # (if created)
```

### CLI Tool

```bash
# Run on production DB (creates snapshot automatically)
python -m app.tools.p3_verify

# Or specify custom DB
python -m app.tools.p3_verify --db path/to/your.db --project-id 1

# Output directory
python -m app.tools.p3_verify --out-dir runtime/verifications/p3/custom
```

**✅ Pass criteria:**
- `test_p3_verification.py`: Core verification tests pass
- `test_p3_dictionary_import_csv.py`: All CSV import tests pass (5/5)
- `test_p3_dictionary_import_xlsx.py`: All XLSX import tests pass (3/3)
- `test_p3_conflict_policies.py`: All conflict tests pass (5/5)
- `test_p3_export_csv_injection.py`: All injection protection tests pass (3/3)
- No regressions in M7 or P1 tests

**Reports:**
- `runtime/verifications/p3/<timestamp>/P3_VERIFICATION_REPORT.json`
- `runtime/verifications/p3/<timestamp>/P3_VERIFICATION_REPORT.md`

