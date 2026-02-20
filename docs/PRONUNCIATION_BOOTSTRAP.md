# Pronunciation Bootstrap (Phonikud Offline Baseline)

## Goal

Generate local baseline pronunciation metadata offline for source terms.

Default generator:

- `phonikud` (if installed locally)

## Script

`scripts/bootstrap_pronunciation.py`

Example:

```powershell
python scripts/bootstrap_pronunciation.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --lang he
```

## Key flags

- `--fill-only-missing-auto` (default behavior)
- `--rebuild-auto` (overwrite non-manual auto rows)
- `--limit N`
- `--dry-run` (collect + generate, then rollback)
- `--skip-lemmas`
- `--skip-terms`
- `--skip-user-dictionary`

## Merge and safety rules

- `manual override` is never overwritten by bootstrap.
- Writes are chunked and WAL-friendly.
- Baseline rows are tagged as `source=auto_phonikud` with confidence hint.

## Idempotency

Running bootstrap twice with fill-only mode should produce no additional updates on second run.
