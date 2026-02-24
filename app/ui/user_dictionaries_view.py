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
    QStackedWidget,
    QSplitter,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.normalization.normalizer import normalize_for_tm
from app.infra.settings import SettingsService
from app.services.audio_asset_service import AudioAssetService
from app.services.db_service import DBService
from app.services.audio_playback_service import AudioPlaybackService
from app.services.study_service import StudyService
from app.services.user_dictionary_service import UserDictionaryService
from app.ui.dialogs.add_to_user_dictionary_dialog import show_add_to_user_dictionary_dialog
from app.ui.dialogs.batch_audio_dialog import show_batch_audio_dialog
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
from app.ui.dialogs.batch_translate_dialog import show_batch_translate_dialog
from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog
from app.ui.audio_playlist_actions import add_selected_items_to_playlist_dialog
from app.ui.delegates.audio_play_delegate import AudioPlayDelegate
from app.ui.models_qt import UserDictionaryItemsTableModel, UserDictionaryListModel
from app.ui.table_layout_controller import TableLayoutController
from app.ui.workers import (
    UserDictionaryBulkAddWorker,
    UserDictionaryBulkRemoveWorker,
    UserDictGenerateAudioWorker,
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
        self.audio_playback_service = AudioPlaybackService()
        self.study_service = StudyService()
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
        self._audio_worker = None
        self._review_cards = []
        self._review_index = -1
        self._view_mode = "browse"

        self.dictionary_model = UserDictionaryListModel()
        self.items_model = UserDictionaryItemsTableModel()
        self.COLUMN_TO_SORT = {
            0: "kind",
            1: "src_text",
            2: "translation",
            3: "translation_status",
            4: "is_noise",
            5: "study_state",
            6: "last_grade",
            7: "origin_project_id",
            8: "origin_project_name",
            10: "pronunciation",
        }
        self._visible_columns_key = "user_dict/columns_visible"
        self._column_actions: List[QAction] = []

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

        self.dictionary_summary_label = QLabel("Words: 0 | Added: 0 | Again: 0 | Hard: 0 | Good: 0 | Easy: 0")
        self.dictionary_summary_label.setStyleSheet("color: #444; font-size: 11px;")
        layout.addWidget(self.dictionary_summary_label)

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

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self.mode_browse_btn = QPushButton("Browse")
        self.mode_browse_btn.setCheckable(True)
        self.mode_browse_btn.clicked.connect(lambda: self.on_mode_changed("browse"))
        mode_layout.addWidget(self.mode_browse_btn)
        self.mode_review_btn = QPushButton("Review")
        self.mode_review_btn.setCheckable(True)
        self.mode_review_btn.clicked.connect(lambda: self.on_mode_changed("review"))
        mode_layout.addWidget(self.mode_review_btn)
        self.review_refresh_btn = QPushButton("Refresh Due Queue")
        self.review_refresh_btn.clicked.connect(lambda: self.load_review_queue(reset_index=True))
        mode_layout.addWidget(self.review_refresh_btn)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

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

        self.dictionary_table_layout_controller = TableLayoutController(
            settings=self.settings,
            table_id="user_dict_dictionary_list",
            table=self.dictionary_table,
            default_widths={0: 220, 1: 80},
        )
        self.dictionary_table_layout_controller.install()

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

        self.columns_btn = QToolButton()
        self.columns_btn.setText("⚙")
        self.columns_btn.setToolTip("Select visible columns")
        filters_row.addWidget(self.columns_btn)

        right_layout.addLayout(filters_row)

        self.items_table = QTableView()
        self.items_table.setModel(self.items_model)
        self.items_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.items_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.items_table.setAlternatingRowColors(True)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.horizontalHeader().setSectionsClickable(True)
        self.audio_play_delegate = AudioPlayDelegate(
            self.items_table,
            on_play_clicked=self.on_audio_cell_play_clicked,
        )
        self.items_table.setItemDelegateForColumn(11, self.audio_play_delegate)
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
            default_widths={
                0: 110,
                1: 220,
                2: 220,
                3: 110,
                4: 85,
                5: 110,
                6: 120,
                7: 90,
                8: 180,
                9: 110,
                10: 180,
                11: 90,
            },
        )
        self.table_layout_controller.install()
        self._init_column_visibility_menu()

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
        self.generate_audio_btn = QPushButton("Generate Audio...")
        self.generate_audio_btn.clicked.connect(self.on_generate_audio_selected)
        self.generate_audio_btn.setEnabled(False)
        actions_row.addWidget(self.generate_audio_btn)
        self.play_audio_btn = QPushButton("Play Audio")
        self.play_audio_btn.clicked.connect(self.on_play_audio_selected)
        self.play_audio_btn.setEnabled(False)
        actions_row.addWidget(self.play_audio_btn)
        self.pronunciation_bootstrap_btn = QPushButton("Pronunciation Bootstrap...")
        self.pronunciation_bootstrap_btn.clicked.connect(self.on_pronunciation_bootstrap_selected)
        self.pronunciation_bootstrap_btn.setEnabled(False)
        actions_row.addWidget(self.pronunciation_bootstrap_btn)
        self.mark_due_btn = QPushButton("Mark Due Now")
        self.mark_due_btn.clicked.connect(self.set_selected_due_now)
        self.mark_due_btn.setEnabled(False)
        actions_row.addWidget(self.mark_due_btn)
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

        review_page = QWidget()
        review_layout = QVBoxLayout(review_page)
        self.review_scope_label = QLabel("")
        self.review_scope_label.setStyleSheet("color: #666; font-size: 11px;")
        review_layout.addWidget(self.review_scope_label)
        self.review_queue_label = QLabel("Due queue: 0")
        review_layout.addWidget(self.review_queue_label)
        self.review_source_label = QLabel("Source: -")
        self.review_source_label.setWordWrap(True)
        review_layout.addWidget(self.review_source_label)
        self.review_translation_label = QLabel("Current translation: -")
        self.review_translation_label.setWordWrap(True)
        review_layout.addWidget(self.review_translation_label)

        review_edit_row = QHBoxLayout()
        review_edit_row.addWidget(QLabel("Edit translation:"))
        self.review_translation_edit = QLineEdit()
        self.review_translation_edit.setPlaceholderText("Type translation and press Save")
        review_edit_row.addWidget(self.review_translation_edit, 1)
        self.review_save_translation_btn = QPushButton("Save Translation")
        self.review_save_translation_btn.clicked.connect(self.on_review_save_translation)
        review_edit_row.addWidget(self.review_save_translation_btn)
        self.review_play_audio_btn = QPushButton("Play Audio")
        self.review_play_audio_btn.clicked.connect(self.on_review_play_audio)
        review_edit_row.addWidget(self.review_play_audio_btn)
        review_layout.addLayout(review_edit_row)

        self.review_meta_label = QLabel("")
        self.review_meta_label.setWordWrap(True)
        review_layout.addWidget(self.review_meta_label)

        rating_row = QHBoxLayout()
        self.review_again_btn = QPushButton("Again")
        self.review_again_btn.clicked.connect(lambda: self.on_review_rate("again"))
        rating_row.addWidget(self.review_again_btn)
        self.review_hard_btn = QPushButton("Hard")
        self.review_hard_btn.clicked.connect(lambda: self.on_review_rate("hard"))
        rating_row.addWidget(self.review_hard_btn)
        self.review_good_btn = QPushButton("Good")
        self.review_good_btn.clicked.connect(lambda: self.on_review_rate("good"))
        rating_row.addWidget(self.review_good_btn)
        self.review_easy_btn = QPushButton("Easy")
        self.review_easy_btn.clicked.connect(lambda: self.on_review_rate("easy"))
        rating_row.addWidget(self.review_easy_btn)
        rating_row.addStretch()
        review_layout.addLayout(rating_row)

        self.review_status_label = QLabel("Ready")
        self.review_status_label.setStyleSheet("color: #666; font-size: 11px;")
        review_layout.addWidget(self.review_status_label)
        review_layout.addStretch()

        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(splitter)
        self.main_stack.addWidget(review_page)
        layout.addWidget(self.main_stack, 1)
        self.on_mode_changed("browse")
        self._apply_scope_mode(reset_page=False)

    def _init_column_visibility_menu(self) -> None:
        menu = QMenu(self.columns_btn)
        self.columns_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.columns_btn.setMenu(menu)
        self._column_actions.clear()

        for col_idx, header in enumerate(self.items_model.headers):
            action = QAction(header, self)
            action.setCheckable(True)
            action.setData(col_idx)
            action.toggled.connect(self._on_column_visibility_toggled)
            menu.addAction(action)
            self._column_actions.append(action)

        self._restore_column_visibility_state()

    def _restore_column_visibility_state(self) -> None:
        raw = self.settings.get_json(self._visible_columns_key, None)
        if not isinstance(raw, list) or len(raw) != len(self.items_model.headers):
            visible = [True] * len(self.items_model.headers)
        else:
            visible = [bool(v) for v in raw]
            if not any(visible):
                visible = [True] * len(self.items_model.headers)

        for action in self._column_actions:
            col_idx = int(action.data())
            action.blockSignals(True)
            action.setChecked(visible[col_idx])
            action.blockSignals(False)
            self.items_table.setColumnHidden(col_idx, not visible[col_idx])

        self._save_column_visibility_state()

    def _save_column_visibility_state(self) -> None:
        if not self._column_actions:
            return
        visible = [False] * len(self.items_model.headers)
        for action in self._column_actions:
            col_idx = int(action.data())
            visible[col_idx] = bool(action.isChecked())
        self.settings.set_json(self._visible_columns_key, visible)

    def _on_column_visibility_toggled(self, checked: bool) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        if not checked:
            checked_count = sum(1 for a in self._column_actions if a.isChecked())
            if checked_count <= 1:
                action.blockSignals(True)
                action.setChecked(True)
                action.blockSignals(False)
                return

        col_idx = int(action.data())
        self.items_table.setColumnHidden(col_idx, not bool(action.isChecked()))
        self._save_column_visibility_state()

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
        if self._view_mode == "review":
            self.load_review_queue(reset_index=True)

    def on_mode_changed(self, mode: str):
        """Switch between browse and review modes."""
        if mode not in ("browse", "review"):
            return
        self._view_mode = mode
        self.mode_browse_btn.blockSignals(True)
        self.mode_review_btn.blockSignals(True)
        self.mode_browse_btn.setChecked(mode == "browse")
        self.mode_review_btn.setChecked(mode == "review")
        self.mode_browse_btn.blockSignals(False)
        self.mode_review_btn.blockSignals(False)
        self.main_stack.setCurrentIndex(0 if mode == "browse" else 1)
        if mode == "review":
            self.load_review_queue(reset_index=True)

    def _set_review_controls_enabled(self, enabled: bool):
        self.review_save_translation_btn.setEnabled(enabled)
        self.review_play_audio_btn.setEnabled(enabled)
        self.review_again_btn.setEnabled(enabled)
        self.review_hard_btn.setEnabled(enabled)
        self.review_good_btn.setEnabled(enabled)
        self.review_easy_btn.setEnabled(enabled)

    def _current_review_card(self):
        if 0 <= self._review_index < len(self._review_cards):
            return self._review_cards[self._review_index]
        return None

    def _render_review_card(self):
        card = self._current_review_card()
        if not card:
            self.review_queue_label.setText("Due queue: 0")
            self.review_source_label.setText("Source: -")
            self.review_translation_label.setText("Current translation: -")
            self.review_translation_edit.setText("")
            self.review_meta_label.setText("No due items for current scope.")
            self.review_status_label.setText("Queue empty")
            self._set_review_controls_enabled(False)
            return

        self._set_review_controls_enabled(True)
        scope_text = (
            f"Current Project ({self.project_id})"
            if self.scope_mode == "current_project" and self.project_id is not None
            else "All projects"
        )
        self.review_scope_label.setText(f"Scope: {scope_text}")
        self.review_queue_label.setText(
            f"Due queue: {len(self._review_cards)} (card {self._review_index + 1}/{len(self._review_cards)})"
        )
        self.review_source_label.setText(f"Source: {card.src_text} ({card.kind})")
        self.review_translation_label.setText(f"Current translation: {(card.translation or '').strip() or '-'}")
        self.review_translation_edit.setText((card.translation or "").strip())
        self.review_meta_label.setText(
            f"Study: {card.study_state}, due: {card.due_human or 'n/a'}, "
            f"reviews={card.review_count}, lapses={card.lapse_count}, "
            f"interval={card.interval_days}d, EF={card.ease_factor:.2f}"
        )
        self.review_status_label.setText("Ready for rating")

    def load_review_queue(self, reset_index: bool = False):
        """Load due queue for review mode."""
        scope_origin_project_id = self.project_id if self.scope_mode == "current_project" and self.project_id else None
        try:
            with self.db_service.get_session() as session:
                cards = self.study_service.get_due_queue(
                    session=session,
                    dictionary_id=self.current_dictionary_id,
                    scope_origin_project_id=scope_origin_project_id,
                    limit=500,
                )
            self._review_cards = cards
            if reset_index or self._review_index < 0:
                self._review_index = 0
            if self._review_index >= len(self._review_cards):
                self._review_index = 0
            self._render_review_card()
        except Exception as e:
            logger.error("Failed to load due review queue: %s", e, exc_info=True)
            self.review_status_label.setText(f"Failed to load queue: {e}")
            self._review_cards = []
            self._review_index = -1
            self._render_review_card()

    def on_review_save_translation(self):
        """Persist translation edit for current review card via canonical write path."""
        card = self._current_review_card()
        if not card:
            return
        try:
            with self.db_service.get_session() as session:
                self.user_dict_service.update_item_translation(
                    session=session,
                    item_id=card.item_id,
                    translation=self.review_translation_edit.text(),
                )
                session.commit()
            card.translation = self.review_translation_edit.text().strip()
            self.review_translation_label.setText(f"Current translation: {card.translation or '-'}")
            self.review_status_label.setText("Translation saved")
            self.load_items()
        except Exception as e:
            logger.error("Failed to save review translation: %s", e, exc_info=True)
            QMessageBox.warning(self, "Save Error", f"Failed to save translation:\n{e}")

    def on_review_rate(self, rating: str):
        """Apply SM-2 rating and move to next due card."""
        card = self._current_review_card()
        if not card or not card.progress_id:
            return

        try:
            pending_translation = self.review_translation_edit.text().strip()
            if pending_translation != (card.translation or "").strip():
                with self.db_service.get_session() as session:
                    self.user_dict_service.update_item_translation(
                        session=session,
                        item_id=card.item_id,
                        translation=pending_translation,
                    )
                    session.commit()
                card.translation = pending_translation

            with self.db_service.get_session() as session:
                summary = self.study_service.apply_review(
                    session=session,
                    progress_id=card.progress_id,
                    rating=rating,
                )
                session.commit()
            self.review_status_label.setText(
                f"Rated '{rating}': next due {summary.due_human or 'n/a'}"
            )
            self.load_items()
            self.load_review_queue(reset_index=False)
        except Exception as e:
            logger.error("Failed to apply review rating: %s", e, exc_info=True)
            QMessageBox.warning(self, "Review Error", f"Failed to apply rating:\n{e}")

    def on_review_play_audio(self):
        """Play audio for current review card (if ready asset exists)."""
        card = self._current_review_card()
        if not card:
            return
        self._play_audio_items(
            [
                {
                    "src_lang": (card.src_lang or "").strip(),
                    "src_norm": (card.src_norm or "").strip(),
                    "src_text": (card.src_text or "").strip(),
                }
            ],
            play_mode="enqueue",
            start_immediately=True,
        )

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
                self._update_study_summary()
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

        by_lang: Dict[str, List[str]] = {}
        for item in items:
            by_lang.setdefault(item.src_lang, []).append(item.src_norm)

        status_map = {}
        for lang, norms in by_lang.items():
            mapping = self.audio_service.bulk_get_status_any(
                session,
                lang=lang,
                norm_texts=norms,
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
            self._update_study_summary()
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
            self._update_study_summary()
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
            if self._view_mode == "review":
                self.load_review_queue(reset_index=True)

    def on_filter_changed(self):
        self.current_page = 1
        self.settings.set_value("user_dict/filter_kind", self.kind_combo.currentText())
        self.settings.set_value("user_dict/hide_noise", self.hide_noise_checkbox.isChecked())
        self.load_items()
        if self._view_mode == "review":
            self.load_review_queue(reset_index=True)

    def on_items_selection_changed(self):
        count = len(self.items_table.selectionModel().selectedRows())
        self.remove_selected_btn.setEnabled(count > 0)
        self.translate_selected_btn.setEnabled(count > 0)
        self.generate_audio_btn.setEnabled(count > 0)
        self.play_audio_btn.setEnabled(count > 0)
        self.pronunciation_bootstrap_btn.setEnabled(count > 0)
        self.mark_due_btn.setEnabled(count > 0)

    def _update_study_summary(self):
        """Update top summary bar for the currently opened dictionary."""
        if not self.current_dictionary_id:
            self.dictionary_summary_label.setText(
                "Words: 0 | Added: 0 | Again: 0 | Hard: 0 | Good: 0 | Easy: 0"
            )
            return

        scope_origin_project_id = self.project_id if self.scope_mode == "current_project" and self.project_id else None
        try:
            with self.db_service.get_session() as session:
                counters = self.user_dict_service.get_dictionary_review_summary(
                    session=session,
                    dictionary_id=self.current_dictionary_id,
                    scope_origin_project_id=scope_origin_project_id,
                    hide_noise=self.hide_noise_checkbox.isChecked(),
                )
            self.dictionary_summary_label.setText(
                f"Words: {counters['words']:,} | "
                f"Added: {counters['added']:,} | "
                f"Again: {counters['again']:,} | "
                f"Hard: {counters['hard']:,} | "
                f"Good: {counters['good']:,} | "
                f"Easy: {counters['easy']:,}"
            )
        except Exception as e:
            logger.warning("Failed to load dictionary study summary: %s", e)
            self.dictionary_summary_label.setText("Words: n/a | Added: n/a | Again: n/a | Hard: n/a | Good: n/a | Easy: n/a")

    def on_context_menu(self, pos):
        selected_rows = self.items_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        count = len(selected_rows)
        menu = QMenu(self)

        translate_action = QAction(f"Translate Selected ({count} rows)...", self)
        translate_action.triggered.connect(self.on_translate_selected)
        menu.addAction(translate_action)
        generate_audio_action = QAction(f"Generate Audio Selected ({count} rows)...", self)
        generate_audio_action.triggered.connect(self.on_generate_audio_selected)
        menu.addAction(generate_audio_action)
        play_audio_action = QAction(f"Play Audio Selected ({count} rows)", self)
        play_audio_action.triggered.connect(self.on_play_audio_selected)
        menu.addAction(play_audio_action)
        add_playlist_action = QAction(f"Add Selected to Playlist ({count} rows)...", self)
        add_playlist_action.triggered.connect(self.on_add_selected_to_playlist)
        menu.addAction(add_playlist_action)
        edit_pron_action = QAction("Mispronounced -> Add Pronunciation...", self)
        edit_pron_action.triggered.connect(self.on_edit_pronunciation_selected)
        menu.addAction(edit_pron_action)
        bootstrap_pron_action = QAction(f"Pronunciation Bootstrap Selected ({count} rows)...", self)
        bootstrap_pron_action.triggered.connect(self.on_pronunciation_bootstrap_selected)
        menu.addAction(bootstrap_pron_action)
        menu.addSeparator()

        mark_noise_action = QAction(f"Mark Selected as Noise ({count} rows)", self)
        mark_noise_action.triggered.connect(lambda: self.set_selected_noise_status(True))
        menu.addAction(mark_noise_action)

        mark_valid_action = QAction(f"Mark Selected as Valid ({count} rows)", self)
        mark_valid_action.triggered.connect(lambda: self.set_selected_noise_status(False))
        menu.addAction(mark_valid_action)
        menu.addSeparator()

        mark_due_action = QAction(f"Mark Selected as Due now ({count} rows)", self)
        mark_due_action.triggered.connect(self.set_selected_due_now)
        menu.addAction(mark_due_action)

        suspend_action = QAction(f"Suspend Selected ({count} rows)", self)
        suspend_action.triggered.connect(lambda: self.set_selected_suspension(True))
        menu.addAction(suspend_action)

        resume_action = QAction(f"Resume Selected ({count} rows)", self)
        resume_action.triggered.connect(lambda: self.set_selected_suspension(False))
        menu.addAction(resume_action)

        menu.exec(self.items_table.viewport().mapToGlobal(pos))

    def on_edit_pronunciation_selected(self):
        """Edit pronunciation for the first selected item."""
        item_ids = self._selected_item_ids()
        if not item_ids:
            return
        item = self.items_model.get_item(0)
        selected_rows = self.items_table.selectionModel().selectedRows()
        if selected_rows:
            item = self.items_model.get_item(selected_rows[0].row())
        if not item:
            return
        src_norm = normalize_for_tm(item.src_lang, item.src_text, "surface").norm
        src_norm = (src_norm or "").strip() or (item.src_norm or "").strip()
        if not src_norm:
            return
        changed = show_edit_pronunciation_dialog(
            parent=self,
            src_lang=item.src_lang,
            src_norm=src_norm,
            src_text=item.src_text,
        )
        if changed:
            self.load_items()

    def _selected_pronunciation_items(self) -> List[Dict[str, str]]:
        """Build pronunciation payloads from selected user-dictionary rows."""
        selected_rows = self.items_table.selectionModel().selectedRows()
        payloads: List[Dict[str, str]] = []
        for index in sorted(selected_rows, key=lambda idx: idx.row()):
            item = self.items_model.get_item(index.row())
            if not item:
                continue
            src_norm = normalize_for_tm(item.src_lang, item.src_text, "surface").norm
            src_norm = (src_norm or "").strip() or (item.src_norm or "").strip()
            if not src_norm:
                continue
            if item.kind == "lemma":
                source_group = "lemmas"
            elif item.kind == "term_cluster":
                source_group = "terms"
            else:
                source_group = "user_dictionary"
            payloads.append(
                {
                    "src_lang": item.src_lang,
                    "src_text": item.src_text,
                    "src_norm": src_norm,
                    "raw_src_norm": src_norm,
                    "source_group": source_group,
                }
            )
        return payloads

    def on_pronunciation_bootstrap_selected(self):
        """Open pronunciation bootstrap dialog with selected rows scope."""
        from app.ui.dialogs.pronunciation_bootstrap_dialog import show_pronunciation_bootstrap_dialog

        selected_items = self._selected_pronunciation_items()
        changed = False
        if not selected_items:
            changed = show_pronunciation_bootstrap_dialog(parent=self)
        else:
            changed = show_pronunciation_bootstrap_dialog(parent=self, selected_items=selected_items)
        if changed:
            self.load_items()

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

    def set_selected_due_now(self):
        item_ids = self._selected_item_ids()
        if not item_ids:
            return

        if len(item_ids) > 100:
            reply = QMessageBox.question(
                self,
                "Confirm Bulk Action",
                f"You are about to mark {len(item_ids):,} rows as due now.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            with self.db_service.get_session() as session:
                changed = self.user_dict_service.set_items_due_now_bulk(
                    session=session,
                    item_ids=item_ids,
                )
                session.commit()
            QMessageBox.information(
                self,
                "Success",
                f"Marked {changed:,} rows as due now.\n"
                "Note: SRS progress is global by canonical key.",
            )
            self.load_items()
            if self._view_mode == "review":
                self.load_review_queue(reset_index=True)
        except Exception as e:
            logger.error("Failed to mark user dictionary rows due now: %s", e, exc_info=True)
            QMessageBox.warning(self, "Update Failed", f"Failed to mark due now:\n{e}")

    def set_selected_suspension(self, is_suspended: bool):
        item_ids = self._selected_item_ids()
        if not item_ids:
            return

        action_text = "suspend" if is_suspended else "resume"
        if len(item_ids) > 100:
            reply = QMessageBox.question(
                self,
                "Confirm Bulk Action",
                f"You are about to {action_text} {len(item_ids):,} rows.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            with self.db_service.get_session() as session:
                changed = self.user_dict_service.set_items_suspension_bulk(
                    session=session,
                    item_ids=item_ids,
                    is_suspended=is_suspended,
                    suspended_reason="USER_SUSPENDED" if is_suspended else None,
                )
                session.commit()
            QMessageBox.information(
                self,
                "Success",
                f"{'Suspended' if is_suspended else 'Resumed'} {changed:,} rows.",
            )
            self.load_items()
            if self._view_mode == "review":
                self.load_review_queue(reset_index=True)
        except Exception as e:
            logger.error("Failed to update user dictionary suspension flags: %s", e, exc_info=True)
            QMessageBox.warning(self, "Update Failed", f"Failed to update suspension:\n{e}")

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
            if self._view_mode == "review":
                self.load_review_queue(reset_index=True)
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

    def _selected_audio_items(self) -> List[Dict[str, str]]:
        selected_rows = self.items_table.selectionModel().selectedRows()
        items: List[Dict[str, str]] = []
        for idx in selected_rows:
            item = self.items_model.get_item(idx.row())
            if not item:
                continue
            src_lang = (item.src_lang or "").strip()
            src_norm = (item.src_norm or "").strip()
            src_text = (item.src_text or "").strip()
            if not src_lang or not src_norm:
                continue
            items.append(
                {
                    "src_lang": src_lang,
                    "src_norm": src_norm,
                    "src_text": src_text,
                    "kind": "term" if item.kind == "term_cluster" else item.kind,
                    "source_id": item.origin_entity_id,
                    "project_id": item.origin_project_id,
                    "source_label": "User Dictionaries",
                    "translation": item.translation or "",
                    "pronunciation_text": getattr(item, "pronunciation_text", "") or "",
                }
            )
        return items

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
        if self._view_mode == "review":
            self.load_review_queue(reset_index=True)

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

    def on_generate_audio_selected(self):
        if not self.current_dictionary_id:
            return

        selected_ids = self._selected_item_ids()
        if not selected_ids:
            return

        with self.db_service.get_session() as session:
            filtered_count = self.user_dict_service.count_item_ids_for_translation(
                session=session,
                dictionary_id=self.current_dictionary_id,
                filters=self.build_filters(),
                write_mode="OVERWRITE",
            )

        accepted, provider_mode, write_mode, scope = show_batch_audio_dialog(
            parent=self,
            selected_count=len(selected_ids),
            scope_enabled=True,
            filtered_count=filtered_count,
        )
        if not accepted:
            return

        total = filtered_count if scope == "all_filtered" else len(selected_ids)
        progress_dialog = BatchProgressDialogV3(parent=self, total=total)
        progress_dialog.setWindowTitle("Batch Generate Source Audio")
        progress_dialog.show()

        worker = UserDictGenerateAudioWorker(
            dictionary_id=self.current_dictionary_id,
            scope=scope,
            selected_item_ids=selected_ids,
            filters=self.build_filters(),
            provider_mode=provider_mode,
            write_mode=write_mode,
            id_fetch_chunk=200,
            audio_chunk=25,
        )
        self._audio_worker = worker
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda result: self._on_generate_audio_finished(result, progress_dialog))
        worker.error.connect(lambda err: self._on_generate_audio_error(err, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.generate_audio_btn.setEnabled(False)
        worker.finished.connect(self.on_items_selection_changed)
        worker.error.connect(self.on_items_selection_changed)
        worker.start()

    def on_play_audio_selected(self):
        items = self._selected_audio_items()
        if not items:
            return
        self._play_audio_items(items, play_mode="enqueue", start_immediately=True)

    def on_add_selected_to_playlist(self):
        items = self._selected_audio_items()
        if not items:
            return
        add_selected_items_to_playlist_dialog(
            parent=self,
            items=items,
            db_manager=self.db_service,
        )

    def on_audio_cell_play_clicked(self, index):
        item = self.items_model.get_item(index.row())
        if not item:
            return
        self._play_audio_items(
            [
                {
                    "src_lang": (item.src_lang or "").strip(),
                    "src_norm": (item.src_norm or "").strip(),
                    "src_text": (item.src_text or "").strip(),
                    "kind": "term" if item.kind == "term_cluster" else item.kind,
                    "source_id": item.origin_entity_id,
                    "project_id": item.origin_project_id,
                    "source_label": "User Dictionaries",
                    "translation": item.translation or "",
                    "pronunciation_text": getattr(item, "pronunciation_text", "") or "",
                }
            ],
            play_mode="enqueue",
        )

    def _play_audio_items(self, items: List[Dict[str, str]], *, play_mode: str, start_immediately: bool = False):
        try:
            with self.db_service.get_session() as session:
                ready_items = self.audio_playback_service.resolve_ready_paths(session, items=items)

            if not ready_items:
                QMessageBox.information(
                    self,
                    "Audio Missing",
                    "No ready audio found for selected rows.\nUse 'Generate Audio...' first.",
                )
                return

            paths = [row[0] for row in ready_items]
            labels = [str((row[1] or {}).get("src_text") or row[0].stem) for row in ready_items]
            contexts = []
            for _, item in ready_items:
                payload = item or {}
                contexts.append(
                    {
                        "snapshot_hebrew": str(payload.get("src_text") or ""),
                        "snapshot_niqqud": str(
                            payload.get("pronunciation_text")
                            or payload.get("snapshot_niqqud")
                            or payload.get("niqqud")
                            or ""
                        ),
                        "snapshot_translation": str(
                            payload.get("translation")
                            or payload.get("snapshot_translation")
                            or ""
                        ),
                        "snapshot_source_label": str(
                            payload.get("source_label")
                            or payload.get("snapshot_source_label")
                            or "User Dictionaries"
                        ),
                        "kind": payload.get("kind"),
                        "source_id": payload.get("source_id"),
                        "project_id": payload.get("project_id"),
                    }
                )
            self.audio_playback_service.launch_audio_files(
                paths,
                labels=labels,
                play_mode=play_mode,
                contexts=contexts,
                start_immediately=start_immediately,
            )
        except Exception as e:
            logger.error("Failed to play audio in User Dictionaries: %s", e, exc_info=True)
            QMessageBox.warning(self, "Playback Error", f"Failed to play audio:\n{e}")

    def _on_generate_audio_finished(self, result: Dict[str, int], progress_dialog):
        progress_dialog.set_completed()
        progress_dialog.update_counts(
            int(result.get("succeeded", 0)),
            int(result.get("skipped", 0)),
            int(result.get("failed", 0)),
        )
        progress_dialog.accept()

        msg = (
            "Audio generation completed.\n\n"
            f"Total: {int(result.get('total', 0))}\n"
            f"Ready: {int(result.get('succeeded', 0))}\n"
            f"Skipped: {int(result.get('skipped', 0))}\n"
            f"Failed: {int(result.get('failed', 0))}"
        )
        if int(result.get("failed", 0)) > 0:
            QMessageBox.warning(self, "Audio Generation Complete (with errors)", msg)
        else:
            QMessageBox.information(self, "Audio Generation Complete", msg)

        self._audio_worker = None
        self.load_items()

    def _on_generate_audio_error(self, error_msg: str, progress_dialog):
        progress_dialog.reject()
        QMessageBox.warning(self, "Audio Generation Failed", error_msg)
        self._audio_worker = None
        self.on_items_selection_changed()

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
        if self._view_mode == "review":
            self.load_review_queue(reset_index=True)

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
        if self._view_mode == "review":
            self.load_review_queue(reset_index=True)

    def _on_add_error(self, error_msg: str, progress_dialog):
        progress_dialog.close()
        QMessageBox.warning(self, "Add Failed", error_msg)
        self._bulk_worker = None

    def closeEvent(self, event):
        """Graceful worker shutdown on panel close."""
        for worker in (self._bulk_worker, self._translate_worker, self._audio_worker):
            try:
                if worker and worker.isRunning():
                    if hasattr(worker, "cancel"):
                        worker.cancel()
                    worker.wait(2000)
            except Exception:
                pass
        self.dictionary_table_layout_controller.save_now()
        self.table_layout_controller.save_now()
        super().closeEvent(event)
