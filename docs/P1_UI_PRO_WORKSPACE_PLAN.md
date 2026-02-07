# P1 UI Pro Workspace - Implementation Plan

**Date:** 2026-02-07
**Status:** PRE-FLIGHT COMPLETE → Planning Phase
**Complexity:** Large (3-4 weeks estimated)
**Priority:** P1 (per ROADMAP_PREMIUM_PRO.md)

---

## 0. PRE-FLIGHT RECONNAISSANCE (COMPLETED ✅)

### 0.1 Documentation Review

#### Found Documents:
- ✅ **ROADMAP_PREMIUM_PRO.md** - Epic 2: UI Pro Workspace (lines 117-159)
  - Components: workspace_manager.py (NEW), command_palette.py (NEW), models_qt.py (ENHANCE), app_window.py (ENHANCE), settings.py (NEW)
  - Acceptance: layout saves/loads, command palette <50ms, keyboard shortcuts, bulk selection 1000+

- ✅ **IMPLEMENTED_STAGES_AUDIT.md** - Full system audit
  - M1-M7 + P1-P3 complete
  - 17 Services, 13 UI Components, 46+ test files
  - **No SettingsService exists** - need to create
  - **No keyboard shortcuts framework** - need to create

- ❌ **KEYBOARD_SHORTCUTS.md** - Does NOT exist yet (will be created in PATCH-P1-05)
- ❌ **ARCH.md** - Does NOT exist (architecture implicit in code)

#### UI/UX Constraints (from ROADMAP section 3):
- ❌ NO fixed heights/widths for content areas
- ✅ Flexible layouts (QVBoxLayout, QHBoxLayout, QSplitter)
- ✅ Scroll areas for long content
- ✅ Keyboard accessible (Tab, Shift+Tab, Enter, Space)
- ✅ All long operations (>100ms) in worker threads
- ✅ Progress indicators for ops >1 second
- ✅ Cancellation support for ops >5 seconds

### 0.2 Repo Reconnaissance

#### MainWindow Architecture (`app/ui/app_window.py`):
```python
class AppWindow(QMainWindow):
    - Central widget: QStackedWidget (self.stack)
    - Navigation: stack.addWidget() → stack.setCurrentWidget()
    - Menu: Tools (Verification, Import), Premium (TM, Coverage)
    - Existing shortcuts:
      - Ctrl+Shift+V: Verification
      - Ctrl+Shift+I: Import Dictionary
      - Ctrl+Shift+T: Translation Management
      - Ctrl+Shift+C: QA/Coverage
```

**Current Flow:**
1. Dashboard (ProjectDashboard)
2. User selects project → open_project(project_id)
3. ProjectView added to stack
4. Back button → back_to_dashboard() → removes widget from stack

**FINDING:** No workspace manager or splitters yet. All views are full-screen stacks.

#### Existing Panels/Views (13 components):
- `app_window.py` - Main window ✅
- `project_dashboard.py` - Project list ✅
- `project_view.py` - Project container ✅
- `documents_view.py` - Document management ✅
- `dictionary_view.py` - Lemma table (LemmaTableModel) ✅
- `terms_view.py` - Term clusters (TermClusterTableModel) ✅
- `concordance_view.py` - KWIC search ✅
- `translation_management_panel.py` - TM admin (P2) ✅
- `coverage_panel.py` - QA metrics (P2) ✅
- `verification_panel.py` - P1 verification ✅
- `import_wizard.py` - Dictionary import (P3) ✅
- `term_card_view.py` - Term curation (M8 placeholder) 🔶
- `export_view.py` - Export center (M9 placeholder) 🔶

#### Table Models (`app/ui/models_qt.py`):
```python
ProjectListModel        - 6 columns (ID, Name, Docs, Processed, Lemmas, N-grams)
LemmaTableModel         - 7 columns (Lemma, POS, Freq, DocFreq, Translation, Source, Status)
                        - Translation column ALREADY editable (flags() + setData())
TermClusterTableModel   - 14 columns (Term, Lemma, Freq, DocFreq, Members, PMI, LLR, Dice, Weirdness, Keyness, Termhood, Translation, Source, Status)
TranslationManagementTableModel - 9 columns (ID, Kind, Source, Translation, Status, Scope, Origin, SourceRef, Updated)
TermCardTableModel      - 8 columns (ID, Term, Status, Freq, Aliases, Notes, Created, Updated)
```

