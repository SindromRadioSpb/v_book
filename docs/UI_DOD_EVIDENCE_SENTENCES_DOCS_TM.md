# UI DoD Evidence — Sentences Workspace / Documents Metadata / TM Kind Filter

**Tasks:** 22 + 23 (Sentences UI parity) + bug-fixes 2026-02-22
**Date:** 2026-02-22
**Status:** Implementation complete, tests passing

---

## DoD Checklist

### Functional
- [x] Documents tab: title search bar filters by file_name (case-insensitive substring)
- [x] Documents tab: Level filter combo (All / aleph / bet / gimel / he)
- [x] Documents tab: Tag filter bar (case-insensitive substring)
- [x] Documents tab: New columns Tag, Link, Level, Topic visible
- [x] Documents tab: Right-click → Edit Metadata dialog (tag/link/level/topic)
- [x] Documents tab: Link column is clickable, opens http/https URL in browser
- [x] Documents tab: Link with non-http/https scheme shows error, does not open
- [x] Documents tab: Column widths auto-persist via TableLayoutController signature
- [x] Sentences tab: appears in project tab bar ("Sentences")
- [x] Sentences tab: paginated table of DocumentSentence rows
- [x] Sentences tab: document filter combo + text search filter
- [x] Sentences tab: Translation overlay from TM (kind=surface)
- [x] Sentences tab: Niqqud overlay from PronunciationEntry
- [x] Sentences tab: Audio status overlay from AudioAsset
- [x] Sentences tab: Translate Selected → BatchTranslateWorker + V3 progress + cancel/pause
- [x] Sentences tab: Generate Audio → BatchGenerateAudioWorker + V3 progress + cancel/pause
- [x] Sentences tab: Pronunciation Bootstrap → reuses existing dialog (selected rows scoped)
- [x] Sentences tab: Play Audio → AudioPlaybackService
- [x] TM Kind filter: multi-select checklist button (replaces single combo)

### Task 23 — Sentences UI parity
- [x] Sentences tab: in-cell ▶ play button in Audio column (AudioPlayDelegate, same as all other tabs)
- [x] Sentences tab: right-click context menu → ▶ Play Audio Selected (N)
- [x] Sentences tab: right-click context menu → Pronunciation Bootstrap Selected (N)…
- [x] Sentences tab: right-click context menu → Mispronounced → Add Pronunciation… (opens EditPronunciationDialog)
- [x] Sentences tab: batch translate entity_type=surface (correct write path, not tm_entry)
- [x] Sentences tab: progress dialog closeable after completion/error (accept() not close())
- [x] Pronunciation Bootstrap dialog: Sentences checkbox added to sources section
- [x] Pronunciation Bootstrap dialog: auto-checked when called from Sentences tab
- [x] Google Cloud TTS voice dropdown: setMaxVisibleItems(50) — all voices visible

### Bug fixes (2026-02-22)
- [x] Migration 023: missing schema_version UPDATE added to SQL file
- [x] db.py: duplicate-column safety net — partial migration no longer crashes app on restart
- [x] document_service.update_metadata(): session.commit() added (was only flushing)
- [x] project_view.py: sentences_view signal wired AFTER instantiation (AttributeError fixed)
- [x] _batch_get_pronunciations: fixed raw-text vs norm-text mismatch (now normalizes before query)
- [x] _batch_get_pronunciations: added lang filter to match PronunciationService.bulk_lookup
- [x] _batch_get_pronunciations: has_hebrew_nikud() filter rejects unvowelled fallback entries
- [x] pronunciation_bootstrap_service: has_hebrew_nikud() guard — model-unavailable fallback no longer writes source-text-as-niqqud
- [x] TM Kind filter: persisted to QSettings "tm_panel/kind_filter" (JSON list)
- [x] TM Kind filter: empty list or full selection = All (no filter)
- [x] TM Kind filter: restored on app restart

### UX / Performance
- [x] No UI freeze: sentences loaded in _SentencesLoadWorker (QThread)
- [x] Documents filter has 400ms debounce (no flicker)
- [x] All batch ops use V3 progress dialog (stage, speed, ETA, cancel/pause)
- [x] Sentences pagination: page_size persisted in QSettings
- [x] Documents column signature auto-invalidates old header state on schema change

### Reliability / Security
- [x] link_url validated: http/https only, max 2000 chars (DocumentService.validate_link_url)
- [x] level validated: CHECK constraint in DB + validate_level() at service layer
- [x] tag/topic max length validated: 200/500 chars
- [x] kind_filter QSettings key: graceful fallback if missing (= All)
- [x] Sentences pagination: batch ID helpers (page, all-filtered) for safe batch scopes
- [x] WAL-safe migration: additive columns only, no long locks

