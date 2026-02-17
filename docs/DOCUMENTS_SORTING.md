# Documents Table Sorting

## Overview

Documents view now supports interactive column sorting. Click any column header to sort the table by that column.

## Features

- **Click to sort:** Click column header to sort ascending
- **Toggle direction:** Click again to toggle between ascending/descending
- **Visual indicator:** Arrow icon shows current sort direction
- **Numeric sorting:** ID, Size, Sentences, Tokens sort numerically (not alphabetically)
- **Text sorting:** File Name, Status, Path sort alphabetically
- **Column width persistence:** Manually resized widths are restored across sessions
- **Layout reset:** Right-click header → **Reset Columns Layout**

## Columns

| Column | Type | Sort Behavior |
|--------|------|--------------|
| ID | Numeric | 1, 2, 10, 100 (correct numeric order) |
| File Name | Text | Alphabetical (a-z or z-a) |
| Size (KB) | Numeric | By actual size (2.1, 5.2, 15.5, 100.0) |
| Status | Text | Alphabetical (failed, imported, processed) |
| Sentences | Numeric | By count (0, 5, 10, 50, 200) |
| Tokens | Numeric | By count (0, 50, 100, 500, 2000) |
| Imported | Text | Chronological (as formatted string) |
| Path | Text | Alphabetical |

## Technical Implementation

**QTableWidget built-in sorting:**
- Uses `setSortingEnabled(True)` on QTableWidget
- Numeric columns use `setData(Qt.ItemDataRole.DisplayRole, numeric_value)`
- Text columns use standard `QTableWidgetItem(text_value)`

**Performance optimization:**
- Sorting disabled during table population
- Re-enabled after all rows loaded
- Prevents redundant sorting on each row insert

**Code changes:**
```python
# Enable sorting
self.docs_table.setSortingEnabled(True)

# Numeric column (ID example)
id_item = QTableWidgetItem()
id_item.setData(Qt.ItemDataRole.DisplayRole, doc.doc_id)  # Store as int
self.docs_table.setItem(row, 0, id_item)

# Size with formatted display
size_item = QTableWidgetItem()
size_item.setData(Qt.ItemDataRole.DisplayRole, size_kb)  # Store as float
size_item.setText(f"{size_kb:.1f}")  # Display formatted
self.docs_table.setItem(row, 2, size_item)
```

## Usage

1. Open Documents view
2. Click any column header (ID, File Name, Size, etc.)
3. Table sorts by that column (ascending)
4. Click again to reverse sort direction (descending)
5. Visual arrow indicator shows sort column and direction

## Examples

**Sort by ID (ascending):**
- Before: [1, 10, 2, 100, 25]
- After: [1, 2, 10, 25, 100]

**Sort by Size (descending):**
- Before: [5.2, 15.5, 100.0, 2.1, 50.3]
- After: [100.0, 50.3, 15.5, 5.2, 2.1]

**Sort by File Name (alphabetical):**
- Before: [file10.txt, file2.txt, file1.txt]
- After: [file1.txt, file10.txt, file2.txt]

## Notes

- **Persistent across reloads:** Sort order NOT preserved when reloading documents
- **Persistent across sessions:** Column order and widths are preserved
- **Default order:** Imported date descending (most recent first)
- **Empty values:** Numeric columns treat NULL as 0 for sorting
- **Selection preserved:** Selected rows remain selected after sorting

## Testing

Created test scripts:
- `scripts/test_documents_sorting.py` - GUI test with sample data
- `scripts/test_sorting_simple.py` - Logic test without GUI

To test manually:
1. Import documents with varying IDs, sizes, sentence counts
2. Click ID header → verify numeric order (1, 2, 10 not 1, 10, 2)
3. Click Size header → verify by size (2.1, 5.2, 100.0)
4. Click File Name → verify alphabetical order
