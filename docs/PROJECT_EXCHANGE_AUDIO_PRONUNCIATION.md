# Project Exchange Policy: Audio + Pronunciation

## Scope

This policy defines what is included in project bundles (`.hdleproj`) for audio-related data.

## Current policy

- `audio_asset` files are never embedded into project bundles.
- `audio_asset` metadata is treated as operational cache and not exchanged between projects.
- `pronunciation_entry` is a global metadata layer and is excluded from project bundles.

Rationale:

- Avoid cross-project pollution for global pronunciation data.
- Keep project bundles deterministic and compact.
- Avoid unique-key conflicts on import (`lang + src_norm`) in multi-project databases.

## Recommended transfer path for pronunciation metadata

- Use dedicated pronunciation exchange (CSV/TSV import/export service), not project bundle import.
- Merge rule remains `manual override > auto`.

## Future option (not enabled now)

- Optional bundle flag `include_pronunciation_metadata` can be added later after explicit merge policy and conflict-resolution UX are finalized.
