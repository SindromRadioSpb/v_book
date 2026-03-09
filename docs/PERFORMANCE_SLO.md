# Performance SLO Contract (Hewiki Scale)

## Scope

This contract defines baseline read-path performance targets for large databases
(hewiki-scale) in HDLE Premium.

Target dataset reference:

- Approved Task 30 DB:
  `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`
- Verified schema version:
  `35`

## SLO Targets

All budgets are measured in seconds:

- `Dictionary first page (100 rows)`:
  - `p50 <= 0.20`
  - `p95 <= 0.50`
- `Dictionary count (same filter)`:
  - `p50 <= 0.50`
  - `p95 <= 1.50`
- `Document Picker open (empty search, first page)`:
  - `p50 <= 0.10`
  - `p95 <= 0.30`
- `Document Picker search page`:
  - `p50 <= 0.60`
  - `p95 <= 1.50`
- `Export cancel acknowledgement`:
  - `p95 <= 1.0` from cancel action to cancellation acknowledgement state
- `SQLite busy retry UX`:
  - no UI freeze,
  - visible inline retry status,
  - eventual success or clear terminal error after retry budget.

## Measurement Method (Mandatory)

- Warm-up runs: `1`
- Measured runs: `5`
- Aggregates: `p50`, `p95`
- Output format: JSON artifact from `scripts/perf_harness.py`
- Artifact metadata must include DB path and schema version
- Measure read paths only for perf harness (no UI actions, no writes).

## Non-Goals / Constraints

- Absolute timings are not guaranteed on HDD/network storage.
- Budgets are defined for SSD/NVMe-class environments.
- In readonly reference DB environments, write checks are out of scope for
  performance harness and may be skipped in prebuild validation via
  `reference-ro` profile.

## Regression Rules

- Do not move long DB work into UI thread.
- Do not introduce per-row SQL in model paint/data paths.
- Keep worker cancel/interrupt semantics unchanged.
- Keep WAL-safe transaction hygiene and rollback behavior unchanged.
