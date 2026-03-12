# Sentences Workspace Cold-Path Repair (2026-03-12)

## Why this document exists

This document records the bounded runtime repair that was opened by:

- `docs/SENTENCES_WORKSPACE_COLD_AUDIT_2026-03-12.md`

This repair stays narrow:

- it changes the stage-1 Sentences page query shape only;
- it preserves the existing staged first-paint and anti-stale UI contract;
- it does not reopen startup, picker, governance, readiness, telemetry, or heavy-validation branches;
- it does not introduce new schema, FTS rebuild work, or new product behavior.

## Patch scope

Code changes:

- `app/services/sentences_workspace_service.py`
- `tests/test_sentences_workspace_service.py`

Bounded implementation:

- default `sentence_id ASC` page loads without `doc_id_filter` now use a
  `document_sentence NOT INDEXED` PK/rowid-ordered scan;
- doc-scoped queries and non-default sorts keep the existing ORM path;
- exact filtered counts are unchanged in this patch;
- UI worker staging and request-id stale-drop logic are unchanged.

## Evidence artifacts

- `build/logs/cold_audit/sentences_workspace/sentences_repair_after.json`
- `build/logs/cold_audit/sentences_workspace/sentences_repair_breakdown_after.json`
- `build/logs/cold_audit/sentences_workspace/sentences_service_hewiki_breakdown.json`
- `build/logs/cold_audit/sentences_workspace/sentences_cold_audit_summary.json`

Approved target:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- schema `42`
- access mode: strict read-only via `ReadOnlyDatabaseManager`

Safety evidence:

- DB `LastWriteTime` / `st_mtime_ns` stayed unchanged across the repair probe;
- the approved target was never opened in write mode for this validation wave.

## Before / after summary

Before the repair, the audit wave recorded:

- unfiltered first page: `3.56s` to `4.10s`
- unfiltered count: `0.016s` to `0.024s`
- filtered exact count (`text_search='wiki'`): `8.31s` to `8.72s`
- dominant page-query substep: `~3.68s`
- query plan included `USE TEMP B-TREE FOR ORDER BY`

After the repair:

- unfiltered first page: `0.219s`
- unfiltered count: `0.021s`
- filtered first page (`text_search='wiki'`): `2.182s`
- filtered exact count (`text_search='wiki'`): `7.889s`
- fast page plan: `SCAN document_sentence`
- fast filtered page plan: `SCAN document_sentence`

## After-breakdown findings

Measured service-step breakdown after the repair:

- default page:
  - `page_rows ~= 0.002s`
  - `audio ~= 0.195s`
  - `count ~= 0.021s`
- filtered page (`text_search='wiki'`):
  - `page_rows ~= 1.852s`
  - `audio ~= 0.243s`
  - `count ~= 7.592s`

Engineering meaning:

- the original P0 blocker was the default stage-1 page query;
- that blocker is now removed from the dominant path;
- the current residual tail is the filtered search path, especially the exact
  filtered count;
- search-page latency is materially lower than before, but it is not eliminated.

## Current classification

Current status after the repair:

- `default first-page blocker`: closed
- `recommended priority`: P0 closed
- `current dominant residual tail`: filtered search exact count
- `open another patch immediately`: no

Decision logic:

- the original evidence gate was crossed by the `~3.7s` unfiltered stage-1 page query;
- that exact blocker no longer exists on the approved target;
- the remaining filtered search/count tail is real, but it is a narrower
  follow-up decision, not an automatic reopen of the whole Sentences branch.

## Branch and roadmap effect

This repair closes the active Sentences P0 branch for the default first usable
state.

What remains closed:

- startup cold-path branch
- picker cold-path branch
- governance/readiness branches
- telemetry retention branches
- heavy-validation branches

What stays decision-gated:

- any follow-up on filtered Sentences search/count
- any FTS health or rebuild work
- any broader Sentences redesign

The next active engineering action is therefore:

- return to the canonical cold-audit framework for the next narrow subsystem wave,
  unless new approved-target evidence promotes the residual filtered search tail
  into a new blocker

## Repeatability commands

```powershell
New-Item -ItemType Directory -Force build\logs\cold_audit\sentences_workspace | Out-Null
New-Item -ItemType Directory -Force build\tmp\pytest | Out-Null
$env:TEMP = (Resolve-Path build\tmp\pytest).Path
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests\test_sentences_workspace_service.py tests\test_patch_h_anti_stale.py tests\test_sentences_context_menu.py tests\test_sentences_user_dictionary_refresh.py -q
```

Read-only evidence probe:

```powershell
@'
import json
import time
from pathlib import Path

from app.infra.db import ReadOnlyDatabaseManager
from app.services.sentences_workspace_service import SentencesWorkspaceService

db_path = Path(r"J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db")
out_path = Path(r"J:\Project_Vibe\V_book\build\logs\cold_audit\sentences_workspace\sentences_repair_after.json")
svc = SentencesWorkspaceService()
manager = ReadOnlyDatabaseManager(db_path)
try:
    with manager.get_session() as session:
        started = time.perf_counter()
        rows = svc.list_sentences(session, 1, page=1, page_size=100)
        default_s = round(time.perf_counter() - started, 3)

        started = time.perf_counter()
        filtered_rows = svc.list_sentences(session, 1, text_search="wiki", page=1, page_size=100)
        filtered_s = round(time.perf_counter() - started, 3)

        started = time.perf_counter()
        filtered_total = svc.count_sentences(session, 1, text_search="wiki")
        filtered_count_s = round(time.perf_counter() - started, 3)
finally:
    manager.close()

payload = {
    "default_page_s": default_s,
    "filtered_page_s": filtered_s,
    "filtered_count_s": filtered_count_s,
    "default_rows": len(rows),
    "filtered_rows": len(filtered_rows),
    "filtered_total": int(filtered_total),
}
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False))
'@ | .\.venv\Scripts\python.exe -
```
