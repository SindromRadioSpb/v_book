# Iteration 1 (Epic 1) - Status Report

**Date:** 2026-02-04
**Goal:** Complete Core Roadmap (M8-M10) to production-grade premium level
**Current Progress:** **4/12 patches complete** (33%)

---

## ✅ Completed Patches

### PATCH 0: Preconditions + Baseline
**Status:** ✅ COMPLETE
**Time:** ~1 hour

**Deliverables:**
- ✅ Dependencies verified (PyQt6, SQLAlchemy, Stanza, openpyxl)
- ✅ Baseline tests run (M1-M7, P1-P3)
- ✅ ITERATION_1_BASELINE.md created with evidence
- ✅ run_baseline_tests.ps1 PowerShell test runner

**Key Findings:**
- **test_m7.py: 5/5 PASS** (previously documented 4/5 already fixed!)
- test_p3_verification.py: 9/9 PASS
- All core milestones passing
- No blocking issues found

### PATCH 1: Fix test_m7 Flake
**Status:** ✅ SKIPPED (Already Fixed)
**Time:** 0 minutes

**Outcome:** test_m7.py already passing 5/5. No action needed.

### PATCH 2: M8 Schema + TermCardService Backend
**Status:** ✅ COMPLETE
**Time:** ~2 hours

**Deliverables:**
- ✅ Migration 005_m8_term_curation.sql (curation fields)
- ✅ Updated sa_models.py (TermCluster extended)
- ✅ Created term_card_service.py (full functionality)
- ✅ Added TermCardDTO
- ✅ Created test_m8_basic.py (8/8 tests PASS)
- ✅ Committed (SHA: 5079598)

**Evidence:**
```
test_m8_basic.py: Ran 8 tests in 0.179s OK
Schema version: 5 (M8 migration applied)
```

### PATCH 3: M8 UI wiring (TermCardView)
**Status:** ✅ COMPLETE
**Time:** ~2 hours

**Deliverables:**
- ✅ TermCardView fully implemented (617 lines, replaced placeholder)
- ✅ TermCardTableModel for review queue (75 lines)
- ✅ All UI actions wired to TermCardService
- ✅ Card display with all metadata
- ✅ Status workflow (auto/needs_review/approved/rejected)
- ✅ Alias management (add/remove)
- ✅ Stopword actions (toggle on/off)
- ✅ Pin/unpin translation
- ✅ Review queue navigation (prev/next/click)
- ✅ Filtering (status/order/min freq)
- ✅ UI_DOD_M8_TERM_CURATION.md documentation
- ✅ Committed (SHA: c7cb3f8)

**Evidence:**
```
app/ui/term_card_view.py: 617 lines (full implementation)
app/ui/models_qt.py: Added TermCardTableModel
docs/UI_DOD_M8_TERM_CURATION.md: DoD checklist verified
```

### PATCH 4: M8 tests (test_m8.py)
**Status:** ✅ COMPLETE
**Time:** ~1.5 hours

**Deliverables:**
- ✅ test_m8.py comprehensive suite (730 lines, 15 tests)
- ✅ All tests PASS (15/15)
- ✅ Anti-flake verification (20x PASS, NO FLAKES)
- ✅ M8_COMPLETE.md milestone report
- ✅ Committed (SHA: c0a3acf)

**Evidence:**
```
test_m8.py: 15/15 tests PASS
Anti-flake: 20/20 iterations PASS
Total M8 coverage: 23 tests (basic + comprehensive)
docs/M8_COMPLETE.md: Full milestone documentation
```

---

## 🚧 In Progress

Currently working on Iteration 1, which consists of 12 patches across 3 milestones:
- **M8: Term Curation** (PATCH 2-4) - ✅ **COMPLETE**
- **M9: Export Center** (PATCH 5-8) - 🔶 In progress
- **M10: Packaging + QA** (PATCH 9-12) - Not started

---

## 📋 Remaining Patches

### M9: Export Center (4 patches)

**PATCH 5: M9 XLSX multi-sheet export**
- Status: 🔶 PENDING
- Estimated: 2-3 hours
- Deliverables:
  - export_excel_xlsx() with Dictionary + Statistics sheets
  - openpyxl implementation
  - Atomic writes

**PATCH 6: M9 TBX + TMX export**
- Status: 🔶 PENDING
- Estimated: 3-4 hours
- Deliverables:
  - export_tbx() (TermBase eXchange XML)
  - export_tmx() (Translation Memory eXchange XML)
  - XML validation + escaping
  - Decision: Data sources (TBX from term_cluster, TMX from tm_entry)

**PATCH 7: M9 UI wiring (ExportView)**
- Status: 🔶 PENDING
- Estimated: 2 hours
- Deliverables:
  - Wire ExportView to ExportService
  - Format selection, progress/cancel
  - UI_DOD_M9_EXPORT_CENTER.md

**PATCH 8: M9 tests (test_m9.py)**
- Status: 🔶 PENDING
- Estimated: 2 hours
- Deliverables:
  - test_m9.py (>=8 tests)
  - XLSX sheets, TBX/TMX parsing, CSV injection regression
  - M9_COMPLETE.md

### M10: Packaging + QA (4 patches)

**PATCH 9: M10 auto-backup before migrations**
- Status: 🔶 PENDING
- Estimated: 1-2 hours
- Deliverables:
  - SQLite backup API integration
  - Retention policy
  - DBService enhancement

