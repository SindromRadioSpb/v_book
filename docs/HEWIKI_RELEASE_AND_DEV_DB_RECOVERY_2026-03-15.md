# Hewiki release and dev DB recovery (2026-03-15)

## Scope

This note records the bounded operational recovery of the two large hewiki DB
targets that remain important after the cold/recovery program:

- release reconnect target:
  - `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
- ongoing development / operator test target:
  - `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`

The goal of this wave was not a new cold-hunt. It was to restore both
canonical DB paths to a usable lower-layer state before the release decision.

## Starting state

Both DBs failed the current ship-gate corruption probe:

- `hewiki_gpu_processing.db`
- `hewiki_gpu_processing test.db`

Both showed `btreeInitPage() returns error code 11` on the corruption probe,
which made them unsuitable as:

- the post-install reconnect DB for release smoke
- the heavy-project DB for continued development testing

## Recovery path used

For both DBs:

1. `scripts/repair_db_corruption.py` with known-good sqlite3 CLI:
   - `C:\msys64\ucrt64\bin\sqlite3.exe`
2. recovered DB artifact created out-of-place
3. `scripts/repair_fts_schema.py` run on the recovered DB when `.recover`
   restored structure but left `sentence_fts_row_mismatch`
4. recovered DB promoted back onto the canonical original path

## Current state

### Release reconnect target

Canonical path:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`

Current lower-layer validation:

- `app.main --self-check db_open`:
  - `ok = true`
  - `schema_version = 42`
  - `supported_schema_version = 42`
- `scripts/repair_fts_schema.py --dry-run`:
  - `status = OK`
  - `sentence_fts = 13,387,588`
  - `document_sentence = 13,387,588`

Role:

- this is the heavy reconnect target to use after install/restart smoke
- this is the DB to treat as the clean release-facing reconnect candidate

### Ongoing development / operator test target

Canonical path:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`

Current lower-layer validation:

- `app.main --self-check db_open`:
  - `ok = true`
  - `schema_version = 42`
  - `supported_schema_version = 42`
- `scripts/repair_fts_schema.py --dry-run`:
  - `status = OK`
  - `sentence_fts = 13,389,386`
  - `document_sentence = 13,389,386`

Role:

- keep using this DB for ongoing heavy-project testing during further
  development
- do not confuse it with the release reconnect sign-off target

## Important boundary

This wave restores the DB artifacts to a usable lower-layer state.

It does **not** mean the whole release is signed off.

Still pending for release:

- fresh `dist` rebuild from current `main`
- fresh installer rebuild from current `main`
- frozen self-check pass on rebuilt artifacts
- installed/VM smoke on rebuilt artifacts
- final ship-gate/prebuild evidence using the chosen release DB
