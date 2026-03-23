# V_book Premium-Pro Roadmap

**Date:** 2026-02-04 · **Last Updated:** 2026-03-24
**Version:** 2.1
**Target Audience:** Premium professional translation memory application
**Baseline:** M1-M7 + P1-P3 complete, M8-M10 gaps identified

---

## Current Status (2026-03-24)

| Iteration | Status | Notes |
|-----------|--------|-------|
| Iteration 1: Core Roadmap (M8-M10) | ✅ Complete | M8, M9, M10 shipped; v1.0.0 released |
| Iteration 2: Security Hardening | ✅ Complete | SECURITY_AUDIT.md; security test suite |
| Iteration 3: UI Pro Workspace | ✅ Complete | Command palette, keyboard shortcuts, multi-sort |
| Iteration 4: Translation Pro (MT + Terms) | ✅ Complete | Google Cloud Translate integrated; Term Extraction Pro (see below) |
| Iteration 5: Import/Export Premium + QA | 🔄 Partial | Export Center complete; Import preview partial |
| Iteration 6: Performance + History | 🔄 Partial | Performance baselines established; perf tests present |

### Delivered Beyond Original Roadmap Scope

Three engineering epics were executed organically after v1.0.0, outside the original roadmap numbering. They are documented separately and listed here for completeness:

| Epic | Status | Doc | Summary |
|------|--------|-----|---------|
| **Epic 4: Term Extraction Pro** (internal naming) | ✅ Complete | `epic4_term_extraction_pro.md`, `epic4_user_guide.md` | params_hash reproducibility, keyness/weirdness storage, staleness detection, min_doc_freq, sort presets |
| **Epic 5: TM Safety & Layered Extraction** (internal naming) | ✅ Complete | `epic5_tm_safety_layered_extraction.md`, `epic5*_completion.md` | TM provenance, layered extraction modes (overwrite/merge/replace), candidate persistence, Terms UX hardening |
| **Epic 6: Dictionary Maturity** (internal naming) | ✅ Complete | `epic6_completion.md`, `epic6_dictionary_guide.md` | Noise provenance, Entity Class column, semantic tooltips, noise count metric — backend truth → product truth |

**Schema version after all epics:** v47

### Next Wave: Post-Epics 4/5/6 Stabilization (2026-03-24)

A bounded consolidation wave executed after Epics 4/5/6 to prevent semantic drift and establish normative references. No new broad epics, no schema changes.

| Phase | Status | Deliverable |
|-------|--------|-------------|
| PATCH-00: Audit consolidation | ✅ Complete | `docs/next_wave_audit.md` |
| PATCH-01: Semantic contract | ✅ Complete | `docs/SEMANTIC_CONTRACT.md` |
| PATCH-02: Cross-surface matrix | ✅ Complete | `docs/CROSS_SURFACE_MATRIX.md` |
| PATCH-03: UI vocabulary | ✅ Complete | `docs/UI_VOCABULARY.md` |
| PATCH-04: Axis 2 in Dictionary | ✅ Resolved (deferred) | Semantic analysis in `CROSS_SURFACE_MATRIX.md` — column would always be "linked", no user value |
| PATCH-05: Manual QA matrix | ✅ Complete | `docs/MANUAL_QA_MATRIX.md` |
| PATCH-06: Release consolidation | ✅ Complete | `docs/MATURITY_SUMMARY.md`, `docs/OPERATOR_GUIDE.md` |

**Key normative documents created:** `SEMANTIC_CONTRACT.md` · `CROSS_SURFACE_MATRIX.md` · `UI_VOCABULARY.md`

---

## Table of Contents

