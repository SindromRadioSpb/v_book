# User Dictionaries (P0) Plan

## Canonical Contract

- Canonical key: `(src_lang, tgt_lang, kind, src_norm)`.
- `canonical_hash = SHA256(src_lang + tgt_lang + kind + src_norm)`.
- `user_dictionary_item` stores study targets only.
- Translation is resolved via `tm_global` join, not persisted in `user_dictionary_item`.

## Data Model (P0)

- `user_dictionary`: dictionary metadata.
- `user_dictionary_item`: dictionary content with dedupe by `UNIQUE(dictionary_id, canonical_hash)`.
- `audio_asset`: TTS architecture stub for status lookup (`missing|ready|failed`).

## P0 UX Scope

- New project tab: `User Dictionaries`.
- Dictionary CRUD: create/rename/delete.
- Item operations: add manual, remove selected, translate selected.
- Filters: search, kind, translation empty/non-empty, study state, hide noise (default ON).
- Translation progress: `BatchProgressDialogV3`, background worker, cancel/pause/resume.

## Integration Points

- `Dictionary`: context menu action to add selected rows.
- `Terms`: context menu action to add selected rows.
- `Term Cards`: queue context menu action to add selected rows.
- `Translation Management`: context menu action to add selected rows.
