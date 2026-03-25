# Manual QA Matrix — HDLE Premium

> **Status:** Active (approved 2026-03-24, updated 2026-03-25)
> **Scope:** Terms view · Dictionary view · TM panel · Cross-surface
> **Schema version:** v51
> **Automation coverage:** See test suite (≥1708 automated tests). This matrix covers scenarios that automation cannot verify: visual readability, hover UX, user trust, wording clarity.

---

## How to Use

Mark each scenario with:
- ✅ PASS — behaves as described
- ❌ FAIL — bug, capture screenshot + steps to reproduce
- ⚠️ PARTIAL — works but unclear UX; note the specific concern
- N/A — not applicable (e.g., feature not yet implemented)

Run this matrix after:
- Any UI change touching Dictionary view, Terms view, or TM panel
- Any schema migration
- Before a release build

---

## Section 1 — Dictionary View

### 1.1 Noise Column (col 8)

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| D-01 | Lemma with `is_noise=1, noise_source="auto", noise_updated_at=2026-01-15T10:00:00Z` | Open Dictionary, find lemma, hover Noise col | Badge: "Noise (auto)". Tooltip: "Automatically classified as noise by NLP pipeline\nDate: 2026-01-15" | |
| D-02 | Lemma with `is_noise=0, noise_source="manual", noise_updated_at=2026-02-01T08:00:00Z` | Hover Noise col | Badge: "Valid (manual)". Tooltip: "Manually confirmed as valid\nDate: 2026-02-01" | |
| D-03 | Lemma with `is_noise=1, noise_source=NULL` (legacy) | Hover Noise col | Badge: "Noise" (no suffix). Tooltip: "Noise — source unknown (legacy data)". No empty "Date:" line. | |
| D-04 | Lemma with `is_noise=NULL` (unclassified) | Hover Noise col | Badge: empty cell "". Tooltip: "Not yet classified" | |
| D-05 | Lemma with `is_noise=0, noise_source="auto", noise_updated_at=NULL` | Hover Noise col | Badge: "Valid (auto)". Tooltip: no date line (omit entirely, not "Date: "). | |
| D-06 | Manual noise toggle on lemma | Toggle noise via right-click / bulk action | Badge changes to "Noise (manual)" immediately after refresh. `noise_updated_at` reflects today's date. | |

### 1.2 Entity Class Column (col 9)

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| D-07 | Lemma with `entity_class="PER"` | Hover Entity Class col | Cell: "PER". Tooltip: "Person name" | |
| D-08 | Lemma with `entity_class="GPE"` | Hover Entity Class col | Tooltip: "Geo-Political Entity" | |
| D-09 | Lemma with `entity_class=NULL` | View cell | Cell: empty string, no tooltip | |
| D-10 | Lemma with unknown entity class (e.g., "XYZ") | Hover | Tooltip: "Named entity class: XYZ" (fallback) | |

### 1.3 Status Bar — Noise Count

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| D-11 | Project with 47 noise lemmas, search filter active (showing 20 lemmas) | Apply search filter that returns 20 lemmas | Status: "Found: 20" AND "Noise: 47". Noise count does NOT change when filter changes. | |
| D-12 | Project with 0 noise lemmas | Open Dictionary | Status: "Noise: 0" | |
| D-13 | Apply noise filter | Open Filters dialog → select noise state → apply | "Found:" count decreases to match selected noise states. "Noise: N" in status bar stays the same (project-wide, independent of filter). | |

### 1.4 Translation Column (col 5)

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| D-14 | Inline edit translation | Double-click col 5 cell | Cell enters edit mode. No other column triggers edit mode. | |
| D-15 | Verify column 5 not shifted after Epic 6B changes | Count columns left to right | 0=UD, 1=Lemma, 2=POS, 3=Freq, 4=Docs, 5=Translation (editable), 6=Source, 7=Status, 8=Noise, 9=Entity Class, 10=Last Review, 11=Niqqud, 12=Audio. Total: 13 columns. | |

### 1.5 Legacy Data UX Trust

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| D-16 | New project with no reprocessing done | Open Dictionary | Most lemmas show "Noise" or "Valid" (no suffix) — legacy badges. No error indicators. UI does not look broken. | |
| D-17 | Hover legacy badge | Hover "Noise" or "Valid" without suffix | Tooltip says "source unknown (legacy data)" — communicates clearly without alarming the user | |

---

## Section 2 — Terms View

### 2.1 min_freq Display-Time Filter

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| T-01 | Change min_freq spinner | Change from 1 to 5 | Clusters list refreshes instantly. No extraction triggered. Progress bar does not appear. | |
| T-02 | Hidden count when min_freq > 1 | Set min_freq=5 with 50 clusters total (20 freq≥5, 30 freq<5) | Status bar: "Found: 20  Hidden by min freq: 30" | |
| T-03 | No hidden count when min_freq=1 | Set min_freq=1 | Status bar shows "Found: N" only, no hidden count line | |
| T-04 | Tooltip on min_freq spinner | Hover spinner | Tooltip: "Display-time filter only. All candidates stored. Change freely." | |

