# P2 Premium Workflow - Translation Management & QA

## Overview

**P2 Premium Workflow** provides advanced translation management and quality assurance features for power users. It consists of two main components:

1. **Translation Management Panel**: Search, edit, approve/reject translations in the Translation Memory (TM)
2. **QA/Coverage Panel**: View coverage metrics and identify untranslated items

## Workspace Navigation Contract (PATCH-01..06)

The application now uses a deterministic workspace contract to avoid duplicate views and unstable routing:

- Sidebar primary navigation: `Projects`, `Translation Management`, `User Dictionaries`, `Audio Player`.
- Repeated open action focuses existing workspace instance when context is the same.
- Current Project is a single source-of-truth (`current_project_id`) in `AppWindow`.
- Sidebar `Current Project` card exposes deep links to:
  - `Documents`
  - `Sentences`
  - `Dictionary`
  - `Terms`
  - `Term Cards`
  - `Export`
- Scope chips in TM and User Dictionaries are harmonized:
  - `Current Project` vs `All`
  - Scope selection persists per workspace between sessions.
- Project quick search in sidebar:
  - debounce `280ms`
  - min query length `2`
  - ranking order: recent boost, exact, prefix, contains
  - keyboard navigation: `Up/Down/Enter/Esc`
- Sidebar collapsible sections:
  - `Project Search` and `Tools` have expanded/collapsed state persistence.
- Navigation feedback:
  - status-line updates for route/focus operations
  - deterministic home: `Projects Dashboard`
  - workspace back flow focuses existing instances and does not create new views.
- Current Project CTA behavior:
  - when current project is not set, `Open Project...` routes to dashboard;
  - deep-link tab request is queued and auto-routed after the user opens a project.
- Shortcut safety:
  - startup validates duplicate active shortcut bindings and emits warnings if conflicts are found.

## Features

### Translation Management Panel

**Access**: `Premium → Translation Management` (Ctrl+Shift+T)

**Capabilities**:
- Search and filter TM entries by kind, status, scope, origin, source reference
- View all TM entries with metadata (ID, kind, source, translation, status, scope, origin, source ref, last updated)
- Non-intrusive study tooltip enrichment (from User Dictionaries/SRS state) on TM rows
- **Inline editing**: Click on translation column to edit directly
- **Bulk operations**: Approve, reject, or deprecate multiple entries at once
- **History viewer**: See all previous versions of a translation
- **Revert**: Restore a translation to any previous version
- **Project/Global scope**: Manage project-specific or global TM entries

**Filters**:
- **Search**: Free text search in source or translation
- **Kind**: lemma, term_cluster, ngram, surface, or All
- **Status**: draft, approved, rejected, deprecated, or All
- **Scope**: Project-specific, Global, or All
- **Origin**: user_edit, import, mt_accept, mt_auto, merge, revert, or All
- **Source Ref**: Filter by source reference (e.g., dict_import, ui_test)

**Workflow**:
```
Draft → Approve → Approved
      ↘ Reject → Rejected
      ↘ Deprecate → Deprecated
```

**Status Semantics**:
- **draft**: New entry, not yet reviewed
- **approved**: Reviewed and approved, will be used in translation lookup
- **rejected**: Reviewed and rejected, won't be used
- **deprecated**: Previously approved but now obsolete, won't be used

**Actions**:
- **✓ Approve Selected**: Set status to approved, sets approved_at and approved_by
- **✕ Reject Selected**: Set status to rejected, clears approved_at and approved_by
- **⊘ Deprecate Selected**: Set status to deprecated, clears approved_at and approved_by
- **📜 View History**: Show all previous versions with change history
- **Revert**: Restore translation to a previous version (sets origin="revert")

### QA/Coverage Panel

**Access**: `Premium → QA / Coverage` (Ctrl+Shift+C)

**Note**: Requires project context. Open a project first, then access this panel.

