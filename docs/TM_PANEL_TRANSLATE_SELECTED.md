# TM Panel: Translate Selected

Date: 2026-02-16
Status: Implemented

## Summary

Translation Management Panel now includes `Translate Selected...` with the same batch dialog modes used in Dictionary/Terms:

- Provider mode: `chain` or `force:<provider>`
- Write mode: `FILL_EMPTY`, `OVERWRITE`, `SKIP_NON_EMPTY`
- Scope: `current_page` or `all_filtered`

## Runtime behavior

- `current_page` uses `BatchTranslateWorker` + `BatchProgressDialog`.
- `all_filtered` uses `TranslateAllFilteredWorker` + `BatchProgressDialogV3`.
- TM rows are translated through `BatchMTTranslateService` with `entity_type="tm_entry"`.
- `tm_entry.translation` is updated while preserving existing `status`, `origin`, and `is_noise`.
- `tm_global` upsert/link remains in the same write path used by existing batch flows.

## All-filtered ID selection

TM all-filtered selection is SQL-based (no UI select-all):

- `TranslationAdminService.count_tm_ids_for_translation(...)`
- `TranslationAdminService.fetch_tm_ids_for_translation(...)`

Both methods apply TM filters and write mode semantics. IDs are fetched as `tm_id ASC` for deterministic chunking.

## Manual smoke matrix

1. Select rows with empty/non-empty translations, run `FILL_EMPTY`: only empty rows get translations.
2. Select rows with non-empty translations, run `OVERWRITE`: values are overwritten.
3. Select rows with non-empty translations, run `SKIP_NON_EMPTY`: non-empty values are unchanged.
4. Run `all_filtered` on large filtered set: progress dialog stays responsive and supports cancel.