**FINDING:** Models are basic QAbstractTableModel. No multi-sort, no column reorder persistence, no header state management.

#### Settings/Persistence:
```bash
# Search results:
grep -r "QSettings" app/  → NO RESULTS
grep -r "SettingsService" app/  → NO RESULTS
glob "**/settings*.py" → NO MATCHES in app/
```

**FINDING:** ❌ **NO settings persistence mechanism exists.**
**DECISION REQUIRED:** Create `app/infra/settings.py` with QSettings backend.

#### Action/Command System:
```bash
grep -r "QAction|QShortcut" app/ui/  → NO MATCHES (except app_window.py menu)
```

**FINDING:** ❌ **NO centralized action registry.**
**DECISION REQUIRED:** Create ActionsRegistry in `app/ui/command_palette.py`.

### 0.3 Preconditions Gate

#### Environment Check:
- ✅ PyQt6 installed (confirmed via imports in app_window.py)
- ✅ UI launches (app_window.py functional)
- ✅ Tests passing (per IMPLEMENTED_STAGES_AUDIT: 46+ test files, >95% pass rate)

#### Storage Decision:
**CHOSEN:** QSettings (platform-native)
- **Path:** `~/.config/HDLE_Premium/settings.ini` (Linux/macOS) or Registry (Windows)
- **Format:** INI-style key-value
- **Binary data:** QByteArray → base64 for splitter/header states
- **Versioning:** `layout_schema_version` key (start at 1)

**Rationale:**
- No existing settings infrastructure → start simple
- QSettings is cross-platform, built-in, atomic writes
- Easy migration path to JSON files if needed later

#### Fallback Strategy:
- If layout load fails → log error, return default layout
- If layout version mismatch → log warning, use default
- If splitter state corrupt → ignore, use default sizes
- **NO CRASHES** - always fall back gracefully

### 0.4 Blind Spots Checklist

#### 1. Actions Registry
**Q:** Where and how to register actions?
**A:** Create `ActionsRegistry` singleton in `command_palette.py`. Each view/panel registers actions on init.

**Structure:**
```python
@dataclass
class ActionSpec:
    action_id: str          # e.g., "import.dictionary"
    title: str              # e.g., "Import Dictionary"
    keywords: List[str]     # e.g., ["import", "dict", "csv", "xlsx"]
    shortcut: str           # e.g., "Ctrl+Shift+I"
    callback: Callable      # e.g., app_window.open_import_wizard
    enabled_predicate: Callable[[], bool] | None  # e.g., lambda: project_id is not None
```

#### 2. Default Panels in Workspace
**Q:** Which panels should be in default workspace layout?
**A:** Based on current app_window.py flow:

**Default Layout (3-panel horizontal split):**
```
+------------------+----------------------+------------------+
| Navigation       | Main Content         | Details/Tools    |
| (Dashboard/List) | (Active View)        | (Context Panel)  |
| 20% width        | 50% width            | 30% width        |
+------------------+----------------------+------------------+
```

**Minimal panels for MVP:**
- Left: ProjectDashboard (always visible)
- Center: Active view (Documents, Dictionary, Terms, Concordance)
- Right: Context panel (Coverage, TM search, Term details) - optional

**ALTERNATIVE (simpler for MVP):**
Just make current QStackedWidget structure splitter-aware:
- Root: QSplitter(Horizontal)
  - Left: Navigation sidebar (optional toggle)
  - Right: QStackedWidget (current behavior)

**DECISION:** Start simple - add optional sidebar to existing stack. Full multi-panel can be Phase 2.

#### 3. Panel Identification (panel_id)
**Q:** How to identify panels stably for layout persistence?
**A:** Use class name + context ID (if applicable).

