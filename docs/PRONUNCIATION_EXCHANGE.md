# Pronunciation Exchange (Metadata-Only)

## Scope

This document defines safe exchange rules for pronunciation metadata:

- manual overrides,
- auto baseline entries,
- import channels (`CSV/TSV`, `PLS`).

No audio binaries are included in this flow.

## Data model contract

`pronunciation_entry` key:

- `lang`
- `src_norm`

Payload fields:

- `niqqud_text`
- `ipa`
- `reading_text`
- `source`
- `confidence`
- `is_override`
- `notes`

## Merge semantics

- `is_override=1` (manual) always wins.
- Incoming auto/import rows cannot overwrite a manual row.
- Auto rows can fill missing fields.
- Optional explicit overwrite is allowed only for non-manual rows.

## Formats

### CSV/TSV columns

Fixed order:

`lang,src_norm,niqqud_text,ipa,reading_text,source,confidence,is_override,notes`

### PLS (basic profile)

- `xml:lang` -> `lang`
- `lexeme/grapheme` -> `src_norm`
- `phoneme alphabet=\"ipa\"` -> `ipa`
- imported rows get `source=import_pls` (unless imported as manual override)

## Project Exchange integration

- Bundle can include optional `pronunciation_metadata.tsv`.
- Sidecar contains only project-intersection norms (metadata-only subset).
- On import, sidecar is merged with the same manual-wins semantics.
