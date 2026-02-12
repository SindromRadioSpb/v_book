"""Test script for Documents table sorting functionality."""
import sys
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt

def test_numeric_sorting():
    """Test that numeric columns sort correctly."""
    app = QApplication(sys.argv)

    # Create test widget
    widget = QWidget()
    layout = QVBoxLayout()

    label = QLabel("Test Documents Sorting - Click column headers to sort")
    layout.addWidget(label)

    # Create table with same structure as DocumentsView
    table = QTableWidget()
    table.setColumnCount(8)
    table.setHorizontalHeaderLabels([
        "ID", "File Name", "Size (KB)", "Status", "Sentences", "Tokens", "Imported", "Path"
    ])
    table.setSortingEnabled(True)

    # Add test data (similar to load_documents)
    test_data = [
        (1, "file1.txt", 5.2, "imported", 10, 100),
        (10, "file10.txt", 15.5, "processed", 50, 500),
        (2, "file2.txt", 100.0, "failed", 5, 50),
        (100, "file100.txt", 2.1, "processed", 200, 2000),
        (25, "file25.txt", 50.3, "imported", 0, 0),
    ]

    table.setSortingEnabled(False)  # Disable while populating
    table.setRowCount(len(test_data))

    for row, (doc_id, file_name, size_kb, status, sentences, tokens) in enumerate(test_data):
        # ID column - numeric
        id_item = QTableWidgetItem()
        id_item.setData(Qt.ItemDataRole.DisplayRole, doc_id)
        table.setItem(row, 0, id_item)

        # File Name - text
        table.setItem(row, 1, QTableWidgetItem(file_name))

        # Size - numeric with formatted display
        size_item = QTableWidgetItem()
        size_item.setData(Qt.ItemDataRole.DisplayRole, size_kb)
        size_item.setText(f"{size_kb:.1f}")
        table.setItem(row, 2, size_item)

        # Status - text
        table.setItem(row, 3, QTableWidgetItem(status))

        # Sentences - numeric
        sentences_item = QTableWidgetItem()
        sentences_item.setData(Qt.ItemDataRole.DisplayRole, sentences)
        sentences_item.setText(str(sentences))
        table.setItem(row, 4, sentences_item)

        # Tokens - numeric
        tokens_item = QTableWidgetItem()
        tokens_item.setData(Qt.ItemDataRole.DisplayRole, tokens)
        tokens_item.setText(str(tokens))
        table.setItem(row, 5, tokens_item)

        # Imported - text
        table.setItem(row, 6, QTableWidgetItem("2026-02-12 10:00:00"))

        # Path - text
        table.setItem(row, 7, QTableWidgetItem(f"/path/to/{file_name}"))

    table.setSortingEnabled(True)  # Re-enable after population

    layout.addWidget(table)
    widget.setLayout(layout)
    widget.resize(900, 400)
    widget.setWindowTitle("Documents Sorting Test")
    widget.show()

    print("✓ Table created with sorting enabled")
    print("✓ Test data:")
    print("  IDs: 1, 10, 2, 100, 25 (should sort numerically, not as text)")
    print("  Sizes: 5.2, 15.5, 100.0, 2.1, 50.3")
    print("✓ Click column headers to test sorting")
    print("✓ Expected: ID column sorts 1, 2, 10, 25, 100 (NOT 1, 10, 100, 2, 25)")

    sys.exit(app.exec())

if __name__ == '__main__':
    test_numeric_sorting()