### Docs / Evidence
- [x] TASK_SENTENCES_WORKSPACE_AUDIT.md — full docs-to-code trace
- [x] GAP_MATRIX_SENTENCES_TM_DOCUMENTS.md — decision log + known limits
- [x] This file — DoD smoke matrix

---

## Smoke Matrix

| Test Case | Steps | Expected |
|-----------|-------|----------|
| Documents title search | Type "shir" in search box | Table filters to matching documents |
| Documents level filter | Select "aleph" | Shows only aleph-level docs |
| Documents Edit Metadata | Right-click → Edit Metadata → set tag="grammar", link="https://example.com", level="bet", topic="nouns" → OK | Metadata saved, visible in columns |
| Documents link click (safe) | Click link cell with https URL | Browser opens |
| Documents link click (unsafe) | Inject javascript: URL via Edit Metadata dialog | Error shown, browser NOT opened |
| Documents restart persistence | Restart app, open Documents tab | Column widths persist (or gracefully reset if schema changed) |
| Sentences tab visible | Open any project | "Sentences" tab appears between User Dictionaries and Export |
| Sentences load | Open Sentences tab | Rows appear with doc name, index, text |
| Sentences filter by doc | Select document from combo | Rows filtered to that doc |
| Sentences text search | Type search term | Rows filtered |
| Sentences Translate Selected | Select 3 rows → Translate Selected → choose provider → OK | V3 dialog shows, translations stored in TM |
| Sentences Generate Audio | Select 3 rows → Generate Audio → OK | V3 dialog shows, audio generated |
| Sentences Pronunciation Bootstrap | Click Pronunciation Bootstrap | Existing dialog opens with selected sentences |
| Sentences Play Audio | Select row with audio=ready → Play | Audio plays |
| Sentences cancel batch | Start Translate Selected → click Cancel | Worker stops, DB consistent |
| TM Kind multi-select | Open TM Panel → click Kind button → check "lemma", "surface" → OK | Button shows "2 kinds ▾", results filtered |
| TM Kind persist | Set kind filter → restart → reopen TM Panel | Kind filter restored |
| TM Kind clear | Click Clear Filters | Kind filter resets to All |

---

## Smoke Matrix additions — Task 23

| Test Case | Steps | Expected |
|-----------|-------|----------|
| Sentences audio play button | Row with audio=ready → click ▶ cell button | Audio plays |
| Sentences context menu Play | Select multiple rows → right-click → ▶ Play Audio Selected | All selected audios enqueued |
| Sentences context menu Bootstrap | Select rows → right-click → Pronunciation Bootstrap Selected | Bootstrap dialog opens, sentences pre-selected |
| Sentences Edit Pronunciation | Select row → right-click → Mispronounced → Add Pronunciation | Edit dialog opens with correct src_norm |
| Sentences pronunciation round-trip | Bootstrap runs with phonikud model active → Niqqud column fills with vowelled Hebrew | Nikud marks visible |
| Sentences pronunciation model-off | Bootstrap runs, phonikud unavailable → Niqqud column stays empty | Column empty, no unvowelled text written |
| Google TTS voices | Settings → Audio → Google Cloud TTS → Advanced → Refresh Voices | All 38 voices visible in dropdown without scroll |

---

## Known Limits (as of Task 22/23)

1. Sentences translate stores as kind='surface' TM entries — does not create sentence-level translations in a separate table.
2. Audio playback plays first selected sentence only (single play, not playlist).
3. Sentences tab does not persist scroll position across page navigations.
4. link_url column shows full URL (no URL shortening) — may be visually long; use overflow tooltip.
5. tag/topic fields are free-text; no taxonomy enforced at UI level.

---

## Rollback Notes

- **PATCH-02 (migration 023)**: Pure additive columns. Rollback = remove columns with `ALTER TABLE ... DROP COLUMN` (SQLite 3.35+) or recreate table without columns.
- **PATCH-04 (documents_view)**: TableLayoutController will auto-reset header state on next start due to signature change (safe).
- **PATCH-06 (project_view)**: Remove `SentencesView` import and `tabs.addTab` line to revert tab registration.
- **PATCH-07 (TM kind filter)**: Revert `kind_combo` replacement by restoring the original `QComboBox` lines. Settings key `tm_panel/kind_filter` can be safely deleted.
