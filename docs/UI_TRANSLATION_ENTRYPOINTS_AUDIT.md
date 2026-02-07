# UI Translation Entrypoints Audit

**Date:** 2026-02-08
**Scope:** PATCH-UI-T00 - Audit current UI integration for MT translation features
**Status:** ❌ **NO USER-INITIATED TRANSLATION ENTRYPOINT FOUND**

---

## Executive Summary

**Finding:** Translation infrastructure exists (TranslationService, providers, cache) but **NO explicit UI entrypoint** for user-initiated translation.

**Current State:**
- ✅ Translation occurs AUTOMATICALLY (background worker when loading terms)
- ❌ User CANNOT manually translate arbitrary text via UI
- ❌ User CANNOT access Provider Settings from menu
- ❌ No "Translate..." button/menu/dialog visible to user

**Recommendation:** Implement PATCH-UI-T01 (add minimal UI entrypoints)

---

## Detailed Findings

### 1. AUTOMATIC Translation (Existing)

**Location:** `app/ui/terms_view.py`

**How it works:**
1. User opens **Premium → Translation Management** or **Terms** view
2. On `load_terms()`, system automatically calls `start_translation_worker()`
3. `TranslationResolveWorker` runs in background, bulk-translates all term clusters
4. Results populate Translation column in table
5. User can edit translations inline (saves to TM)

**Code Flow:**
```python
# app/ui/terms_view.py:259
def load_terms():
    clusters = self.term_service.list_term_clusters(...)
    self.terms_model.update_clusters(clusters)
    self.start_translation_worker(clusters)  # AUTOMATIC

# app/ui/terms_view.py:355
def start_translation_worker(clusters):
    items = [(cluster.representative_he, "term_cluster") for cluster in clusters]
    self.translation_worker = TranslationResolveWorker(
        items=items,
        project_id=self.project_id,
        src_lang="he",
        tgt_lang="ru",
        allow_draft=False,
    )
    self.translation_worker.start()
```

**TranslationService Usage:**
- `app/ui/workers.py:394` - `translation_service.bulk_resolve()`
- Backend: uses TranslationService → provider chain → Local MT / Cloud MT
- Logging: trace_id, provider_id, cache_hit, latency_ms (in logs, not UI)

**Verdict:**
- ✅ Works for term clusters (automatic batch translation)
- ❌ User cannot translate arbitrary text
- ❌ User cannot see which provider was used (no UI visibility)
- ❌ User cannot test Local MT without opening Terms view

---

### 2. Provider Settings Dialog (Exists but Hidden)

**Location:** `app/ui/provider_settings_dialog.py`

**Status:** ✅ IMPLEMENTED, ❌ NOT ACCESSIBLE FROM UI

**Dialog Features:**
- Configure rate limits per provider
- Enable/disable providers (deepl, microsoft, libretranslate, local_nllb, local_seamless)
- Configure provider chain priority

**Function exists:**
```python
# app/ui/provider_settings_dialog.py:308
def show_provider_settings(parent=None):
    """Show provider settings dialog."""
    dialog = ProviderSettingsDialog(parent)
    return dialog.exec()
```

**Problem:** No menu item calls this function!

**Search results:**
```bash
$ grep -r "show_provider_settings" app/ui/
app/ui/provider_settings_dialog.py:def show_provider_settings(parent=None):

# NOT FOUND in app_window.py, menus, or any UI code
```

**Verdict:**
- ✅ Dialog exists and functional
- ❌ No menu item: Tools → MT Provider Settings
- ❌ User must know Python to call `show_provider_settings()`

---

### 3. Main Window Menus (No MT Entrypoints)

**Location:** `app/ui/app_window.py`

**Current Menus:**
```python
# Tools menu
- Verification (P1 Scenario 7)      [Ctrl+Shift+V]
- Import Dictionary...               [Ctrl+Shift+I]

# Premium menu
- Translation Management             [Ctrl+Shift+T]  # TM entries, NOT translation!
- QA / Coverage                      [Ctrl+Shift+C]

# View menu
- Toggle Sidebar                     [Ctrl+B]
- Reset Layout to Default            [Ctrl+Shift+R]
```

**MISSING:**
- ❌ Tools → Translation → "Translate Text..."
- ❌ Tools → Translation → "MT Provider Settings..."
- ❌ No "Translate" action in any context menu

**Verdict:**
- Translation infrastructure ready
- Zero UI discoverability