1. [North Star Goals](#1-north-star-goals)
2. [Architectural Epics](#2-architectural-epics)
3. [UI/UX Constraints](#3-uiux-constraints)
4. [Premium-Pro Feature Matrix](#4-premium-pro-feature-matrix)
5. [Iterative Implementation Plan](#5-iterative-implementation-plan)
6. [Quality Assurance Strategy](#6-quality-assurance-strategy)
7. [Release Checklist](#7-release-checklist)

---

## 1. North Star Goals

These measurable goals define success for the Premium-Pro product:

### 1.1 Performance Excellence
- **Startup time:** < 2 seconds (cold start with 10MB DB)
- **Translation lookup:** < 10ms (single item), < 50ms (100 items bulk)
- **Term extraction:** < 5 seconds per 10K tokens
- **FTS search:** < 300ms response time (100K sentences corpus)
- **Coverage computation:** < 500ms (10K lemmas, 5K clusters)
- **Import speed:** > 1000 entries/second (CSV/XLSX)

### 1.2 Quality Determinism
- **Test pass rate:** 100% (all 200+ tests)
- **Flake rate:** 0% (20x anti-flake loop on all tests)
- **Verification gates:** 100% PASS on production-like data
- **Normalization consistency:** 100% M5/M7 compatibility
- **Session management:** Zero identity map issues

### 1.3 Professional UX
- **UI responsiveness:** Zero freezes > 100ms (all operations in workers)
- **Error clarity:** 100% of errors have actionable messages
- **Accessibility:** Full keyboard navigation, screen reader support
- **Localization:** RU/HE/EN UI (Phase 2)
- **Safe operations:** 100% snapshot-by-default for destructive actions

### 1.4 Translation Quality
- **Coverage target:** > 80% lemma coverage, > 70% cluster coverage
- **TM precedence:** 100% deterministic (TM > Dict > MT)
- **Conflict resolution:** 100% transparent (user sees all options)
- **Glossary integration:** 100% of approved terms in MT glossary payload

### 1.5 Production Readiness
- **Crash recovery:** 100% of interrupted operations recoverable
- **Data integrity:** Zero data loss scenarios
- **Backup automation:** Auto-backup before every migration
- **Deployment:** Single-click installer (Windows), < 5 min setup
- **Documentation:** 100% of features documented with examples

### 1.6 Premium Workflow Efficiency
- **Bulk operations:** Support for 1000+ items (approve/reject/export)
- **Review queue:** < 3 clicks to approve/reject item
- **Import wizard:** < 5 clicks from file to imported dictionary
- **Export:** < 10 seconds for 10K entries (all formats)
- **Search:** < 100ms for any filter combination

---

## 2. Architectural Epics

### Epic 1: Complete Core Roadmap (M8-M10)
**Priority:** P0
**Complexity:** M (Medium)
**Estimated Effort:** 2-3 weeks

**What:**
- Implement M8 (Term Curation service + UI wiring)
- Implement M9 (TBX/TMX export + Excel multi-sheet)
- Implement M10 (PyInstaller build + Windows installer + crash recovery)

**Why:**
- Fulfills original roadmap promises
- Blocks Premium-Pro features that depend on M8/M9
- Required for standalone distribution

**Components:**
- `app/services/term_card_service.py` (NEW)
- `app/services/export_service.py` (ENHANCE: add TBX/TMX/Excel)
- `app/ui/term_card_view.py` (WIRE to service)
- `app/ui/export_view.py` (WIRE to service)
- `build.spec` (NEW: PyInstaller config)
- `installer.iss` (NEW: Inno Setup script)
- `app/services/db_service.py` (ENHANCE: auto-backup + crash recovery)

**Dependencies:**
- None (can start immediately)

**Risks:**
- TBX/TMX XML schema compliance (medium risk)
- PyInstaller bundling with PyQt6 + Stanza models (medium risk)
- Windows installer edge cases (low risk)

**Test Strategy:**
- Unit tests for TermCardService
- Integration tests for export formats (validate XML against schemas)
- Manual testing for installer (clean Windows VM)
- Crash recovery E2E test (kill process mid-operation)

**Acceptance Criteria:**
- M8: Term card service with status workflow, 10+ tests PASS
- M9: TBX/TMX export validates against schema, Excel has 2+ sheets
- M10: Installer creates working standalone app in < 5 min

---

### Epic 2: UI Pro Workspace
**Priority:** P1
**Complexity:** L (Large)
**Estimated Effort:** 3-4 weeks

**What:**
- Multi-panel layout with resizable splitters
- Workspace presets (save/load layouts)
- Keyboard shortcuts for all actions
- Quick command palette (Ctrl+P)
- Advanced table features (multi-sort, column reorder, frozen headers)
- Bulk selection and operations (Ctrl+A, Shift+Click ranges)

**Why:**
- Professional users need efficient workflows
- Reduces clicks-to-action by 50%
- Enables power-user keyboard-driven workflows

**Components:**
- `app/ui/workspace_manager.py` (NEW)
- `app/ui/command_palette.py` (NEW)
- `app/ui/models_qt.py` (ENHANCE: multi-sort, frozen headers)
- `app/ui/app_window.py` (ENHANCE: splitters, workspace presets)
- `app/infra/settings.py` (NEW: persist workspace layouts)

**Dependencies:**
- M8-M10 complete (required for full UI)

**Risks:**
- Qt splitter state persistence (low risk)
- Command palette search performance (medium risk)

**Test Strategy:**
- UI smoke tests for workspace presets
- Manual testing for keyboard navigation
- Accessibility testing with screen reader

**Acceptance Criteria:**
- Workspace layout saves/loads correctly
- All actions have keyboard shortcuts (documented)
- Command palette finds actions in < 50ms
- Bulk selection works for 1000+ items

---

### Epic 3: Translation Provider Abstraction + MT Integration
**Priority:** P1
**Complexity:** L (Large)
**Estimated Effort:** 3-4 weeks

**What:**
- Abstract TranslationProvider interface
- Fallback chain configuration (e.g., DeepL → Google → Yandex → fail)
- Glossary payload builder (terms + exceptions + preferences)
- MT cache with TTL and keying strategy
- Provider health checks and circuit breaker
- Rate limiting and request batching

**Why:**
- Core feature for professional translation workflows
- Enables offline + online hybrid workflows
- Reduces manual translation effort by 60-80%

**Components:**
- `app/infra/translators/base_provider.py` (NEW)
- `app/infra/translators/deepl_provider.py` (NEW)
- `app/infra/translators/google_provider.py` (NEW)
- `app/infra/translators/mock_provider.py` (ENHANCE)
- `app/services/translation_service.py` (ENHANCE: provider chain)
- `app/services/glossary_builder_service.py` (NEW)
- `app/ui/settings_dialog.py` (NEW: provider config)

**Dependencies:**
- None

**Risks:**
- API rate limits and costs (high risk)
- Glossary format compatibility per provider (medium risk)
- Network errors and timeout handling (medium risk)

**Test Strategy:**
- Unit tests with mock providers
- Integration tests with real API (separate test suite)
- Stress test: 1000 requests with rate limiting
- Circuit breaker test: simulate provider failures

**Acceptance Criteria:**
- Fallback chain works (primary fails → secondary succeeds)
- Glossary payload includes approved terms
- MT cache hit rate > 80% on second run
- Provider failure doesn't crash app

---

### Epic 4: Term Extraction Pro (Advanced Association Measures)
**Priority:** P1
**Complexity:** M (Medium)
**Estimated Effort:** 2 weeks

**What:**
- Termhood algorithm presets (PMI/Dice/LLR/Keyness/Weirdness)
- Reference corpus selection UI
- Reproducibility (save extraction config)
- Explainability: "Why is this term ranked #1?"
- Candidate filtering (min freq, min doc freq, POS patterns)
- Batch re-extraction with progress

**Why:**
- Professional terminologists need transparency
- Enables domain-specific term extraction
- Supports research workflows (reproducible experiments)

**Components:**
- `app/services/term_extraction_service.py` (ENHANCE: presets, explainability)
- `app/ui/term_extraction_panel.py` (NEW: config UI)
- `app/domain/term_extraction/explainer.py` (NEW: why-ranked logic)
- `app/infra/sa_models.py` (ENHANCE: extraction_config JSON field in TermCluster)

**Dependencies:**
- M5 complete (already done)

**Risks:**
- Explainability complexity (medium risk)
- Reference corpus management (low risk)

**Test Strategy:**
- Unit tests for each algorithm
- E2E test: extract → explain → verify reasoning
- Reproducibility test: same config → same results

**Acceptance Criteria:**
- All presets produce ranked lists
- Explainability shows formula breakdown
- Extraction config serializes to JSON
- Re-extraction with same config produces identical results

---

### Epic 5: Import/Export Premium
**Priority:** P1
**Complexity:** M (Medium)
**Estimated Effort:** 2 weeks

**What:**
- Schema validation (detect column types automatically)
- Import preview (show first 10 rows before committing)
- Conflict resolution UI (side-by-side comparison)
- Versioned snapshot DB (before every import)
- Import history log (who imported what when)
- Export templates (customizable column selection)

**Why:**
- Reduces import errors by 90%
- Enables safe experimentation (can rollback)
- Supports collaborative workflows (audit trail)

**Components:**
- `app/services/dictionary_import_service.py` (ENHANCE: preview, validation)
- `app/services/snapshot_service.py` (IMPLEMENT)
- `app/ui/import_wizard.py` (ENHANCE: preview step, conflict UI)
- `app/ui/export_view.py` (ENHANCE: templates)
- `dict_import_log` table (NEW: import history)

**Dependencies:**
- M10 complete (snapshot service)

**Risks:**
- Large import preview performance (medium risk)
- Snapshot storage cost (low risk)

**Test Strategy:**
- Unit tests for validation rules
- UI test: import with conflicts → resolve → verify
- Rollback test: import → snapshot → rollback

**Acceptance Criteria:**
- Preview shows first 10 rows in < 500ms
- Conflict UI shows side-by-side diff
- Snapshot created automatically (< 2 seconds for 100MB DB)
- Import history log persists correctly

---

### Epic 6: QA/Coverage Pro
**Priority:** P1
**Complexity:** S (Small)
**Estimated Effort:** 1 week

**What:**
- Coverage trends over time (chart)
- Untranslated hotspots (by document, by POS)
- Quality metrics (translation consistency, termhood-weighted coverage)
- Export coverage report (PDF/HTML)
- Coverage goals and alerts (e.g., "Alert if coverage drops below 75%")

**Why:**
- Enables data-driven translation prioritization
- Supports project management workflows
- Provides visibility into translation progress

**Components:**
- `app/services/coverage_service.py` (ENHANCE: trends, hotspots, quality metrics)
- `app/ui/coverage_panel.py` (ENHANCE: charts, export)
- `coverage_snapshot` table (NEW: historical coverage data)

**Dependencies:**
- P2 complete (already done)

**Risks:**
- Chart rendering performance (low risk)

**Test Strategy:**
- Unit tests for metrics calculations
- UI test: export coverage report → verify PDF
- Performance test: compute trends for 10K lemmas

**Acceptance Criteria:**
- Coverage chart shows trend over 7 snapshots
- Hotspot analysis identifies top 10 documents
- Quality metrics include termhood-weighted coverage
- Export generates valid PDF/HTML

---

### Epic 7: History and Audit Pro
**Priority:** P2
**Complexity:** M (Medium)
**Estimated Effort:** 2 weeks

**What:**
- Immutable history log for all TM changes
- Diff view (before/after comparison)
- Revert with reason (mandatory comment)
- Rollback to timestamp (restore DB to specific point)
- Audit report (who changed what when)
- Change notifications (email/webhook for critical changes)

**Why:**
- Supports compliance and audit requirements
- Enables collaborative workflows with accountability
- Prevents accidental data loss

**Components:**
- `tm_entry_history` table (ENHANCE: add reason field)
- `app/services/translation_admin_service.py` (ENHANCE: revert with reason)
- `app/ui/history_dialog.py` (ENHANCE: diff view)
- `app/services/audit_service.py` (NEW)
- `audit_log` table (NEW)

**Dependencies:**
- P2 complete (already done)

**Risks:**
- Storage cost for history (medium risk)
- Performance of diff calculation (low risk)

**Test Strategy:**
- Unit tests for diff algorithm
- E2E test: edit → revert with reason → verify history
- Audit test: generate report for date range

**Acceptance Criteria:**
- Diff view shows before/after side-by-side
- Revert requires mandatory reason (max 500 chars)
- Audit report exports to CSV
- Rollback restores DB to specific timestamp

---

### Epic 8: Security and Data Protection
**Priority:** P0
**Complexity:** M (Medium)
**Estimated Effort:** 2 weeks

**What:**
- Input sanitization (SQL injection, command injection, path traversal)
- CSV injection protection (already done, verify)
- File upload validation (max size, allowed types, virus scan integration)
- Secure credential storage (for MT API keys)
- Data encryption at rest (optional, configurable)
- Security audit logging

**Why:**
- Blocks common attack vectors
- Protects sensitive translation data
- Enables enterprise deployments

**Components:**
- `app/infra/security/` (NEW: sanitizer, validator, crypto modules)
- `app/infra/settings.py` (ENHANCE: secure credential storage)
- All services (AUDIT: input validation)
- `security_audit_log` table (NEW)

**Dependencies:**
- None

**Risks:**
- Encryption performance overhead (medium risk)
- Credential storage cross-platform compatibility (low risk)

**Test Strategy:**
- Security test suite with injection attempts
- Penetration testing (manual)
- Encryption performance benchmark

**Acceptance Criteria:**
- All inputs validated (whitelist approach)
- CSV injection protection verified (test_p3_export_csv_injection.py PASS)
- API keys encrypted at rest
- Security audit log captures all sensitive operations

---

### Epic 9: Localization and Accessibility
**Priority:** P2
**Complexity:** L (Large)
**Estimated Effort:** 3-4 weeks

**What:**
- i18n framework (gettext or Qt Linguist)
- UI strings externalized (RU/HE/EN)
- RTL layout support for Hebrew
- Accessibility: screen reader support, keyboard navigation, high contrast
- Font scaling (125%, 150%, 200%)
- Color-blind friendly color schemes

**Why:**
- Reaches international markets (RU, HE, EN users)
- Meets accessibility standards (WCAG 2.1 AA)
- Supports diverse user needs

**Components:**
- `app/i18n/` (NEW: translation files)
- All UI components (ENHANCE: externalize strings)
- `app/ui/styles/` (NEW: themes and color schemes)
- `app/infra/settings.py` (ENHANCE: language + theme selection)

**Dependencies:**
- Epic 2 (UI Pro Workspace) for theme system

**Risks:**
- RTL layout bugs (medium risk)
- Translation maintenance cost (high risk)

**Test Strategy:**
- Manual testing in each language
- Accessibility audit with screen reader
- Visual regression testing for RTL

**Acceptance Criteria:**
- All UI strings translated to RU/HE/EN
- RTL layout works correctly in Hebrew
- Screen reader reads all UI elements
- Font scaling works at 125%, 150%, 200%

---

### Epic 10: Performance and Scalability
**Priority:** P1
**Complexity:** M (Medium)
**Estimated Effort:** 2 weeks

**What:**
- Performance budget enforcement (fail test if exceeded)
- Profiling integration (cProfile, memory_profiler)
- Database query optimization (EXPLAIN QUERY PLAN for all queries)
- Batch processing for large operations (chunk size tuning)
- Progress indicators with cancellation support
- Resource monitoring (CPU, memory, disk)

**Why:**
- Ensures app remains responsive at scale
- Prevents performance regressions
- Enables large corpus processing (100K+ sentences)

**Components:**
- `tests/benchmarks/` (NEW: performance tests)
- `app/infra/profiler.py` (NEW: profiling wrapper)
- All services (AUDIT: query optimization)
- `app/ui/workers.py` (ENHANCE: cancellation support)

**Dependencies:**
- None

**Risks:**
- Performance budget too strict (medium risk)
- Profiling overhead (low risk)

**Test Strategy:**
- Benchmark suite (run before every release)
- Load testing with large corpora (100K sentences)
- Memory leak detection (run overnight)

**Acceptance Criteria:**
- All operations meet performance budget (defined in North Star)
- Benchmark suite runs in < 5 minutes
- No memory leaks detected
- Cancellation works for all long-running operations

---

## 3. UI/UX Constraints

These constraints **MUST** be followed for all UI work:

### 3.1 Layout Constraints

**Prohibited:**
- ❌ Fixed heights for content areas (e.g., `setFixedHeight(400)`)
- ❌ Fixed widths for content areas (e.g., `setFixedWidth(600)`)
- ❌ Non-scrollable long content (must add scroll areas)

**Required:**
- ✅ Flexible layouts (use `QVBoxLayout`, `QHBoxLayout`, `QSplitter`)
- ✅ Minimum sizes only (e.g., `setMinimumHeight(200)`)
- ✅ Scroll areas for long content (vertical scroll for lists/tables)
- ✅ Overflow handling for tables (`horizontalScrollBarPolicy`)

### 3.2 Safe Insets and Margins

**Required:**
- ✅ Content must respect safe insets (margins from window edges)
- ✅ Minimum margin: 10px from all edges
- ✅ Buttons must not hide behind window chrome
- ✅ Text must not clip at window edges

### 3.3 Accessibility Requirements

**Required:**
- ✅ All actions accessible via keyboard (Tab, Shift+Tab, Enter, Space)
- ✅ Focus indicators visible (highlight current widget)
- ✅ Keyboard shortcuts documented (Ctrl+S, Ctrl+O, etc.)
- ✅ Sufficient color contrast (WCAG 2.1 AA: 4.5:1 for text)
- ✅ Readable font scaling (support 125%, 150%, 200%)

**Prohibited:**
- ❌ Mouse-only interactions
- ❌ Low contrast text (e.g., light gray on white)
- ❌ Fixed font sizes (must scale with system settings)

### 3.4 Responsiveness

**Required:**
- ✅ All long operations (> 100ms) in worker threads
- ✅ Progress indicators for operations > 1 second
- ✅ Cancellation support for operations > 5 seconds
- ✅ No UI freezes (main thread always responsive)

**Prohibited:**
- ❌ Blocking main thread (e.g., `time.sleep()` in UI code)
- ❌ Operations > 100ms without progress indicator
- ❌ Non-cancelable long operations

### 3.5 Error Handling

**Required:**
- ✅ All errors have user-friendly messages (no raw exceptions)
- ✅ Actionable error messages ("Click here to fix" or "Try X instead")
- ✅ Non-modal error notifications for non-critical errors
- ✅ Modal dialogs only for errors requiring user decision

**Prohibited:**
- ❌ Silent failures (must log and notify user)
- ❌ Technical jargon in error messages (e.g., "KeyError: 'lemma_id'")
- ❌ Errors without recovery path

### 3.6 UI DoD (Definition of Done) Evidence

**For every UI task, provide:**
1. **Screenshot/Recording:** Show UI before and after changes
2. **Scenario List:** Document all tested scenarios (happy path, edge cases, errors)
3. **Checklist:** Verify all constraints above (flexible layout, accessibility, responsiveness, etc.)
4. **Keyboard Navigation:** Document keyboard shortcuts and tab order
5. **Error Scenarios:** Test and screenshot all error cases

**Template:**
```markdown
## UI DoD Evidence: [Feature Name]

### Screenshots
- Before: [screenshot]
- After: [screenshot]
- Error state: [screenshot]

### Tested Scenarios
1. Happy path: [description]
2. Edge case 1: [description]
3. Error case 1: [description]

### Constraint Checklist
- [x] Flexible layout (no fixed heights/widths)
- [x] Scrollable content
- [x] Safe insets (10px margins)
- [x] Keyboard accessible (Tab, Enter, shortcuts)
- [x] Focus indicators visible
- [x] Sufficient contrast (4.5:1)
- [x] Font scaling works (125%, 150%, 200%)
- [x] No UI freezes (workers used)
- [x] Progress indicators (> 1s operations)
- [x] Cancellation support (> 5s operations)
- [x] User-friendly errors

### Keyboard Shortcuts
- Ctrl+S: [action]
- Ctrl+O: [action]

### Tab Order
1. [Widget 1]
2. [Widget 2]
...
```

---

## 4. Premium-Pro Feature Matrix

### 4.1 Feature Prioritization

| Feature | Priority | Complexity | Estimated Effort | Epic | Phase |
|---------|----------|------------|------------------|------|-------|
| **M8: Term Curation Service** | P0 | M | 3-4 days | Epic 1 | Iteration 1 |
| **M9: TBX/TMX Export** | P0 | M | 2-3 days | Epic 1 | Iteration 1 |
| **M10: PyInstaller + Installer** | P0 | M | 3-4 days | Epic 1 | Iteration 1 |
| **Security Audit + Sanitization** | P0 | M | 2 weeks | Epic 8 | Iteration 2 |
| **Multi-panel Workspace** | P1 | L | 3 weeks | Epic 2 | Iteration 3 |
| **Command Palette** | P1 | S | 3 days | Epic 2 | Iteration 3 |
| **MT Provider Integration** | P1 | L | 3 weeks | Epic 3 | Iteration 4 |
| **Glossary Builder** | P1 | M | 1 week | Epic 3 | Iteration 4 |
| **Term Extraction Presets** | P1 | M | 1 week | Epic 4 | Iteration 4 |
| **Import Preview + Validation** | P1 | M | 1 week | Epic 5 | Iteration 5 |
| **Snapshot Service** | P1 | S | 3 days | Epic 5 | Iteration 5 |
| **Coverage Trends** | P1 | S | 1 week | Epic 6 | Iteration 5 |
| **Performance Budget** | P1 | M | 2 weeks | Epic 10 | Iteration 6 |
| **Profiling Integration** | P1 | S | 3 days | Epic 10 | Iteration 6 |
| **History Diff View** | P2 | M | 1 week | Epic 7 | Iteration 6 |
| **Audit Service** | P2 | M | 1 week | Epic 7 | Future |
| **i18n Framework (RU/HE/EN)** | P2 | L | 3 weeks | Epic 9 | Future |
| **Accessibility Audit** | P2 | M | 1 week | Epic 9 | Future |
| **RTL Layout** | P2 | M | 1 week | Epic 9 | Future |

### 4.2 Feature Dependencies

```
Epic 1 (M8-M10) → Epic 2 (UI Pro) → Epic 9 (i18n + A11y)
                → Epic 5 (Import/Export)

Epic 3 (MT) ← Epic 4 (Term Extraction)
          ↓
       Epic 6 (QA/Coverage)

Epic 8 (Security) → ALL (required for prod)

Epic 10 (Performance) → ALL (continuous)

Epic 7 (History/Audit) ← Epic 2 (UI Pro)
```

---

## 5. Iterative Implementation Plan

### Iteration 1: Complete Core Roadmap (M8-M10)
**Duration:** 2-3 weeks
**Status:** ✅ COMPLETE — v1.0.0 shipped
**Goal:** Fulfill original plan, enable standalone distribution

**P0 Tasks:**
1. **M8 Term Curation** (5 days)
   - Implement TermCardService with status workflow
   - Wire TermCardView to service
   - Add alias management UI
   - Create test_m8.py (10+ tests)
   - Document M8_COMPLETE.md

2. **M9 Export Enhancements** (4 days)
   - Implement TBX export (validate against schema)
   - Implement TMX export (validate against schema)
   - Implement Excel multi-sheet export (openpyxl)
   - Wire ExportView to service
   - Create test_m9.py (8+ tests)
   - Document M9_COMPLETE.md

3. **M10 Packaging** (5 days)
   - Implement crash recovery (ProcessService startup check)
   - Add auto-backup before migrations (DBService wrapper)
   - Create PyInstaller build.spec (bundle PyQt6 + Stanza models)
   - Create Inno Setup installer script (Windows)
   - Test on clean Windows VM
   - Create test_m10.py (5+ tests)
   - Document M10_COMPLETE.md

**Artifacts:**
- Standalone Windows installer (.exe)
- M8_COMPLETE.md, M9_COMPLETE.md, M10_COMPLETE.md
- Test suite: 23+ new tests

**Smoke Check:**
```powershell
# Install from .exe
./V_book_Setup.exe

# Launch app
# Verify: All M1-M10 features functional
# Verify: Import → Process → Extract → Translate → Export workflow
```

**DoD:**
- All M8-M10 tests PASS
- Installer creates working app in < 5 minutes
- No regressions in M1-M7 or P1-P3

---

### Iteration 2: Security Hardening
**Duration:** 2 weeks
**Status:** ✅ COMPLETE
**Goal:** Production-grade security for enterprise deployments

**P0 Tasks:**
1. **Security Audit** (3 days)
   - Audit all input points (file uploads, CSV import, search queries)
   - Audit all output points (export, logging, error messages)
   - Identify injection vulnerabilities (SQL, command, path traversal)
   - Document findings in SECURITY_AUDIT.md

2. **Input Sanitization** (4 days)
   - Implement sanitizer module (SQL, command, path, CSV)
   - Add validation for file uploads (max size, type whitelist)
   - Add validation for text inputs (max length, character whitelist)
   - Verify CSV injection protection (test_p3_export_csv_injection.py)
   - Create test_security.py (15+ tests)

3. **Credential Storage** (3 days)
   - Implement secure storage for MT API keys (platform-specific)
   - Use Windows DPAPI, macOS Keychain, Linux Secret Service
   - Encrypt database at rest (optional, configurable)
   - Create test_credential_storage.py (5+ tests)

**P1 Tasks:**
4. **Security Logging** (2 days)
   - Create security_audit_log table
   - Log all sensitive operations (import, export, TM changes)
   - Implement audit report export
   - Create test_security_audit.py (3+ tests)

**Artifacts:**
- SECURITY_AUDIT.md (findings and remediations)
- app/infra/security/ module
- Test suite: 23+ security tests

**DoD:**
- All injection attempts blocked (SQL, command, path, CSV)
- API keys encrypted at rest
- Security audit log captures all sensitive ops

---

### Iteration 3: UI Pro Workspace
**Duration:** 3 weeks
**Status:** ✅ COMPLETE
**Goal:** Professional multi-panel workspace with keyboard-driven workflows

**P1 Tasks:**
1. **Workspace Manager** (5 days)
   - Implement multi-panel layout with resizable splitters
   - Add workspace presets (save/load layouts to JSON)
   - Create workspace switcher (dropdown menu)
   - Persist workspace state (app/infra/settings.py)
   - Create test_workspace.py (8+ tests)

2. **Command Palette** (3 days)
   - Implement Ctrl+P command palette (fuzzy search)
   - Index all actions (import, export, approve, search, etc.)
   - Add keyboard shortcut hints
   - Create test_command_palette.py (5+ tests)

3. **Advanced Table Features** (4 days)
   - Multi-column sort (Shift+Click on headers)
   - Column reorder (drag-drop)
   - Frozen headers (sticky during scroll)
   - Bulk selection (Ctrl+A, Shift+Click ranges)
   - Enhance LemmaTableModel, TermClusterTableModel
   - Create test_advanced_tables.py (10+ tests)

4. **Keyboard Shortcuts** (2 days)
   - Document all shortcuts (KEYBOARD_SHORTCUTS.md)
   - Add shortcut hints in UI (tooltips)
   - Test all actions via keyboard
   - Create test_keyboard_navigation.py (15+ tests)

**Artifacts:**
- Workspace presets (JSON files)
- KEYBOARD_SHORTCUTS.md
- Test suite: 38+ UI tests

**DoD:**
- Workspace layout saves/restores correctly
- Command palette finds actions in < 50ms
- All actions accessible via keyboard
- Bulk selection works for 1000+ items

---

### Iteration 4: Translation Pro (MT + Term Extraction)
**Duration:** 4 weeks
**Status:** ✅ COMPLETE (2026-03)
**Goal:** Automated translation with MT providers + advanced term extraction

**P1 Tasks:**
1. **Translation Provider Abstraction** (5 days)
   - Implement BaseProvider interface
   - Implement DeepLProvider, GoogleProvider
   - Enhance MockProvider (return mock translations)
   - Add fallback chain logic (TranslationService)
   - Create test_translation_providers.py (10+ tests)

2. **Glossary Builder** (3 days)
   - Implement GlossaryBuilderService
   - Build payload: approved terms + aliases + exclusions
   - Format per provider (DeepL, Google, Yandex)
   - Create test_glossary_builder.py (5+ tests)

3. **MT Caching** (2 days)
   - Enhance MTCache with TTL (time-to-live)
   - Add cache invalidation strategy
   - Add keying strategy (include glossary hash in key)
   - Create test_mt_cache.py (5+ tests)

4. **Provider Configuration UI** (3 days)
   - Create settings_dialog.py (provider selection, API keys)
   - Add fallback chain editor (drag-drop to reorder)
   - Add test connection button
   - Create test_settings_dialog.py (5+ tests)

5. **Term Extraction Presets** (5 days)
   - Implement presets (PMI_HIGH, LLR_MEDIUM, DICE_LOW, TERMHOOD_HIGH)
   - Add reference corpus selection UI
   - Add explainability ("Why ranked #1?")
   - Save extraction config to JSON (reproducibility)
   - Create test_term_extraction_presets.py (8+ tests)

**Artifacts:**
- app/infra/translators/ module
- app/services/glossary_builder_service.py
- app/ui/settings_dialog.py
- Term extraction presets (JSON configs)
- Test suite: 33+ tests

**DoD:**
- Fallback chain works (primary fails → secondary succeeds)
- Glossary payload includes approved terms
- MT cache hit rate > 80% on second run
- All presets produce ranked lists
- Extraction config reproduces identical results

---

### Iteration 5: Import/Export Premium + QA Pro
**Duration:** 2 weeks
**Status:** 🔄 PARTIAL — Export Center complete; Import preview and Coverage trends in progress
**Goal:** Safe imports with preview + enhanced QA coverage

**P1 Tasks:**
1. **Import Preview** (3 days)
   - Add preview step to ImportWizard (show first 10 rows)
   - Add schema validation (detect column types)
   - Add conflict resolution UI (side-by-side diff)
   - Create test_import_preview.py (8+ tests)

2. **Snapshot Service** (2 days)
   - Implement SnapshotService (create versioned snapshots)
   - Create snapshot before every import (automatic)
   - Add rollback functionality
   - Create test_snapshot_service.py (5+ tests)

3. **Import History** (2 days)
   - Create dict_import_log table
   - Log all imports (who, what, when, result)
   - Add import history view in ImportWizard
   - Create test_import_history.py (3+ tests)

4. **Coverage Trends** (3 days)
   - Create coverage_snapshot table
   - Implement trend calculation (CoverageService)
   - Add coverage chart to CoveragePanel (matplotlib or Qt Charts)
   - Add hotspot analysis (by document, by POS)
   - Create test_coverage_trends.py (5+ tests)

5. **Export Coverage Report** (2 days)
   - Implement PDF/HTML export (reportlab or jinja2)
   - Include: coverage %, trend chart, hotspots, untranslated lists
   - Create test_coverage_report.py (3+ tests)

**Artifacts:**
- app/services/snapshot_service.py (IMPLEMENTED)
- coverage_snapshot, dict_import_log tables
- Coverage report templates (PDF/HTML)
- Test suite: 24+ tests

**DoD:**
- Preview shows first 10 rows in < 500ms
- Conflict UI shows side-by-side diff
- Snapshot created automatically (< 2s for 100MB DB)
- Coverage chart shows trend over 7 snapshots
- Coverage report exports to PDF/HTML

---

### Iteration 6: Performance + History Enhancements
**Duration:** 3 weeks
**Status:** 🔄 PARTIAL — Performance baselines and benchmarks established; History diff and audit not yet done
**Goal:** Enforce performance budgets + enhance history/audit

**P1 Tasks:**
1. **Performance Budget** (5 days)
   - Define budget for all operations (based on North Star)
   - Create tests/benchmarks/ suite (pytest-benchmark)
   - Add CI job to run benchmarks (fail if budget exceeded)
   - Optimize slow queries (EXPLAIN QUERY PLAN)
   - Create PERFORMANCE_REPORT.md

2. **Profiling Integration** (2 days)
   - Create app/infra/profiler.py (cProfile wrapper)
   - Add profiling decorators (@profile)
   - Create profiling report generator
   - Create test_profiling.py (3+ tests)

3. **Cancellation Support** (3 days)
   - Enhance all workers with cancellation support
   - Add cancel buttons to all long-running operations
   - Test cancellation for each worker
   - Create test_cancellation.py (10+ tests)

4. **History Diff View** (4 days)
   - Enhance HistoryDialog with diff view (side-by-side)
   - Add revert with reason (mandatory comment)
   - Add rollback to timestamp (restore DB)
   - Create test_history_diff.py (5+ tests)

5. **Memory Leak Detection** (2 days)
   - Create memory profiling test (memory_profiler)
   - Run overnight (8+ hours)
   - Fix any detected leaks
   - Document memory management patterns

**Artifacts:**
- tests/benchmarks/ suite
- PERFORMANCE_REPORT.md
- app/infra/profiler.py
- Enhanced HistoryDialog with diff view
- Test suite: 18+ tests

**DoD:**
- All operations meet performance budget
- Benchmark suite runs in < 5 minutes
- No memory leaks detected (8+ hour run)
- Cancellation works for all long-running ops
- Diff view shows before/after side-by-side

---

## 6. Quality Assurance Strategy

### 6.1 Testing Pyramid

**Unit Tests (70%):**
- All services (TranslationService, CoverageService, etc.)
- All domain logic (normalization, scoring, extraction)
- All utilities (sanitization, validation, crypto)
- Target: > 80% code coverage

**Integration Tests (20%):**
- Service + database (with real SQLite)
- Service + UI (with QTest)
- Provider + API (with mock servers)
- Target: All critical paths tested

**E2E Tests (10%):**
- Full workflows (import → process → extract → translate → export)
- Verification gates (P1, P3)
- UI smoke tests (instantiation, navigation)
- Target: All user scenarios tested

### 6.2 Verification Gates

**P1 Verification Gate:**
- Run before every release
- Verify TM persistence through re-extraction
- Status: PASS required (not PARTIAL or FAIL)
- Runtime: < 5 seconds (50MB DB)

**P3 Verification Gate:**
- Run before every release
- Verify import/export/conflicts (8 steps)
- Status: PASS required (all 8 steps)
- Runtime: < 5 seconds (snapshot creation + verification)

**Custom Gates (Future):**
- Performance gate: All benchmarks pass
- Security gate: All injection attempts blocked
- Accessibility gate: Screen reader test passes

### 6.3 Anti-Flake Strategy

**Principles:**
1. **Deterministic tests:** No timing dependencies, no random data
2. **Isolated tests:** Each test cleans up before/after (setUp/tearDown)
3. **Session boundaries:** Commit + expire_all after each operation
4. **20x anti-flake loop:** All tests run 20 times, must PASS 20/20

**Implementation:**
```powershell
# Run anti-flake loop
for ($i=1; $i -le 20; $i++) {
    python test_suite.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL on iteration $i"
        exit 1
    }
}
Write-Host "PASS 20/20"
```

### 6.4 Performance Testing

**Benchmarks:**
- Startup time (cold start with 10MB DB)
- Translation lookup (single + bulk)
- Term extraction (10K tokens)
- FTS search (100K sentences)
- Coverage computation (10K lemmas)
- Import speed (1000 entries/second)

**Tools:**
- pytest-benchmark for Python
- cProfile for profiling
- memory_profiler for memory leaks
- EXPLAIN QUERY PLAN for SQL

**CI Integration:**
- Run benchmarks before every release
- Fail if budget exceeded
- Store results in artifacts (trend analysis)

### 6.5 Security Testing

**Injection Tests:**
- SQL injection (malicious WHERE clauses)
- Command injection (shell metacharacters)
- Path traversal (../../../etc/passwd)
- CSV injection (=cmd|'/c calc'!A1)

**Tools:**
- Custom security test suite (test_security.py)
- Manual penetration testing
- OWASP ZAP (if web interface added)

**Audit:**
- Review all input points before release
- Review all output points before release
- Document findings and remediations

---

## 7. Release Checklist

### 7.1 Pre-Release (2 weeks before)

- [ ] All iteration tasks complete
- [ ] All tests PASS (unit + integration + E2E)
- [ ] P1 verification PASS on production-like data
- [ ] P3 verification PASS on production-like data
- [ ] Performance benchmarks meet budget
- [ ] Security tests PASS (all injection attempts blocked)
- [ ] Anti-flake loop PASS (20/20 for all tests)
- [ ] Documentation updated (CHANGELOG.md, README.md, user guide)
- [ ] Schema version correct (verify with sqlite3)

### 7.2 Release Week

- [ ] Create release branch (release/v2.0.0)
- [ ] Run full test suite on release branch (3 platforms: Windows, macOS, Linux)
- [ ] Build standalone installer (PyInstaller + Inno Setup)
- [ ] Test installer on clean Windows VM
- [ ] Test upgrade from previous version (preserve user data)
- [ ] Create release notes (CHANGELOG.md)
- [ ] Tag release (git tag v2.0.0)
- [ ] Sign installer (code signing certificate)
- [ ] Upload to distribution channel (GitHub Releases, website, etc.)

### 7.3 Post-Release

- [ ] Monitor for crash reports (first 48 hours)
- [ ] Monitor for performance regressions
- [ ] Respond to user feedback (GitHub Issues, email, etc.)
- [ ] Hot fix if critical issues found
- [ ] Update documentation based on user questions
- [ ] Plan next iteration based on feedback

### 7.4 Version Numbering

**Semantic Versioning:** MAJOR.MINOR.PATCH
- **MAJOR:** Breaking changes (schema incompatibility, API changes)
- **MINOR:** New features (M8, M9, M10, epics)
- **PATCH:** Bug fixes, performance improvements

**Actual shipped versions:**
- v1.0.0: M1-M10 + P1-P3 + Security + UI Pro + MT Integration *(shipped 2026-03)*
- v1.x.x: Epic 4 (Term Extraction Pro) + Epic 5 (TM Safety + Layered Extraction) + Epic 6 (Dictionary Maturity)

**Planned:**
- v1.x+1: Import Preview + Coverage Trends (Iteration 5 remainder)
- v2.0.0: Next major feature wave (History/Audit, Performance Budget, Localization)

---

## 8. Success Metrics (KPIs)

### 8.1 Development Velocity
- **Iterations per quarter:** 2-3 iterations
- **Features per iteration:** 5-10 P1 features
- **Tests per feature:** 3-5 tests (unit + integration)
- **Code review time:** < 24 hours

### 8.2 Quality Metrics
- **Test pass rate:** 100% (no exceptions)
- **Flake rate:** 0% (20x anti-flake loop)
- **Code coverage:** > 70% overall, > 80% for services
- **Performance budget adherence:** 100% (all benchmarks pass)
- **Security issues:** 0 critical, 0 high

### 8.3 User Satisfaction (Future)
- **NPS (Net Promoter Score):** > 50
- **Support tickets per user:** < 0.1 per month
- **Feature requests per user:** > 0.5 per quarter
- **Retention rate:** > 80% (6 months)

### 8.4 Performance Actuals (Measured)
- **Startup time:** < 2 seconds (cold start, 10MB DB)
- **Translation lookup:** < 10ms (single), < 50ms (100 items)
- **Term extraction:** < 5 seconds per 10K tokens
- **FTS search:** < 300ms (100K sentences corpus)
- **Coverage computation:** < 500ms (10K lemmas, 5K clusters)
- **Import speed:** > 1000 entries/second (CSV/XLSX)

---

## Appendix A: Technology Stack

**Core:**
- Python 3.11+ (language)
- PyQt6 (UI framework)
- SQLite 3.40+ (database)
- SQLAlchemy 2.x (ORM)

**NLP:**
- Stanza 1.7+ (Hebrew NLP)
- Regex (pattern matching)

**Import/Export:**
- openpyxl (Excel)
- pandas (CSV/data manipulation)
- xml.etree (TBX/TMX XML)
- reportlab or jinja2 (PDF/HTML reports)

**Translation:**
- requests (HTTP for MT APIs)
- DeepL API, Google Translate API, Yandex Translate API

**Testing:**
- pytest (test framework)
- pytest-qt (Qt testing)
- pytest-benchmark (performance testing)
- memory_profiler (memory leak detection)

**Packaging:**
- PyInstaller (standalone executable)
- Inno Setup (Windows installer)
- cx_Freeze (alternative packager)

**Security:**
- keyring (secure credential storage)
- cryptography (encryption)

**Profiling:**
- cProfile (profiling)
- py-spy (sampling profiler)

---

## Appendix B: File Structure (Future)

```
V_book/
├── app/
│   ├── services/
│   │   ├── term_card_service.py        # M8
│   │   ├── snapshot_service.py         # M10
│   │   ├── glossary_builder_service.py # Epic 3
│   │   ├── audit_service.py            # Epic 7
│   │   └── ...
│   ├── infra/
│   │   ├── security/
│   │   │   ├── sanitizer.py
│   │   │   ├── validator.py
│   │   │   └── crypto.py
│   │   ├── translators/
│   │   │   ├── base_provider.py
│   │   │   ├── deepl_provider.py
│   │   │   ├── google_provider.py
│   │   │   └── mock_provider.py
│   │   ├── settings.py                 # Persistent settings
│   │   ├── profiler.py                 # Performance profiling
│   │   └── ...
│   ├── ui/
│   │   ├── workspace_manager.py        # Epic 2
│   │   ├── command_palette.py          # Epic 2
│   │   ├── settings_dialog.py          # Epic 3
│   │   ├── term_extraction_panel.py    # Epic 4
│   │   └── ...
│   ├── domain/
│   │   ├── term_extraction/
│   │   │   ├── explainer.py            # Epic 4
│   │   │   └── ...
│   │   └── ...
│   ├── i18n/                           # Epic 9
│   │   ├── en.po
│   │   ├── ru.po
│   │   ├── he.po
│   │   └── ...
│   └── tools/
│       ├── p1_verify.py
│       ├── p3_verify.py
│       └── ...
├── tests/
│   ├── benchmarks/                     # Epic 10
│   │   ├── test_startup.py
│   │   ├── test_translation.py
│   │   └── ...
│   ├── security/                       # Epic 8
│   │   ├── test_injection.py
│   │   ├── test_sanitization.py
│   │   └── ...
│   └── ...
├── docs/
│   ├── IMPLEMENTED_STAGES_AUDIT.md
│   ├── PLAN_GAP_ANALYSIS.md
│   ├── ROADMAP_PREMIUM_PRO.md
│   ├── KEYBOARD_SHORTCUTS.md           # Epic 2
│   ├── SECURITY_AUDIT.md               # Epic 8
│   ├── PERFORMANCE_REPORT.md           # Epic 10
│   └── ...
├── build.spec                          # PyInstaller config
├── installer.iss                       # Inno Setup script
├── pyproject.toml
├── README.md
├── CHANGELOG.md
└── ...
```

---

**Last Updated:** 2026-03-23
**Document Version:** 2.0
**Next Review:** Before next major feature wave
**Maintainer:** Project Lead / Product Owner
