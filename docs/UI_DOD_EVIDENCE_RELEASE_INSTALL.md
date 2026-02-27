# UI DoD Evidence: Release and Installer Hardening

## Scope

This evidence covers:

- deterministic resource paths,
- installer component flow (`Core / Local Models / Baseline`),
- in-app Resources Manager,
- first-run wizard,
- unified health check remediation.

## Manual smoke matrix (clean machine)

1. Install `Core Application` only.
2. Start app and verify first-run wizard opens.
3. In wizard Step 1, keep default data folder and continue.
4. In wizard Step 2, verify required model checks show missing state.
5. In wizard Step 3, skip baseline installation.
6. In wizard Step 5, run health summary and verify pronunciation + sentence niqqud checks show actionable remediation.
7. Open `Tools -> Resources Manager...`.
8. Verify table contains:
   - `Phonikud Pronunciation Model`,
   - `Sentence Niqqud Model`,
   - `Hebrew Wikipedia Baseline`.
9. Select pronunciation model and run `Import from File...` with ONNX payload.
10. Verify status changes to `installed` (or checksum-corrupted if payload does not match manifest checksum).
11. Select baseline row and import `.hdleproj` bundle.
12. Verify import worker progress runs without UI freeze and baseline project appears in dashboard.
13. Click `Run Health Check` from Resources Manager and verify updated report.
14. Restart app; verify `resources/data_root` and installed statuses persist.
15. Run app with CLI flag:
    - `python -m app.main --open-resources-manager`
    - verify manager opens on startup.
16. Run app with CLI flag:
    - `python -m app.main --run-health-check`
    - verify health dialog appears and reports checks.
17. Install with optional installer components (`Local Models`, `Baseline`) when available in installer payload and verify files are placed under `%LOCALAPPDATA%\HDLE`.
18. Uninstall app and verify user data folder preservation policy works as documented.

### DB Selection smoke matrix

- `DBSEL-01`: First-run wizard -> choose `Use Hebrew Wikipedia Baseline (processed)` -> finish -> restart -> selected baseline DB is active.
- `DBSEL-02`: `Tools -> Switch Database...` -> choose `Default DB (AppData)` -> `Switch & Restart` -> default DB is active.
- `DBSEL-03`: `Tools -> Switch Database...` -> choose invalid/missing path -> clear non-crashing error -> no switch applied.

## Non-functional checks

- No hardcoded dev path (`M:\...`) is used in runtime resource resolution.
- No long-running resource operation runs in UI thread.
- Downloads/imports run in worker with progress and cancel.
- Checksum mismatch does not activate corrupted payload.
- Resource writes happen only under user-writable data root.

## Regression evidence commands

```powershell
python -m pytest tests/test_resource_paths.py tests/test_resource_registry.py tests/test_health_check_service.py tests/test_resource_download_worker.py -q
python -m pytest tests/test_workspace_app_window_contract.py tests/test_phonikud_adapter_modes.py tests/test_pronunciation_bootstrap_ui_wiring.py tests/test_project_exchange_bundle_extras.py -q
```

Expected:

- all tests pass,
- no new warnings/errors in touched release/resource modules.

## Artifacts checklist

- Screenshot: Installer component selection page.
- Screenshot: First-run wizard Step 2/5 (local models status).
- Screenshot: Resources Manager with status table.
- Screenshot: Health Check report with remediation.
- Screenshot: Baseline import completion message.
- Screenshot: First-run wizard DB step (default/existing/baseline options).
- Screenshot: Switch Database dialog with current DB metadata + restart CTA.
- Screenshot: DBSEL-03 invalid path warning (single error, app alive).

## Hewiki Large-DB smoke (installer)

Target DB for manual smoke and profiling:

- `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`

Pre-smoke prerequisite (run once per target DB when FTS is uncertain):

```powershell
python scripts/repair_fts_schema.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db"
```

If bulk FTS repopulation fails on a damaged source DB, run schema-only recovery:

```powershell
python scripts/repair_fts_schema.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --skip-rebuild
```

Expected:

- script returns `status=OK` or `status=REPAIRED`,
- JSON evidence is saved to `build/logs/fts_repair_*.json`.

Corruption prerequisite (when benchmark or probes hit `database disk image is malformed`):

