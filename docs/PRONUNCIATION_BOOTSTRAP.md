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
- Bootstrap stores by canonical key `(lang, src_norm)` but infers from preferred source surface text.
- Preferred source selection is deterministic and favors:
  - separator-free source forms,
  - phrase forms with spaces,
  - longer source text (keeps Hebrew prefixes/articles),
  - stable source priority + id tie-breaker.
- Generated niqqud goes through sanitizer before persist (`_` -> space, `|` autofix/reject policy).

## Idempotency

Running bootstrap twice with fill-only mode should produce no additional updates on second run.

## Quality notes

- If model output contains malformed separators (`_`, `|`), the persisted value is sanitized and tagged in notes (`qc:*`).
- Spacing-only structure drift (same Hebrew letters, different spacing such as `ה|חומר`) is accepted and tagged with `qc:source_spacing_variation`.
- If auto-generated pronunciation becomes invalid after sanitize, bootstrap skips that row and reports failure count.

## Premium UI gate (in-app)

Entry point:

- `Tools -> Translation -> Pronunciation Bootstrap...`
- Selection-scoped launch from table workspaces:
  - `Dictionary`, `Terms`, `User Dictionaries`, `Term Cards`, `Translation Management`
  - Button: `Pronunciation Bootstrap...` (enabled on row selection)
  - Context menu: `Pronunciation Bootstrap Selected (N rows)...`

Capabilities:

- Model selection and persistence (`pronunciation/phonikud/model_path`):
  - direct `.onnx` file selection (preferred),
  - or folder selection (auto-picks `*int8.onnx` first, then first `*.onnx`).
- Health check via worker (no UI freeze), with mode/status/latency/samples.
- Health check is local/offline-only for ONNX paths:
  - no implicit Hugging Face downloads during readiness check,
  - bounded timeout,
  - bootstrap cancel can interrupt the health preflight instead of hanging indefinitely.
- Worker-safe bootstrap with `BatchProgressDialogV3`:
  - stages, counters, activity log, cancel/pause/resume.
- Selection scope preserves existing source checkboxes:
  - `Lemmas`, `Terms`, `User Dictionaries`
  - selected rows are filtered by checked source groups before generation.
- Fallback warning before bootstrap run.
- Dry-run support with rollback summary.

## Resources Manager and first-run integration

Bootstrap readiness is now part of unified resource health:

- `Tools -> Resources Manager...` shows model status and remediation actions.
- `Tools -> Run Health Check...` reports pronunciation/sentence bootstrap readiness.
- first-run wizard surfaces missing local models and routes user to Resources Manager.

Deterministic model path resolution order:

1. UI setting `pronunciation/phonikud/model_path`
2. env `PHONIKUD_MODEL_PATH`
3. auto-discovery in `<data_root>/models/phonikud` (`*int8.onnx` preferred)

`data_root` resolves through `ResourcePaths` (`%LOCALAPPDATA%\HDLE` by default on Windows).

## Health-check contract

- `Pronunciation Bootstrap` readiness checks must not fetch remote assets implicitly.
- If local ONNX/tokenizer prerequisites are missing, health-check fails fast with remediation instead of hanging.
- `Cancel` during bootstrap must stop at health-check safe points and return `cancelled`, not require process kill.
