# Query Plan Evidence Pack (PATCH-07)

## Purpose
- Capture reproducible query-plan evidence before index/schema/algorithm optimization.
- Make SQL plan changes auditable with timestamped artifacts.
- Keep execution bounded and read-only.

## Safety Rules
- Use only local `J:\` DB paths for evidence runs.
- Never point evidence collection to `M:\` reference DB path.
- Script opens DB in read-only mode (`mode=ro`).

## Script
- `scripts/collect_queryplan_evidence.py`

Outputs:
- `build\logs\queryplan_evidence_<timestamp>.json`
- `build\logs\queryplan_evidence_<timestamp>.md`

## Covered Areas
- Extract Terms hot-path query (`lemma_doc_stat` rollup)
- Dictionary listing query
- Terms listing + terms LIKE search
- Translation Management listing + TM global lookup

## Canonical Command
```powershell
cd /d J:\Project_Vibe\V_book
.\.venv\Scripts\python.exe scripts\collect_queryplan_evidence.py `
  --db-path "J:\Project_Vibe\V_book\build\bench\hewiki_pipeline_sandbox.db" `
  --project-id 1 `
  --search-term "wiki" `
  --out-dir "build\logs"
```

## Artifact Content
Per query:
- `query_id`
- `area`
- SQL text
- EXPLAIN QUERY PLAN rows
- sample elapsed time (ms) and sample row count
- plan notes (temp b-tree/full scan hints)

Header:
- UTC timestamp
- DB path
- project id
- index snapshot for key tables

## Bounded Execution Notes
- All SQL includes `LIMIT`.
- No benchmark loops in this script.
- Intended runtime is bounded to seconds/minutes, not long perf runs.

## How to Use in Future Perf Patches
1. Capture evidence before index/schema change.
2. Capture evidence after change on the same bounded DB/project.
3. Compare:
   - temp b-tree usage markers
   - full scan markers
   - elapsed sample timings
4. Attach both JSON/MD artifacts in patch DoD evidence.

