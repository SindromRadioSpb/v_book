# Project Exchange Policy: Audio + Pronunciation

## Scope

This policy defines what is included in project bundles (`.hdleproj`) for audio-related data.

## Current policy

- `audio_asset` files are never embedded into project bundles.
- `audio_asset` metadata is treated as operational cache and not exchanged between projects.
- `pronunciation_entry` table itself remains excluded from payload DB copy.
- Optional sidecar `pronunciation_metadata.tsv` may be included in bundle metadata section.

Rationale:

- Keep payload schema deterministic while allowing controlled metadata exchange.
- Preserve global-key safety (`lang + src_norm`) with merge-on-import rules.
- Avoid embedding audio binaries and keep bundles compact.

## Recommended transfer path for pronunciation metadata

- Dedicated pronunciation exchange (CSV/TSV/PLS) remains supported.
- Bundle sidecar import uses the same merge rule: `manual override > auto/import`.

## Bundle sidecar behavior

- Export option `include_pronunciation_metadata` controls sidecar inclusion.
- Sidecar contains project-intersection norms only.
- Import merges sidecar after main payload import and appends a summary warning line with counts.
- Very large bundles may still exceed global archive size policy; this is expected and should be surfaced as a user-facing warning.