**Capabilities**:
- **Lemma Coverage**: Percentage of lemmas that have translations (from TM or dictionary)
- **Term Cluster Coverage**: Percentage of term clusters that have translations
- **Untranslated Lemmas**: List of lemmas without translations, ranked by frequency or alphabetically
- **Untranslated Term Clusters**: List of term clusters without translations, ranked by termhood, frequency, or alphabetically
- **Include Draft**: Option to count draft TM entries as "translated"

**Metrics Display**:
- Coverage percentage (large display)
- Progress bar
- Breakdown: covered / total (uncovered)

**Untranslated Lists**:
- **Lemmas**: Shows lemma text, POS, frequency, doc frequency
- **Term Clusters**: Shows representative text, canonical key, termhood score, frequency

**Use Cases**:
1. **Translation Progress Tracking**: Monitor how much of the corpus is covered
2. **Prioritization**: Identify high-frequency untranslated items to focus on
3. **Quality Assurance**: Find gaps in translation coverage
4. **Termhood-based Ranking**: Focus on technical terms first (high termhood score)

## Architecture

### Service Layer

**TranslationAdminService** (`app/services/translation_admin_service.py`):
- `search_tm_entries(session, filters, limit, offset)`: Search with filters
- `count_tm_entries(session, filters)`: Count matching entries
- `get_entry(session, tm_id)`: Get single entry
- `set_status(session, tm_id, status, approved_by)`: Change status
- `bulk_set_status(session, tm_ids, status, approved_by)`: Bulk status change
- `get_history(session, tm_id)`: Get version history
- `revert(session, tm_id, version, approved_by)`: Revert to previous version
- `update_translation(session, tm_id, translation, notes)`: Update translation

**CoverageService** (`app/services/coverage_service.py`):
- `compute_lemma_coverage(session, project_id, include_draft)`: Calculate lemma coverage %
- `compute_termcluster_coverage(session, project_id, include_draft)`: Calculate cluster coverage %
- `list_untranslated_lemmas(session, project_id, limit, order_by)`: List untranslated lemmas
- `list_untranslated_termclusters(session, project_id, limit, order_by)`: List untranslated clusters

**Performance**:
- **No N+1 queries**: All operations use efficient SQL with joins
- Query count ceilings:
  - Coverage computation: ≤ 3 queries
  - Untranslated lists: ≤ 5 queries
- Verified by automated tests with query counters

### UI Layer

**TranslationManagementPanel** (`app/ui/translation_management_panel.py`):
- Qt widget with filters, table view, and action buttons
- Uses TranslationManagementTableModel for data display
- TMSearchWorker for non-blocking search
- HistoryDialog for viewing/reverting versions

**CoveragePanel** (`app/ui/coverage_panel.py`):
- Qt widget with metrics display and tabs for untranslated items
- CoverageWorker for non-blocking coverage calculation
- Separate tables for lemmas and term clusters

**Models**:
- **TranslationManagementTableModel** (`app/ui/models_qt.py`): QAbstractTableModel for TM entries
  - 9 columns: ID, Kind, Source, Translation, Status, Scope, Origin, Source Ref, Updated
  - Translation column is editable (inline editing)
  - Emits dataChanged signal on edit

**Workers**:
- **TMSearchWorker** (`app/ui/workers.py`): Background search operation
- **CoverageWorker** (`app/ui/workers.py`): Background coverage calculation
- Both use QThread to prevent UI freeze

### Data Transfer Objects (DTOs)

**TMEntryDTO** (`app/domain/dto.py`):
```python
@dataclass
class TMEntryDTO:
    tm_id: int
    project_id: Optional[int]  # None = global
    kind: str  # lemma|ngram|term_cluster|surface
    src_lang: str
    tgt_lang: str
    src_text: str
    src_norm: str
    translation: str
    translation_norm: Optional[str]
    pos: Optional[str]
    domain: Optional[str]
    notes: Optional[str]
    status: str  # draft|approved|rejected|deprecated
    confidence: Optional[float]
    origin: str  # user_edit|import|mt_accept|mt_auto|merge|revert
    source_ref: Optional[str]
    created_at: str
    updated_at: str
    approved_at: Optional[str]
    approved_by: Optional[str]
```