**Examples:**
```python
"ProjectDashboard"
"ProjectView-1"          # project_id=1
"DictionaryView-1"       # project_id=1
"CoveragePanel-1"        # project_id=1
"TranslationManagementPanel-global"  # project_id=None
```

**Storage:**
```json
{
  "layout_schema_version": 1,
  "splitter_state": "base64_encoded_bytes",
  "panel_visibility": {
    "ProjectDashboard": true,
    "sidebar": false
  },
  "window_geometry": [x, y, width, height]
}
```

#### 4. Layout Schema Migration Policy
**Q:** What happens when layout schema version changes?
**A:**
- Current version: Read from QSettings `"layout_schema_version"`
- Expected version: Hardcoded in code (e.g., `LAYOUT_SCHEMA_VERSION = 1`)
- If `current < expected`: Attempt migration function
- If `current > expected` or migration fails: **Fallback to default** + log audit note
- Migration functions: `migrate_layout_v1_to_v2(layout_data) -> new_data`

#### 5. Crash Safety
**Q:** How to ensure layout corruption doesn't break app startup?
**A:**
```python
def load_layout_or_default():
    try:
        data = QSettings().value("workspace/layout")
        if not data:
            return build_default_layout()

        # Validate schema version
        version = data.get("layout_schema_version", 0)
        if version != LAYOUT_SCHEMA_VERSION:
            logger.warning(f"Layout schema mismatch: {version} != {LAYOUT_SCHEMA_VERSION}")
            return build_default_layout()

        # Attempt restore
        restore_layout(data)
        return data

    except Exception as e:
        logger.error(f"Failed to load layout: {e}", exc_info=True)
        return build_default_layout()
```

**Principle:** Any exception → default layout. User can always reset via menu action.

---

## 1. DESIGN DECISIONS (LOCKED)

### 1.1 Workspace Layout Persistence

**Storage:** QSettings (`~/.config/HDLE_Premium/settings.ini`)

**Format:**
```python
{
    "layout_schema_version": 1,
    "splitter_state": base64(QByteArray),  # Main splitter
    "sidebar_visible": bool,
    "sidebar_width": int,
    "window_geometry": [x, y, w, h],
    "window_state": base64(QByteArray)  # Maximized/fullscreen
}
```

**Versioning:**
- Schema v1: Basic splitter + sidebar
- Migration policy: Unknown version → default layout + audit log

**Crash Safety:**
- Try/except wrapper around load
- Validation checks before restore
- Fallback to `build_default_layout()` on any error

**Autosave:**
- On `closeEvent()` of main window
- Debounced on splitter resize (500ms timer)

### 1.2 Workspace Architecture

**Minimal Viable Workspace (MVP):**
```python
class WorkspaceManager(QWidget):
    - Root: QSplitter(Qt.Orientation.Horizontal)
      - Left: Sidebar (optional, toggle via Ctrl+B)
        - Quick actions panel
        - Recent projects
        - Bookmarks (future)
      - Right: QStackedWidget (existing AppWindow.stack)

    - Methods:
      - build_default_layout()
      - save_current_layout()
      - load_layout_or_default()
      - toggle_sidebar()
```

**Panel Registry (for future multi-panel):**
```python
@dataclass
class PanelSpec:
    panel_id: str
    title: str
    factory: Callable[[], QWidget]
    default_region: str  # "left", "center", "right"
    closeable: bool = True
```

**DECISION:** Start with simple sidebar toggle. Full multi-panel registry is Phase 2 (after MVP).

### 1.3 Command Palette

**Implementation:**
```python
class CommandPaletteDialog(QDialog):
    - Layout: QVBoxLayout
      - QLineEdit (search input)
      - QListView (results)
      - QLabel (status: "X actions found")

    - Model: QStandardItemModel (action list)
    - Fuzzy search: rapidfuzz.fuzz.partial_ratio()
    - Shortcuts:
      - Ctrl+P: Open palette
      - Esc: Close palette
      - Enter: Execute selected action
      - ↑/↓: Navigate results
      - Tab: (future) Autocomplete
```

