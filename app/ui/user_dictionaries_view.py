"""User Dictionaries view (P0)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.infra.settings import SettingsService
from app.services.audio_asset_service import AudioAssetService
from app.services.db_service import DBService
from app.services.user_dictionary_service import UserDictionaryService
from app.ui.dialogs.add_to_user_dictionary_dialog import show_add_to_user_dictionary_dialog
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
from app.ui.dialogs.batch_translate_dialog import show_batch_translate_dialog
from app.ui.models_qt import UserDictionaryItemsTableModel, UserDictionaryListModel
from app.ui.table_layout_controller import TableLayoutController
from app.ui.workers import (
    UserDictionaryBulkAddWorker,
    UserDictionaryBulkRemoveWorker,
    UserDictTranslateWorker,
)

logger = logging.getLogger(__name__)


class ManualUserDictionaryItemDialog(QDialog):
    """Dialog for adding one custom item."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Manual Item")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("Kind:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["lemma", "term_cluster", "ngram", "surface"])
        kind_row.addWidget(self.kind_combo)
        layout.addLayout(kind_row)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Source lang:"))
        self.src_lang_edit = QLineEdit("he")
        self.src_lang_edit.setMaximumWidth(90)
        lang_row.addWidget(self.src_lang_edit)
        lang_row.addWidget(QLabel("Target lang:"))
        self.tgt_lang_edit = QLineEdit("ru")
        self.tgt_lang_edit.setMaximumWidth(90)
        lang_row.addWidget(self.tgt_lang_edit)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        text_row = QHBoxLayout()
        text_row.addWidget(QLabel("Source text:"))
        self.src_text_edit = QLineEdit()
        text_row.addWidget(self.src_text_edit, 1)
        layout.addLayout(text_row)

        self.is_noise_checkbox = QCheckBox("Mark as noise")
        self.is_noise_checkbox.setChecked(False)
        layout.addWidget(self.is_noise_checkbox)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #d32f2f;")
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Add")
        ok_btn.setDefault(True)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        if not self.src_text_edit.text().strip():
            self.error_label.setText("Source text is required.")
            return
        if not self.src_lang_edit.text().strip() or not self.tgt_lang_edit.text().strip():
            self.error_label.setText("Language codes are required.")
            return
        self.accept()

    def payload(self) -> Dict[str, object]:
        return {
            "kind": self.kind_combo.currentText(),
            "src_lang": self.src_lang_edit.text().strip(),
            "tgt_lang": self.tgt_lang_edit.text().strip(),
            "src_text": self.src_text_edit.text().strip(),
            "is_noise": 1 if self.is_noise_checkbox.isChecked() else 0,
            "origin_entity_type": "manual",
            "origin_source_ref": "user_dictionaries_manual",
        }


class UserDictionariesView(QWidget):
    """User Dictionaries workspace."""

    back_requested = pyqtSignal()
    open_translation_management_requested = pyqtSignal()

    def __init__(self, project_id: Optional[int] = None, show_back_button: bool = False):
        super().__init__()
        self.project_id = project_id
        self.show_back_button = show_back_button
        self.db_service = DBService.get_instance()
        self.user_dict_service = UserDictionaryService()
        self.audio_service = AudioAssetService()
        self.settings = SettingsService.get_instance()
        self._scope_setting_key = (
            "user_dict/scope_mode_project" if self.project_id is not None else "user_dict/scope_mode_global"
        )

        self.current_dictionary_id: Optional[int] = self.settings.get_int("user_dict/current_dictionary_id", 0) or None
        self.current_page = 1
        self.page_size = self.settings.get_int("user_dict/page_size", 50)
        self.total_count = 0
        self.sort_column = self.settings.get_string("user_dict/sort_column", "updated_at")
        self.sort_direction = self.settings.get_string("user_dict/sort_direction", "desc")
        self.scope_mode = self.settings.get_string(
            self._scope_setting_key,
            "current_project" if self.project_id is not None else "all",
        )
        if self.scope_mode not in ("current_project", "all"):
            self.scope_mode = "all"
        if self.scope_mode == "current_project" and self.project_id is None:
            self.scope_mode = "all"
        self._bulk_worker = None
        self._translate_worker = None

        self.dictionary_model = UserDictionaryListModel()
        self.items_model = UserDictionaryItemsTableModel()
        self.COLUMN_TO_SORT = {
            0: "kind",
            1: "src_text",
            2: "translation",
            3: "translation_status",
            4: "is_noise",
            5: "study_state",
        }

        self._init_ui()
        self.load_dictionaries()

    @property
    def total_pages(self) -> int:
        if self.total_count <= 0:
            return 1
        return (self.total_count + self.page_size - 1) // self.page_size

    @property
    def current_offset(self) -> int:
        return (self.current_page - 1) * self.page_size

    def _init_ui(self):
        layout = QVBoxLayout(self)

        header_layout = QHBoxLayout()
        header = QLabel("User Dictionaries")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        header_layout.addWidget(header)

        self.open_tm_btn = QPushButton("Open Translation Management")
        self.open_tm_btn.clicked.connect(self.open_translation_management_requested.emit)
        header_layout.addWidget(self.open_tm_btn)
        header_layout.addStretch()

        self.back_btn = QPushButton("Projects Dashboard")
        self.back_btn.clicked.connect(self.back_requested.emit)
        self.back_btn.setVisible(self.show_back_button)
        header_layout.addWidget(self.back_btn)
        layout.addLayout(header_layout)

        scope_layout = QHBoxLayout()
        scope_layout.addWidget(QLabel("Scope:"))
        self.scope_current_btn = QPushButton("Current Project")
        self.scope_current_btn.setCheckable(True)
        self.scope_current_btn.clicked.connect(lambda: self.on_scope_changed("current_project"))
        scope_layout.addWidget(self.scope_current_btn)

        self.scope_all_btn = QPushButton("All")
        self.scope_all_btn.setCheckable(True)
        self.scope_all_btn.clicked.connect(lambda: self.on_scope_changed("all"))
        scope_layout.addWidget(self.scope_all_btn)

        self.scope_status_label = QLabel("")
        self.scope_status_label.setStyleSheet("color: #666; font-size: 11px;")
        scope_layout.addWidget(self.scope_status_label)

        self.scope_show_all_btn = QPushButton("Show All")
        self.scope_show_all_btn.clicked.connect(lambda: self.on_scope_changed("all"))
        scope_layout.addWidget(self.scope_show_all_btn)
        scope_layout.addStretch()
        layout.addLayout(scope_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Dictionaries"))

        self.dictionary_table = QTableView()
        self.dictionary_table.setModel(self.dictionary_model)
        self.dictionary_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.dictionary_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.dictionary_table.setAlternatingRowColors(True)
        self.dictionary_table.verticalHeader().setVisible(False)
        self.dictionary_table.setColumnWidth(0, 220)
        self.dictionary_table.setColumnWidth(1, 80)
        left_layout.addWidget(self.dictionary_table, 1)
        self.dictionary_table.selectionModel().selectionChanged.connect(self.on_dictionary_selected)

        dict_btn_row = QHBoxLayout()
        self.new_dict_btn = QPushButton("New")
        self.new_dict_btn.clicked.connect(self.on_new_dictionary)
        dict_btn_row.addWidget(self.new_dict_btn)
        self.rename_dict_btn = QPushButton("Rename")
        self.rename_dict_btn.clicked.connect(self.on_rename_dictionary)
        dict_btn_row.addWidget(self.rename_dict_btn)
        self.delete_dict_btn = QPushButton("Delete")
        self.delete_dict_btn.clicked.connect(self.on_delete_dictionary)
        dict_btn_row.addWidget(self.delete_dict_btn)
        left_layout.addLayout(dict_btn_row)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        filters_row = QHBoxLayout()
        filters_row.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search source / translation...")
        self.search_edit.textChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.search_edit, 1)

        filters_row.addWidget(QLabel("Kind:"))
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["All", "lemma", "term_cluster", "ngram", "surface"])
        self.kind_combo.setCurrentText(self.settings.get_string("user_dict/filter_kind", "All"))
        self.kind_combo.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.kind_combo)

        filters_row.addWidget(QLabel("Translation:"))
        self.translation_combo = QComboBox()
        self.translation_combo.addItems(["All", "Empty", "Non-empty"])
        self.translation_combo.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.translation_combo)

        filters_row.addWidget(QLabel("Tier:"))
        self.translation_tier_combo = QComboBox()
        self.translation_tier_combo.addItems(["All", "Missing", "MT", "User", "Approved", "Deprecated"])
        self.translation_tier_combo.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.translation_tier_combo)

        filters_row.addWidget(QLabel("Study:"))
        self.study_combo = QComboBox()
        self.study_combo.addItems(["All", "new", "learning", "due", "mastered", "suspended"])
        self.study_combo.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.study_combo)

        filters_row.addWidget(QLabel("Origin:"))
        self.origin_combo = QComboBox()
        self.origin_combo.addItems(["All", "project", "manual", "imported"])
        self.origin_combo.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.origin_combo)

        filters_row.addWidget(QLabel("Audio:"))
        self.audio_combo = QComboBox()
        self.audio_combo.addItems(["All", "missing", "ready", "failed"])
        self.audio_combo.currentTextChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.audio_combo)

        self.hide_noise_checkbox = QCheckBox("Hide Noise")
        self.hide_noise_checkbox.setChecked(self.settings.get_bool("user_dict/hide_noise", True))
        self.hide_noise_checkbox.stateChanged.connect(self.on_filter_changed)
        filters_row.addWidget(self.hide_noise_checkbox)

        right_layout.addLayout(filters_row)

        self.items_table = QTableView()
        self.items_table.setModel(self.items_model)
        self.items_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.items_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.horizontalHeader().setSectionsClickable(True)
        self.items_table.horizontalHeader().sectionClicked.connect(self.on_items_header_clicked)
        self.items_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.items_table.customContextMenuRequested.connect(self.on_context_menu)
        right_layout.addWidget(self.items_table, 1)
        self.items_table.selectionModel().selectionChanged.connect(self.on_items_selection_changed)
        self.items_model.dataChanged.connect(self.on_translation_edited)

        self.table_layout_controller = TableLayoutController(
            settings=self.settings,
            table_id="user_dict_items",
            table=self.items_table,
            default_widths={0: 120, 1: 230, 2: 230, 3: 110, 4: 90, 5: 110, 6: 120, 7: 90},
        )
        self.table_layout_controller.install()

        pagination = QHBoxLayout()
        self.first_btn = QPushButton("<<")
        self.first_btn.setMaximumWidth(38)
        self.first_btn.clicked.connect(self.on_first_page)
        pagination.addWidget(self.first_btn)
        self.prev_btn = QPushButton("<")
        self.prev_btn.setMaximumWidth(38)
        self.prev_btn.clicked.connect(self.on_prev_page)
        pagination.addWidget(self.prev_btn)
        pagination.addWidget(QLabel("Page"))
        self.page_combo = QComboBox()
        self.page_combo.setEditable(True)
        self.page_combo.setMaximumWidth(80)
        self.page_combo.currentTextChanged.connect(self.on_page_changed)
        pagination.addWidget(self.page_combo)
        self.page_count_label = QLabel("of 1")
        pagination.addWidget(self.page_count_label)
        self.next_btn = QPushButton(">")
        self.next_btn.setMaximumWidth(38)
        self.next_btn.clicked.connect(self.on_next_page)
        pagination.addWidget(self.next_btn)
        self.last_btn = QPushButton(">>")
        self.last_btn.setMaximumWidth(38)
        self.last_btn.clicked.connect(self.on_last_page)
        pagination.addWidget(self.last_btn)
        pagination.addSpacing(20)
        self.range_label = QLabel("Showing 0-0 of 0")
        pagination.addWidget(self.range_label)
        pagination.addSpacing(20)
        pagination.addWidget(QLabel("Page size:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250", "500"])
        self.page_size_combo.setCurrentText(str(self.page_size))
        self.page_size_combo.currentTextChanged.connect(self.on_page_size_changed)
        pagination.addWidget(self.page_size_combo)
        pagination.addStretch()
        right_layout.addLayout(pagination)

        actions_row = QHBoxLayout()
        self.add_manual_btn = QPushButton("Add Manual")
        self.add_manual_btn.clicked.connect(self.on_add_manual)
        actions_row.addWidget(self.add_manual_btn)
        self.remove_selected_btn = QPushButton("Remove Selected")
        self.remove_selected_btn.clicked.connect(self.on_remove_selected)
        self.remove_selected_btn.setEnabled(False)
        actions_row.addWidget(self.remove_selected_btn)
        self.translate_selected_btn = QPushButton("Translate Selected...")
        self.translate_selected_btn.clicked.connect(self.on_translate_selected)
        self.translate_selected_btn.setEnabled(False)
        actions_row.addWidget(self.translate_selected_btn)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_items)
        actions_row.addWidget(self.refresh_btn)
        actions_row.addStretch()
        right_layout.addLayout(actions_row)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        right_layout.addWidget(self.status_label)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        self._apply_scope_mode(reset_page=False)

    def _apply_scope_mode(self, reset_page: bool = True):
        """Apply scope chip state to current filters."""
        if self.scope_mode == "current_project" and self.project_id is not None:
            active_project_id = self.project_id
        else:
            self.scope_mode = "all"
            active_project_id = None

        self.scope_current_btn.blockSignals(True)
        self.scope_all_btn.blockSignals(True)
        self.scope_current_btn.setChecked(self.scope_mode == "current_project")
        self.scope_all_btn.setChecked(self.scope_mode == "all")
        self.scope_current_btn.setEnabled(self.project_id is not None)
        self.scope_current_btn.blockSignals(False)
        self.scope_all_btn.blockSignals(False)

        self.scope_show_all_btn.setVisible(self.scope_mode == "current_project")
        self.settings.set_value(self._scope_setting_key, self.scope_mode)

        if active_project_id is not None:
            self.scope_status_label.setText(f"Filtered by: Current Project ({active_project_id})")
        else:
            self.scope_status_label.setText("Filtered by: All projects")

        if reset_page:
            self.current_page = 1

    def on_scope_changed(self, scope_mode: str):
        """Handle scope chip click."""
        if scope_mode not in ("current_project", "all"):
            return
        if scope_mode == "current_project" and self.project_id is None:
            QMessageBox.information(
                self,
                "Project Context Required",
                "Current Project scope is available only when opened from a project context.",
            )
            return
        if self.scope_mode == scope_mode:
            return
        self.scope_mode = scope_mode
        self._apply_scope_mode(reset_page=True)
        self.load_items()

    def build_filters(self) -> Dict[str, object]:
        filters: Dict[str, object] = {"hide_noise": self.hide_noise_checkbox.isChecked()}
        if self.kind_combo.currentText() != "All":
            filters["kind"] = self.kind_combo.currentText()
        if self.study_combo.currentText() != "All":
            filters["study_state"] = self.study_combo.currentText()

        search = self.search_edit.text().strip()
        if search:
            filters["search_text"] = search

        tr_filter = self.translation_combo.currentText().lower()
        if tr_filter == "empty":
            filters["translation_filter"] = "empty"
        elif tr_filter == "non-empty":
            filters["translation_filter"] = "non_empty"
        else:
            filters["translation_filter"] = "all"

        tier_filter = self.translation_tier_combo.currentText().strip().lower()
        if tier_filter and tier_filter != "all":
            filters["translation_tier"] = tier_filter

        origin_filter = self.origin_combo.currentText().strip().lower()
        if origin_filter and origin_filter != "all":
            filters["origin_filter"] = origin_filter

        audio_filter = self.audio_combo.currentText().strip().lower()
        if audio_filter and audio_filter != "all":
            filters["audio_filter"] = audio_filter

        if self.scope_mode == "current_project" and self.project_id is not None:
            filters["origin_project_id"] = self.project_id

        return filters

    def load_dictionaries(self):
        try:
            with self.db_service.get_session() as session:
                dictionaries = self.user_dict_service.list_dictionaries(session)

            self.dictionary_model.update_dictionaries(dictionaries)
            if not dictionaries:
                self.current_dictionary_id = None
                self.items_model.update_items([], 0)
                self.total_count = 0
                self.update_pagination_controls()
                return

            selected_row = 0
            if self.current_dictionary_id:
                for idx, row in enumerate(dictionaries):
                    if row.dictionary_id == self.current_dictionary_id:
                        selected_row = idx
                        break
            else:
                self.current_dictionary_id = dictionaries[0].dictionary_id

            self.dictionary_table.selectRow(selected_row)
            selected = self.dictionary_model.get_dictionary(selected_row)
            if selected:
                self.current_dictionary_id = selected.dictionary_id
                self.settings.set_value("user_dict/current_dictionary_id", self.current_dictionary_id)

            self.load_items()
        except Exception as e:
            logger.error("Failed to load user dictionaries: %s", e, exc_info=True)
            QMessageBox.warning(self, "Error", f"Failed to load dictionaries:\n{e}")

    def _apply_audio_status(self, session, items):
        if not items:
            return

        voice_id = self.settings.get_string("user_dict/audio_voice_id", "default")
        provider = self.settings.get_string("user_dict/audio_provider", "none")
        speed_raw = self.settings.get_string("user_dict/audio_speed", "1.0")
        try:
            speed = float(speed_raw)
        except Exception:
            speed = 1.0

        by_lang: Dict[str, List[str]] = {}
        for item in items:
            by_lang.setdefault(item.src_lang, []).append(item.src_norm)

        status_map = {}
        for lang, norms in by_lang.items():
            mapping = self.audio_service.bulk_get_status(
                session,
                lang=lang,
                norm_texts=norms,
                voice_id=voice_id,
                speed=speed,
                provider=provider,
            )
            for norm, status in mapping.items():
                status_map[(lang, norm)] = status

        for item in items:
            item.audio_status = status_map.get((item.src_lang, item.src_norm), "missing")

    def load_items(self):
        if not self.current_dictionary_id:
            self.items_model.update_items([], 0)
            self.total_count = 0
            self.update_pagination_controls()
            return

        try:
            filters = self.build_filters()
            with self.db_service.get_session() as session:
                items, total = self.user_dict_service.query_items(
                    session=session,
                    dictionary_id=self.current_dictionary_id,
                    filters=filters,
                    limit=self.page_size,
                    offset=self.current_offset,
                    sort_column=self.sort_column,
                    sort_direction=self.sort_direction,
                )
                self._apply_audio_status(session, items)

            self.items_model.update_items(items, total)
            self.total_count = total
            self.update_pagination_controls()
            self.on_items_selection_changed()
            self.status_label.setText(f"Loaded {len(items)} rows")
        except Exception as e:
            logger.error("Failed to load dictionary items: %s", e, exc_info=True)
            QMessageBox.warning(self, "Error", f"Failed to load dictionary items:\n{e}")

    def on_dictionary_selected(self):
        selected_rows = self.dictionary_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        dictionary = self.dictionary_model.get_dictionary(row)
        if not dictionary:
            return

        if dictionary.dictionary_id != self.current_dictionary_id:
            self.current_dictionary_id = dictionary.dictionary_id
            self.settings.set_value("user_dict/current_dictionary_id", self.current_dictionary_id)
            self.current_page = 1
            self.load_items()

    def on_filter_changed(self):
        self.current_page = 1
        self.settings.set_value("user_dict/filter_kind", self.kind_combo.currentText())
        self.settings.set_value("user_dict/hide_noise", self.hide_noise_checkbox.isChecked())
        self.load_items()

    def on_items_selection_changed(self):
        count = len(self.items_table.selectionModel().selectedRows())
        self.remove_selected_btn.setEnabled(count > 0)
        self.translate_selected_btn.setEnabled(count > 0)

    def on_context_menu(self, pos):
        selected_rows = self.items_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        count = len(selected_rows)
        menu = QMenu(self)

        translate_action = QAction(f"Translate Selected ({count} rows)...", self)
        translate_action.triggered.connect(self.on_translate_selected)
        menu.addAction(translate_action)
        menu.addSeparator()

        mark_noise_action = QAction(f"Mark Selected as Noise ({count} rows)", self)
        mark_noise_action.triggered.connect(lambda: self.set_selected_noise_status(True))
        menu.addAction(mark_noise_action)

        mark_valid_action = QAction(f"Mark Selected as Valid ({count} rows)", self)
        mark_valid_action.triggered.connect(lambda: self.set_selected_noise_status(False))
        menu.addAction(mark_valid_action)

        menu.exec(self.items_table.viewport().mapToGlobal(pos))

    def on_translation_edited(self, top_left, bottom_right, roles):
        if top_left.column() != 2:
            return
        if roles and Qt.ItemDataRole.EditRole not in roles:
            return

        item = self.items_model.get_item(top_left.row())
        if not item:
            return

        try:
            with self.db_service.get_session() as session:
                self.user_dict_service.update_item_translation(
                    session=session,
                    item_id=item.item_id,
                    translation=item.translation or "",
                )
                session.commit()
            self.load_items()
        except Exception as e:
            logger.error("Failed to update user dictionary translation: %s", e, exc_info=True)
            QMessageBox.warning(self, "Save Error", f"Failed to save translation:\n{e}")
            self.load_items()

    def set_selected_noise_status(self, is_noise: bool):
        item_ids = self._selected_item_ids()
        if not item_ids:
            return

        count = len(item_ids)
        status_text = "noise" if is_noise else "valid"
        if count > 100:
            reply = QMessageBox.question(
                self,
                "Confirm Bulk Action",
                f"You are about to mark {count:,} rows as {status_text}.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            with self.db_service.get_session() as session:
                changed = self.user_dict_service.set_items_noise_status_bulk(
                    session=session,
                    item_ids=item_ids,
                    is_noise=is_noise,
                    noise_reason="NOISE_USER_MARKED" if is_noise else None,
                )
                session.commit()
            QMessageBox.information(self, "Success", f"Updated {changed:,} rows.")
            self.load_items()
        except Exception as e:
            logger.error("Failed to set user dictionary noise status: %s", e, exc_info=True)
            QMessageBox.warning(self, "Update Failed", f"Failed to update noise status:\n{e}")

    def on_new_dictionary(self):
        name, ok = QInputDialog.getText(self, "New Dictionary", "Dictionary name:")
        if not ok or not (name or "").strip():
            return

        try:
            with self.db_service.get_session() as session:
                dto = self.user_dict_service.create_dictionary(session, name=name.strip())
                session.commit()
            self.current_dictionary_id = dto.dictionary_id
            self.load_dictionaries()
        except Exception as e:
            QMessageBox.warning(self, "Create Failed", str(e))

    def on_rename_dictionary(self):
        if not self.current_dictionary_id:
            return

        current = next((d for d in self.dictionary_model.dictionaries if d.dictionary_id == self.current_dictionary_id), None)
        old_name = current.name if current else ""
        new_name, ok = QInputDialog.getText(self, "Rename Dictionary", "New name:", text=old_name)
        if not ok or not (new_name or "").strip():
            return

        try:
            with self.db_service.get_session() as session:
                self.user_dict_service.rename_dictionary(session, self.current_dictionary_id, new_name.strip())
                session.commit()
            self.load_dictionaries()
        except Exception as e:
            QMessageBox.warning(self, "Rename Failed", str(e))

    def on_delete_dictionary(self):
        if not self.current_dictionary_id:
            return

        reply = QMessageBox.question(
            self,
            "Delete Dictionary",
            "Delete selected dictionary and all its items?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with self.db_service.get_session() as session:
                self.user_dict_service.delete_dictionary(session, self.current_dictionary_id)
                session.commit()
            self.current_dictionary_id = None
            self.load_dictionaries()
        except Exception as e:
            QMessageBox.warning(self, "Delete Failed", str(e))

    def on_add_manual(self):
        if not self.current_dictionary_id:
            QMessageBox.information(self, "Dictionary Required", "Create or select a dictionary first.")
            return

        dialog = ManualUserDictionaryItemDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        payload = dialog.payload()
        if self.project_id is not None and self.scope_mode == "current_project":
            payload["origin_project_id"] = self.project_id
        try:
            with self.db_service.get_session() as session:
                self.user_dict_service.bulk_add_items(
                    session,
                    dictionary_id=self.current_dictionary_id,
                    items=[payload],
                    include_noise=True,
                    skip_duplicates=True,
                    chunk_size=1,
                )
                session.commit()
            self.load_dictionaries()
            self.load_items()
        except Exception as e:
            QMessageBox.warning(self, "Add Failed", str(e))

    def _selected_item_ids(self) -> List[int]:
        selected_rows = self.items_table.selectionModel().selectedRows()
        ids = []
        for idx in selected_rows:
            item = self.items_model.get_item(idx.row())
            if item:
                ids.append(item.item_id)
        return sorted(set(ids))

    def on_remove_selected(self):
        item_ids = self._selected_item_ids()
        if not item_ids:
            return

        reply = QMessageBox.question(
            self,
            "Remove Items",
            f"Remove {len(item_ids)} selected items from dictionary?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog("Removing selected items...", "Cancel", 0, len(item_ids), self)
        progress.setWindowTitle("User Dictionaries")
        progress.setModal(True)
        progress.setMinimumDuration(0)
        progress.show()

        worker = UserDictionaryBulkRemoveWorker(item_ids=item_ids, chunk_size=500)
        self._bulk_worker = worker
        worker.progress.connect(lambda done, total: progress.setValue(done))
        worker.finished.connect(lambda result: self._on_remove_finished(result, progress))
        worker.error.connect(lambda msg: self._on_remove_error(msg, progress))
        progress.canceled.connect(worker.cancel)
        worker.start()

    def _on_remove_finished(self, result, progress_dialog):
        progress_dialog.close()
        QMessageBox.information(
            self,
            "Remove Complete",
            f"Removed: {result.get('removed', 0)}\n"
            f"Processed: {result.get('processed', 0)} / {result.get('total', 0)}",
        )
        self._bulk_worker = None
        self.load_dictionaries()
        self.load_items()

    def _on_remove_error(self, error_msg: str, progress_dialog):
        progress_dialog.close()
        QMessageBox.warning(self, "Remove Failed", error_msg)
        self._bulk_worker = None

    def on_translate_selected(self):
        if not self.current_dictionary_id:
            return

        selected_ids = self._selected_item_ids()
        if not selected_ids:
            return

        filtered_count = 0
        with self.db_service.get_session() as session:
            filtered_count = self.user_dict_service.count_item_ids_for_translation(
                session=session,
                dictionary_id=self.current_dictionary_id,
                filters=self.build_filters(),
                write_mode="FILL_EMPTY",
            )

        accepted, provider_mode, write_mode, scope = show_batch_translate_dialog(
            parent=self,
            selected_count=len(selected_ids),
            scope_enabled=True,
            filtered_count=filtered_count,
        )
        if not accepted:
            return

        if scope == "all_filtered" and write_mode == "OVERWRITE" and filtered_count > 100:
            reply = QMessageBox.question(
                self,
                "Confirm Overwrite",
                f"This will overwrite {filtered_count} existing translations.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if scope == "all_filtered":
            with self.db_service.get_session() as session:
                total = self.user_dict_service.count_item_ids_for_translation(
                    session=session,
                    dictionary_id=self.current_dictionary_id,
                    filters=self.build_filters(),
                    write_mode=write_mode,
                )
        else:
            total = len(selected_ids)

        progress_dialog = BatchProgressDialogV3(parent=self, total=total)
        progress_dialog.show()

        worker = UserDictTranslateWorker(
            dictionary_id=self.current_dictionary_id,
            scope=scope,
            selected_item_ids=selected_ids,
            filters=self.build_filters(),
            provider_mode=provider_mode,
            write_mode=write_mode,
            id_fetch_chunk=200,
            translation_chunk=25,
        )
        self._translate_worker = worker

        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda result: self._on_translate_finished(result, progress_dialog))
        worker.error.connect(lambda err: self._on_translate_error(err, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.translate_selected_btn.setEnabled(False)
        worker.finished.connect(self.on_items_selection_changed)
        worker.error.connect(self.on_items_selection_changed)
        worker.start()

    def _on_translate_finished(self, result, progress_dialog):
        progress_dialog.set_completed()
        progress_dialog.update_counts(result.succeeded, result.skipped, result.failed)
        progress_dialog.accept()

        msg = (
            "Translation completed.\n\n"
            f"Total: {result.total}\n"
            f"Succeeded: {result.succeeded}\n"
            f"Skipped: {result.skipped}\n"
            f"Failed: {result.failed}"
        )
        if result.failed > 0:
            QMessageBox.warning(self, "Translation Complete (with errors)", msg)
        else:
            QMessageBox.information(self, "Translation Complete", msg)

        self._translate_worker = None
        self.load_items()

    def _on_translate_error(self, error_msg: str, progress_dialog):
        progress_dialog.reject()
        QMessageBox.warning(self, "Translation Failed", error_msg)
        self._translate_worker = None
        self.on_items_selection_changed()

    def on_items_header_clicked(self, logical_index: int):
        sort_col = self.COLUMN_TO_SORT.get(logical_index)
        if not sort_col:
            return

        if self.sort_column == sort_col:
            self.sort_direction = "desc" if self.sort_direction == "asc" else "asc"
        else:
            self.sort_column = sort_col
            self.sort_direction = "asc"

        self.settings.set_value("user_dict/sort_column", self.sort_column)
        self.settings.set_value("user_dict/sort_direction", self.sort_direction)
        self.current_page = 1
        self.load_items()

    def on_first_page(self):
        if self.current_page != 1:
            self.current_page = 1
            self.load_items()

    def on_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_items()

    def on_next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.load_items()

    def on_last_page(self):
        if self.current_page != self.total_pages:
            self.current_page = self.total_pages
            self.load_items()

    def on_page_changed(self, text: str):
        text = (text or "").strip()
        if not text.isdigit():
            return

        page = int(text)
        if 1 <= page <= self.total_pages and page != self.current_page:
            self.current_page = page
            self.load_items()

    def on_page_size_changed(self, size_text: str):
        if not size_text.isdigit():
            return

        size = int(size_text)
        if size != self.page_size:
            self.page_size = size
            self.settings.set_value("user_dict/page_size", self.page_size)
            self.current_page = 1
            self.load_items()

    def update_pagination_controls(self):
        total_pages = self.total_pages
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for i in range(1, total_pages + 1):
            self.page_combo.addItem(str(i))
        if self.current_page > total_pages:
            self.current_page = total_pages
        self.page_combo.setCurrentText(str(self.current_page))
        self.page_combo.blockSignals(False)

        self.page_count_label.setText(f"of {total_pages}")
        self.first_btn.setEnabled(self.current_page > 1)
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < total_pages)
        self.last_btn.setEnabled(self.current_page < total_pages)

        if self.total_count == 0:
            self.range_label.setText("Showing 0-0 of 0")
        else:
            start = self.current_offset + 1
            end = min(self.current_offset + self.page_size, self.total_count)
            self.range_label.setText(f"Showing {start}-{end} of {self.total_count}")

    def open_add_to_dictionary_dialog_for_payloads(self, payloads: List[Dict[str, object]]):
        """Utility entrypoint used by other views to add prepared payloads."""
        if not payloads:
            return

        accepted, dictionary_id, options = show_add_to_user_dictionary_dialog(
            parent=self,
            selected_count=len(payloads),
            default_dictionary_id=self.current_dictionary_id,
        )
        if not accepted or not dictionary_id:
            return

        tags = options.get("tags", [])
        preserve_origin = bool(options.get("preserve_origin_refs", True))
        prepared = []
        for item in payloads:
            row = dict(item)
            if tags:
                row["tags_json"] = tags
            if not preserve_origin:
                row["origin_project_id"] = None
                row["origin_entity_type"] = None
                row["origin_entity_id"] = None
                row["origin_tm_entry_id"] = None
                row["origin_doc_id"] = None
                row["origin_source_ref"] = None
            prepared.append(row)

        progress = QProgressDialog("Adding items to dictionary...", "Cancel", 0, len(prepared), self)
        progress.setWindowTitle("User Dictionaries")
        progress.setModal(True)
        progress.setMinimumDuration(0)
        progress.show()

        worker = UserDictionaryBulkAddWorker(
            dictionary_id=dictionary_id,
            items=prepared,
            include_noise=bool(options.get("include_noise", False)),
            skip_duplicates=bool(options.get("skip_duplicates", True)),
            chunk_size=500,
        )
        self._bulk_worker = worker
        worker.progress.connect(lambda done, total: progress.setValue(done))
        worker.finished.connect(lambda result: self._on_add_finished(result, progress, dictionary_id))
        worker.error.connect(lambda err: self._on_add_error(err, progress))
        progress.canceled.connect(worker.cancel)
        worker.start()

    def _on_add_finished(self, result, progress_dialog, dictionary_id: int):
        progress_dialog.close()
        QMessageBox.information(
            self,
            "Add Complete",
            f"Added: {result.get('added', 0)}\n"
            f"Skipped: {result.get('skipped', 0)}\n"
            f"Failed: {result.get('failed', 0)}",
        )
        self.current_dictionary_id = dictionary_id
        self._bulk_worker = None
        self.load_dictionaries()
        self.load_items()

    def _on_add_error(self, error_msg: str, progress_dialog):
        progress_dialog.close()
        QMessageBox.warning(self, "Add Failed", error_msg)
        self._bulk_worker = None