**TMHistoryDTO** (`app/domain/dto.py`):
```python
@dataclass
class TMHistoryDTO:
    hist_id: int
    tm_id: int
    version: int
    translation: str
    notes: Optional[str]
    status: str
    origin: str
    changed_at: str
    change_kind: str  # edit|approve|reject|deprecate|revert
```

**CoverageMetrics** (`app/domain/dto.py`):
```python
@dataclass
class CoverageMetrics:
    total: int
    covered: int
    uncovered: int
    coverage_pct: float
```

## User Guide

### Scenario 1: Review and Approve Imported Translations

**Goal**: Review translations imported from a dictionary and approve good ones.

**Steps**:
1. Open `Premium → Translation Management`
2. Set filter **Origin** = `import`
3. Set filter **Status** = `draft`
4. Review each translation in the table
5. Select translations to approve (Ctrl+Click or Shift+Click for multiple)
6. Click **✓ Approve Selected**
7. Confirm the bulk action

**Result**: Selected translations are now approved and will be used in lookup.

### Scenario 2: Fix an Incorrect Translation

**Goal**: Correct a translation that was approved but is wrong.

**Steps**:
1. Open `Premium → Translation Management`
2. Search for the source text in the **Search** box
3. Click on the translation cell to edit inline
4. Type the corrected translation and press Enter
5. The translation is updated with origin="user_edit"

**Alternative**: If you want to revert to a previous version:
1. Select the entry
2. Click **📜 View History**
3. Select the version to restore
4. Click **Revert to Selected**

### Scenario 3: Identify High-Priority Untranslated Terms

**Goal**: Find the most important untranslated terms to focus translation efforts.

**Steps**:
1. Open a project
2. Go to `Premium → QA / Coverage`
3. Switch to **Untranslated Term Clusters** tab
4. Set **Order by** = `termhood`
5. Review the top items (highest termhood = most technical/domain-specific)
6. Note the terms and create translations manually or via import

**Result**: You have a prioritized list of technical terms that need translation.

### Scenario 4: Track Translation Progress

**Goal**: Monitor how much of the project is translated over time.

**Steps**:
1. Open a project
2. Go to `Premium → QA / Coverage`
3. Note the **Lemma Coverage** and **Term Cluster Coverage** percentages
4. Optionally check **Include Draft TM in Coverage** to see draft impact
5. Click **🔄 Refresh** periodically to see progress
6. Focus on **Untranslated Lemmas** tab to see what's left

**Result**: You can track coverage metrics and see translation progress.

### Scenario 5: Bulk Reject Low-Quality MT Suggestions

**Goal**: Reject machine translation suggestions that are low quality.

**Steps**:
1. Open `Premium → Translation Management`
2. Set filter **Origin** = `mt_auto`
3. Set filter **Status** = `draft`
4. Review the translations
5. Select low-quality entries (Ctrl+Click for multiple)
6. Click **✕ Reject Selected**

**Result**: Low-quality MT suggestions are marked as rejected and won't be used.

## Database Schema

### tm_entry Table

Core TM entry table with all translation data.

**Key Fields**:
- `tm_id`: Primary key
- `project_id`: NULL for global, otherwise project-specific
- `kind`: Entry type (lemma, term_cluster, ngram, surface)
- `src_text`, `src_norm`: Source text and normalized form
- `translation`, `translation_norm`: Translation and normalized form
- `status`: draft, approved, rejected, deprecated
- `origin`: user_edit, import, mt_accept, mt_auto, merge, revert
- `source_ref`: Reference to origin source (e.g., dict_import, ui_test)
- `approved_at`, `approved_by`: Approval timestamp and approver
- `created_at`, `updated_at`: Timestamps

### tm_entry_history Table

Version history for TM entries.

