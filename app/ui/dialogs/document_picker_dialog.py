"""Premium document picker dialog for large project datasets."""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QSignalBlocker, Qt, QTimer
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.infra.settings import SettingsService
from app.ui.workers import ProjectDocumentsPageWorker

logger = logging.getLogger(__name__)


class DocumentPickerDialog(QDialog):
    """Searchable/paged document picker for very large project lists."""

    COL_ID = 0
    COL_TITLE = 1
    COL_TAG = 2
    COL_TOPIC = 3
    COL_LEVEL = 4

    def __init__(
        self,
        *,
        project_id: int,
        selected_doc_id: Optional[int] = None,
        settings: Optional[SettingsService] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.project_id = int(project_id)
        self.settings = settings or SettingsService.get_instance()
        self.current_page = 1
        self.page_size = 50
        self.total_count = 0
        self._request_seq = 0
        self._active_request_id = 0
        self._worker: Optional[ProjectDocumentsPageWorker] = None
        self._current_rows = []
        self._selected_doc_id = selected_doc_id
        self._selected_doc_name = "All Documents"
        self._frequent_tag_buttons: dict[str, QPushButton] = {}

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._on_search_timeout)

        self._init_ui()
        self._restore_filter_state()
        self.document_edit.setFocus()
        self._render_active_filter_chips()
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
        root.setSpacing(10)

        form_card = QFrame()
        form_card.setFrameShape(QFrame.Shape.StyledPanel)
        form_layout = QGridLayout(form_card)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setHorizontalSpacing(18)
        form_layout.setVerticalSpacing(10)
        form_layout.setColumnMinimumWidth(0, 86)
        form_layout.setColumnMinimumWidth(2, 78)
        form_layout.setColumnStretch(0, 0)
        form_layout.setColumnStretch(1, 1)
        form_layout.setColumnStretch(2, 0)
        form_layout.setColumnStretch(3, 1)

        form_layout.addWidget(QLabel("Document"), 0, 0)
        self.document_edit = QLineEdit()
        self.document_edit.setPlaceholderText("Partial title / file name")
        self.document_edit.textChanged.connect(self._on_filter_text_changed)
        self.document_edit.setMaximumWidth(260)
        form_layout.addWidget(self._compact_field(self.document_edit, 260), 0, 1)

        form_layout.addWidget(QLabel("Document ID"), 0, 2)
        self.document_id_edit = QLineEdit()
        self.document_id_edit.setPlaceholderText("Exact ID")
        self.document_id_edit.setValidator(QIntValidator(1, 999999999, self))
        self.document_id_edit.textChanged.connect(self._on_filter_text_changed)
        self.document_id_edit.setMaximumWidth(120)
        form_layout.addWidget(self._compact_field(self.document_id_edit, 120), 0, 3)

        form_layout.addWidget(QLabel("Topic"), 1, 0)
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("Partial topic")
        self.topic_edit.textChanged.connect(self._on_filter_text_changed)
        self.topic_edit.setMaximumWidth(260)
        form_layout.addWidget(self._compact_field(self.topic_edit, 260), 1, 1)

        form_layout.addWidget(QLabel("Level"), 1, 2)
        self.level_combo = QComboBox()
        self.level_combo.addItems(["All", "aleph", "bet", "gimel", "he"])
        self.level_combo.currentTextChanged.connect(self._on_combo_filter_changed)
        self.level_combo.setMaximumWidth(120)
        form_layout.addWidget(self._compact_field(self.level_combo, 120), 1, 3)

        form_layout.addWidget(QLabel("Tags"), 2, 0)
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("Comma-separated tags, partial match")
        self.tag_edit.textChanged.connect(self._on_tag_text_changed)
        self.tag_edit.setMaximumWidth(260)
        form_layout.addWidget(self._compact_field(self.tag_edit, 260), 2, 1)

        form_layout.addWidget(QLabel("Tag mode"), 2, 2)
        self.tag_mode_combo = QComboBox()
        self.tag_mode_combo.addItems(["Any tag", "All tags"])
        self.tag_mode_combo.currentTextChanged.connect(self._on_combo_filter_changed)
        self.tag_mode_combo.setMaximumWidth(120)
        form_layout.addWidget(self._compact_field(self.tag_mode_combo, 120), 2, 3)
        root.addWidget(form_card)

        top_tags_card = QFrame()
        top_tags_card.setFrameShape(QFrame.Shape.StyledPanel)
        top_tags_layout = QVBoxLayout(top_tags_card)
        top_tags_layout.setContentsMargins(10, 8, 10, 8)
        top_tags_layout.setSpacing(6)
        tags_title = QLabel("Top tags")
        tags_title.setStyleSheet("font-weight: 600; color: #223;")
        top_tags_layout.addWidget(tags_title)
        tags_row = QHBoxLayout()
        tags_row.setContentsMargins(0, 0, 0, 0)
        tags_row.setSpacing(6)
        self.quick_tags_wrap = QHBoxLayout()
        self.quick_tags_wrap.setSpacing(6)
        tags_row.addLayout(self.quick_tags_wrap)
        tags_row.addStretch()
        top_tags_layout.addLayout(tags_row)
        root.addWidget(top_tags_card)

        active_filters_card = QFrame()
        active_filters_card.setFrameShape(QFrame.Shape.StyledPanel)
        active_filters_layout = QVBoxLayout(active_filters_card)
        active_filters_layout.setContentsMargins(10, 8, 10, 8)
        active_filters_layout.setSpacing(6)
        active_title = QLabel("Active filters")
        active_title.setStyleSheet("font-weight: 600; color: #223;")
        active_filters_layout.addWidget(active_title)
        chips_row = QHBoxLayout()
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(6)
        self.active_filters_layout = QHBoxLayout()
        self.active_filters_layout.setSpacing(6)
        chips_row.addLayout(self.active_filters_layout)
        chips_row.addStretch()
        active_filters_layout.addLayout(chips_row)

        actions_row = QHBoxLayout()
        actions_row.addStretch()
        self.clear_filters_btn = QPushButton("Clear filters")
        self.clear_filters_btn.clicked.connect(self._clear_filters)
        actions_row.addWidget(self.clear_filters_btn)
        active_filters_layout.addLayout(actions_row)
        root.addWidget(active_filters_card)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(["ID", "Title", "Tag", "Topic", "Level"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(False)
        self.results_table.itemDoubleClicked.connect(lambda _item: self._accept_selected())
        self.results_table.itemActivated.connect(lambda _item: self._accept_selected())
        self.results_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.results_table.setColumnWidth(self.COL_ID, 85)
        self.results_table.setColumnWidth(self.COL_TITLE, 330)
        self.results_table.setColumnWidth(self.COL_TAG, 140)
        self.results_table.setColumnWidth(self.COL_TOPIC, 140)
        self.results_table.setColumnWidth(self.COL_LEVEL, 90)
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

    def _compact_field(self, widget: QWidget, max_width: int) -> QWidget:
        """Keep filter editors compact and left-aligned without fixed fragile geometry."""
        widget.setMaximumWidth(max_width)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget)
        layout.addStretch()
        return wrapper

    def _settings_key(self, suffix: str) -> str:
        return f"document_picker/project_{self.project_id}/{suffix}"

    def _restore_filter_state(self) -> None:
        blockers = [
            QSignalBlocker(self.document_edit),
            QSignalBlocker(self.document_id_edit),
            QSignalBlocker(self.topic_edit),
            QSignalBlocker(self.tag_edit),
            QSignalBlocker(self.level_combo),
            QSignalBlocker(self.tag_mode_combo),
        ]
        self.document_edit.setText(self.settings.get_string(self._settings_key("document"), ""))
        self.document_id_edit.setText(self.settings.get_string(self._settings_key("document_id"), ""))
        self.topic_edit.setText(self.settings.get_string(self._settings_key("topic"), ""))
        self.tag_edit.setText(self.settings.get_string(self._settings_key("tags"), ""))
        level = self.settings.get_string(self._settings_key("level"), "All") or "All"
        tag_mode = self.settings.get_string(self._settings_key("tag_mode"), "Any tag") or "Any tag"
        level_index = self.level_combo.findText(level)
        tag_mode_index = self.tag_mode_combo.findText(tag_mode)
        self.level_combo.setCurrentIndex(level_index if level_index >= 0 else 0)
        self.tag_mode_combo.setCurrentIndex(tag_mode_index if tag_mode_index >= 0 else 0)
        del blockers

    def _save_filter_state(self) -> None:
        self.settings.set_value(self._settings_key("document"), self.document_edit.text().strip())
        self.settings.set_value(self._settings_key("document_id"), self.document_id_edit.text().strip())
        self.settings.set_value(self._settings_key("topic"), self.topic_edit.text().strip())
        self.settings.set_value(self._settings_key("tags"), self.tag_edit.text().strip())
        self.settings.set_value(self._settings_key("level"), self.level_combo.currentText().strip())
        self.settings.set_value(self._settings_key("tag_mode"), self.tag_mode_combo.currentText().strip())

    def _on_search_timeout(self) -> None:
        self._reload(reset_page=True)

    def _on_filter_text_changed(self, _text: str) -> None:
        self._save_filter_state()
        self._render_active_filter_chips()
        self._search_timer.start()

    def _on_tag_text_changed(self, _text: str) -> None:
        self._save_filter_state()
        self._sync_quick_tag_state()
        self._render_active_filter_chips()
        self._search_timer.start()

    def _on_combo_filter_changed(self, _text: str) -> None:
        self._save_filter_state()
        self._render_active_filter_chips()
        self._search_timer.start()

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

        self._render_active_filter_chips()
        self.status_label.setText("Loading documents...")

        worker = ProjectDocumentsPageWorker(
            request_id=request_id,
            project_id=self.project_id,
            search_query=None,
            document_filter=self.document_edit.text().strip() or None,
            document_id=self._current_document_id_filter(),
            tag_filter=self.tag_edit.text().strip() or None,
            topic_filter=self.topic_edit.text().strip() or None,
            level_filter=self._current_level_filter(),
            tag_match_mode=self._current_tag_mode(),
            page_size=self.page_size,
            page_index=self.current_page,
        )
        self._worker = worker
        worker.status.connect(self._on_worker_status)
        worker.page_loaded.connect(self._on_page_loaded)
        worker.frequent_tags_loaded.connect(self._on_frequent_tags_loaded)
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

            topic_item = QTableWidgetItem(doc.topic or "")
            topic_item.setFlags(topic_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.results_table.setItem(row_idx, self.COL_TOPIC, topic_item)

            level_item = QTableWidgetItem(doc.level or "")
            level_item.setFlags(level_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.results_table.setItem(row_idx, self.COL_LEVEL, level_item)

            if self._selected_doc_id is not None and int(doc.doc_id) == int(self._selected_doc_id):
                self.results_table.selectRow(row_idx)
        if self.results_table.rowCount() > 0 and not self.results_table.selectedItems():
            self.results_table.selectRow(0)

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

    def _current_document_id_filter(self) -> Optional[int]:
        raw_value = self.document_id_edit.text().strip()
        if not raw_value:
            return None
        try:
            return int(raw_value)
        except ValueError:
            return None

    def _current_level_filter(self) -> Optional[str]:
        level = self.level_combo.currentText().strip()
        return None if level == "All" else level

    def _current_tag_mode(self) -> str:
        return "all" if self.tag_mode_combo.currentIndex() == 1 else "any"

    def _set_tag_filter_tokens(self, tokens: list[str]) -> None:
        joined = ", ".join(tokens)
        if self.tag_edit.text() == joined:
            return
        self.tag_edit.blockSignals(True)
        self.tag_edit.setText(joined)
        self.tag_edit.blockSignals(False)
        self._sync_quick_tag_state()
        self._render_active_filter_chips()
        self._search_timer.start()

    def _toggle_quick_tag(self, tag: str) -> None:
        tokens = self._parse_tag_tokens(self.tag_edit.text())
        lookup = {token.casefold(): token for token in tokens}
        norm = tag.casefold()
        if norm in lookup:
            tokens = [token for token in tokens if token.casefold() != norm]
        else:
            tokens.append(tag)
        self._set_tag_filter_tokens(tokens)

    def _parse_tag_tokens(self, raw_value: str) -> list[str]:
        parts = [part.strip() for part in raw_value.replace(";", ",").split(",")]
        tokens: list[str] = []
        seen: set[str] = set()
        for part in parts:
            token = " ".join(part.split())
            if not token:
                continue
            norm = token.casefold()
            if norm in seen:
                continue
            seen.add(norm)
            tokens.append(token)
        return tokens

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _render_quick_tags(self, tags: list[str]) -> None:
        self._clear_layout(self.quick_tags_wrap)
        self._frequent_tag_buttons.clear()
        for tag in tags:
            btn = QPushButton(tag)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, value=tag: self._toggle_quick_tag(value))
            self.quick_tags_wrap.addWidget(btn)
            self._frequent_tag_buttons[tag.casefold()] = btn
        self.quick_tags_wrap.addStretch()
        self._sync_quick_tag_state()

    def _sync_quick_tag_state(self) -> None:
        active = {token.casefold() for token in self._parse_tag_tokens(self.tag_edit.text())}
        for norm, btn in self._frequent_tag_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(norm in active)
            btn.blockSignals(False)

    def _add_filter_chip(self, text: str) -> None:
        chip = QLabel(text)
        chip.setStyleSheet(
            "padding: 3px 8px; border: 1px solid #aeb6c2; border-radius: 10px; "
            "background: #eef3f8; color: #223;"
        )
        self.active_filters_layout.addWidget(chip)

    def _render_active_filter_chips(self) -> None:
        self._clear_layout(self.active_filters_layout)
        doc = self.document_edit.text().strip()
        doc_id = self.document_id_edit.text().strip()
        topic = self.topic_edit.text().strip()
        level = self._current_level_filter()
        tags = self._parse_tag_tokens(self.tag_edit.text())
        if doc:
            self._add_filter_chip(f"Document: {doc}")
        if doc_id:
            self._add_filter_chip(f"ID: {doc_id}")
        for tag in tags:
            self._add_filter_chip(f"Tag: {tag}")
        if tags:
            self._add_filter_chip("Tag mode: All" if self._current_tag_mode() == "all" else "Tag mode: Any")
        if topic:
            self._add_filter_chip(f"Topic: {topic}")
        if level:
            self._add_filter_chip(f"Level: {level}")
        if self.active_filters_layout.count() == 0:
            self._add_filter_chip("No active filters")
        self.active_filters_layout.addStretch()

    def _clear_filters(self) -> None:
        self._search_timer.stop()
        for widget in (self.document_edit, self.document_id_edit, self.topic_edit, self.tag_edit):
            widget.blockSignals(True)
        self.level_combo.blockSignals(True)
        self.tag_mode_combo.blockSignals(True)
        self.document_edit.clear()
        self.document_id_edit.clear()
        self.topic_edit.clear()
        self.tag_edit.clear()
        self.level_combo.setCurrentIndex(0)
        self.tag_mode_combo.setCurrentIndex(0)
        for widget in (self.document_edit, self.document_id_edit, self.topic_edit, self.tag_edit):
            widget.blockSignals(False)
        self.level_combo.blockSignals(False)
        self.tag_mode_combo.blockSignals(False)
        self._save_filter_state()
        self._sync_quick_tag_state()
        self._render_active_filter_chips()
        self._reload(reset_page=True)

    def _on_frequent_tags_loaded(self, request_id: int, tags: list) -> None:
        if int(request_id) != self._active_request_id:
            return
        self._render_quick_tags([str(tag) for tag in (tags or []) if str(tag).strip()])

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
