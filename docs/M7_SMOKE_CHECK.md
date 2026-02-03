# M7 + P2 Manual Smoke Check

Quick manual smoke test to verify core functionality after deployments or major changes.

## Prerequisites

- HDLE Premium application running
- Test database with at least one project
- Project has processed documents with lemmas and term clusters

## M7 Translation Memory - Basic Smoke Test

### 1. Dictionary View Translation Lookup (5 min)

**Goal**: Verify TM lookup works for lemmas.

**Steps**:
1. Open a project
2. Go to **Dictionary** tab
3. Find a lemma (e.g., בית)
4. Check **Translation** column:
   - ✓ Shows translation if exists in TM/dict
   - ✓ Shows "—" if no translation
5. Click "Add Translation" if missing
6. Enter translation (e.g., "дом")
7. Verify translation appears immediately without refresh

**Expected**: Translations display correctly, inline add works.

### 2. Terms View Translation Lookup (5 min)

**Goal**: Verify TM lookup works for term clusters.

**Steps**:
1. Go to **Terms** tab
2. Find a term cluster (e.g., בית הספר)
3. Check **Translation** column:
   - ✓ Shows translation if exists
   - ✓ Shows "—" if missing
4. Click "Add Translation" if missing
5. Enter translation (e.g., "школа")
6. Verify translation appears immediately

**Expected**: Translations display correctly, inline add works.

### 3. Concordance View Translation Display (3 min)

**Goal**: Verify translations show in concordance results.

**Steps**:
1. Go to **Concordance** tab
2. Search for a lemma that has a translation
3. Check concordance results table:
   - ✓ **Translation** column shows correct translation
   - ✓ Translation matches what's in Dictionary view

**Expected**: Translations appear in concordance results.

## P2 Premium Workflow - Basic Smoke Test

### 4. Translation Management Panel Access (2 min)

**Goal**: Verify panel opens and loads data.

**Steps**:
1. Click **Premium → Translation Management** (or Ctrl+Shift+T)
2. Panel opens with:
   - ✓ Filter controls visible (Search, Kind, Status, Scope, Origin, Source Ref)
   - ✓ Table view with TM entries (or empty if no entries)
   - ✓ Results count shows "Results: N"
   - ✓ Action buttons visible (Approve, Reject, Deprecate, View History, Cancel Search)
   - ✓ Status bar shows "Ready"

**Expected**: Panel loads without errors, UI elements present.

### 5. Search and Filter (3 min)

**Goal**: Verify filtering works.

**Steps**:
1. In Translation Management panel:
2. Set **Status** = `approved`
3. Verify table shows only approved entries
4. Change **Kind** = `lemma`
5. Verify table shows only lemmas
6. Type text in **Search** box (e.g., "בית")
7. Wait 500ms (debounce)
8. Verify table filters to matching entries
9. Click **Clear Filters**
10. Verify all entries shown again

**Expected**: Filters work, search debounces, clear works.

### 6. Inline Translation Edit (2 min)

**Goal**: Verify inline editing works.

**Steps**:
1. Find an entry in the table
2. Click on **Translation** column cell
3. Edit the translation text
4. Press Enter
5. Verify:
   - ✓ Table cell updates immediately
   - ✓ No error messages

**Expected**: Inline editing works, no errors.

### 7. Bulk Approve (3 min)

**Goal**: Verify bulk status change.

**Steps**:
1. Set filter **Status** = `draft` (if no drafts, skip)
2. Select 1-2 entries (Ctrl+Click)
3. Click **✓ Approve Selected**
4. Confirm dialog
5. Verify:
   - ✓ Success message appears
   - ✓ Table refreshes
   - ✓ Entries no longer in draft list

**Expected**: Bulk approve works, transactional.

### 8. View History (2 min)

**Goal**: Verify history dialog opens.

**Steps**:
1. Select any entry
2. Click **📜 View History**
3. Verify:
   - ✓ History dialog opens
   - ✓ Shows version list (or "No history" if new entry)
   - ✓ Each version shows: version number, change_kind, timestamp, translation, status, origin
4. Close dialog

**Expected**: History dialog works, shows versions.

### 9. QA/Coverage Panel Access (2 min)

**Goal**: Verify coverage panel opens.

