# Coverage / QA Reporting Phase 1 (2026-03-15)

## Goal

Add a bounded operator-facing reporting layer on top of the existing
`QA / Coverage` panel without reopening coverage computation, lower-layer
recovery, or a broad export-center redesign.

## Why this wave exists

The current panel already computes and stages useful metrics:

- lemma coverage
- term-cluster coverage
- untranslated lemmas
- untranslated term clusters

But before this wave it remained mostly a live screen. Operators could inspect
the panel, but had no direct way to:

- copy the current state into a handoff note;
- export a lightweight report for QA/review;
- preserve the exact current panel view without rebuilding a separate query
  path.

## Implemented in this wave

- added `Copy Report` to the `QA / Coverage` panel
- added `Export Report...` to the `QA / Coverage` panel
- report content is generated from the panel's current staged state:
  - current project id
  - draft-inclusion toggle
  - current sort choices
  - current coverage metrics
  - current untranslated lemma list
  - current untranslated cluster list
- report actions enable as soon as staged partial results are available
- no new SQL/report worker pipeline was introduced

## Files

- `app/ui/coverage_panel.py`
- `tests/test_coverage_panel_reporting.py`
- `tests/test_coverage_panel_staged_loading.py`
- `docs/COVERAGE_REPORTING_PHASE1_2026-03-15.md`
- `docs/ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md`

## Out of scope

- PDF export
- HTML export
- Coverage report integration into Export Center
- new coverage queries or persistence
- project-wide reporting redesign
- onboarding/reconnect UX changes

## Decision gate after this wave

If product-facing work continues from here, the next bounded choice should be
one of:

- guided onboarding / reconnect health UX
- richer release/readiness evidence aggregation
- or a later Coverage Phase 2 focused on stronger report formats rather than
  new metrics.