```powershell
python scripts/repair_db_corruption.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db"
```

Expected:

- script returns `OK`, `SALVAGED_OK`, or `SALVAGED_WITH_WARNINGS`,
- JSON evidence is saved to `build/logs/db_corruption_repair_*.json`,
- recover log is saved to `build/logs/db_recover_*.log`.

### Smoke cases

1. `PHON-01`: run prebuild validate gate and confirm required local module check includes `phonikud` and passes import.
2. `PHON-02`: start installed app, open `Tools -> Run Health Check...`, verify pronunciation and sentence niqqud checks do not fail with `No module named phonikud`.
3. `DICT-01`: open huge project (`project_id=1`) and Dictionary view, verify first page appears quickly and status updates from loading to populated rows (no endless searching state).
4. `DICT-02`: open a small project and Dictionary view, verify first page loads without multi-second stall.
5. `SENT-01`: open Sentences, click `Select...` for document filter, verify picker opens without freezing and does not preload a 387k-row combo list.
6. `SENT-02`: in picker search by title fragment, by numeric ID, and by tag; verify paged results and keyboard navigation (`Up/Down`, `Enter`, `Esc`) work.
7. `EXP-01`: export small project and cancel during `project_snapshot`; verify cancel transitions quickly, temp files are cleaned, and UI becomes responsive.
8. `LOCK-01`: after cancel, execute save/update actions (TM inline edit and reference-corpus update path) and verify no poisoned session behavior; user sees retry status and final friendly error only if retries are exhausted.
9. `DEL-01`: delete small projects from dashboard while huge project exists; verify deletion succeeds and dashboard refreshes deterministically.

### Regression commands for this smoke pack

```powershell
python scripts/prebuild_validate.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db"
python -m pytest tests/test_phonikud_import_available.py tests/test_sqlite_busy_retry.py tests/test_dictionary_pagination_flow.py tests/test_document_picker_flow.py tests/test_project_delete_flow.py -q
python -m pytest tests/test_project_exchange.py -k "cancel_returns_cancelled_report" -q
```

Expected:

- prebuild validate includes `CHECK 0: Required Local Modules` and reports `phonikud: IMPORT OK`,
- targeted pytest suite passes,
- no repeated modal spam for transient DB busy windows.

### Installer-level automated smoke evidence (2026-02-27)

