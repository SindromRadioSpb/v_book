# Gap Matrix — Sentences / TM / Documents Iteration (Task 22)

**Date:** 2026-02-21

---

## Feature vs. Readiness Matrix

| Feature | DB Ready | Service Ready | UI Ready | Tests | Gap |
|---------|----------|---------------|----------|-------|-----|
| Doc metadata (tag/link/level/topic) | ❌ | ❌ | ❌ | ❌ | PATCH-02/03/04 |
| Doc title search | ✅ (file_name col exists) | ❌ | ❌ | ❌ | PATCH-03/04 |
| Sentences workspace tab | ✅ (document_sentence table) | ❌ | ❌ | ❌ | PATCH-05/06 |
| Sentences batch translate | ✅ (batch engine v2 exists) | ❌ wire | ❌ | ❌ | PATCH-06 |
| Sentences batch audio | ✅ (audio workers exist) | ❌ wire | ❌ | ❌ | PATCH-06 |
| Sentences pronunciation bootstrap | ✅ (bootstrap service exists) | ❌ wire | ❌ | ❌ | PATCH-06 |
| TM Kind multi-select | ✅ (kind column exists) | ✅ (query supports list) | ❌ | ❌ | PATCH-07 |
| TM Kind persistence | ✅ | ✅ | ❌ | ❌ | PATCH-07 |

---

## Patch Series Summary

| Patch | What | Files | Risk |
|-------|------|-------|------|
| PATCH-01 | Docs/Audit gate | docs/TASK_SENTENCES_WORKSPACE_AUDIT.md, this file | None |
| PATCH-02 | DB migration + ORM + DTO | 023_documents_metadata.sql, sa_models.py, dto.py | Low (additive) |
| PATCH-03 | Document service APIs | document_service.py (new) | Low |
| PATCH-04 | Documents UI upgrade | documents_view.py, models_qt.py | Medium (column count change) |
| PATCH-05 | Sentences service | sentences_workspace_service.py (new) | Low |
| PATCH-06 | Sentences UI tab | sentences_view.py (new), main_window tab reg | Medium |
| PATCH-07 | TM Kind multi-select | translation_management_panel.py, settings | Low |
| PATCH-08 | Evidence docs | USER_GUIDE_SENTENCES_WORKSPACE.md, UI_DOD_EVIDENCE | None |

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Additive columns on source_document (not separate table) | Simpler joins, no FK complexity, doc metadata is 1:1 with doc |
| level enum as CHECK constraint | SQL-level validation, consistent with existing status/origin patterns |
| link_url whitelist: http/https only | Prevents javascript:, file:// execution via QDesktopServices |
| Sentences paginated (page_size=100 default) | document_sentence can have 100k+ rows; full-scan in UI = freeze |
| kind multi-select stored as JSON list in QSettings | Consistent with existing JSON persistence pattern in SettingsService |
| kind=[] (empty selection) → show all kinds | Safest fallback; empty = no filter applied |
| Reuse V3 progress dialog for sentences batch ops | Prevents code duplication; V3 has pause/resume/cancel/heartbeat |

---

## Known Limits (as of PATCH-08)

1. Sentences view does not support inline edit of translation (read from TM overlay only).
2. doc tag/topic fields are free-text (no validation of allowed values beyond length).
3. link_url supports single URL per document (not multiple links).
4. Sentences pagination default page size = 100 (configurable via UI in future iteration).
5. TM kind multi-select does not support "OR" across kinds — all selected kinds included.
