"""Sentences workspace view — sentence-level training tab.

Provides:
- Paginated table of DocumentSentence rows with overlays (translation/niqqud/audio).
- Batch actions: Translate Selected, Generate Audio, Pronunciation Bootstrap, Play Audio.
- All long-ops via QThread workers + BatchProgressDialogV3 + cancel/pause.
- Persistent filter/sort/pagination state via SettingsService.
- No UI freeze: all DB reads happen in workers; main thread only updates model.
"""
import logging
from typing import List, Optional, Dict, Any

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QSizePolicy,
    QAbstractItemView,
    QMenu,
    QInputDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QAction

from app.services.db_service import DBService
from app.services.sentences_workspace_service import SentencesWorkspaceService
from app.services.audio_playback_service import AudioPlaybackService
from app.ui.audio_playlist_actions import add_selected_items_to_playlist_dialog
from app.ui.delegates.audio_play_delegate import AudioPlayDelegate
from app.infra.settings import SettingsService
from app.domain.dto import SentenceDTO
from app.ui.dialogs import show_error, show_info, show_warning

logger = logging.getLogger(__name__)

# Column indices (8 columns — QC column added in Task 24)
COL_ID = 0
COL_DOC = 1
COL_IDX = 2
COL_TEXT = 3
COL_TRANSLATION = 4
COL_NIQQUD = 5
COL_QC = 6
COL_AUDIO = 7


class _SentencesLoadWorker(QThread):
    """Background worker: load paginated sentences + count."""

    finished = pyqtSignal(list, int)   # (dtos, total_count)
    error = pyqtSignal(str)

    def __init__(self, project_id: int, page: int, page_size: int,
                 doc_filter: Optional[int], text_search: Optional[str]):
        super().__init__()
        self.project_id = project_id
        self.page = page
        self.page_size = page_size
        self.doc_filter = doc_filter
        self.text_search = text_search

    def run(self):
        try:
            from app.services.sentences_workspace_service import SentencesWorkspaceService
            from app.services.db_service import DBService
            db = DBService.get_instance()
            svc = SentencesWorkspaceService()
            with db.get_session() as session:
                dtos = svc.list_sentences(
                    session,
                    self.project_id,
                    doc_id_filter=self.doc_filter,
                    text_search=self.text_search,
                    page=self.page,
                    page_size=self.page_size,
                )
                total = svc.count_sentences(
                    session,
                    self.project_id,
                    doc_id_filter=self.doc_filter,
                    text_search=self.text_search,
                )
            self.finished.emit(dtos, total)
        except Exception as e:
            self.error.emit(str(e))