Executed against installed binary:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_frozen_health.ps1 -DistRoot "M:\Soft\HDLE" -DbPath "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" -OutDir "J:\Project_Vibe\V_book\build\verify"
Start-Process -FilePath "M:\Soft\HDLE\HDLE_Premium.exe" -ArgumentList "--self-check db_open --db-path `"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`" --self-check-out `"J:\Project_Vibe\V_book\build\verify\db_open_dist.json`"" -Wait -PassThru
```

Artifacts:

- `build/verify/probe_dist.json` (`ok=true`)
- `build/verify/import_dist.json` (`phonikud_import.ok=true`, `onnxruntime_import.ok=true`)
- `build/verify/health_dist.json` (`ok=true`, bootstrap checks `ok`)
- `build/verify/db_open_dist.json` (`ok=true`, `elapsed_ms=163`)

Targeted regression evidence (same run window):

- `python -m pytest tests/test_dictionary_pagination_flow.py tests/test_document_picker_flow.py -q` -> `9 passed`
- `python -m pytest tests/test_project_exchange.py -k "cancel_returns_cancelled_report" -q` -> `2 passed`
- `python -m pytest tests/test_project_exchange.py -q` -> `18 passed`
- `python -m pytest tests/test_write_gate.py tests/test_translation_admin_write_gate.py -q` -> `4 passed`

### Connected M: DB short smoke evidence (2026-02-27)

Connected DB path:

- `M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`

Commands (automated):

```powershell
python scripts/perf_harness.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --runs 3 --warmup 1 --out build/logs/perf_smoke_m_hewiki_20260227_144336.json
```

Artifacts:

- `build/logs/perf_smoke_m_hewiki_20260227_144336.json`
- `build/verify/smoke_short_m_hewiki_20260227_124425.json`

Key results:

- Dictionary (`project_id=1`): `page_rows=100`, `page_elapsed_ms=33.452`, `count_total=2070890`, `count_elapsed_ms=184.4`
- Picker (`project_id=1`): `empty_elapsed_ms=58.035`, `search_elapsed_ms=67.3`, `search_rows=1`
- Sentences (`project_id=1`): `total_count=13387588`, `count_elapsed_ms=1066.278`, `page_rows=100`, `page_elapsed_ms=6387.039`, `doc_filter_elapsed_ms=48.302`
- Export cancel (`project_id=2`): `success=false` (expected), `error_message="Export cancelled by user."`, `elapsed_ms=65.126`, temporary output cleaned (`output_removed_after_cancel=true`)

## Performance Smoke (Hewiki)

Performance contract source:

- `docs/PERFORMANCE_SLO.md`

SLO budgets (hewiki-scale, warm-up 1 + runs 5):

- Dictionary first page: `p50 <= 0.20s`, `p95 <= 0.50s`
- Dictionary count: `p50 <= 0.50s`, `p95 <= 1.50s`
- Document picker open (empty): `p50 <= 0.10s`, `p95 <= 0.30s`
- Document picker search: `p50 <= 0.60s`, `p95 <= 1.50s`
- Export cancel acknowledgement: `p95 <= 1.0s`

Measurement commands:

```powershell
cd J:\Project_Vibe\V_book
python scripts/perf_harness.py --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" --runs 5 --warmup 1 --out perf_hewiki.json
python scripts/perf_harness.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db" --runs 5 --warmup 1 --out perf_dev.json
```

Query plan audit:

```powershell
python scripts/query_plan_audit.py --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" --out docs/PERF_QUERY_PLANS_HEWIKI.md
```

Smoke expectations:

- Dictionary first page/count remain within SLO budgets (or deviations are documented with environment notes).
- Document picker open/search remain responsive and non-blocking.
- Export cancellation remains responsive and does not leave UI blocked.

### Import + Concurrent Save (P0-03 follow-up)

Goal:

- keep write serialization correctness,
- reduce long write-gate hold windows during import,
- preserve `0 SQLITE_BUSY` under concurrent TM saves.

Benchmark command:

```powershell
python scripts/benchmark_import_concurrent_save.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --seed-docs 6000 --seed-lemmas 120000 --lemma-batch-size 2000 --save-cadence-ms 100 --max-save-attempts 100
```

Release-gate evidence command (validated reference DB):

```powershell
python scripts/benchmark_import_concurrent_save.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" --seed-docs 6000 --seed-lemmas 120000 --lemma-batch-size 2000 --save-cadence-ms 100 --max-save-attempts 100 --quick-check-timeout-sec 5
```

Benchmark on repaired DB explicitly:

```powershell
python scripts/benchmark_import_concurrent_save.py --db-path "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db" --use-repaired-db "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.recovered_YYYYMMDD_HHMMSS.db" --seed-docs 6000 --seed-lemmas 120000 --lemma-batch-size 2000 --save-cadence-ms 100 --max-save-attempts 100
```

Behavior note:

- strict mode by default: malformed target DB causes benchmark failure (no silent fallback),
- sandbox fallback is available only with explicit `--allow-fallback`.

Artifacts:

- `build/logs/import_concurrent_save_metrics_20260227_041029.json`
- `build/logs/import_concurrent_save_ops_20260227_041029.jsonl`
- `build/logs/import_write_gate_trace_20260227_041029.jsonl`
- `build/logs/import_concurrent_save_metrics_20260227_115457.json` (release-gate evidence on `J:\...`)
- `build/logs/import_concurrent_save_metrics_20260227_140745.json` (post-rebuild release-gate evidence on `J:\...`)
- `build/logs/import_concurrent_save_ops_20260227_140745.jsonl`
- `build/logs/import_write_gate_trace_20260227_140745.jsonl`

Before/after summary (baseline before chunked lemma phase vs current):

- `max_save_latency_ms`: `2060.02 -> 281.342`
- `save_latency_p95_ms`: `2060.02 -> 225.634`
- `count_gt_1000ms`: `1 -> 0`
- `terminal SQLITE_BUSY`: `0 -> 0`

Release-gate evidence summary (`build/logs/import_concurrent_save_metrics_20260227_115457.json`):

- `save_latency_p95_ms`: `205.234`
- `max_save_latency_ms`: `384.936`
- `count_gt_1000ms`: `0`
- `gate_release.max_hold_ms`: `287.526`
- `target_db_mode`: `direct`

Release-gate evidence summary (`build/logs/import_concurrent_save_metrics_20260227_140745.json`):

- `save_latency_p95_ms`: `209.879`
- `max_save_latency_ms`: `345.706`
- `count_gt_1000ms`: `0`
- `gate_release.max_hold_ms`: `339.617`
- `target_db_mode`: `direct`
- `target_db_used == target_db_input`: `true`

Evidence line (benchmark command + artifact + key numbers):

- `python scripts/benchmark_import_concurrent_save.py --db-path "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" --seed-docs 6000 --seed-lemmas 120000 --lemma-batch-size 2000 --save-cadence-ms 100 --max-save-attempts 100 --quick-check-timeout-sec 5` -> `build/logs/import_concurrent_save_metrics_20260227_140745.json` (`p95=209.879ms`, `max=345.706ms`, `count_gt_1000ms=0`, `max_hold_ms=339.617ms`)

Top gate holds after chunking (`gate_release.max_hold_ms`, by phase):

- `import.table.source_document`: `339.617ms`
- `import.table.lemma`: `336.396ms`
- `import.table.document_text`: `108.771ms`

Batch-size rationale:

- `lemma` is the dominant write volume in this scenario; importing it in `2000`-row serialized batches
  keeps lock windows short while preserving correctness and cleanup semantics.
- Batch size is tunable via `HDLE_IMPORT_LEMMA_BATCH_SIZE` (`500..10000`) for environment-specific tuning.

Environment note:

- benchmark evidence for release must be captured in direct mode:
  `target_db_used == target_db_input`.
- if direct probe fails, repair target DB first via `scripts/repair_fts_schema.py` and rerun benchmark.

## Prebuild Profiles

Default profile (strict, write checks enabled):

```powershell
python scripts/prebuild_validate.py --db-path "J:\Project_Vibe\V_book\hdle_premium.db"
```

Readonly reference profile (huge DB pipeline, write checks skipped):

```powershell
python scripts/prebuild_validate.py --profile reference-ro --db-path "M:\V_book\HDLE_Processing\hewiki_gpu_processing.db" --skip-quick-check
```

Expected for `reference-ro`:

- write checks (`Project Lifecycle`, `Export/Import`) are reported as `SKIPPED`,
- final status is `PASS_WITH_SKIPS`,
- exit code is success.

## Environment Limitations (Known)

- Readonly hewiki DB cannot execute write probes in prebuild; use `--profile reference-ro`.
- In this environment, `python -m pytest -q` may fail in capture teardown; use
  targeted/regression suites for release evidence and record this constraint.

## Frozen ONNX Health Gate

Authoritative contract:

- `docs/VERIFY_FROZEN_ONNX.md`

Release smoke must include console ONNX probe before installer verification:

```powershell
Start-Process "J:\Project_Vibe\V_book\dist\HDLE_Premium\HDLE_ONNX_Probe.exe" -ArgumentList "--out `"J:\Project_Vibe\V_book\build\verify\probe_dist.json`"" -Wait
Start-Process "J:\Project_Vibe\V_book\dist\HDLE_Premium\HDLE_Premium.exe" -ArgumentList "--self-check import --self-check-out `"J:\Project_Vibe\V_book\build\verify\import_dist.json`"" -Wait
Start-Process "J:\Project_Vibe\V_book\dist\HDLE_Premium\HDLE_Premium.exe" -ArgumentList "--self-check health --db-path `"M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db`" --self-check-out `"J:\Project_Vibe\V_book\build\verify\health_dist.json`"" -Wait
```

Expected:

- Probe returns `ok=true`, `stage=infer`, `has_niqqud=true`.
- `--self-check import` passes `checks.onnxruntime_import.ok=true`.
- `--self-check health` reports pronunciation/sentence bootstrap checks as `ok` (not fallback warn).

Fail-fast pre-build gate (run before long rebuild):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prebuild_fast_gates.ps1 -DbPath "M:\Soft\1. Data folder HDLE Local (model, dataset, logs temporary)\HDLE_Processing\hewiki_gpu_processing.db"
```

`rebuild.ps1` now runs the same fast gates automatically before PyInstaller unless `-SkipFastGates` is explicitly passed.