**Steps**:
1. Ensure a project is open (Coverage requires project context)
2. Click **Premium → QA / Coverage** (or Ctrl+Shift+C)
3. Panel opens with:
   - ✓ **Lemma Coverage** metric displayed (percentage)
   - ✓ **Term Cluster Coverage** metric displayed
   - ✓ Progress bars showing coverage
   - ✓ Tabs: "Untranslated Lemmas" and "Untranslated Term Clusters"
   - ✓ Options: "Include Draft TM in Coverage" checkbox, Refresh button, Cancel button
   - ✓ Status bar shows "Ready" after loading

**Expected**: Panel loads, metrics display correctly.

### 10. Coverage Metrics Accuracy (3 min)

**Goal**: Verify coverage calculation is reasonable.

**Steps**:
1. In Coverage panel, note **Lemma Coverage** percentage
2. Switch to **Dictionary** view
3. Count rough number of lemmas with translations vs without
4. Verify coverage % is approximately correct
5. Go back to Coverage panel
6. Check **Include Draft TM in Coverage**
7. Click **🔄 Refresh**
8. Verify:
   - ✓ Coverage % changes (increases if drafts exist)
   - ✓ Metrics update

**Expected**: Coverage calculation is reasonable, draft toggle works.

### 11. Untranslated Lists (2 min)

**Goal**: Verify untranslated item lists.

**Steps**:
1. In Coverage panel, go to **Untranslated Lemmas** tab
2. Verify:
   - ✓ Table shows lemmas without translations
   - ✓ Columns: Lemma, POS, Frequency, Doc Freq
   - ✓ Ordered by frequency (default)
3. Change **Order by** to `alpha`
4. Verify table reorders alphabetically
5. Switch to **Untranslated Term Clusters** tab
6. Verify:
   - ✓ Table shows term clusters without translations
   - ✓ Columns: Term, Canonical, Termhood, Frequency
   - ✓ Ordered by termhood (default)

**Expected**: Untranslated lists display correctly, ordering works.

### 12. Cancel Operations (2 min)

**Goal**: Verify cancel buttons work.

**Steps**:
1. In Translation Management panel, enter a search query
2. While search is running, click **✕ Cancel Search**
3. Verify:
   - ✓ Search stops
   - ✓ Status shows "Search canceled"
   - ✓ Cancel button disables
4. Go to Coverage panel
5. Click **🔄 Refresh**
6. While loading, click **✕ Cancel**
7. Verify:
   - ✓ Coverage calculation stops
   - ✓ Status shows "Coverage calculation canceled"

**Expected**: Cancel buttons stop background operations.

### 13. Worker Cleanup on Close (1 min)

**Goal**: Verify workers stop when panel closes.

**Steps**:
1. In Coverage panel, click **🔄 Refresh**
2. Immediately click **← Back** button (before loading completes)
3. Verify:
   - ✓ Panel closes without error
   - ✓ No warnings in console about running workers
4. Reopen Coverage panel
5. Verify:
   - ✓ Panel loads fresh data
   - ✓ No stale worker references

**Expected**: Workers stop cleanly on panel close.

## Summary Checklist

**M7 Core (3 checks)**:
- [ ] Dictionary view translation lookup
- [ ] Terms view translation lookup
- [ ] Concordance view translation display

**P2 Translation Management (6 checks)**:
- [ ] Panel access and UI
- [ ] Search and filter
- [ ] Inline edit
- [ ] Bulk approve
- [ ] View history
- [ ] Cancel search

**P2 Coverage (4 checks)**:
- [ ] Panel access and UI
- [ ] Coverage metrics accuracy
- [ ] Untranslated lists
- [ ] Cancel coverage

**P2 Worker Cleanup (1 check)**:
- [ ] Worker cleanup on close

**Total**: 14 manual checks, ~30 minutes

## Troubleshooting

### Panel Won't Open
- Check console for import errors
- Verify schema version >= 6
- Ensure db_service initialized

### Coverage Shows 0%
- Verify project has lemmas/clusters
- Check if TM entries exist: `SELECT COUNT(*) FROM tm_entry;`
- Try "Include Draft TM" option

### Workers Won't Cancel
- Check if worker.terminate() called in on_cancel_*
- Verify closeEvent implemented
- Look for worker.wait() after terminate()

### Search Returns No Results
- Click "Clear Filters" to reset
- Check if database has TM entries
- Try global scope instead of project scope
