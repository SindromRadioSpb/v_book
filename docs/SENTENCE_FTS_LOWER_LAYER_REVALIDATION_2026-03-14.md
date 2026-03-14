# sentence_fts Lower-Layer Revalidation (2026-03-14)

## Why this document exists

This note records the operational lower-layer recovery that followed the
completed cold-hunt stage.

Its purpose is narrow:

- confirm that repo tests and canonical docs were aligned before touching the
  approved target DB;
- record the real approved-target `sentence_fts` repair on the large DB;
- record post-repair revalidation evidence;
- state what this changes for the remaining residual branches.

## Preconditions

Before touching the approved target DB:

- the cold-hunt residual branch docs were already synced;
- the canonical repair tooling was regression-checked;
- `scripts/repair_fts_schema.py --dry-run` was hardened to detect row-count
  mismatch, not only malformed schema/triggers issues.

Targeted regression suite run before repair:

- `tests/test_repair_fts_schema.py`
- `tests/test_repair_lemma_fts.py`
- `tests/test_perf_lemma_fts.py`
- `tests/test_dictionary_pagination_flow.py`
- `tests/test_dictionary_worker_lifecycle.py`
- `tests/test_security.py`

Result:

- `61 passed`

Focused repair-tool suite after hardening:

- `tests/test_repair_fts_schema.py`
- `tests/test_security.py`

Result:

- `38 passed`

## Approved target

Real DB used for the lower-layer repair:

- `J:\Project_Vibe\V_book\ref_corpora\HDLE_Processing_hewiki_gpu_processing.db\hewiki_gpu_processing test.db`

This is the same approved target used for the meaningful cold evidence.

## Dry-run result before repair

After the repair-tool hardening, the approved-target dry-run finally matched the
documented defect:

- `status = FAILED`
- `issues_detected = ["sentence_fts_row_mismatch: sentence_fts=1792, document_sentence=13389383"]`

Engineering meaning:

- the canonical operator tool and the canonical cold docs were now aligned;
- it became safe to proceed to the actual repair step with backup.

## Real repair result

Command path used:

- `python scripts/repair_fts_schema.py --db-path "<approved-target-db>"`

Outcome:

- `status = REPAIRED`
- backup created:
  - `hewiki_gpu_processing test.fts_repair_20260314_162923.db.bak`
- actions completed:
  - `dropped_existing_fts_tables_and_triggers`
  - `recreated_fts_tables_and_triggers`
  - `rebuild_sentence_fts_completed`
  - `rebuild_term_fts_completed`
  - `fts_optimize_completed:sentence_fts`
  - `fts_optimize_completed:term_fts`

Canonical repair summary:

- `build/logs/fts_repair_20260314_164152.json`

## Post-repair revalidation evidence

Canonical revalidation artifact:

- `build/logs/cold_audit/lower_layer/sentence_fts_revalidation_2026-03-14.json`

Observed after repair:

- `sentence_fts_count = 13,389,383`
- `document_sentence_count = 13,389,383`
- `sentence_fts rowid 3679 exists = 1`
- `document_sentence row 3679 exists = 1`
- `sentence_fts MATCH 'wiki' = 140`
- `project1_joined_rows = 13,387,588`
- `project1_sentence_rows = 13,387,588`
- `project1_original_match_count = 666`
- `project1_original_match_elapsed_s = 1.666`

Post-repair dry-run:

- `status = OK`
- `issues_detected = []`

Engineering meaning:

- the old `sentence_fts` dependency-health gate on the approved target is now
  actually crossed;
- Concordance is no longer blocked by zero project-joined rows on this DB;
- Sentences filtered-tail work is no longer blocked by the old unhealthy
  `sentence_fts` substrate.

## What changes strategically

What is now closed:

- lower-layer `sentence_fts` health recovery on the approved target

What is now unlocked:

- honest Concordance revalidation on the repaired approved target
- honest decision on whether Sentences filtered search/count still deserves any
  follow-up after the substrate is healthy

What is still not justified automatically:

- reopening broad cold-hunt
- reopening generic `P3` sweeps
- opening a second Sentences runtime patch without fresh post-repair evidence

## Recommended next move

If work continues immediately, the next clean revalidation order is:

1. Concordance on the repaired approved target
2. Sentences filtered search/count on the repaired approved target

That is now a post-repair revalidation stage, not a generic cold-hunt stage.
