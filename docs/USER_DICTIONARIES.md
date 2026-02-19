# User Dictionaries (P0)

## Access

- Global workspace: `Premium -> User Dictionaries` or `Ctrl+Shift+U`.
- Project workspace: open any project and switch to `User Dictionaries` tab.

## Key Behavior

- Add rows from `Dictionary`, `Terms`, `Term Cards`, and `Translation Management`.
- Dedupe inside each dictionary by canonical hash.
- `Hide Noise` is enabled by default.
- Translation is resolved from `tm_global`, not copied into dictionary items.
- Added rows are also materialized into `tm_entry` anchors (`source_ref=user_dictionary_add`) so they are visible in `Translation Management`.
- `origin_tm_entry_id` is stored on dictionary items and reused for future sync operations.

## Unified Status System

- Origin: `project` / `manual` / `imported` (reserved).
- Study: `new` / `learning` / `due` / `mastered` / `suspended`.
- Translation tier (truth from `tm_global`): `missing` / `mt` / `user` / `approved` / `deprecated`.
- Audio status (stub): `missing` / `ready` / `failed` (`generating` reserved).
- Noise: `is_noise` flag (with default `Hide Noise = ON`).

UI composition in `User Dictionaries`:
- `Origin` marker column
- `Study` chip column
- `Last Review` column (`Added/Again/Hard/Good/Easy`) with cell-only semantic highlight
- `Status` icon stack (translation/audio/noise) + full tooltip
- Semantic colors applied to Study/Origin/Status/Audio/Noise for instant scanning
- Top summary strip for opened dictionary:
  - `Words total`
  - review counters `Added/Again/Hard/Good/Easy`

## Scope

- Scope chip: `Current Project` / `All`.
- Default scope: `Current Project` when opened from project context, otherwise `All`.
- Active scope is shown as `Filtered by: ...`, and `Show All` is available for quick reset.
- Summary strip respects active scope and `Hide Noise` state.
- Summary strip is stable and does not depend on the search text filter.

## Translate Selected

- Uses the same batch translate dialog modes:
  - `Fill empty only`
  - `Overwrite existing`
  - `Skip non-empty`
- Uses progress UX `BatchProgressDialogV3`.
- Runs in background worker with cancel/pause/resume.
- Writes canonical translation to `tm_global` and propagates to linked `tm_entry`.

## Review Mode (SRS / SM-2)

- Toggle in header: `Browse` / `Review`.
- Review queue shows only due items for current dictionary and active scope.
- Scope-aware queue:
  - `Current Project` (when project context exists)
  - `All projects`
- Rating buttons:
  - `Again` / `Hard` / `Good` / `Easy`
- Ratings update `study_progress` (global by `canonical_hash`) using SM-2.
- Every review persists `study_progress.last_grade` and `study_progress.last_graded_at`.
- Optional inline translation edit in Review mode writes via canonical path and propagates to linked TM.
- Manual due action is available in Browse mode: `Mark Due Now` / context action `Mark Selected as Due now (N rows)`.
  - This sets linked `study_progress.due_at` to current time.
  - It does not reset review history (`review_count`, `ease_factor`, `lapse_count`, `last_grade`, `last_graded_at`).
  - Progress is global by canonical key, so duplicates linked to the same canonical hash become due together.

## Inline Edit + Context Menu

- `Translation` column is editable directly in the table.
- Inline edits write through canonical TM (`tm_global`) and propagate to linked `tm_entry`.
- Right-click on selected rows provides:
  - `Translate Selected (N rows)...`
  - `Generate Audio Selected (N rows)...`
  - `Mark Selected as Noise (N rows)`
  - `Mark Selected as Valid (N rows)`
  - `Mark Selected as Due now (N rows)`
  - `Suspend Selected (N rows)`
  - `Resume Selected (N rows)`
- Noise changes sync from User Dictionaries to `tm_global`, linked `tm_entry`, and linked source entities.
- Suspension is per-item (does not delete progress) and excludes items from Review queue.

## Legacy Canonical-Key Guard

- Legacy user-dictionary rows with non-canonical `src_norm` still resolve translation by canonical fallback lookup.
- New `Add to User Dictionary` payloads always use canonical `src_norm` from `normalize_for_tm(...)`.

## Deep Link

- `User Dictionaries` header includes `Open Translation Management`.
- `Translation Management` header includes `Open User Dictionaries`.

## Cross-View Indicators

- `Dictionary`, `Terms`, and `Term Card` rows display a saved-to-UD marker and study tooltip.
- Marker contract: `*` for saved in UD, `*!` for saved and due.
- `Dictionary`, `Terms`, `Term Card`, and `Translation Management` include a `Last Review` column.
- Cross-view rows get semantic fill by last review grade (`Added/Again/Hard/Good/Easy`) only when item is in UD.
- Rows not present in UD are not filled.
- `Translation Management` rows receive non-intrusive study tooltip enrichment.
- Metadata is resolved by batch lookup per page (no per-row SQL loops).

## Audio Column (P0)

- `Audio` column shows `missing|ready|failed` from `audio_asset`.
- Generation is source-only (`src_text`/`src_norm`), not translation-based.
- Batch generation entry points:
  - toolbar button `Generate Audio...`
  - context menu `Generate Audio Selected (N rows)...`
- Batch generation uses worker + `BatchProgressDialogV3` with cancel/pause/resume.
- Playback is still out of scope for this patch line.
