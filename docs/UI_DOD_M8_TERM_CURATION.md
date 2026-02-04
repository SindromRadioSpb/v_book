# UI Definition of Done: M8 Term Curation

**Date:** 2026-02-04
**Milestone:** M8 - Term Curation
**Component:** TermCardView

---

## Overview

TermCardView provides a term-by-term review workflow for curating automatically extracted terms. The interface displays one term at a time with full metadata, allows multiple curation actions, and provides a filterable review queue for navigation.

---

## Functional Requirements

### FR-1: Card Display
**Status:** ✅ IMPLEMENTED

The view displays the currently selected term with all relevant information:

- **Term Metadata:**
  - Representative Hebrew form
  - Lemma (canonical form)
  - Frequency (absolute + document frequency)
  - Curation status (auto/needs_review/approved/rejected)

- **Curation Data:**
  - Pinned translation (user override)
  - Aliases (variant forms)
  - Stopword status (Yes/No)
  - Curation notes
  - Curated by / timestamp
  - Pinned example sentence

**Implementation:** `term_card_view.py:284-322` (update_card_display)

### FR-2: Status Workflow
**Status:** ✅ IMPLEMENTED

Users can set the curation status for the current term:

- **Available Statuses:**
  - `auto` - Default, auto-extracted, not reviewed
  - `needs_review` - Flagged for manual review
  - `approved` - Manually approved by curator
  - `rejected` - Marked as not a term (noise)

- **Workflow:**
  1. Click status button (Auto/Needs Review/Approved/Rejected)
  2. Enter optional curation notes
  3. System records curator ID and timestamp
  4. Status updates immediately

**Implementation:** `term_card_view.py:357-393` (set_status)

### FR-3: Alias Management
**Status:** ✅ IMPLEMENTED

Users can manage variant forms (aliases) for terms:

- **Add Alias:**
  1. Click "Add Alias"
  2. Enter variant form (e.g., with nikud: "דֻגְמָה" for "דוגמה")
  3. Enter optional note
  4. Alias saved to `term_alias` table

- **Remove Alias:**
  1. Click "Remove Alias"
  2. Select alias from dropdown
  3. Confirm removal

**Implementation:**
- Add: `term_card_view.py:395-435`
- Remove: `term_card_view.py:437-473`

### FR-4: Stopword Actions
**Status:** ✅ IMPLEMENTED

Users can mark terms as stopwords (common words to exclude):

- **Toggle Stopword:**
  1. Click "Toggle Stopword"
  2. If setting: Enter reason (e.g., "Too common", "Not a term")
  3. If unsetting: Confirm action
  4. System updates `stopword_item` table

**Implementation:** `term_card_view.py:475-520` (toggle_stopword)

### FR-5: Pin Translation
**Status:** ✅ IMPLEMENTED

Users can override automatic translation lookup:

- **Pin Translation:**
  1. Click "Pin Translation"
  2. Enter translation text
  3. System stores in `term_cluster.pinned_translation`
  4. Future lookups use pinned value

- **Unpin Translation:**
  1. Click "Unpin Translation"
  2. Confirm action
  3. System reverts to automatic lookup

**Implementation:**
- Pin: `term_card_view.py:522-556`
- Unpin: `term_card_view.py:558-594`

### FR-6: Pin Example (Future)
**Status:** 🔶 NOT IMPLEMENTED (UI for pinning example sentences)

**Rationale:** Backend supports pin_example() but UI integration requires sentence selection dialog. Deferred to post-M8.

**Workaround:** Example pinning can be done via backend API if needed.

### FR-7: Review Queue Navigation
**Status:** ✅ IMPLEMENTED

Users can navigate through terms:

- **Navigation Controls:**
  - "< Previous" button (disabled at start)
  - "Next >" button (disabled at end)
  - Position indicator (e.g., "5 / 128")

- **Queue Interaction:**
  - Click any row in review queue table to jump to that term
  - Queue updates when filters change

**Implementation:**
- Navigation: `term_card_view.py:340-351`
- Queue click: `term_card_view.py:270-282`

### FR-8: Filtering and Ordering
**Status:** ✅ IMPLEMENTED

Users can filter and sort the review queue:

- **Status Filter:**
  - All (default)
  - auto
  - needs_review
  - approved
  - rejected

- **Order By:**
  - freq (frequency, high to low) - default
  - termhood (termhood score)
  - weirdness (domain specificity)
  - pmi (association strength)
  - alpha (alphabetical)

- **Min Frequency:**
  - Spinner control (0-1000)
  - Filters out low-frequency terms

**Implementation:** `term_card_view.py:237-268` (load_review_queue)

---

## UI/UX Constraints Adherence

### UX-1: No Time Estimates
✅ **PASS** - No time estimates in UI or error messages.

### UX-2: Clear Error Messages
✅ **PASS** - All error messages are specific and actionable:
- "Please select a term first" (when no term loaded)
- "This term has no aliases" (when trying to remove)
- "Alias already exists" (duplicate detection)
- Database errors wrapped with context

### UX-3: Confirmation Dialogs
✅ **PASS** - Destructive actions have confirmations:
- Unpin translation: QMessageBox confirmation
- Status changes: Optional notes dialog allows cancel
- Remove alias: Dropdown selection prevents accidents

### UX-4: Immediate Feedback
✅ **PASS** - All actions provide immediate feedback:
- Success: `show_info()` dialog
- Error: `show_error()` dialog
- UI updates immediately after action (reload_current_card)

### UX-5: Keyboard Navigation
🔶 **PARTIAL** - Mouse-driven interface, keyboard shortcuts not implemented.