class SentencesView(QWidget):
    """Sentence-level workspace tab."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.db_service = DBService.get_instance()
        self.sentences_service = SentencesWorkspaceService()
        self.audio_playback_service = AudioPlaybackService()
        self.settings = SettingsService.get_instance()

        self.current_page = 1
        self.page_size = self.settings.get_int("sentences_view/page_size", 100)
        self.total_count = 0
        self._doc_filter: Optional[int] = None
        self._text_search: Optional[str] = None
        self._load_worker: Optional[_SentencesLoadWorker] = None

        # Batch workers refs (to prevent GC)
        self._batch_translate_worker = None
        self._batch_audio_worker = None

        # Debounce timer for search
        self._filter_timer = QTimer()
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(400)
        self._filter_timer.timeout.connect(self._reload)

        # Current DTOs for selection lookup
        self._current_dtos: List[SentenceDTO] = []

        self._init_ui()
        self._load_doc_list()
        self._reload()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout()

        # --- Header row ---
        header = QHBoxLayout()
        title = QLabel("Sentences")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._reload)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        # --- Filter row ---
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Document:"))
        self.doc_combo = QComboBox()
        self.doc_combo.setMinimumWidth(200)
        self.doc_combo.addItem("All Documents", None)
        self.doc_combo.currentIndexChanged.connect(self._on_doc_filter_changed)
        filter_row.addWidget(self.doc_combo)

        filter_row.addWidget(QLabel("Search:"))
        self.text_search_edit = QLineEdit()
        self.text_search_edit.setPlaceholderText("Filter by sentence text...")
        self.text_search_edit.setMaximumWidth(280)
        self.text_search_edit.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.text_search_edit)

        clear_btn = QPushButton("Clear")
        clear_btn.setMaximumWidth(60)
        clear_btn.clicked.connect(self._on_clear_filters)
        filter_row.addWidget(clear_btn)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # --- Action row ---
        action_row = QHBoxLayout()

        self.translate_btn = QPushButton("Translate Selected...")
        self.translate_btn.setEnabled(False)
        self.translate_btn.clicked.connect(self.on_batch_translate)
        action_row.addWidget(self.translate_btn)

        self.audio_btn = QPushButton("Generate Audio...")
        self.audio_btn.setEnabled(False)
        self.audio_btn.clicked.connect(self.on_generate_audio)
        action_row.addWidget(self.audio_btn)

        self.bootstrap_btn = QPushButton("Pronunciation Bootstrap...")
        self.bootstrap_btn.clicked.connect(self.on_pronunciation_bootstrap)
        action_row.addWidget(self.bootstrap_btn)

        self.niqqud_btn = QPushButton("Niqqud Bootstrap…")
        self.niqqud_btn.setToolTip("Run sentence niqqud bootstrap (all filtered)")
        self.niqqud_btn.clicked.connect(self.on_niqqud_bootstrap_all)
        action_row.addWidget(self.niqqud_btn)

        self.niqqud_sel_btn = QPushButton("Niqqud Selected…")
        self.niqqud_sel_btn.setEnabled(False)
        self.niqqud_sel_btn.setToolTip("Run sentence niqqud bootstrap for selected rows")
        self.niqqud_sel_btn.clicked.connect(self.on_niqqud_bootstrap_selected)
        action_row.addWidget(self.niqqud_sel_btn)

        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self.on_play_audio)
        action_row.addWidget(self.play_btn)

        action_row.addStretch()
        layout.addLayout(action_row)

        # --- Table ---
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "ID", "Document", "#", "Sentence Text",
            "Translation", "Niqqud", "QC", "Audio"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(False)  # Server-side only
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Column widths
        self.table.setColumnWidth(COL_ID, 70)
        self.table.setColumnWidth(COL_DOC, 180)
        self.table.setColumnWidth(COL_IDX, 50)
        self.table.setColumnWidth(COL_TEXT, 400)
        self.table.setColumnWidth(COL_TRANSLATION, 280)
        self.table.setColumnWidth(COL_NIQQUD, 200)
        self.table.setColumnWidth(COL_QC, 55)
        self.table.setColumnWidth(COL_AUDIO, 90)

        # In-cell play button for Audio column (same pattern as Dictionary/TM/Terms)
        self.audio_play_delegate = AudioPlayDelegate(
            self.table, on_play_clicked=self.on_audio_cell_play_clicked
        )
        self.table.setItemDelegateForColumn(COL_AUDIO, self.audio_play_delegate)

        layout.addWidget(self.table)

        # --- Pagination row ---
        pag_row = QHBoxLayout()
        self.first_btn = QPushButton("«")
        self.first_btn.setMaximumWidth(35)
        self.first_btn.clicked.connect(self._on_first_page)
        pag_row.addWidget(self.first_btn)

        self.prev_btn = QPushButton("‹")
        self.prev_btn.setMaximumWidth(35)
        self.prev_btn.clicked.connect(self._on_prev_page)
        pag_row.addWidget(self.prev_btn)

        pag_row.addWidget(QLabel("Page"))
        self.page_spinbox = QSpinBox()
        self.page_spinbox.setMinimum(1)
        self.page_spinbox.setMaximum(9999)
        self.page_spinbox.setValue(1)
        self.page_spinbox.setMaximumWidth(65)
        self.page_spinbox.valueChanged.connect(self._on_page_spinbox_changed)
        pag_row.addWidget(self.page_spinbox)

        self.page_count_label = QLabel("of 1")
        pag_row.addWidget(self.page_count_label)

        self.next_btn = QPushButton("›")
        self.next_btn.setMaximumWidth(35)
        self.next_btn.clicked.connect(self._on_next_page)
        pag_row.addWidget(self.next_btn)

        self.last_btn = QPushButton("»")
        self.last_btn.setMaximumWidth(35)
        self.last_btn.clicked.connect(self._on_last_page)
        pag_row.addWidget(self.last_btn)

        pag_row.addSpacing(15)

        pag_row.addWidget(QLabel("Page size:"))
        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250"])
        self.page_size_combo.setCurrentText(str(self.page_size))
        self.page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        pag_row.addWidget(self.page_size_combo)

        pag_row.addStretch()

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        pag_row.addWidget(self.status_label)

        layout.addLayout(pag_row)
        self.setLayout(layout)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_doc_list(self):
        """Populate document filter combo from DB (short sync read)."""
        try:
            from sqlalchemy import select
            from app.infra.sa_models import SourceDocument, SourceCorpus
            with self.db_service.get_session() as session:
                stmt = (
                    select(SourceDocument.doc_id, SourceDocument.file_name)
                    .join(SourceCorpus, SourceDocument.corpus_id == SourceCorpus.corpus_id)
                    .where(SourceCorpus.project_id == self.project_id)
                    .order_by(SourceDocument.file_name.asc())
                )
                docs = session.execute(stmt).all()
            self.doc_combo.blockSignals(True)
            self.doc_combo.clear()
            self.doc_combo.addItem("All Documents", None)
            for doc_id, file_name in docs:
                self.doc_combo.addItem(file_name, doc_id)
            self.doc_combo.blockSignals(False)
        except Exception as e:
            logger.warning(f"Failed to load document list: {e}")

    def _reload(self):
        """Launch background load worker."""
        if self._load_worker and self._load_worker.isRunning():
            return  # Debounce: skip if already running

        self._text_search = self.text_search_edit.text().strip() or None
        self._doc_filter = self.doc_combo.currentData()

        self.status_label.setText("Loading...")
        self._load_worker = _SentencesLoadWorker(
            self.project_id,
            self.current_page,
            self.page_size,
            self._doc_filter,
            self._text_search,
        )
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_load_finished(self, dtos: List[SentenceDTO], total: int):
        """Populate table from loaded DTOs."""
        self._current_dtos = dtos
        self.total_count = total
        self._populate_table(dtos)
        self._update_pagination(total)
        self.status_label.setText(f"Showing {len(dtos)} of {total} sentences")

    def _on_load_error(self, msg: str):
        self.status_label.setText(f"Error: {msg}")
        logger.error(f"Sentences load error: {msg}")

    @staticmethod
    def _qc_badge_static(qc_status: Optional[str]):
        """Return (badge_text, QColor_or_None) for a QC status."""
        from PyQt6.QtGui import QColor
        _MAP = {
            "ok": ("✓", QColor("darkGreen")),
            "auto_fixed": ("~", QColor("olive")),
            "partial": ("~", QColor("darkorange")),
            "rejected": ("✗", QColor("red")),
            "failed": ("!", QColor("red")),
            "pending": ("…", QColor("gray")),
        }
        if not qc_status:
            return "—", None
        return _MAP.get(qc_status, (qc_status[:2], None))

    def _populate_table(self, dtos: List[SentenceDTO]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(dtos))

        def _ro(text=""):
            item = QTableWidgetItem(str(text))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item

        for row, dto in enumerate(dtos):
            self.table.setItem(row, COL_ID, _ro(dto.sentence_id))
            self.table.setItem(row, COL_DOC, _ro(dto.doc_name))
            self.table.setItem(row, COL_IDX, _ro(dto.sent_index))
            self.table.setItem(row, COL_TEXT, _ro(dto.text))
            self.table.setItem(row, COL_TRANSLATION, _ro(dto.translation or ""))

            # Niqqud column with tooltip
            niqqud_item = _ro(dto.pronunciation_text or "")
            if dto.pronunciation_text:
                cov_pct = f"{dto.niqqud_coverage * 100:.0f}%" if dto.niqqud_coverage is not None else "—"
                conf_str = f"{dto.niqqud_confidence:.2f}" if dto.niqqud_confidence is not None else "—"
                override_str = "manual override" if dto.niqqud_is_override else "auto"
                tooltip_lines = [
                    f"Source: {dto.niqqud_source or '—'}  ({override_str})",
                    f"Confidence: {conf_str}",
                    f"Coverage: {cov_pct}",
                    f"QC: {dto.niqqud_qc or '—'}",
                ]
                if dto.niqqud_qc in ("partial", "rejected") and dto.niqqud_coverage is not None:
                    pass  # qc_reason would be in overlay but not in DTO — tooltip shows coverage
                niqqud_item.setToolTip("\n".join(tooltip_lines))
            self.table.setItem(row, COL_NIQQUD, niqqud_item)

            # QC badge column
            qc_badge, qc_color = self._qc_badge_static(dto.niqqud_qc)
            qc_item = _ro(qc_badge)
            if qc_color:
                qc_item.setForeground(qc_color)
            if dto.niqqud_qc:
                qc_item.setToolTip(f"QC status: {dto.niqqud_qc}")
            self.table.setItem(row, COL_QC, qc_item)

            audio_text = dto.audio_status or "—"
            audio_item = _ro(audio_text)
            if dto.audio_status == "ready":
                audio_item.setForeground(Qt.GlobalColor.darkGreen)
            elif dto.audio_status == "failed":
                audio_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, COL_AUDIO, audio_item)

        self.table.setSortingEnabled(False)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _update_pagination(self, total: int):
        page_count = max(1, (total + self.page_size - 1) // self.page_size)
        self.page_count_label.setText(f"of {page_count}")
        self.page_spinbox.blockSignals(True)
        self.page_spinbox.setMaximum(page_count)
        self.page_spinbox.setValue(self.current_page)
        self.page_spinbox.blockSignals(False)
        self.first_btn.setEnabled(self.current_page > 1)
        self.prev_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < page_count)
        self.last_btn.setEnabled(self.current_page < page_count)

    def _on_first_page(self): self._go_to_page(1)
    def _on_prev_page(self): self._go_to_page(self.current_page - 1)
    def _on_next_page(self): self._go_to_page(self.current_page + 1)
    def _on_last_page(self):
        page_count = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self._go_to_page(page_count)

    def _on_page_spinbox_changed(self, value: int):
        if value != self.current_page:
            self._go_to_page(value)

    def _on_page_size_changed(self, text: str):
        try:
            self.page_size = int(text)
            self.settings.set_value("sentences_view/page_size", self.page_size)
        except ValueError:
            pass
        self._go_to_page(1)

    def _go_to_page(self, page: int):
        if page < 1:
            return
        self.current_page = page
        self._reload()

    def focus_sentence_by_id(self, sentence_id: int) -> bool:
        """Best-effort focus helper used by Audio Player 'Go to Source'."""
        for row, dto in enumerate(self._current_dtos):
            if int(getattr(dto, "sentence_id", 0) or 0) != int(sentence_id):
                continue
            self.table.setCurrentCell(row, COL_ID)
            self.table.selectRow(row)
            item = self.table.item(row, COL_ID)
            if item is not None:
                self.table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
            return True
        return False

    # ------------------------------------------------------------------
    # Filter handlers
    # ------------------------------------------------------------------

    def _on_filter_changed(self):
        self.current_page = 1
        self._filter_timer.start()

    def _on_doc_filter_changed(self):
        self.current_page = 1
        self._reload()

    def _on_clear_filters(self):
        self.text_search_edit.blockSignals(True)
        self.text_search_edit.clear()
        self.text_search_edit.blockSignals(False)
        self.doc_combo.setCurrentIndex(0)
        self.current_page = 1
        self._reload()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        has_sel = bool(self.table.selectedItems())
        self.translate_btn.setEnabled(has_sel)
        self.audio_btn.setEnabled(has_sel)
        self.play_btn.setEnabled(has_sel)
        self.niqqud_sel_btn.setEnabled(has_sel)

    def _get_selected_dtos(self) -> List[SentenceDTO]:
        rows = {item.row() for item in self.table.selectedItems()}
        return [self._current_dtos[r] for r in sorted(rows) if r < len(self._current_dtos)]

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        selected = self._get_selected_dtos()
        if not selected:
            return
        menu = QMenu(self)
        n = len(selected)

        tr_action = menu.addAction(f"Translate Selected ({n})...")
        tr_action.triggered.connect(self.on_batch_translate)

        edit_tr_action = menu.addAction("Edit Translation...")
        edit_tr_action.setEnabled(n == 1)
        edit_tr_action.triggered.connect(self.on_edit_translation_selected)

        clear_tr_action = menu.addAction(f"Clear Translation ({n})...")
        clear_tr_action.triggered.connect(self.on_clear_translation_selected)

        audio_action = menu.addAction(f"Generate Audio ({n})...")
        audio_action.triggered.connect(self.on_generate_audio)

        menu.addSeparator()

        play_action = menu.addAction(f"▶ Play Audio Selected ({n})")
        play_action.triggered.connect(self.on_play_audio)

        playlist_action = menu.addAction(f"Add Selected to Playlist ({n})...")
        playlist_action.triggered.connect(self.on_add_selected_to_playlist)

        bootstrap_action = menu.addAction(f"Pronunciation Bootstrap Selected ({n})...")
        bootstrap_action.triggered.connect(self.on_pronunciation_bootstrap)

        menu.addSeparator()

        niqqud_action = menu.addAction(f"Niqqud Selected ({n})…")
        niqqud_action.triggered.connect(self.on_niqqud_bootstrap_selected)

        edit_niqqud_action = menu.addAction("Edit Niqqud…")
        edit_niqqud_action.triggered.connect(self.on_edit_niqqud_selected)

        clear_niqqud_action = menu.addAction(f"Clear Niqqud ({n})…")
        clear_niqqud_action.triggered.connect(self.on_clear_niqqud_selected)

        menu.addSeparator()

        edit_pron_action = menu.addAction("Mispronounced -> Add Pronunciation...")
        edit_pron_action.triggered.connect(self.on_edit_pronunciation_selected)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Batch actions
    # ------------------------------------------------------------------

    def on_batch_translate(self):
        """Batch translate selected sentences via existing pipeline (kind='surface')."""
        selected = self._get_selected_dtos()
        if not selected:
            return

        from app.ui.dialogs import show_batch_translate_dialog
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import BatchTranslateWorker
        from app.services.batch_mt_translate_service import (
            BatchTranslateItem,
            BatchTranslateOptions,
        )

        accepted, provider_mode, write_mode, _scope = show_batch_translate_dialog(
            parent=self,
            selected_count=len(selected),
            scope_enabled=False,
        )
        if not accepted:
            return

        # Get project src/tgt lang
        try:
            from app.services.project_service import ProjectService
            with self.db_service.get_session() as session:
                proj = ProjectService().get_project(session, self.project_id)
                src_lang = proj.src_lang if proj else "he"
                tgt_lang = proj.tgt_lang if proj else "ru"
        except Exception:
            src_lang, tgt_lang = "he", "ru"

        items = [
            BatchTranslateItem(
                entity_type="surface",
                entity_id=str(dto.sentence_id),
                source_text=dto.text,
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                current_translation=dto.translation,
                project_id=self.project_id,
            )
            for dto in selected
        ]
        options = BatchTranslateOptions(
            provider_mode=provider_mode,
            write_mode=write_mode,
        )

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.show()

        worker = BatchTranslateWorker(items=items, options=options, tab_type="sentences")
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda _r: self._on_batch_done(progress_dialog, "Translation"))
        worker.error.connect(lambda e: self._on_batch_error(e, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.translate_btn.setEnabled(False)
        worker.finished.connect(lambda _: self.translate_btn.setEnabled(True))
        worker.error.connect(lambda _: self.translate_btn.setEnabled(True))
        worker.start()
        self._batch_translate_worker = worker

    def on_generate_audio(self):
        """Batch generate audio for selected sentences."""
        selected = self._get_selected_dtos()
        if not selected:
            return

        from app.ui.dialogs.batch_audio_dialog import show_batch_audio_dialog
        from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
        from app.ui.workers import BatchGenerateAudioWorker

        try:
            from app.services.project_service import ProjectService
            with self.db_service.get_session() as session:
                proj = ProjectService().get_project(session, self.project_id)
                src_lang = proj.src_lang if proj else "he"
        except Exception:
            src_lang = "he"

        accepted, provider_mode, write_mode, _scope = show_batch_audio_dialog(
            parent=self, selected_count=len(selected)
        )
        if not accepted:
            return

        # Build items for audio worker (src_text, src_lang, src_norm)
        from app.services.sentences_workspace_service import SentencesWorkspaceService
        svc = SentencesWorkspaceService()
        items = [
            {
                "src_text": dto.text,
                "src_lang": src_lang,
                "src_norm": svc._norm(src_lang, dto.text),
                "entity_id": str(dto.sentence_id),
            }
            for dto in selected
        ]

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.show()

        worker = BatchGenerateAudioWorker(
            items=items,
            provider_mode=provider_mode,
            write_mode=write_mode,
        )
        worker.progress.connect(progress_dialog.update_progress)
        worker.stats_updated.connect(progress_dialog.update_counts)
        worker.row_translated.connect(progress_dialog.add_recent_item)
        worker.stage_updated.connect(progress_dialog.set_stage)
        worker.finished.connect(lambda _r: self._on_batch_done(progress_dialog, "Audio generation"))
        worker.error.connect(lambda e: self._on_batch_error(e, progress_dialog))
        progress_dialog.cancel_requested.connect(worker.cancel)
        progress_dialog.pause_requested.connect(worker.pause)
        progress_dialog.resume_requested.connect(worker.resume)

        self.audio_btn.setEnabled(False)
        worker.finished.connect(lambda _: self.audio_btn.setEnabled(True))
        worker.error.connect(lambda _: self.audio_btn.setEnabled(True))
        worker.start()
        self._batch_audio_worker = worker

    def on_edit_translation_selected(self):
        """Edit translation for one selected sentence (manual TM surface write)."""
        selected = self._get_selected_dtos()
        if len(selected) != 1:
            return
        dto = selected[0]
        current = (dto.translation or "").strip()
        new_translation, ok = QInputDialog.getText(
            self,
            "Edit Translation",
            "Translation:",
            text=current,
        )
        if not ok:
            return
        value = (new_translation or "").strip()
        if value == current:
            return
        try:
            with self.db_service.get_session() as session:
                self._upsert_sentence_translation(session, dto=dto, translation=value)
                session.commit()
            self._reload()
        except Exception as e:
            logger.error("Failed to edit sentence translation: %s", e, exc_info=True)
            show_error(self, "Save Error", f"Failed to save translation:\n{e}")

    def on_clear_translation_selected(self):
        """Clear translation for selected sentence rows."""
        selected = self._get_selected_dtos()
        if not selected:
            return
        reply = QMessageBox.question(
            self,
            "Clear Translation",
            f"Clear translation for {len(selected)} selected sentence(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            with self.db_service.get_session() as session:
                for dto in selected:
                    self._upsert_sentence_translation(session, dto=dto, translation="")
                session.commit()
            self._reload()
            show_info(self, "Clear Translation", f"Cleared translation for {len(selected)} sentence(s).")
        except Exception as e:
            logger.error("Failed to clear sentence translation: %s", e, exc_info=True)
            show_error(self, "Save Error", f"Failed to clear translation:\n{e}")

    def _upsert_sentence_translation(self, session, *, dto: SentenceDTO, translation: str) -> None:
        """Upsert TM kind=surface for sentence row and propagate to tm_global."""
        from datetime import datetime

        from sqlalchemy import select

        from app.infra.db_retry import with_retry_on_locked
        from app.infra.sa_models import TMEntry
        from app.services.tm_global_service import TMGlobalService

        src_lang = self._get_src_lang()
        tgt_lang = self._get_tgt_lang()
        src_norm = SentencesWorkspaceService._norm(src_lang, dto.text)
        if not src_norm:
            raise ValueError("Cannot save translation: invalid source norm")

        stmt = select(TMEntry).where(
            TMEntry.project_id == self.project_id,
            TMEntry.kind == "surface",
            TMEntry.src_norm == src_norm,
        )
        existing = session.execute(stmt).scalar_one_or_none()

        value = (translation or "").strip()
        tm_entry = existing
        if existing:
            existing.translation = value
            existing.status = "approved"
            existing.origin = "user_edit"
            existing.source_ref = f"sentence:{dto.sentence_id}"
            existing.updated_at = datetime.now()
        else:
            tm_entry = TMEntry(
                project_id=self.project_id,
                kind="surface",
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                src_text=dto.text,
                src_norm=src_norm,
                translation=value,
                status="approved",
                origin="user_edit",
                source_ref=f"sentence:{dto.sentence_id}",
                is_noise=0,
            )
            session.add(tm_entry)

        def _flush_and_propagate() -> None:
            session.flush()
            TMGlobalService().upsert_and_link(
                session,
                tm_entry,
                force_global_update=(value == ""),
            )

        with_retry_on_locked(_flush_and_propagate, max_retries=3)

    def on_pronunciation_bootstrap(self):
        """Run pronunciation bootstrap for selected (or all) sentences."""
        from app.ui.dialogs.pronunciation_bootstrap_dialog import show_pronunciation_bootstrap_dialog
        selected = self._get_selected_dtos()
        if selected:
            src_lang = self._get_src_lang()
            items = [
                {
                    "src_text": dto.text,
                    "src_norm": SentencesWorkspaceService._norm(src_lang, dto.text),
                    "src_lang": src_lang,
                    "source_group": "sentences",
                }
                for dto in selected
            ]
            changed = show_pronunciation_bootstrap_dialog(parent=self, selected_items=items)
        else:
            changed = show_pronunciation_bootstrap_dialog(parent=self)
        if changed:
            self._reload()

    def on_edit_pronunciation_selected(self):
        """Open Edit Pronunciation dialog for the first selected sentence row (lexical bootstrap)."""
        from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog
        selected = self._get_selected_dtos()
        if not selected:
            return
        dto = selected[0]
        src_lang = self._get_src_lang()
        norm = SentencesWorkspaceService._norm(src_lang, dto.text)
        changed = show_edit_pronunciation_dialog(
            parent=self, src_lang=src_lang, src_norm=norm, src_text=dto.text
        )
        if changed:
            self._reload()

    # ------------------------------------------------------------------
    # Sentence niqqud actions (sentence_pronunciation table)
    # ------------------------------------------------------------------

    def on_niqqud_bootstrap_all(self):
        """Run sentence niqqud bootstrap for all filtered sentences."""
        src_lang = self._get_src_lang()
        try:
            all_ids = []
            with self.db_service.get_session() as session:
                all_ids = self.sentences_service.get_all_filtered_sentence_ids(
                    session, self.project_id,
                    doc_id_filter=self._doc_filter,
                    text_search=self._text_search,
                )
        except Exception as e:
            from app.ui.dialogs import show_error
            show_error(self, "Error", f"Failed to fetch sentence IDs: {e}")
            return

        page_ids = [dto.sentence_id for dto in self._current_dtos]
        selected_ids = [dto.sentence_id for dto in self._get_selected_dtos()]

        from app.ui.dialogs.sentence_niqqud_bootstrap_dialog import show_sentence_niqqud_bootstrap_dialog
        changed = show_sentence_niqqud_bootstrap_dialog(
            self,
            selected_ids=selected_ids,
            page_ids=page_ids,
            all_ids=all_ids,
            lang=src_lang,
        )
        if changed:
            self._reload()

    def on_niqqud_bootstrap_selected(self):
        """Run sentence niqqud bootstrap for selected rows only."""
        selected = self._get_selected_dtos()
        if not selected:
            return
        selected_ids = [dto.sentence_id for dto in selected]
        src_lang = self._get_src_lang()

        from app.ui.dialogs.sentence_niqqud_bootstrap_dialog import show_sentence_niqqud_bootstrap_dialog
        changed = show_sentence_niqqud_bootstrap_dialog(
            self,
            selected_ids=selected_ids,
            page_ids=[dto.sentence_id for dto in self._current_dtos],
            all_ids=selected_ids,  # constrain to selection in this path
            lang=src_lang,
        )
        if changed:
            self._reload()

    def on_edit_niqqud_selected(self):
        """Open manual niqqud edit dialog for the first selected sentence."""
        selected = self._get_selected_dtos()
        if not selected:
            return
        dto = selected[0]
        from app.ui.dialogs.edit_sentence_niqqud_dialog import show_edit_sentence_niqqud_dialog
        changed = show_edit_sentence_niqqud_dialog(
            self,
            sentence_id=dto.sentence_id,
            sentence_text=dto.text,
            current_niqqud=dto.pronunciation_text,
        )
        if changed:
            self._reload()

    def on_clear_niqqud_selected(self):
        """Clear sentence niqqud for selected rows (sets to pending)."""
        selected = self._get_selected_dtos()
        if not selected:
            return
        from PyQt6.QtWidgets import QMessageBox
        resp = QMessageBox.question(
            self,
            "Clear Niqqud",
            f"Clear niqqud for {len(selected)} selected sentence(s)?\n"
            "This resets to 'pending' and removes any stored niqqud text.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        try:
            from app.services.sentence_pronunciation_service import SentencePronunciationService
            svc = SentencePronunciationService()
            cleared = 0
            with self.db_service.get_session() as session:
                for dto in selected:
                    if svc.clear(session, sentence_id=dto.sentence_id):
                        cleared += 1
                session.commit()
            self._reload()
            from app.ui.dialogs import show_info
            show_info(self, "Clear Niqqud", f"Cleared niqqud for {cleared} sentence(s).")
        except Exception as e:
            from app.ui.dialogs import show_error
            show_error(self, "Error", f"Failed to clear niqqud: {e}")

    def on_play_audio(self):
        """Play audio for all selected sentences (enqueue mode)."""
        items = self._selected_audio_items()
        if not items:
            return
        self._play_audio_items(items, play_mode="enqueue", start_immediately=True)

    def on_add_selected_to_playlist(self):
        """Open shared playlist dialog and add selected sentence rows."""
        items = self._selected_audio_items()
        if not items:
            return
        add_selected_items_to_playlist_dialog(
            parent=self,
            items=items,
            db_manager=self.db_service,
        )

    def on_audio_cell_play_clicked(self, index):
        """Handle in-cell play button click (AudioPlayDelegate callback)."""
        row = index.row()
        if row < 0 or row >= len(self._current_dtos):
            return
        dto = self._current_dtos[row]
        src_lang = self._get_src_lang()
        norm = SentencesWorkspaceService._norm(src_lang, dto.text)
        self._play_audio_items(
            [
                {
                    "src_lang": src_lang,
                    "src_norm": norm,
                    "src_text": dto.text,
                    "kind": "sentence",
                    "source_id": int(dto.sentence_id),
                    "project_id": self.project_id,
                    "source_label": dto.doc_name or "Sentences",
                    "translation": dto.translation or "",
                    "pronunciation_text": dto.pronunciation_text or "",
                }
            ],
            play_mode="enqueue",
            start_immediately=True,
        )

    def _get_src_lang(self) -> str:
        """Return project source language, defaulting to 'he'."""
        try:
            from app.services.project_service import ProjectService
            with self.db_service.get_session() as session:
                proj = ProjectService().get_project(session, self.project_id)
                return proj.src_lang if proj else "he"
        except Exception:
            return "he"

    def _get_tgt_lang(self) -> str:
        """Return project target language, defaulting to 'ru'."""
        try:
            from app.services.project_service import ProjectService
            with self.db_service.get_session() as session:
                proj = ProjectService().get_project(session, self.project_id)
                return proj.tgt_lang if proj else "ru"
        except Exception:
            return "ru"

    def _selected_audio_items(self) -> list:
        """Build audio item dicts for all selected rows."""
        selected = self._get_selected_dtos()
        if not selected:
            return []
        src_lang = self._get_src_lang()
        return [
            {
                "src_lang": src_lang,
                "src_norm": SentencesWorkspaceService._norm(src_lang, dto.text),
                "src_text": dto.text,
                "kind": "sentence",
                "source_id": int(dto.sentence_id),
                "project_id": self.project_id,
                "source_label": dto.doc_name or "Sentences",
                "translation": dto.translation or "",
                "pronunciation_text": dto.pronunciation_text or "",
            }
            for dto in selected
        ]

    def _play_audio_items(self, items: list, *, play_mode: str, start_immediately: bool = False) -> None:
        """Resolve and play audio files for given items (same pattern as all other views)."""
        try:
            with self.db_service.get_session() as session:
                ready_items = self.audio_playback_service.resolve_ready_paths(
                    session, items=items
                )
            if not ready_items:
                QMessageBox.information(
                    self, "Audio Missing",
                    "No ready audio found for selected rows.\nUse 'Generate Audio...' first."
                )
                return
            paths = [row[0] for row in ready_items]
            labels = [
                str((row[1] or {}).get("src_text") or row[0].stem)
                for row in ready_items
            ]
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
                            or "Sentences"
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
            logger.error("Failed to play audio: %s", e, exc_info=True)
            QMessageBox.warning(self, "Playback Error", f"Failed to play audio:\n{e}")

    # ------------------------------------------------------------------
    # Batch result handlers
    # ------------------------------------------------------------------

    def _on_batch_done(self, progress_dialog, label: str):
        progress_dialog.set_completed()
        progress_dialog.accept()
        self._reload()

    def _on_batch_error(self, msg: str, progress_dialog):
        progress_dialog.set_stage(f"Error: {msg[:80]}")
        progress_dialog.accept()
        show_error(self, "Batch Error", msg)
