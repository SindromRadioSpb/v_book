# Pronunciation Bootstrap (Phonikud Offline Baseline)

## Goal

Generate local baseline pronunciation metadata offline for source terms.

Default generator:

- `phonikud` (if installed locally)

Runtime modes:

- `real_inference`: real model inference is active (preferred).
- `fallback`: deterministic fallback path is active (quality may be degraded).
- `error`: runtime/import/model path failure.

For real baseline quality, configure local model checkpoint path (`PHONIKUD_MODEL_PATH` or UI setting).

## Script

`scripts/bootstrap_pronunciation.py`

Example:

```powershell
python scripts/bootstrap_pronunciation.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --lang he
```

Optional model path and gate:

```powershell
python scripts/bootstrap_pronunciation.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --lang he --model-path "J:\Models\phonikud"
```

Health banner in CLI now reports:

- `status=ok|fallback|error`
- `mode=real_inference|fallback|error`
- sample input/output pairs.

## Key flags

- `--fill-only-missing-auto` (default behavior)
- `--rebuild-auto` (overwrite non-manual auto rows)
- `--limit N`
- `--dry-run` (collect + generate, then rollback)
- `--skip-lemmas`
- `--skip-terms`
- `--skip-user-dictionary`
- `--model-path <path>` (optional)
- `--disable-phonikud` (forces disabled/error mode)

## Merge and safety rules

- `manual override` is never overwritten by bootstrap.
- Writes are chunked and WAL-friendly.
- Baseline rows are tagged as `source=auto_phonikud` with confidence hint.
- UI and CLI expose generator mode explicitly (real/fallback/error).

## Idempotency

Running bootstrap twice with fill-only mode should produce no additional updates on second run.

## Premium UI gate (in-app)

Entry point:

- `Tools -> Translation -> Pronunciation Bootstrap...`

Capabilities:

- Model selection and persistence (`pronunciation/phonikud/model_path`):
  - direct `.onnx` file selection (preferred),
  - or folder selection (auto-picks `*int8.onnx` first, then first `*.onnx`).
- Health check via worker (no UI freeze), with mode/status/latency/samples.
- Worker-safe bootstrap with `BatchProgressDialogV3`:
  - stages, counters, activity log, cancel/pause/resume.
- Fallback warning before bootstrap run.
- Dry-run support with rollback summary.