**Justification:** Sequential review workflow benefits from keyboard, but not critical for M8 DoD. Can be added in iteration 2.

### UX-6: Responsive Layout
✅ **PASS** - Uses QSplitter for resizable card/queue sections.

---

## Technical Requirements

### TR-1: Service Layer Integration
✅ **PASS** - All actions use `TermCardService` methods:
- `get_card()` - Load term data
- `set_status()` - Update curation status
- `add_alias() / remove_alias()` - Alias management
- `set_stopword() / unset_stopword()` - Stopword marking
- `pin_translation() / unpin_translation()` - Translation override
- `list_review_queue()` - Queue population

### TR-2: Database Session Management
✅ **PASS** - Proper context manager usage:
```python
with self.db_service.get_session() as session:
    # operations
    session.commit()
```

### TR-3: Error Handling
✅ **PASS** - All service calls wrapped in try/except:
```python
try:
    # database operation
except Exception as e:
    logger.exception("Failed to ...")
    show_error(self, "Error", f"Failed to ...: {e}")
```

### TR-4: Model/View Pattern
✅ **PASS** - Uses `TermCardTableModel` for review queue:
- Inherits from `QAbstractTableModel`
- Implements rowCount, columnCount, data, headerData
- `update_cards()` for refresh
- `get_card()` for row access

### TR-5: Signal Safety
✅ **PASS** - No worker threads needed (all operations are fast DB queries). No QThread lifecycle issues.

---

## Test Coverage

### Test Scenarios Implemented

**In test_m8_basic.py (8/8 tests):**
1. ✅ Migration applied (curation columns exist)
2. ✅ Create term cluster with curation fields
3. ✅ Get term card
4. ✅ Set curation status
5. ✅ Add/remove alias
6. ✅ Set/unset stopword
7. ✅ Pin/unpin translation
8. ✅ Review queue listing

**Manual UI Testing Required:**
- [ ] Load term card view in app
- [ ] Navigate through review queue
- [ ] Set each status type (auto/needs_review/approved/rejected)
- [ ] Add and remove aliases
- [ ] Toggle stopword on/off
- [ ] Pin and unpin translation
- [ ] Filter by status (needs_review, approved)
- [ ] Change sort order (freq → alpha)
- [ ] Adjust min frequency filter
- [ ] Verify card updates after actions
- [ ] Check error handling (select term first, no aliases, etc.)

---

## Known Limitations

### L-1: No Bulk Actions
**Description:** Users must review terms one at a time. No bulk approve/reject.

**Rationale:** Curation is inherently manual. Bulk actions risk approving noise.

**Workaround:** `TermCardService.bulk_set_status()` exists for scripted workflows if needed.

### L-2: No Pin Example UI
**Description:** Cannot pin example sentences from UI.

**Rationale:** Requires sentence selection dialog, out of scope for M8.

**Workaround:** Example sentences shown if pinned via backend API.

### L-3: No Search in Queue
**Description:** Cannot search for specific term in review queue.

**Rationale:** Filters (status, freq, order) cover most use cases. Full search requires FTS integration.

**Workaround:** Use alphabetical sort and scroll.

### L-4: No Undo
**Description:** No undo for curation actions.

**Rationale:** All actions are reversible (change status back, remove alias, unpin). Full undo stack adds complexity.

**Workaround:** Manual reversal of actions.

---

## Accessibility

### A-1: Screen Reader Support
🔶 **PARTIAL** - Qt labels have text, but no ARIA attributes or explicit roles.

**Note:** PyQt6 accessibility limited on Windows. Full WCAG 2.1 compliance not achievable without native platform integration.

### A-2: High Contrast
✅ **PASS** - No custom colors, inherits system theme.

### A-3: Font Scaling
✅ **PASS** - Uses default system fonts, respects OS scaling.

---

## DoD Checklist

- [x] FR-1: Card display shows all term metadata
- [x] FR-2: Status workflow (4 statuses)
- [x] FR-3: Alias management (add/remove)
- [x] FR-4: Stopword actions (toggle)
- [x] FR-5: Pin translation (pin/unpin)
- [ ] FR-6: Pin example (deferred)
- [x] FR-7: Review queue navigation (prev/next/click)
- [x] FR-8: Filtering and ordering (status/order/freq)
- [x] UX-1: No time estimates
- [x] UX-2: Clear error messages
- [x] UX-3: Confirmation dialogs
- [x] UX-4: Immediate feedback
- [ ] UX-5: Keyboard navigation (partial, not critical)
- [x] UX-6: Responsive layout
- [x] TR-1: Service layer integration
- [x] TR-2: Database session management
- [x] TR-3: Error handling
- [x] TR-4: Model/View pattern
- [x] TR-5: Signal safety
- [x] Test coverage: Backend (8/8 tests PASS)
- [ ] Test coverage: Manual UI testing (pending)

---

## Conclusion

**Status:** ✅ **PATCH 3 COMPLETE** (UI wiring done)

**Remaining for M8:**
- PATCH 4: Comprehensive test_m8.py (>=10 tests including UI integration)
- Manual UI verification (smoke test in app)
- M8_COMPLETE.md documentation

**Known Gaps:**
- Pin example UI (not critical, deferred)
- Keyboard shortcuts (nice-to-have, not critical)
- Full search in queue (covered by filters)

**Acceptance:** UI meets all critical requirements for term curation workflow. Deferred items are non-blocking enhancements.

---

**Last Updated:** 2026-02-04
**Author:** Claude Sonnet 4.5
**Version:** 1.0
