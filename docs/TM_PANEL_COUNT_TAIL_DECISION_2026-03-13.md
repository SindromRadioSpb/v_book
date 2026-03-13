# TM Panel Count Tail Decision (2026-03-13)

## Why this document exists

This document records the bounded decision-gated follow-up to:

- `docs/TM_PANEL_COLD_AUDIT_2026-03-12.md`
- `docs/TM_PANEL_REPAIR_2026-03-13.md`

The goal of this wave is narrow:

- classify the remaining TM exact-count tail after the first-paint repair;
- determine whether the residual tail justifies an immediate second TM patch;
- record the current decision gate for any follow-up on TM count/search semantics.

This wave does **not**:

- change runtime behavior;
- reopen the TM first-paint repair branch;
- ship approximate or altered count semantics;
- open heavy validation.

## Scope

In scope:

- exact count role in the current TM panel contract
- filtered search tail in the current TM panel contract
- semantics options for total/count presentation
- blocker vs not-blocker decision after the P0 repair

Out of scope:

- runtime patching
- query rewrite or schema/index work
- batch translation write-path changes
- broad TM redesign

## Entry points and evidence

Code entry points:

- `app/ui/translation_management_panel.py`
- `app/services/translation_admin_service.py`
- `app/ui/workers.py`

Regression entry points:

- `tests/test_tm_panel_ux.py`
- `tests/test_tm_results_label_context.py`
- `tests/test_tm_panel_translate_query_builder.py`
- `tests/test_tm_kind_multiselect_filter.py`
- `tests/test_tm_panel_translate_selected.py`

Evidence artifacts:

- `build/logs/cold_audit/tm_panel/tm_panel_probe.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repeated.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repair_after.json`
- `build/logs/cold_audit/tm_panel/tm_panel_repair_summary.json`

## Current exact-count contract

After the repair:

- TM rows render as soon as the page query completes;
- exact total arrives later as stage-2 work;
- while count is pending, the panel shows:
  - `TM entries: <page_count> (counting total...)`
  - `of ?`
  - `Showing <start>-<end> (counting total...)`

Current exact total is still used for:

- final results label (`TM entries: X of Y`)
- final pagination page count
- final range label
- project-lemma coverage context in `_build_results_label()`

Current exact total is **not** the gate for:

- first visible TM rows
- first selection usability
- first row-context actions

Important adjacent invariant:

- batch-translation scope decisions do **not** depend on TM panel display count;
- they use `TranslationAdminService.count_tm_ids_for_translation()` separately.

Engineering meaning:

- the residual exact-count tail is now primarily a UX completeness issue, not a
  first-usable-state blocker;
- changing TM panel total semantics would not automatically change batch action
  safety contracts.

## Current evidence

From the approved-target audit and repair artifacts:

- default page-ready path:
  - `0.050s` to `0.137s`
- default exact-total-ready path:
  - `7.594s` to `10.628s`
- representative filtered search page-ready path:
  - `0.706s` to `0.814s`
- representative filtered exact-total-ready path:
  - `9.208s` to `9.450s`

Engineering meaning:

- the residual tail is real;
- filtered search does not eliminate the tail;
- the tail is now stage-2 only and no longer blocks first render.

## Options considered

### Option A — leave current exact-count semantics unchanged

Current behavior:

- rows render first;
- exact total arrives later;
- pagination stays conservative until exact count completes.

Pros:

- no semantics drift
- no correctness ambiguity
- no new query contract

Tradeoff:

- heavy exact total still completes slowly in large scenarios

### Option B — further defer exact count work or make it less eager

Examples:

- run exact count only after explicit idle period
- skip exact count for some search transitions until user stops changing filters

Pros:

- may reduce churn in rapid search workflows
- preserves exact semantics eventually

Tradeoff:

- introduces a more complex refresh/timing contract
- needs fresh evidence that count churn is a real workflow pain after the P0 fix

### Option C — introduce approximate or partial total semantics

Examples:

- approximate total
- threshold-style total (`100+`, `1000+`)
- page-only first, exact total only on explicit request

Pros:

- could materially reduce visible tail in heavy scenarios

Tradeoff:

- changes user-visible semantics
- changes coverage wording expectations
- would need explicit product/UX acceptance, not just performance evidence

## Decision

Current classification:

- `default first-paint blocker`: closed
- `residual exact-count tail`: real
- `priority`: `P1`
- `open second TM patch now`: no

Decision logic:

- the main user-visible blocker is already removed;
- current residual tail is confined to stage-2 total/count completion;
- further TM work would no longer be a pure speed patch:
  - it would mix query cost with semantics choices;
- the repo does not yet contain new approved-target evidence showing that the
  remaining stage-2 count behavior is a current workflow blocker after the
  first-paint repair.

## Reopen gate

Open a second TM follow-up branch only if one of these is crossed with new
approved-target evidence:

- stage-2 exact total is shown to be a real workflow blocker after the first
  render repair;
- rapid search/filter workflows show count churn or stale-semantics confusion
  that materially harms the user path;
- a bounded semantics change is explicitly approved for TM totals/counts.

Until then:

- keep the TM first-paint repair branch closed;
- keep the residual TM count/search tail documented as `P1`;
- do not open a broad TM redesign branch from this tail alone;
- return to the canonical cold-audit framework for the next narrow subsystem
  wave.

## Verification notes

```powershell
rg -n "counting total|of \\?|_build_results_label|count_tm_ids_for_translation" app\ui\translation_management_panel.py app\services\translation_admin_service.py
rg -n "TM panel P0 first-paint blocker is now operationally closed|decision-gated|P1" docs\TM_PANEL_REPAIR_2026-03-13.md docs\ENGINEERING_CONTROL_OPTIMIZATION_ROADMAP_2026-03-11.md docs\TM_PANEL_COUNT_TAIL_DECISION_2026-03-13.md
git diff --check
```

This wave is documentation-first. It reuses the current approved-target evidence
instead of rerunning another heavy live-probe branch.
