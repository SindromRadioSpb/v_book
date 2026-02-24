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
- **Ctrl+Alt+O**: Open Pronunciation Bootstrap

### Premium Features
- **Ctrl+Shift+T**: Translation Management
- **Ctrl+Shift+U**: User Dictionaries
- **Ctrl+Shift+C**: QA / Coverage (requires project context)
- **Ctrl+Alt+L**: Toggle Audio Player panel

---

## Table Shortcuts

### Sorting
- **Click** column header: Sort by that column (single-column sort)
- **Shift+Click** column header: Add column to sort keys (multi-column sort)

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

### Audio Playback
- **Space**: Play/Pause current audio queue
- **Esc**: Stop audio playback (when player focus/context is active)

### Audio Player Panel (when Audio Player has focus)
- **Space**: Play/Pause
- **J**: Previous track
- **K**: Next track
- **+** or **=**: Increase playback speed by `0.1x`
- **-**: Decrease playback speed by `0.1x`
- **R**: Cycle repeat mode (`Off -> One -> All`)
- **Esc**: Stop playback (keep queue)

Scope rules:
- Audio Player shortcuts are bound with widget scope (`WidgetWithChildrenShortcut`).
- They are active only when focus is inside Audio Player panel.
- They do not override typing in other workspaces/panels.

Playlist Entries table:
- **Enter / Space**: Play selected rows (only when selection has playable rows).
- **Del / Backspace**: Remove selected rows from playlist.

---

## Command Palette Shortcuts

When command palette is open (Ctrl+P):

- **Type**: Filter actions by fuzzy search
- **Up / Down**: Navigate results
- **Enter**: Execute selected action
- **Esc**: Close palette without executing

---

## Navigation

- **Projects Dashboard**: command palette action `Projects` or sidebar **Projects**
- **Translation Management**: sidebar **Translation Management** or **Ctrl+Shift+T**
- **User Dictionaries**: sidebar **User Dictionaries** or **Ctrl+Shift+U**
- **Projects**: Double-click project in dashboard to open

---

## Tips

1. **Keyboard-First Workflow**: Use Ctrl+P to access any feature without memorizing individual shortcuts.
2. **Column Persistence**: Column order and widths are saved automatically for Dictionary, Terms, Documents, Term Cards, and Translation Management.
3. **Bulk Operations**: Select multiple rows with Ctrl+Click or Shift+Click for bulk actions.

---

## Shortcut Conflicts

No known conflicts.

---

## Customization

Keyboard shortcuts are not currently customizable.
