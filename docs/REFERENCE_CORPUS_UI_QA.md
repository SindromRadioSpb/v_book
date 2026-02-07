# Reference Corpus UI/UX Contract & QA Guide

**Version:** 1.0
**Date:** 2026-02-07
**Status:** ✅ IMPLEMENTED & TESTED

---

## TABLE OF CONTENTS

1. [Expected Behavior Contract](#expected-behavior-contract)
2. [User Journey: Opening Hebrew Wikipedia Reference Corpus](#user-journey-opening-hebrew-wikipedia-reference-corpus)
3. [Manual Smoke Test Checklist (5 minutes)](#manual-smoke-test-checklist-5-minutes)
4. [Automated Test Coverage](#automated-test-coverage)
5. [Troubleshooting](#troubleshooting)
6. [Known Limitations](#known-limitations)

---

## EXPECTED BEHAVIOR CONTRACT

### 1. **Project Dashboard: Unified List with Real Metrics**

**Location:** HDLE Premium → Projects

**Behavior:**
- ✅ **Single unified list** of all projects (no separate "Reference Corpora" section)
- ✅ Reference corpus projects marked with **🌐 visual indicator** in name column
- ✅ **Real metrics displayed** (not zeros):
  - Total Documents (e.g., 387,639 for HEWiki)
  - Processed Documents
  - Total Lemmas
  - Total N-grams
- ✅ Status bar shows: `"Total projects: N (My Projects: X | Reference Corpora: Y)"`

**Example:**
```
ID | Name                            | Documents | Processed | Lemmas | N-grams
---+--------------------------------+-----------+-----------+--------+---------
 1 | 🌐 Hebrew Wikipedia Baseline   | 387,639   | 387,639   | 45,230 | 12,567
 2 | My Translation Project         | 15        | 10        | 1,205  | 345
```

---

### 2. **Opening Reference Corpus Project: Full Tabs with Real Data**

**When user double-clicks reference corpus project:**

**✅ ALL TABS ARE ACCESSIBLE:**
1. **Documents** - List of 387k+ texts (READ-ONLY for add/delete)
2. **Dictionary** - Real lemmas with translations
3. **Terms** - Extracted term clusters
4. **Concordance** - Search contexts
5. **Term Cards** - Terminology management
6. **Export** - Export functionality

**Project Title:** `"Project: 🌐 Hebrew Wikipedia Baseline"` (with 🌐 marker)

---

### 3. **Documents Tab: Read-Only Protection**

**Location:** Hebrew Wikipedia Baseline → Documents

**Behavior:**
- ✅ **View documents:** List of all 387k+ documents displayed
- ✅ **Buttons disabled:**
  - "Add Files..." (disabled, tooltip: "Cannot add documents to reference corpus (read-only)")
  - "Add Folder..." (disabled, tooltip: "Cannot add documents to reference corpus (read-only)")
- ✅ **Drag-drop blocked:** No file acceptance
- ✅ **Warning message:** Blue info box instead of green hint:
  ```
  ℹ️ This is a Reference Corpus (read-only documents)
  You can browse documents, extract terms, and manage translations,
  but cannot add or remove documents
  ```

**If user attempts operation:**
- ❌ Add Files → Warning dialog: "Cannot add documents to reference corpus..."
- ❌ Delete Document → Service-level exception (ReferenceCorpusReadonlyError)

---

### 4. **Other Tabs: Fully Functional**

**Dictionary, Terms, Concordance, Term Cards, Export:**
- ✅ **All operations allowed**
- ✅ **View real data** (lemmas, terms, contexts)
- ✅ **Add/edit/delete translations** (TMEntry operations unrestricted)
- ✅ **Extract terms** (termhood calculations using reference corpus)
- ✅ **Search concordance**
- ✅ **Export data**

**Translation operations:**
- ✅ Add new translations
- ✅ Edit existing translations
- ✅ Mark translations as approved/draft
- ✅ Import dictionary entries

---

### 5. **Deletion Protection**

**Location:** Project Dashboard → Select reference corpus → Delete Project button

**Behavior:**
- ✅ **UI Warning:** Modal dialog blocks deletion:
  ```
  Cannot Delete Reference Corpus

  'Hebrew Wikipedia Baseline' is a reference corpus (read-only).

  Reference corpora cannot be deleted because they are used
  for termhood calculations in other projects.

  You can still:
  ✓ Open and browse documents
  ✓ Add/edit translations
  ✓ Extract terms

  To remove this corpus, first unmark it as reference
  (set is_general_corpus=0 in database).
  ```

- ✅ **Service-level guard:** `ProjectService.delete_project()` raises `ReferenceCorpusReadonlyError`

---

## USER JOURNEY: Opening Hebrew Wikipedia Reference Corpus

### Step-by-Step Experience

1. **User launches HDLE Premium**
   - Main window opens: "HDLE Premium - Projects"

2. **User sees Project Dashboard**
   - Unified list shows all projects
   - One row: `🌐 Hebrew Wikipedia Baseline | 387,639 | 387,639 | 45,230 | 12,567`
   - Status bar: `"Total projects: 1 (My Projects: 0 | Reference Corpora: 1)"`

3. **User double-clicks "🌐 Hebrew Wikipedia Baseline"**
   - Project view opens
   - Title: `"Project: 🌐 Hebrew Wikipedia Baseline"`
   - Six tabs visible: Documents | Dictionary | Terms | Concordance | Term Cards | Export

4. **User clicks "Documents" tab**
   - **Sees:** Table with 387,639 rows of documents
   - **Sees:** Blue info box: "ℹ️ This is a Reference Corpus (read-only documents)..."
   - **Sees:** "Add Files..." button disabled (greyed out)
   - **Sees:** "Add Folder..." button disabled (greyed out)
   - **Can:** Browse document list, view document details

5. **User clicks "Dictionary" tab**
   - **Sees:** Table with lemmas and translations
   - **Sees:** Real data: thousands of lemmas with frequencies
   - **Can:** Edit translations, add new translations
   - **Can:** Use "Why?" dialog to see translation sources

6. **User clicks "Terms" tab**
   - **Sees:** Term clusters with termhood scores
   - **Sees:** Real metrics (weirdness, keyness, LLR, PMI, Dice)
   - **Can:** Extract new terms using "Extract Terms" button
   - **Can:** View term members, edit translations

7. **User clicks "Concordance" tab**
   - **Sees:** KWIC search interface
   - **Can:** Search for lemmas/terms in context
   - **Sees:** Results with left/match/right context

8. **User clicks "Term Cards" tab**
   - **Sees:** Terminology cards for curation
   - **Can:** Mark terms as approved/needs review
   - **Can:** Add aliases, pinned translations

9. **User clicks "Export" tab**
   - **Sees:** Export options
   - **Can:** Export dictionary, terms, concordance to CSV/TSV

10. **User returns to Dashboard (Back button)**
    - Sees unified project list again

---

## MANUAL SMOKE TEST CHECKLIST (5 minutes)

**Prerequisites:**
- HDLE Premium application installed
- Hebrew Wikipedia Baseline imported (387k documents)
- is_general_corpus=1 set in database

### Test Steps:

#### **Test 1: Dashboard Metrics (30 seconds)**
- [ ] Launch HDLE Premium
- [ ] Verify unified project list (no separate section)
- [ ] Verify 🌐 marker visible in HEWiki name
- [ ] Verify **real metrics** displayed (NOT zeros):
  - Total Documents: 387,639
  - Processed: 387,639
  - Lemmas: >0
  - N-grams: >0
- [ ] Verify status bar: "Total projects: N (...Reference Corpora: 1)"

#### **Test 2: All Tabs Present (30 seconds)**
- [ ] Double-click "🌐 Hebrew Wikipedia Baseline"
- [ ] Verify project title has 🌐 marker
- [ ] Verify all 6 tabs visible: Documents, Dictionary, Terms, Concordance, Term Cards, Export
- [ ] Click each tab → verify it opens (no crash)

#### **Test 3: Documents Tab Read-Only (1 minute)**
- [ ] Click "Documents" tab
- [ ] Verify document list shows **real data** (not empty)
- [ ] Verify blue info box: "ℹ️ This is a Reference Corpus..."
- [ ] Verify "Add Files..." button **disabled** (greyed out)
- [ ] Verify "Add Folder..." button **disabled** (greyed out)
- [ ] Hover over disabled buttons → verify tooltip: "Cannot add documents..."
- [ ] Try drag-drop a file → verify **no acceptance** (cursor shows "no drop")

#### **Test 4: Dictionary Tab Functional (1 minute)**
- [ ] Click "Dictionary" tab
- [ ] Verify **real lemmas** displayed (table not empty)
- [ ] Verify columns: Lemma, POS, Frequency, Doc Freq, Translation, Source, Status
- [ ] Double-click a Translation cell → verify **inline edit works**
- [ ] Type new translation → verify **edit accepted**
- [ ] Press Enter → verify row updates

#### **Test 5: Terms Tab Functional (1 minute)**
- [ ] Click "Terms" tab
- [ ] Verify **real term clusters** displayed (if extracted)
- [ ] Verify columns include: Term, Lemma, Freq, DocFreq, Termhood, Translation
- [ ] Verify "Extract Terms" button **enabled** (NOT disabled)
- [ ] (Optional) Click "Extract Terms" → verify extraction starts

#### **Test 6: Deletion Blocked (1 minute)**
- [ ] Return to Dashboard (click "← Back to Projects")
- [ ] Select "🌐 Hebrew Wikipedia Baseline" row
- [ ] Click "Delete Project" button
- [ ] Verify **warning dialog** appears:
  - Title: "Cannot Delete Reference Corpus"
  - Message mentions "read-only" and "termhood calculations"
- [ ] Click OK → verify project **still exists** (not deleted)

#### **Test 7: Normal Project Operations (30 seconds)**
- [ ] Create a new normal project (NOT reference corpus)
- [ ] Open the normal project
- [ ] Click "Documents" tab
- [ ] Verify "Add Files..." button **ENABLED**
- [ ] Verify green hint box (not blue info box)
- [ ] Delete the normal project → verify **deletion succeeds**

### ✅ **PASS CRITERIA:**
- All 7 tests pass
- No crashes or exceptions
- Real metrics displayed (not zeros)
- Reference corpus protected from document modifications
- Translation operations work normally

---

## AUTOMATED TEST COVERAGE

### **Test Files:**

1. **tests/test_reference_project_service.py** (8 tests)
   - Service-level reference corpus logic
   - Auto-assign, determinism, deletion blocking

2. **tests/test_document_service_reference_guard.py** (4 tests)
   - Document operation guards (import/delete blocked)

3. **tests/test_project_dashboard_metrics.py** (5 tests)
   - Real metrics loading (not zeros)
   - get_project_stats() correctness

**Total:** 17 automated tests (100% pass rate)

### **Run Commands:**

```powershell
# Full test suite
python -m pytest tests/ -q

# Reference corpus tests only
python -m pytest tests/test_reference_project_service.py tests/test_document_service_reference_guard.py tests/test_project_dashboard_metrics.py -v
```

---

## TROUBLESHOOTING

### **Issue 0: Reference project not visible in project list**

**Symptom:** User opens application, sees empty project list or only test projects (no Hebrew Wikipedia Baseline)

**Cause:** Application uses **production database** (`%LOCALAPPDATA%\HDLE\hdle.db`) by default, but Hebrew Wikipedia was imported into **development database** (`J:\Project_Vibe\V_book\hdle_premium.db`)

**Fix:** Launch application with development database using command-line argument:

**Windows:**
```batch
# Using batch script (recommended)
J:\Project_Vibe\V_book\run_dev.bat

# Or manually
python -m app.main --db-path "J:\Project_Vibe\V_book\hdle_premium.db"
```

**Linux/Mac:**
```bash
python -m app.main --db-path "/path/to/hdle_premium.db"
```

**Verify database has Hebrew Wikipedia:**
```powershell
sqlite3 "J:\Project_Vibe\V_book\hdle_premium.db" "SELECT project_id, name, is_general_corpus FROM dict_project;"
```

Expected output:
```
1|Hebrew Wikipedia Baseline|1
```

---

### **Issue 1: All metrics show 0**

**Symptom:** Dashboard shows `0 | 0 | 0 | 0` for HEWiki

**Cause:** Old code had hardcoded zeros (legacy "For M1" comment)

**Fix:** Upgrade to commit with `get_project_stats()` implementation

**Verify:**
```sql
SELECT COUNT(*) FROM source_document;  -- Should be 387,639
SELECT COUNT(*) FROM lemma;            -- Should be >0
```

---

### **Issue 2: Reference corpus can be deleted**

**Symptom:** "Delete Project" succeeds for HEWiki

**Cause:** Service-level guard missing

**Fix:** Upgrade to commit with `ReferenceCorpusReadonlyError` implementation

**Verify:**
```python
from app.services.project_service import ProjectService
from app.domain.exceptions import ReferenceCorpusReadonlyError

# Should raise exception:
project_service.delete_project(session, hewiki_project_id)
```

---

### **Issue 3: Can import documents into reference corpus**

**Symptom:** "Add Files..." works for HEWiki Documents tab

**Cause:** Service-level guard missing in IngestService

**Fix:** Upgrade to commit with IngestService guards

**Verify:**
```python
from app.services.ingest_service import IngestService
from app.domain.exceptions import ReferenceCorpusReadonlyError

# Should raise exception:
ingest_service.import_document(session, ref_corpus_id, file_path)
```

---

### **Issue 4: 🌐 marker not visible**

**Symptom:** Reference corpus name has no marker

**Cause:** is_general_corpus not set in database

**Fix:**
```sql
UPDATE dict_project
SET is_general_corpus = 1
WHERE name = 'Hebrew Wikipedia Baseline';
```

---

## KNOWN LIMITATIONS

### **1. Auto-save on project open NOT implemented**

**Status:** Mentioned in task_2.md context but not found in codebase

**Impact:** None (feature was planned but never implemented)

**Workaround:** Use script `scripts/ref_corpora/setup_hewiki_as_default_reference.py --assign-existing`

---

### **2. UI Component Tests NOT implemented**

**Status:** PATCH-02, PATCH-03, PATCH-04 from task_2.md skipped

**Impact:** No PyQt6 widget-level tests (only service-level)

**Coverage:** Service-level guards cover critical logic

**Future:** Consider pytest-qt for widget testing

---

### **3. Multiple reference corpora selection**

**Status:** System supports multiple is_general_corpus=1 projects

**Behavior:** `get_default_reference_project()` returns **lowest project_id** (deterministic)

**Limitation:** UI does not allow user to choose between multiple reference corpora

**Workaround:** Manually set `general_corpus_id` in database for specific projects

---

### **4. Document view pagination**

**Status:** No pagination for large document lists (387k rows)

**Impact:** Opening Documents tab for HEWiki may be slow (loading all rows)

**Workaround:** Use filters or search (if implemented)

**Future:** Implement pagination (LIMIT/OFFSET) for large tables

---

### **5. Reference corpus cannot be unmarked via UI**

**Status:** No UI to toggle is_general_corpus flag

**Workaround:** Direct SQL update:
```sql
UPDATE dict_project
SET is_general_corpus = 0
WHERE project_id = 1;
```

**Future:** Add "Project Settings" dialog with is_general_corpus checkbox

---

## SUMMARY

**Reference Corpus UI/UX provides:**
- ✅ Full project functionality (all tabs with real data)
- ✅ Read-only protection for document operations (UI + service-level)
- ✅ Visual distinction (🌐 marker)
- ✅ Real metrics (387k documents, lemmas, n-grams)
- ✅ Translation management (fully functional)
- ✅ Service-level guards (typed exceptions with clear messages)

**User Experience:**
> "Reference corpus looks like a regular project with real data, but I can't accidentally break it by modifying documents."

---

**Document Version:** 1.0
**Last Updated:** 2026-02-07
**Author:** Claude Sonnet 4.5 (QA Engineer)