---

### 4. Context Menus (No Translation Action)

**Checked:**
- `app/ui/terms_view.py:486` - Context menu has "Why this translation?" but NO "Translate" action
- `app/ui/concordance_view.py` - No context menu for translation (checked: no relevant code)
- `app/ui/dictionary_view.py` - No context menu for translation

**Verdict:**
- User cannot right-click → Translate
- User cannot select text → Translate

---

### 5. Search Results: "translate" in UI code

```bash
$ grep -ri "translate" app/ui/*.py | grep -E "(def|class|QAction)"

app/ui/terms_view.py:14:from app.services.translation_service import TranslationService
app/ui/terms_view.py:18:from app.ui/workers import TranslationResolveWorker
app/ui/terms_view.py:32:        self.translation_service = TranslationService()
app/ui/terms_view.py:355:    def start_translation_worker(self, clusters: list):
app/ui/terms_view.py:500:        why_action = QAction("Why this translation?", self)

app/ui/dictionary_view.py:23:from app.services.translation_service import TranslationService
app/ui/dictionary_view.py:40:        self.translation_service = TranslationService()

app/ui/workers.py:360:class TranslationResolveWorker(QThread):

app/ui/translation_management_panel.py:  # This is TM entry management, NOT translation
```

**Verdict:**
- TranslationService imported but only used for AUTOMATIC translation
- No user-facing QAction for manual translation

---

### 6. Smoke-Check Discrepancy

**Documentation vs Reality:**

| Smoke-Check Instruction | Reality |
|-------------------------|---------|
| "Settings → MT Providers" | ❌ Menu item doesn't exist |
| "Local NLLB visible in list" | ⚠️ Can only see if you call `show_provider_settings()` manually |
| "Translate through UI" | ❌ No button/menu/action |
| "Concordance → right-click → Translate" | ❌ Not implemented |

**Conclusion:** Smoke-check describes **intended** UX, not current implementation.

---

## Root Cause Analysis

**Why is UI missing?**

1. **TranslationService implementation focused on backend:**
   - P1-T01 through P1-T05: Provider chain, cache, circuit breaker, glossary builder
   - task_4_MT_local (PATCH-00 to PATCH-10): Local MT integration
   - **BUT:** No UI integration patch

2. **Automatic translation workflow exists:**
   - Terms view auto-translates term clusters (background worker)
   - This works for bulk translation scenarios
   - **BUT:** Not discoverable, not user-controlled

3. **Provider Settings dialog exists but orphaned:**
   - Created in P1 work but never wired to menu
   - Function `show_provider_settings()` ready but not called

---

## Integration Points Identified

**Where to add UI entrypoints (minimal changes):**

### Option A: Main Menu (RECOMMENDED)

**Location:** `app/ui/app_window.py:77-124` (create_menu_bar)

**Proposal:**
```python
# Add new menu: Tools → Translation
translation_menu = tools_menu.addMenu("&Translation")

# Action 1: Translate Text
translate_action = QAction("&Translate Text...", self)
translate_action.setShortcut("Ctrl+Alt+T")
translate_action.triggered.connect(self.open_translate_dialog)
translation_menu.addAction(translate_action)

# Action 2: Provider Settings
provider_settings_action = QAction("&MT Provider Settings...", self)
provider_settings_action.setShortcut("Ctrl+Alt+P")
provider_settings_action.triggered.connect(self.open_provider_settings)
translation_menu.addAction(provider_settings_action)
```

**Impact:**
- Minimal: 15-20 lines in app_window.py
- Zero refactoring of existing code
- Keyboard-first (shortcuts defined)
- Discoverable (menu hierarchy matches docs)

---

### Option B: Context Menu in Terms View (SUPPLEMENTARY)

**Location:** `app/ui/terms_view.py:486` (on_context_menu)

**Proposal:**
```python
# Add to existing context menu
menu = QMenu(self)

# NEW: Translate action
translate_action = QAction("Translate", self)
translate_action.triggered.connect(lambda: self.translate_term(source_row))
menu.addAction(translate_action)

# Existing: "Why?" action
why_action = QAction("Why this translation?", self)
...
```

**Impact:**
- Supplementary (Option A is primary)
- Allows re-translation of single term (refresh translation)
- Shows which provider was used (in result metadata)

---

## Files That Need Changes (PATCH-UI-T01)

### Minimal Implementation (Option A Only):

