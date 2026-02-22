# User Guide — Sentences Workspace

**Features:** Task 22 + Task 23 (Sentences UI parity)
**Date:** 2026-02-22

---

## Overview

The **Sentences** tab provides a sentence-level workspace for each project.
Each row represents one sentence extracted during NLP processing.

You can:
- Browse and filter sentences by document or text content.
- Batch translate, generate audio, run pronunciation bootstrap, and play audio — all reusing existing pipelines.

---

## Opening the Tab

1. Open any project (Documents view).
2. Click the **Sentences** tab in the project tab bar.
3. All NLP-processed sentences for the project load automatically.

---

## Filters

| Control | Description |
|---------|-------------|
| **Document** combo | Filter rows to a single document (or All Documents) |
| **Search** field | Case-insensitive substring match on sentence text |
| **Clear** button | Reset all filters |

Filters apply with 400ms debounce (no excessive DB hits).

---

## Table Columns

| Column | Description |
|--------|-------------|
| ID | Sentence ID (internal) |
| Document | File name of the source document |
| # | Sentence index within document |
| Sentence Text | Original Hebrew sentence |
| Translation | TM translation (kind=surface) if available |
| Niqqud | Pronunciation text if available |
| Audio | Audio status: ready / missing / failed |

---

## Batch Actions

### Translate Selected
1. Select one or more rows.
2. Click **Translate Selected...** (or right-click → Translate Selected).
3. Choose provider and write mode in the dialog.
4. Click OK. A progress dialog (V3) shows real-time progress with cancel/pause.

Translations are stored in Translation Memory as `kind=surface` entries.

### Generate Audio
1. Select rows.
2. Click **Generate Audio...**.
3. Choose provider and write mode.
4. Click OK. Audio is generated for the selected sentence texts.

### Pronunciation Bootstrap
1. Optionally select specific rows.
2. Click **Pronunciation Bootstrap...**.
3. The existing bootstrap dialog opens. If rows selected, only those sentences are processed.

### Play Audio
1. Select a row with `Audio: ready`.
2. Click **▶ Play** (or right-click → ▶ Play Audio Selected).
3. Audio plays via the system audio service.

The **Audio column** also shows an inline ▶ button for any row with `ready` status — click it to play that row immediately without selecting.

### Pronunciation Bootstrap
1. Optionally select specific rows.
2. Click **Pronunciation Bootstrap...** or right-click → **Pronunciation Bootstrap Selected (N)…**.
3. The bootstrap dialog opens. The **Sentences** source checkbox is auto-checked when rows are pre-selected.
4. When the Phonikud model is active, the **Niqqud column** fills with vowelled Hebrew after bootstrap completes.

### Add / Fix Pronunciation (single row)
1. Right-click any row.
2. Select **Mispronounced → Add Pronunciation…**
3. The Edit Pronunciation dialog opens for that sentence's normalized form.
4. Save changes — the Niqqud column refreshes automatically.

---

## Pagination

- Default page size: 100 rows (configurable via Page size dropdown).
- Navigate with « ‹ › » buttons or the page spinbox.
- Page size is persisted between sessions.

---

## Troubleshooting

**No sentences appear** → The project documents have not been processed with NLP yet. Go to the Documents tab and click "Process with NLP".

**Translation column empty** → No TM surface entries exist for these sentences yet. Use "Translate Selected" to create them.

**Audio shows "missing"** → Run "Generate Audio Selected" to generate audio for these sentences.

**Niqqud column empty after bootstrap** → The Phonikud pronunciation model may not be configured or available. Check Settings → Pronunciation → Phonikud status. When the model is unavailable, the bootstrap correctly skips writing unvowelled text as a placeholder — the column stays empty rather than showing misleading content.

**Niqqud column shows text without vowel marks** → This can happen if old stale entries exist from a previous bootstrap run when the model was in fallback mode. Re-run the bootstrap after configuring the model — new proper entries will overwrite the stale ones.