**PATCH 10: M10 crash recovery + SnapshotService**
- Status: 🔶 PENDING
- Estimated: 2-3 hours
- Deliverables:
  - Crash recovery via processor_run/run_error
  - SnapshotService implementation (not placeholder)
  - Startup check logic

**PATCH 11: M10 PyInstaller + Windows installer**
- Status: 🔶 PENDING
- Estimated: 3-4 hours
- Deliverables:
  - build.spec (PyInstaller config)
  - installer.iss (Inno Setup script)
  - BUILD_WINDOWS_INSTALLER.md
  - Install PyInstaller first

**PATCH 12: M10 golden tests + completion docs**
- Status: 🔶 PENDING
- Estimated: 2-3 hours
- Deliverables:
  - test_m10.py (>=5 tests including 2 golden E2E)
  - M8_COMPLETE.md, M9_COMPLETE.md, M10_COMPLETE.md
  - ITERATION_1_REPORT.md

---

## Time Estimates

**Completed:** ~6.5 hours (PATCH 0-4)
- PATCH 0: ~1 hour (baseline)
- PATCH 1: 0 hours (skipped)
- PATCH 2: ~2 hours (M8 backend)
- PATCH 3: ~2 hours (M8 UI)
- PATCH 4: ~1.5 hours (M8 tests)

**Remaining:** ~17-22 hours (PATCH 5-12)
**Total Iteration 1:** ~23.5-28.5 hours

**Breakdown:**
- M8 completion: ✅ Done (6.5 hours)
- M9 full implementation: 9-11 hours (4 patches)
- M10 full implementation: 8-11 hours (4 patches)

---

## Critical Decisions Pending

### 1. TBX/TMX Data Sources (PATCH 6)
**Question:** What data should be exported?
- **TBX:** term_cluster with pinned/approved translations?
- **TMX:** tm_entry only, or include dict_entry?
- **Language codes:** he-IL/ru-RU or he/ru?

**Recommendation:**
- TBX: Export from term_cluster (with translations from TM/pinned)
- TMX: Export from tm_entry (approved + draft with flag)
- Language codes: ISO 639-1 (he, ru) for simplicity

### 2. Stanza Models in PyInstaller (PATCH 11)
**Question:** Bundle models or first-run download?
**Options:**
- A) Bundle in installer (large, ~500MB, but works offline)
- B) First-run download (small installer, requires internet)

**Recommendation:** First-run download (document in BUILD guide)

### 3. Priority Order
**Question:** Continue sequentially or prioritize specific milestones?
**Options:**
- A) Sequential (M8 → M9 → M10) - Complete each milestone fully
- B) Prioritize M10 first (get packaging working early)
- C) Prioritize M9 first (export formats more user-visible)

**Recommendation:** Sequential (A) - Cleanest approach, follows plan

---

## Next Steps

**Current: Continue Sequential (Recommended)**
1. ✅ PATCH 3: M8 UI wiring (DONE)
2. ✅ PATCH 4: M8 tests + docs (DONE)
3. 🔶 PATCH 5: M9 XLSX multi-sheet export (NEXT)
4. PATCH 6-8: M9 TBX/TMX + UI + tests (8-9 hours)
5. PATCH 9-12: M10 implementation (8-11 hours)

**Option 2: Fast-track Export Formats**
1. Skip M8 UI for now (placeholder remains)
2. Focus on PATCH 5-8: M9 (export formats)
3. Return to M8 UI later

**Option 3: Fast-track Packaging**
1. Skip M8 UI and M9 for now
2. Focus on PATCH 9-12: M10 (packaging + installer)
3. Return to M8/M9 later

---

## Risk Assessment

**Current Risks:** 🟢 LOW

**Mitigations:**
- ✅ Baseline established (no regressions)
- ✅ M8 fully tested (23/23 tests passing)
- ✅ Anti-flake verification (20x PASS)
- ✅ Evidence-based approach (examined schema before changes)
- ✅ Incremental commits (safety net)

**Potential Risks:**
- XML schema compliance (M9) - Mitigated by validation tests
- PyInstaller bundling (M10) - Mitigated by documented build process
- UI complexity (M8/M9) - Mitigated by UI/UX constraints adherence

---

## Recommendation

**Continue with Sequential Approach (Option 1)**

**Rationale:**
1. Follows original plan (PATCH 1-12 order)
2. Completes each milestone fully before moving to next
3. Allows testing at milestone boundaries
4. Matches user's detailed patch plan

**Next Action:**
- PATCH 3: M8 UI wiring (TermCardView)
- Estimated completion: 2-3 hours
- Then proceed to PATCH 4 (M8 tests + docs)

**Alternative:** If export formats (M9) are higher priority than term curation UI (M8), can fast-track to PATCH 5-8 and return to M8 UI later.

---

## Questions for User

1. **Priority:** Continue sequential (M8 UI next) or fast-track M9/M10?
2. **TBX/TMX:** Confirm data sources and language code format
3. **PyInstaller:** Bundle Stanza models or first-run download?
4. **Scope:** Complete all 12 patches or focus on subset?

---

**Status:** ✅ **ON TRACK** - 4/12 patches complete (33%), M8 milestone DONE

**Last Updated:** 2026-02-04
**Next Patch:** PATCH 5 (M9 XLSX multi-sheet export)
