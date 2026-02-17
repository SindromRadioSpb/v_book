# HDLE Premium - Keyboard Shortcuts

Comprehensive keyboard shortcuts reference for HDLE Premium.

## Global Shortcuts

### Command Palette
- **Ctrl+P**: Open command palette (fuzzy search for all actions)

### Workspace
- **Ctrl+B**: Toggle sidebar visibility
- **Ctrl+Shift+R**: Reset layout to default

### Tools
- **Ctrl+Shift+V**: Run P1 Verification
- **Ctrl+Shift+I**: Import Dictionary (CSV)

### Premium Features
- **Ctrl+Shift+T**: Translation Management
- **Ctrl+Shift+C**: QA / Coverage (requires project context)

---

## Table Shortcuts

### Sorting
- **Click** column header: Sort by that column (single-column sort)
- **Shift+Click** column header: Add column to sort keys (multi-column sort)
  - Example: Click "Frequency" → Shift+Click "Lemma" sorts by frequency first, then lemma

### Selection
- **Click** row: Select single row
- **Ctrl+Click** row: Add/remove row from selection (multi-select)
- **Shift+Click** row: Select range from last selected to clicked row
- **Ctrl+A**: Select all rows

### Column Operations
- **Drag** column header: Reorder columns (moves persist across sessions)
- **Drag** column divider: Resize column width (widths persist across sessions)
- **Right-Click** column header: Open header menu and use **Reset Columns Layout**

### Editing
- **Double-Click** cell: Edit cell (Translation column in Dictionary/Terms views)
- **F2** or **Enter**: Edit selected cell
- **Esc**: Cancel editing

### Context Menu
- **Right-Click** row: Show context menu with "Why this translation?" option

---

## Command Palette Shortcuts

When command palette is open (Ctrl+P):

- **Type**: Filter actions by fuzzy search
- **↑** / **↓**: Navigate results
- **Enter**: Execute selected action
- **Esc**: Close palette without executing

---

## Navigation

- **Dashboard**: No shortcut (use command palette "Go to Dashboard" or sidebar "📊 Back to Dashboard" button)
- **Projects**: Double-click project in dashboard to open

---

## Tips

1. **Keyboard-First Workflow**: Use Ctrl+P to access any feature without memorizing individual shortcuts
2. **Multi-Column Sort**: Shift+Click multiple headers to build complex sort orders (e.g., POS → Frequency → Lemma)
3. **Column Persistence**: Column order and widths are saved automatically for Dictionary, Terms, Documents, Term Cards, and Translation Management
4. **Bulk Operations**: Select multiple rows with Ctrl+Click or Shift+Click for bulk actions (future feature)

---

## Shortcut Conflicts

No known conflicts. All shortcuts use Ctrl+Shift+ combinations to avoid conflicts with:
- System shortcuts (Alt+Tab, Windows key)
- Browser shortcuts (Ctrl+T, Ctrl+N)
- Text editing shortcuts (Ctrl+C, Ctrl+V, Ctrl+Z)

---

## Customization

Keyboard shortcuts are not currently customizable. If you need custom shortcuts, please file an issue at:
https://github.com/anthropics/claude-code/issues