**ActionsRegistry:**
```python
class ActionsRegistry:
    _instance = None
    _actions: Dict[str, ActionSpec] = {}

    @classmethod
    def get_instance() -> ActionsRegistry:
        if not cls._instance:
            cls._instance = ActionsRegistry()
        return cls._instance

    def register(self, spec: ActionSpec):
        self._actions[spec.action_id] = spec

    def get_all(self) -> List[ActionSpec]:
        return list(self._actions.values())

    def search(self, query: str) -> List[ActionSpec]:
        # Fuzzy match on title + keywords
        pass
```

**Performance:**
- **Target:** <50ms on 1000 actions
- **Strategy:**
  1. Check if `rapidfuzz` available (it's in requirements?)
  2. If not: Implement lightweight scorer (lowercase contains + prefix boost)
  3. Cache lowercased title/keywords
  4. Use list comprehension (fast in Python)

**Perf Test:**
```python
def test_palette_search_performance():
    registry = ActionsRegistry()

    # Generate 1000 fake actions
    for i in range(1000):
        registry.register(ActionSpec(
            action_id=f"action_{i}",
            title=f"Action {i}",
            keywords=[f"keyword{i}", f"tag{i}"],
            shortcut="",
            callback=lambda: None
        ))

    # Measure search time (p95 over 50 runs)
    times = []
    for _ in range(50):
        start = time.perf_counter()
        results = registry.search("import")
        times.append(time.perf_counter() - start)

    p95 = sorted(times)[int(0.95 * len(times))]
    assert p95 < 0.050, f"Search too slow: {p95:.3f}s (expected <0.050s)"
```

### 1.4 Pro Tables

**Multi-Sort:**
```python
class MultiSortProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._sort_keys = []  # [(column, order), ...]

    def add_sort_key(self, column: int, order: Qt.SortOrder):
        # If column already in keys, update order
        # Otherwise append to keys
        pass

    def reset_sort_keys(self, column: int, order: Qt.SortOrder):
        self._sort_keys = [(column, order)]

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        # Compare by first sort key, then second, etc.
        for col, order in self._sort_keys:
            left_data = self.sourceModel().data(left.sibling(left.row(), col))
            right_data = self.sourceModel().data(right.sibling(right.row(), col))

            if left_data != right_data:
                result = left_data < right_data
                return result if order == Qt.SortOrder.AscendingOrder else not result

        return False  # Equal on all keys
```

**Header Interaction:**
```python
# In table view setup:
header = table.horizontalHeader()
header.sectionClicked.connect(self.on_header_clicked)

def on_header_clicked(self, logical_index):
    modifiers = QApplication.keyboardModifiers()

    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        # Add to sort keys
        proxy_model.add_sort_key(logical_index, current_order)
    else:
        # Reset to single sort key
        proxy_model.reset_sort_keys(logical_index, current_order)
```

**Column Reorder + Persistence:**
```python
header.setSectionsMovable(True)
header.sectionMoved.connect(self.on_column_moved)

def save_table_state(table_id: str):
    header = table.horizontalHeader()
    state = header.saveState()  # QByteArray

    settings = QSettings()
    settings.setValue(f"table/{table_id}/header_state", state)

def load_table_state(table_id: str):
    settings = QSettings()
    state = settings.value(f"table/{table_id}/header_state")

    if state:
        header.restoreState(state)
```

**Bulk Selection:**
```python
table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

# Shortcuts (add to ActionsRegistry):
"Ctrl+A": Select All
"Ctrl+Shift+A": Clear Selection
# Shift+Click: Range selection (built-in)
```

**Performance:**
- No heavy computation in `data()` without cache
- Use `QSortFilterProxyModel` (native C++, fast)
- Test with 1000+ rows (load test data fixture)

---

## 2. PATCH IMPLEMENTATION SEQUENCE

### PATCH-P1-00: Docs + Recon Report ✅ (CURRENT)
**Files:**
- `docs/P1_UI_PRO_WORKSPACE_PLAN.md` (THIS FILE)

**Commit:** `docs(P1): add UI Pro Workspace plan and repo recon notes`

### PATCH-P1-01: SettingsService + Basic Persistence
**New Files:**
- `app/infra/settings.py` (SettingsService class)

**Changes:**
- `app/ui/app_window.py`: Save/restore window geometry on close/open

**Tests:**
- `tests/test_p1_settings_service.py`: Roundtrip, fallback, schema version

**Commit:** `feat(P1): add SettingsService with QSettings backend`

### PATCH-P1-02: WorkspaceManager Skeleton + Sidebar
**New Files:**
- `app/ui/workspace_manager.py` (WorkspaceManager, PanelSpec, PanelRegistry)

**Changes:**
- `app/ui/app_window.py`:
  - Replace `self.stack = QStackedWidget()` with `self.workspace = WorkspaceManager()`
  - `self.setCentralWidget(self.workspace)`
  - Add menu: View → Toggle Sidebar (Ctrl+B)
  - Add menu: View → Reset Layout (Ctrl+Shift+R)

**Tests:**
- `tests/test_p1_workspace_manager.py`: build_default_layout, toggle_sidebar

**Commit:** `feat(P1): add WorkspaceManager with optional sidebar`

### PATCH-P1-03: Layout Persistence v1
**Changes:**
- `app/ui/workspace_manager.py`:
  - `save_current_layout()` → QSettings
  - `load_layout_or_default()` ← QSettings
  - Autosave on closeEvent (debounced)

- `app/ui/app_window.py`:
  - Call `workspace.load_layout_or_default()` on startup
  - Call `workspace.save_current_layout()` on closeEvent

**Tests:**
- `tests/test_p1_layout_persistence.py`: save/load roundtrip, fallback on error, version mismatch

**Commit:** `feat(P1): persist workspace layouts (save/load, autosave, versioned)`

### PATCH-P1-04: Command Palette + ActionsRegistry
**New Files:**
- `app/ui/command_palette.py` (ActionSpec, ActionsRegistry, CommandPaletteDialog)

**Changes:**
- `app/ui/app_window.py`:
  - Create global shortcut Ctrl+P → open command palette
  - Register actions:
    - "import.dictionary": Import Dictionary (Ctrl+Shift+I)
    - "verification.p1": Run P1 Verification (Ctrl+Shift+V)
    - "premium.tm": Translation Management (Ctrl+Shift+T)
    - "premium.coverage": QA/Coverage (Ctrl+Shift+C)
    - "view.reset_layout": Reset Layout (Ctrl+Shift+R)
    - "view.toggle_sidebar": Toggle Sidebar (Ctrl+B)

**Fuzzy Search:**
- Check if `rapidfuzz` in requirements
- If yes: Use `rapidfuzz.fuzz.partial_ratio()`
- If no: Implement `simple_scorer(query, candidate)` (lowercase contains + prefix boost)

**Tests:**
- `tests/test_p1_command_palette.py`:
  - Registry: register, get_all, search
  - Dialog: open, search, execute, close
  - Perf: 1000 actions, search <50ms (p95)

**Commit:** `feat(P1): add command palette (Ctrl+P) with fuzzy action search`

### PATCH-P1-05: Pro Tables (multi-sort + reorder + bulk selection)
**New Files:**
- `app/ui/multi_sort_proxy_model.py` (MultiSortProxyModel)

**Changes:**
- `app/ui/dictionary_view.py`:
  - Replace `QSortFilterProxyModel` with `MultiSortProxyModel`
  - Connect header clicks → multi-sort logic
  - Enable `header.setSectionsMovable(True)`
  - Save/restore header state via SettingsService
  - Add context menu: "Select All" (Ctrl+A), "Clear Selection"

- `app/ui/terms_view.py`: Same enhancements

**Tests:**
- `tests/test_p1_multi_sort_proxy_model.py`: multi-key sort order
- `tests/test_p1_table_performance.py`: 1000+ rows scroll/sort without freeze

**Commit:** `feat(P1): pro tables (multi-sort, column reorder, bulk selection)`

### PATCH-P1-06: Docs (Shortcuts + DoD Evidence)
**New Files:**
- `docs/KEYBOARD_SHORTCUTS.md` (all shortcuts documented)
- `docs/UI_DOD_EVIDENCE_P1_WORKSPACE.md` (test scenarios + performance evidence)

**Changes:**
- Update ROADMAP_PREMIUM_PRO.md: Mark Epic 2 as ✅ DONE

**Commit:** `docs(P1): add keyboard shortcuts and UI DoD evidence`

### PATCH-P1-07: Hardening + Polish
**Changes:**
- `app/ui/workspace_manager.py`: Edge cases (layout migration fallback)
- `app/ui/command_palette.py`: Empty results handling, disabled actions, focus return
- `app/ui/app_window.py`: User-friendly status messages

**Tests:**
- Edge case tests: empty palette, disabled action, corrupt layout

**Commit:** `chore(P1): harden workspace/palette UX and edge cases`

---

## 3. INITIAL PANEL REGISTRY (for reference)

**Panels to support in workspace:**
```python
PANEL_REGISTRY = [
    PanelSpec(
        panel_id="ProjectDashboard",
        title="Projects",
        factory=lambda: ProjectDashboard(),
        default_region="left",
        closeable=False  # Always visible
    ),
    PanelSpec(
        panel_id="DocumentsView",
        title="Documents",
        factory=lambda project_id: DocumentsView(project_id),
        default_region="center",
        closeable=False
    ),
    PanelSpec(
        panel_id="DictionaryView",
        title="Dictionary",
        factory=lambda project_id: DictionaryView(project_id),
        default_region="center",
        closeable=False
    ),
    PanelSpec(
        panel_id="TermsView",
        title="Terms",
        factory=lambda project_id: TermsView(project_id),
        default_region="center",
        closeable=False
    ),
    PanelSpec(
        panel_id="CoveragePanel",
        title="QA/Coverage",
        factory=lambda project_id: CoveragePanel(project_id),
        default_region="right",
        closeable=True
    ),
    # ... more panels
]
```

**Note:** Full panel registry is Phase 2. MVP just needs sidebar toggle.

---

## 4. DEPENDENCIES CHECK

### Required Python Packages:
```bash
# Check if rapidfuzz is in requirements
cat requirements.txt | grep rapidfuzz
```

**If NOT present:**
- Option A: Add `rapidfuzz>=2.0.0` to requirements.txt
- Option B: Implement fallback scorer (no new dependency)

**DECISION:** Check first, prefer rapidfuzz if available, else implement fallback.

### PyQt6 Widgets Used:
- QSplitter ✅ (built-in)
- QSettings ✅ (built-in)
- QDialog ✅ (built-in)
- QLineEdit ✅ (built-in)
- QListView ✅ (built-in)
- QStandardItemModel ✅ (built-in)
- QSortFilterProxyModel ✅ (built-in)

**All widgets are standard PyQt6. No additional dependencies.**

---

## 5. RISK ASSESSMENT

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| QSettings platform differences | Medium | Low | Test on Windows/Linux, use portable keys |
| Splitter state corruption | Low | Medium | Always fallback to default on error |
| Command palette search too slow | Medium | High | Perf test with 1000 actions, optimize if needed |
| Multi-sort breaks existing tables | Low | Medium | Use proxy model, don't modify base models |
| Layout migration breaks app | Low | High | Strict try/except + fallback to default |

**Overall Risk:** Low-Medium (well-contained, good fallback strategies)

---

## 6. NEXT STEPS

1. ✅ **PRE-FLIGHT COMPLETE** (this document)
2. 🔲 **Review with user** - Get approval on design decisions
3. 🔲 **Check rapidfuzz dependency** - Confirm availability
4. 🔲 **Create task list** - Break patches into tasks
5. 🔲 **Start PATCH-P1-01** - SettingsService implementation

---

**PRE-FLIGHT STATUS:** ✅ **COMPLETE**
**BLOCKERS:** None identified
**READY TO PROCEED:** Yes (pending user approval of design decisions)
