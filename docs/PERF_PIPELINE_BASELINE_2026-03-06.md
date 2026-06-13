# Pipeline Perf Baseline (2026-03-06)

## Scope
- Harness: `scripts/benchmarks/bench_reference_pipeline.py`
- Mode: staged bounded baselines (no `all` run in this evidence set)
- Safety contract: sandbox-only writes, `--copy-target` required, no write-heavy ops on `M:\`
- Source DB (read/copy source only): `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db`
- Sandbox DB (write target): `J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db`

## Environment Notes
- Scratch/temp root for benchmark working DB copies: `J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work`
- Scratch root was cleaned before each scenario run.
- Free disk space was checked before each scenario run.

## Commands Executed (Exact)
```powershell
cd /d J:\Project_Vibe\V_book

.\.venv\Scripts\python.exe scripts\benchmarks\bench_reference_pipeline.py `
  extract_terms `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db" `
  --copy-target `
  --source-db "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" `
  --source-project-id 1 `
  --doc-limit 30 `
  --overwrite 1 `
  --temp-root "J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work"
```

```powershell
cd /d J:\Project_Vibe\V_book

.\.venv\Scripts\python.exe scripts\benchmarks\bench_reference_pipeline.py `
  niqqud_bootstrap `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db" `
  --copy-target `
  --source-db "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" `
  --source-project-id 1 `
  --doc-limit 30 `
  --overwrite 1 `
  --temp-root "J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work" `
  --phonikud-model-path "M:\V_book\HDLE_Processing\models\phonikud-1.0.int8.onnx"
```

```powershell
cd /d J:\Project_Vibe\V_book

.\.venv\Scripts\python.exe scripts\benchmarks\bench_reference_pipeline.py `
  translate_bootstrap `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db" `
  --copy-target `
  --source-db "J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing.db" `
  --source-project-id 1 `
  --doc-limit 30 `
  --overwrite 1 `
  --lemma-limit 30 `
  --term-limit 30 `
  --sentence-limit 30 `
  --temp-root "J:\Project_Vibe\V_book\build\tmp\pipeline_bench_work" `
  --gct-key-path "/path/to/gct-key-dir"
```

## Results Table
| Scenario | Doc Limit | Processed Count | Success Count | Error Count | Duration (s) | Throughput (items/s) | Metrics JSON | Report MD | Notes |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| `extract_terms` | 30 | 10681 | 10681 | 0 | 100.075 | 106.73 | `build\logs\pipeline_bench_metrics_20260306_191129.json` | `build\logs\pipeline_bench_report_20260306_191129.md` | Non-fatal stanza availability warning in console. |
| `niqqud_bootstrap` | 30 | 2000 | 2000 | 0 | 120.565 | 16.59 | `build\logs\pipeline_bench_metrics_20260306_193418.json` | `build\logs\pipeline_bench_report_20260306_193418.md` | Terms were 0 in this staged run (`lemma=1000`, `sentence=1000`). |
| `translate_bootstrap` | 30 | 60 | 60 | 0 | 975.312 | 0.06 | `build\logs\pipeline_bench_metrics_20260306_205757.json` | `build\logs\pipeline_bench_report_20260306_205757.md` | Completed with DB-usage lock warnings; stage status remained `ok`. |

## Scenario Not Executed In This Evidence Set
- `tts_bootstrap`: intentionally skipped by operator decision to avoid accidental cloud cost risk in this session.

## Safety Confirmation
- No write-heavy operation was executed against `M:\V_book\HDLE_Processing\hewiki_gpu_processing.db`.
- All write-heavy runs used `J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db` with `--copy-target`.

## Conclusions
- Staged bounded baselines were successfully captured for:
  - `extract_terms`
  - `niqqud_bootstrap`
  - `translate_bootstrap`
- This baseline set is bounded and reproducible, and is suitable as initial safety/perf evidence for PATCH work.
- Full-scale soak and strict budget gates remain a separate track.
