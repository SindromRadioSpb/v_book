# Smoke Test — Task 22 End-to-End

**File:** `scripts/smoke_task22_e2e.py`
**Date:** 2026-02-22
**Covers:** Task 22 — Documents metadata + Sentences workspace + TM Kind multi-select filter

---

## What It Tests

| Section | Steps | Coverage |
|---------|-------|----------|
| **A** — Document + metadata | A1–A6b | Project/corpus check, ingest via IngestWorker, metadata CRUD, link safety |
| **B** — NLP + Sentences | B7–B8 | ProcessWorker, sentence count, SentencesWorkspaceService list |
| **C** — Sentences actions | C9a–C10 | BatchTranslateWorker, PronunciationBootstrapService, BatchGenerateAudioWorker, play_async |
| **D** — TM Kind filter | D11–D12 | TranslationAdminService kinds= filter, QSettings persist/restore, None=All fallback |
| **E** — Documents filters | E13a–E13c | title_search, tag_filter, sort by level/topic/tag allowlist |

---

## How to Run

### Full E2E smoke (recommended)

```powershell
cd J:\Project_Vibe\V_book
.\.venv\Scripts\Activate.ps1

python scripts/smoke_task22_e2e.py `
    --project-id 12 `
    --doc-path "E:\andasai_mechonot\Физика. Семестр 2. Год 1\Словарь из учебника\Для программы обработчика Физика. Гос 1. Главы 1-7.docx" `
    --timeout-sec 900
```

With explicit DB path (if not at default location):

```powershell
python scripts/smoke_task22_e2e.py `
    --project-id 12 `
    --doc-path "..." `
    --db-path "M:\V_book\HDLE\hdle.db"
```

### pytest-qt wrapper (service-layer checks only, no long workers)

```powershell
# All smoke tests
python -m pytest tests/smoke/test_task22_e2e.py -q -m smoke

# Individual class
python -m pytest tests/smoke/test_task22_e2e.py::TestTMKindFilter -q
python -m pytest tests/smoke/test_task22_e2e.py::TestDocumentMetadata -q
python -m pytest tests/smoke/test_task22_e2e.py::TestSentencesService -q
```

Set env vars for pytest:

```powershell
$env:SMOKE_DB_PATH = "M:\V_book\HDLE\hdle.db"
$env:SMOKE_PROJECT_ID = "12"
$env:SMOKE_DOC_PATH = "E:\andasai_mechonot\...\Физика. Гос 1. Главы 1-7.docx"
python -m pytest tests/smoke/ -q -m smoke
```

---

## Expected Output (full PASS)

```
======================================================================
TASK 22 SMOKE RUNNER — FINAL REPORT
======================================================================
  [PASS] A1: Check project 12 exists  → project='1' (id=12) corpus_id=X src_lang=he
  [PASS] A2: Ingest document  → Ingested successfully: doc_id=N
  [PASS] A3: Document visible in service  → Visible in DocumentService.list_documents (total=N)
  [PASS] A4: Edit metadata (tag/link/level/topic)  → tag='test' link='https://...' level='gimel' topic='fisics'
  [PASS] A5: Metadata persisted in DB  → All 4 metadata fields verified in fresh DB read
  [PASS] A6a: Link click positive (https://)  → openUrl called once with: https://www.facebook.com/
  [PASS] A6b: Link click negative (javascript:)  → javascript: link correctly blocked
  [PASS] B7: NLP processing (ProcessWorker)  → NLP done (success=1 error=0) — N sentences created
  [PASS] B8: Sentences tab data  → total=N sentences, page1=M rows
  [PASS] C9a: Translate Selected (BatchTranslateWorker)  → Translated K/10 sentences
  [PASS] C9b: Pronunciation Bootstrap  → After bootstrap: K/10 texts have pronunciation entries
  [PASS] C9c: Generate Audio (BatchGenerateAudioWorker)  → Audio ready: K/N norms
  [PASS] C10: Play Audio (monkeypatched)  → play_async called: src_lang=he norm='...'
  [PASS] D11: Kind filter applied (lemma+surface)  → all=N entries, kinds=[...] → M entries
  [PASS] D12: Kind filter persisted in QSettings  → QSettings persistence OK; None=All: N==N
  [PASS] E13a: Title search  → Title search 'Физика' → N results — doc found
  [PASS] E13b: Tag filter  → Tag filter 'test' → M docs, doc found
  [PASS] E13c: Sort stability  → Sort by level/topic/tag/file_name/doc_id: all stable
======================================================================
RESULT: 18/18 steps PASSED
OVERALL: PASS
```

---

## Expected FAIL scenarios and diagnostics

| Step | Common Cause | Expected Message |
|------|-------------|-----------------|
| A2 | File not found | `Document file not found: ...` — check `--doc-path` |
| A2 | Unsupported extension | `Ingest did not produce a doc_id` |
| B7 | Stanza not installed | Uses `use_mock=True` automatically — should still PASS |
| C9a | No MT provider configured | `BatchTranslateWorker failed: ...` — configure MT provider |
| C9c | No TTS provider configured | `BatchGenerateAudioWorker failed: ...` — configure TTS |
| C9b | No niqqud source data | `WARN: acceptable if no niqqud source is configured` |
| D11–D12 | Empty TM database | All assertions still pass (empty counts are valid) |

---

## Design Notes

### Worker contract compliance
All long operations call the **same QThread workers** as the UI:
- `IngestWorker` — document import
- `ProcessWorker` — NLP with `use_mock=True` (matches UI fallback when Stanza absent)
- `BatchTranslateWorker` — translations
- `BatchGenerateAudioWorker` — audio

### QMessageBox interception
All `QMessageBox.question/warning/information/critical` calls are intercepted globally.
Questions auto-answer "Yes" so workers proceed. No modal hangs.

### QDesktopServices.openUrl interception
Link-click tests monkeypatch `QDesktopServices.openUrl` to capture calls.
Original is always restored in `finally`.

### QSettings backup/restore
Keys modified: `tm_panel/kind_filter`
Restored in `finally` block — even on FAIL or exception.

### No N+1 queries
`SentencesWorkspaceService` batch overlay lookups verified in `tests/test_sentences_workspace_service.py`.

### Log file
Written to `logs/smoke_task22_YYYYMMDD_HHMMSS.log` — DEBUG level includes all service calls.

---

## Rollback / Cleanup

The smoke runner does not modify persistent state except:
1. **Adds one document** to corpus (if not already present) — remove via Documents UI → Delete
2. **Adds TM entries** for translated sentences (kind='surface') — harmless; visible in TM Panel
3. **QSettings `tm_panel/kind_filter`** — always restored to pre-test value

To fully clean up:
```powershell
# Delete test document from project 12 via UI (Documents tab → select → Delete)
# Or directly in DB:
# DELETE FROM source_document WHERE corpus_id=X AND file_name LIKE '%Физика%';
```
