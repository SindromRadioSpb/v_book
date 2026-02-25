"""Premium document picker dialog for large project datasets."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.workers import ProjectDocumentsPageWorker

logger = logging.getLogger(__name__)


class DocumentPickerDialog(QDialog):
    """Searchable/paged document picker for very large project lists."""

    COL_ID = 0
    COL_TITLE = 1
    COL_TAG = 2

    def __init__(
        self,
        *,
        project_id: int,
        selected_doc_id: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.project_id = int(project_id)
        self.current_page = 1
        self.page_size = 50
        self.total_count = 0
        self._request_seq = 0
        self._active_request_id = 0
        self._worker: Optional[ProjectDocumentsPageWorker] = None
        self._current_rows = []
        self._selected_doc_id = selected_doc_id
        self._selected_doc_name = "All Documents"

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._on_search_timeout)

        self._init_ui()
        self.search_edit.setFocus()
        self._reload(reset_page=True)

    @property
    def total_pages(self) -> int:
        if self.total_count <= 0:
            return 1
        return max(1, (self.total_count + self.page_size - 1) // self.page_size)

    def _init_ui(self) -> None:
        self.setWindowTitle("Select Document")
        self.setModal(True)
        self.resize(760, 520)
        self.setMinimumWidth(640)

        root = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by title, document ID, or tag...")
        self.search_edit.textChanged.connect(lambda _text: self._search_timer.start())
        search_row.addWidget(self.search_edit)
        root.addLayout(search_row)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["ID", "Title", "Tag"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(False)
        self.results_table.itemDoubleClicked.connect(lambda _item: self._accept_selected())
        self.results_table.itemActivated.connect(lambda _item: self._accept_selected())
        self.results_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.results_table.setColumnWidth(self.COL_ID, 85)
        self.results_table.setColumnWidth(self.COL_TITLE, 470)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.results_table)

        pag_row = QHBoxLayout()
        self.first_btn = QPushButton("<<")
        self.first_btn.setMaximumWidth(36)
        self.first_btn.clicked.connect(lambda: self._go_to_page(1))
        pag_row.addWidget(self.first_btn)

        self.prev_btn = QPushButton("<")
        self.prev_btn.setMaximumWidth(36)
        self.prev_btn.clicked.connect(lambda: self._go_to_page(self.current_page - 1))
        pag_row.addWidget(self.prev_btn)

        pag_row.addWidget(QLabel("Page"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.setValue(1)
        self.page_spin.setMaximumWidth(70)
        self.page_spin.valueChanged.connect(self._on_page_spin_changed)
        pag_row.addWidget(self.page_spin)

        self.page_count_label = QLabel("of 1")
        pag_row.addWidget(self.page_count_label)

        self.next_btn = QPushButton(">")
        self.next_btn.setMaximumWidth(36)
        self.next_btn.clicked.connect(lambda: self._go_to_page(self.current_page + 1))
        pag_row.addWidget(self.next_btn)

        self.last_btn = QPushButton(">>")
        self.last_btn.setMaximumWidth(36)
        self.last_btn.clicked.connect(lambda: self._go_to_page(self.total_pages))
        pag_row.addWidget(self.last_btn)

        pag_row.addSpacing(12)
        self.range_label = QLabel("Showing 0-0 of 0")
        pag_row.addWidget(self.range_label)
        pag_row.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666;")
        pag_row.addWidget(self.status_label)
        root.addLayout(pag_row)

        button_row = QHBoxLayout()
        button_row.addStretch()

        self.select_btn = QPushButton("Select")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self._accept_selected)
        button_row.addWidget(self.select_btn)

        all_btn = QPushButton("All Documents")
        all_btn.clicked.connect(self._accept_all_documents)
        button_row.addWidget(all_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        root.addLayout(button_row)

    def _on_search_timeout(self) -> None:
        self._reload(reset_page=True)

    def _go_to_page(self, page: int) -> None:
        if page < 1:
            return
        if page == self.current_page:
            return
        self.current_page = page
        self._reload(reset_page=False)

    def _on_page_spin_changed(self, page: int) -> None:
        if page != self.current_page:
            self.current_page = int(page)
            self._reload(reset_page=False)

    def _reload(self, *, reset_page: bool) -> None:
        if reset_page:
            self.current_page = 1

        self._request_seq += 1
        request_id = int(self._request_seq)
        self._active_request_id = request_id

        if self._worker and self._worker.isRunning():
            self._worker.cancel()

        self.status_label.setText("Loading documents...")

        worker = ProjectDocumentsPageWorker(
            request_id=request_id,
            project_id=self.project_id,
            search_query=self.search_edit.text().strip() or None,
            page_size=self.page_size,
            page_index=self.current_page,
        )
        self._worker = worker
        worker.status.connect(self._on_worker_status)
        worker.page_loaded.connect(self._on_page_loaded)
        worker.error.connect(self._on_page_error)
        worker.start()

    def _on_worker_status(self, request_id: int, text: str) -> None:
        if int(request_id) != self._active_request_id:
            return
        self.status_label.setText(text)

    def _on_page_loaded(self, request_id: int, total_count: int, rows: list) -> None:
        if int(request_id) != self._active_request_id:
            return

        self.total_count = int(total_count or 0)
        self._current_rows = list(rows or [])
        self._render_rows()
        self._update_pagination()

        if self.total_count == 0:
            self.status_label.setText("No documents found")
        else:
            start = (self.current_page - 1) * self.page_size + 1
            end = min(start + len(self._current_rows) - 1, self.total_count)
            self.status_label.setText(f"Loaded {start}-{end} of {self.total_count}")

    def _on_page_error(self, request_id: int, error_message: str) -> None:
        if int(request_id) != self._active_request_id:
            return
        logger.error("Document picker load failed: %s", error_message)
        self.status_label.setText(f"Load failed: {error_message}")

    def _render_rows(self) -> None:
        self.results_table.setRowCount(len(self._current_rows))

        for row_idx, doc in enumerate(self._current_rows):
            id_item = QTableWidgetItem(str(doc.doc_id))
            id_item.setData(Qt.ItemDataRole.UserRole, int(doc.doc_id))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.results_table.setItem(row_idx, self.COL_ID, id_item)

            title_item = QTableWidgetItem(doc.file_name or "")
            title_item.setData(Qt.ItemDataRole.UserRole, int(doc.doc_id))
            title_item.setFlags(title_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.results_table.setItem(row_idx, self.COL_TITLE, title_item)

            tag_item = QTableWidgetItem(doc.tag or "")
            tag_item.setFlags(tag_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.results_table.setItem(row_idx, self.COL_TAG, tag_item)

            if self._selected_doc_id is not None and int(doc.doc_id) == int(self._selected_doc_id):
                self.results_table.selectRow(row_idx)

    def _update_pagination(self) -> None:
        total_pages = self.total_pages
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(total_pages)
        self.page_spin.setValue(min(max(1, self.current_page), total_pages))
        self.page_spin.blockSignals(False)
        self.page_count_label.setText(f"of {total_pages}")

        if self.total_count == 0:
            self.range_label.setText("Showing 0-0 of 0")
        else:
            start = (self.current_page - 1) * self.page_size + 1
            end = min(start + len(self._current_rows) - 1, self.total_count)
            self.range_label.setText(f"Showing {start}-{end} of {self.total_count}")

        self.first_btn.setEnabled(self.current_page > 1)
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < total_pages)
        self.last_btn.setEnabled(self.current_page < total_pages)

    def _on_selection_changed(self) -> None:
        self.select_btn.setEnabled(bool(self.results_table.selectedItems()))

    def _accept_selected(self) -> None:
        selected = self.results_table.selectedItems()
        if not selected:
            return

        row = selected[0].row()
        if row < 0 or row >= len(self._current_rows):
            return

        dto = self._current_rows[row]
        self._selected_doc_id = int(dto.doc_id)
        self._selected_doc_name = dto.file_name or f"Document #{dto.doc_id}"
        self.accept()

    def _accept_all_documents(self) -> None:
        self._selected_doc_id = None
        self._selected_doc_name = "All Documents"
        self.accept()

    def selected_document(self) -> tuple[Optional[int], str]:
        return self._selected_doc_id, self._selected_doc_name

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(200)
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.results_table.hasFocus():
            self._accept_selected()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
