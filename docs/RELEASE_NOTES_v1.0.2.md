# Release Notes — HDLE Premium v1.0.2

**Release Date:** 2026-03-30
**Previous repository release baseline:** `v1.0.1` (`b9f2341`)

## Summary

`v1.0.2` is a corrective rerelease that supersedes `v1.0.1`.

The main purpose of this release is to fix a real persisted NLP processing regression
that remained in `v1.0.1`:

- `Process with NLP` could fail on real Hebrew documents
- `Re-process` could fail on the same path
- the failure affected both the repository app run and the installed application

The root cause was localized to the managed Stanza subprocess JSON transport layer.
This release hardens that transport boundary without reopening the already-closed
runtime ownership/bootstrap, export, import, or provenance tracks.

## Why v1.0.1 Was Superseded

`v1.0.1` is now considered a known-bad public artifact for persisted NLP processing.

The confirmed failure mode was:

- parent-side decoding of managed Stanza subprocess output was too strict
- real Hebrew processing could fail with `UnicodeDecodeError`
- persisted document processing then surfaced as failed `Process with NLP` / `Re-process`

This was not a new regression in:

- bundled Hebrew payload delivery
- packaged Stanza/Torch runtime ownership/bootstrap
- packaged ONNX helper startup path
- project export/import product closure
- runtime provenance promotion

## What Changed Since v1.0.1

### 1. Managed Stanza Subprocess Transport Is Hardened

- parent-side worker startup and probe execution now decode subprocess pipes with:
  - `encoding="utf-8"`
  - `errors="replace"`
- the managed Stanza worker now forces UTF-8 stdio for its JSON-lines protocol
- the managed Stanza probe now forces the same UTF-8 stdio behavior

### 2. Persisted NLP Processing Is Fixed For The Confirmed Failure Path

- real persisted `Re-process` on the previously failing Hebrew document path now succeeds
- the fix is transport-scoped and does not redesign the NLP processing pipeline
- no silent Mock fallback was introduced
- configured/effective runtime truth remains unchanged

### 3. Packaged Runtime Confirmation Still Holds

- rebuilt frozen artifact still reports:
  - `--self-check import` = green
  - ONNX helper import = green
- packaged `--stanza-worker` now successfully processes a real Hebrew sentence from the proven failure corpus path under a clean `HDLE_DATA_ROOT`

## Operator-Facing Impact

- `Process with NLP` is no longer expected to fail on the confirmed Hebrew transport regression path
- `Re-process` is no longer expected to fail on the same transport path
- the corrective build preserves all previously closed product-facing tracks:
  - packaged runtime sign-off
  - project export closure
  - project import closure
  - schema-backed runtime provenance for new runs

## Compatibility

- no database schema change was introduced in this corrective rerelease
- no project bundle format change was introduced
- no change was made to the existing runtime ownership taxonomy
- installer/runtime packaging contract remains the same as `v1.0.1`, except for the NLP transport fix

## Suggested Verification For This Release

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_stanza_engine_subprocess.py tests\test_nlp_runtime_probe.py tests\test_stanza_worker_stdio.py tests\test_process_service_nlp_runtime.py tests\test_documents_process_progress_ui.py tests\test_documents_engine_readiness.py tests\test_managed_stanza_runtime.py tests\test_release_smoke_nlp_runtime.py -q
.\dist\HDLE_Premium\HDLE_Premium.exe --self-check import
```

Repository/source validation that was used for the corrective fix:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:HDLE_DATA_ROOT = (Join-Path (Get-Location) 'build\tmp_runtime_root_release')
@'
from app.services.db_service import DBService
from app.services.process_service import ProcessService
DBService.shutdown()
DBService._instance = None
DBService._db_manager = None
DBService._ref_managers = {}
DBService.initialize('build/repro_processing_fix2.db')
svc = ProcessService()
with DBService.get_instance().get_session() as session:
    ok = svc.reprocess_document(session, 387647, use_gpu=False, use_mock=False, configured_engine_id='stanza', allow_mock_fallback=False)
    print({'ok': ok})
DBService.shutdown()
'@ | .\.venv\Scripts\python.exe -
```

Expected result:

- `{'ok': True}`

## Git Summary Against v1.0.1

- baseline tag: `v1.0.1`
- comparison range: `v1.0.1..v1.0.2`
- primary release theme:
  - corrective managed Stanza subprocess transport hardening for persisted NLP processing

## Included Corrective Commits

- `717719a` `fix(nlp-runtime): harden managed stanza subprocess json transport`
- `bcc333b` `chore(handoff): record nlp processing transport regression fix`

## Distribution Note

The installer is distributed as a split archive because the packaged installer exceeds the single-asset GitHub release size limit.

Download all parts:

- `HDLE_Premium_Setup_v1.0.2.7z.001`
- `HDLE_Premium_Setup_v1.0.2.7z.002`

Then extract starting from `.001` with 7-Zip.