1. **app/ui/app_window.py** - Add menu items
   - `create_menu_bar()`: Add Tools → Translation submenu
   - `open_translate_dialog()`: NEW method
   - `open_provider_settings()`: NEW method (calls existing function)

2. **app/ui/translate_text_dialog.py** - NEW file
   - TranslateTextDialog(QDialog)
   - Input: source lang, target lang, text (multi-line)
   - Output: translated text (read-only)
   - Metadata: provider_id, cache_hit, used_glossary, latency_ms
   - Button: Translate (runs in background worker)
   - Button: Copy to clipboard

3. **app/ui/workers.py** - MINOR ADDITION (if needed)
   - May need SingleTextTranslateWorker (similar to TranslationResolveWorker but for single text)
   - OR: reuse existing worker with items=[(text, "adhoc")]

4. **docs/PROVIDER_SETUP_GUIDE.md** - UPDATE
   - Add "Using Translation UI" section
   - Step-by-step: Open menu → Translate Text → Enter text → See result
   - Screenshot or description of dialog

---

## Tests Required (PATCH-UI-T01)

### Unit Tests:

1. **test_translate_text_dialog.py**
   - Dialog creation (QT_QPA_PLATFORM=offscreen)
   - Button exists and enabled
   - Input validation (empty text → disabled button)

2. **test_app_window_menus.py**
   - Menu item "Tools → Translation → Translate Text..." exists
   - Menu item "Tools → Translation → MT Provider Settings..." exists
   - Shortcuts registered (Ctrl+Alt+T, Ctrl+Alt+P)

### Manual Tests (DoD Evidence):

1. Smoke-check: Translate "hello" en→he via UI
2. Verify provider_id shown (local_nllb or cloud)
3. Verify cache_hit on second translation
4. Verify glossary applied (if approved term exists)
5. Verify error handling (providers disabled → clear message)

---

## Recommendations

### Immediate Action: PATCH-UI-T01

**Implement Option A (Main Menu):**
- Add Tools → Translation submenu
- Add "Translate Text..." dialog
- Wire Provider Settings to menu
- Document usage
- Create DoD evidence

**Estimated Effort:** 2-3 hours

**Files:** 3 new/modified
- app/ui/app_window.py (minor changes)
- app/ui/translate_text_dialog.py (NEW, ~200 lines)
- docs/PROVIDER_SETUP_GUIDE.md (add section)

**Benefits:**
- User can test Local MT immediately
- User can access Provider Settings
- Smoke-check becomes accurate
- Zero regression risk (no changes to automatic translation)

---

### Future Enhancements (Optional):

**Option B:** Add context menu "Translate" in Terms view
- Allows re-translation of specific term
- Shows provider metadata in dialog

**Option C:** Add "Translate selection" for text editors
- If concordance view has text selection
- Right-click → Translate selection

---

## Blind Spots Identified

**What we DON'T know without UI:**

1. **Does Local MT actually work end-to-end?**
   - Model installed ✅ (verified via scripts)
   - Provider registered ✅ (code exists)
   - Provider chain configured ❓ (no UI to check)
   - Translation succeeds ❓ (can't test via UI)

2. **Which provider is actually used?**
   - Logs show provider_id ✅
   - UI shows provider_id ❌ (no field in Terms view)
   - User doesn't know if translation is local or cloud

3. **Is cache working?**
   - Cache entries in database ✅ (can check via SQL)
   - Cache hit logged ✅ (in console logs)
   - User sees cache hit indicator ❌ (no UI field)

4. **Is glossary applied?**
   - Glossary postprocess runs ✅ (code exists)
   - applied_terms_count logged ✅ (in console)
   - User sees glossary indicator ❌ (no UI field)

**Mitigation:** PATCH-UI-T01 exposes all metadata in dialog.

---

## Conclusion

**Status:** UI integration **INCOMPLETE**

**Required Action:** Implement PATCH-UI-T01 (minimal UI entrypoints)

**Blocked Without UI:**
- User cannot test Local MT
- User cannot configure providers
- Smoke-check instructions invalid
- Release not user-ready

**Next Steps:**
1. ✅ PATCH-UI-T00: Audit complete (this document)
2. 🔜 PATCH-UI-T01: Add minimal UI (menu + dialog)
3. 🔜 PATCH-UI-T02: DoD evidence + hardening

---

**Audit Completed:** 2026-02-08
**Auditor:** Claude Sonnet 4.5