### 2.2 Quick Presets

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| T-05 | Click preset [All (1)] | Click | min_freq spinner → 1. List refreshes. No extraction. | |
| T-06 | Click preset [Common (3)] | Click | min_freq spinner → 3. List refreshes. | |
| T-07 | Click preset [Strict (5)] | Click | min_freq spinner → 5. List refreshes. | |
| T-08 | Click preset [High (10)] | Click | min_freq spinner → 10. List refreshes. | |

### 2.3 Freq Distribution Label

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| T-09 | After search, freq distribution visible | Perform any search | Label shows: "Freq dist: 1→N  2–4→N  5–9→N  10+→N". Updates with each search. | |
| T-10 | No freeze during freq distribution update | Type quickly in search box | UI remains responsive. Freq dist label may lag slightly but does not freeze. | |

### 2.4 Resume Log Note

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| T-11 | Change min_freq after extraction run | Extract with min_freq=2. Change to min_freq=5. Click Extract again (same mode). | Log area shows note: "(min_freq changed: 2→5, resume still valid)". Run starts correctly as resume. | |

### 2.5 Growth Warning

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| T-12 | Large corpus + min_freq=1 + Full Overwrite | Project with >200 docs, set min_freq=1, click Extract | Warning dialog appears: "Large corpus detected: N docs. With min_freq=1 and Store hapax=On, ..." User can cancel. | |

### 2.6 Staleness Warning (Epic 4)

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| T-13 | After reference corpus change | Change reference corpus selection. | Staleness warning appears near keyness/weirdness sort section: "Keyness/Weirdness may be outdated." Recalculate button enabled. | |
| T-14 | Recalculate button | Click Recalculate | Progress shown. Staleness warning disappears after completion. Keyness/weirdness values refresh. | |

### 2.7 Extraction Mode UX

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| T-15 | Mode selection persists per project | Select "Merge" mode. Switch project. Return to first project. | First project still shows "Merge" mode selected. | |
| T-16 | Impact preview on Full Overwrite | Select "Full Overwrite". Click Extract. (Project has TM entries.) | Impact dialog: "This will delete N clusters. N linked TM entries will be preserved." Cancel / Proceed buttons. | |

---

## Section 3 — TM Panel

### 3.1 Src Column (source_status)

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| TM-01 | TM entry with active cluster link | View Src col | ● green. Hover: shows promoted_from_cluster_id + params_hash excerpt. | |
| TM-02 | TM entry where source cluster was deleted (Full Overwrite) | After Full Overwrite, view TM entries that were linked | ● red. Hover: "Source cluster was removed — entry preserved (cluster ID: N)". | |
| TM-03 | TM entry created manually (no cluster) | View manually added TM entry Src col | ● grey (manual). Hover: "Manually created — no cluster source". | |

### 3.2 Batch Translate Safety (R2 Guard)

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| TM-04 | Batch Translate does not overwrite user-approved | Set a TM entry to user_edit+approved. Run Batch Translate. | Entry translation unchanged after batch. Log shows: "Skipping user_edit+approved entry". | |
| TM-05 | Batch Translate fills empty entries | Ensure some entries have no translation. Run Batch Translate. | Empty entries get MT translation. Approved entries unchanged. | |

### 3.3 TM Noise Column

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| TM-06 | TM entry with noise_reason="NOISE_PUNCT_ONLY" | Hover noise col | Tooltip: "punctuation only" (human-readable) | |
| TM-07 | TM entry with is_noise=0, noise_reason=NULL | Hover noise col | Tooltip: "Valid — reason not recorded" | |

---

## Section 4 — Cross-Surface

### 4.1 Wording Consistency

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| X-01 | "Noise" filter label | Compare Dictionary "Hide Noise" vs TM "Hide Noise" checkboxes | Same label text in both surfaces. | |
| X-02 | "Source" missing wording | Compare TM Src col "source_cluster_missing" tooltip vs Dictionary future lifecycle tooltip | Consistent pattern: "Source [X] was removed — entry preserved". Different X (cluster vs lemma). | |
| X-03 | Legacy data is not shown as an error | Check noise badges in fresh project (all legacy) | No red error indicators. "Noise" / "Valid" badges without suffix look intentional, not broken. | |

### 4.2 Column Stability After Epics

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| X-04 | LemmaTableModel column 5 editable | Double-click col 5 in Dictionary | Edit mode activates. No column before or after col 5 activates edit mode. | |
| X-05 | TermClusterTableModel — no column shift | Verify Terms view columns after Epic 6B | Terms view column layout unchanged (Epic 6B only modified LemmaTableModel). | |
| X-06 | TranslationManagementTableModel — col 10 Noise | Hover col 10 in TM panel | Noise tooltip with noise_reason code shown. No regression from LemmaTableModel col shift. | |

---

## Known Automation Gaps (by design)

These scenarios require manual QA because automation cannot verify them:

| Gap | Why not automated | Impact |
|-----|-------------------|--------|
| Tooltip text readability | Automation checks text content, not readability or visual clarity | Medium |
| Badge visual differentiation (Noise (auto) vs Noise (manual)) | Color/style rendering varies by OS/theme | Low |
| "Noise: N" count independent of filter (visual) | Automation checks data; user may not notice the count doesn't change | Medium |
| Legacy badge "looks intentional" | Subjective UX judgment | Low |
| Growth warning UX clarity | Dialog text readability and user decision flow | Medium |
| Resume log note visibility | Log area scrolling and readability | Low |