**Key Fields**:
- `hist_id`: Primary key
- `tm_id`: Foreign key to tm_entry
- `version`: Version number (incremental)
- `translation`: Translation at this version
- `status`: Status at this version
- `origin`: Origin at this version
- `changed_at`: When this version was created
- `change_kind`: Type of change (edit, approve, reject, deprecate, revert)

### Migrations

- **004_m7_translation_memory.sql**: Base TM schema
- **005_m7_add_revert_origin.sql**: Add 'revert' to tm_entry_history.origin CHECK constraint
- **006_p2_add_revert_origin.sql**: Add 'revert' to tm_entry.origin CHECK constraint (P2.3)

## Contracts and Constraints

### Revert Contract (P2.3)

When reverting a TM entry to a previous version:
- **MUST** set `origin = "revert"` (not "user_edit")
- **MUST** create history entry with `change_kind = "revert"`
- **MUST** restore translation, notes, and status from target version

### Status Workflow

```
draft ───┬──→ approved (sets approved_at, approved_by)
         ├──→ rejected (clears approved_at, approved_by)
         └──→ deprecated (clears approved_at, approved_by)
```

### Change Kind Mapping

| Status | Change Kind |
|--------|-------------|
| approved | approve |
| rejected | reject |
| deprecated | deprecate |
| draft | edit |

**Note**: Status values use -ed suffix, change_kind values don't.

### Query Performance

**Coverage Operations**:
- `compute_lemma_coverage`: ≤ 3 SQL queries
- `compute_termcluster_coverage`: ≤ 3 SQL queries
- `list_untranslated_lemmas`: ≤ 5 SQL queries
- `list_untranslated_termclusters`: ≤ 5 SQL queries

Enforced by automated tests with query counters.

## Testing

See [P2_TESTS.md](./P2_TESTS.md) for complete test suite documentation.

**Test Summary**:
- 31 total P2 tests
- 7 service tests (CRUD, status workflow, revert)
- 6 coverage tests (metrics, query count guards)
- 12 model tests (Qt table model, inline editing)
- 6 UI smoke tests (panel instantiation)

**Run All Tests**:
```bash
python test_p2_translation_admin_service.py
python test_p2_coverage_service.py
python test_p2_translation_management_model.py
python test_p2_ui_smoke.py
```

## Troubleshooting

### Coverage Panel Says "Project Required"

**Problem**: Clicked `Premium → QA / Coverage` from dashboard.

**Solution**: Coverage requires project context. Open a project first, then access the panel.

### Search Returns No Results

**Possible causes**:
1. Filters are too restrictive - click **Clear Filters**
2. No TM entries exist yet - import dictionary or create entries manually
3. Database not migrated - ensure schema version ≥ 6

### Inline Editing Not Working

**Problem**: Can't edit translation in table.

**Solution**: Only the **Translation** column is editable. Other columns (ID, Kind, Source, etc.) are read-only.

### Query Performance Issues

**Problem**: Coverage calculation is slow.

**Solution**: Verify query count ceiling tests pass. If queries exceed ceilings, there may be an N+1 query regression. Check test_p2_coverage_service.py.

## Future Enhancements

Potential future additions:
1. **Conflict Resolution**: UI for resolving duplicate TM entries
2. **Batch Import**: Import TM entries from TMX/CSV files
3. **Export**: Export TM entries to TMX format
4. **Advanced Filters**: Filter by confidence range, date range, approver
5. **Audit Log**: Full audit trail of all TM changes
6. **Diff View**: Visual diff between versions in history dialog
7. **Comments**: Allow comments on TM entries for collaboration
8. **Pagination**: Server-side pagination for large result sets
9. **Sorting**: Click column headers to sort
10. **Search Highlighting**: Highlight search terms in results

## Version History

- **P2.0** (M7): Initial TM schema with tm_entry and tm_entry_history tables
- **P2.1**: TranslationAdminService with search, CRUD, history, revert
- **P2.2**: CoverageService with metrics and untranslated lists
- **P2.3**: Revert contract (origin="revert"), coverage tests with query counter, model tests
- **P2.4**: Translation Management Panel and QA/Coverage Panel UI
