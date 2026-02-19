"""Term card view - curation workflow (M8)."""
import logging
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTextEdit, QComboBox, QTableView, QSplitter,
    QGroupBox, QSpinBox, QInputDialog, QMessageBox, QMenu, QProgressDialog
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from app.infra.settings import SettingsService
from app.services.db_service import DBService
from app.services.audio_playback_service import AudioPlaybackService
from app.services.term_card_service import TermCardService
from app.services.user_dictionary_service import UserDictionaryService
from app.domain.normalization.normalizer import normalize_for_tm
from app.domain.dto import TermCardDTO
from app.ui.models_qt import TermCardTableModel
from app.ui.table_layout_controller import TableLayoutController
from app.ui.delegates.audio_play_delegate import AudioPlayDelegate
from app.ui.dialogs import show_error, show_info
from app.ui.dialogs.edit_pronunciation_dialog import show_edit_pronunciation_dialog
from app.ui.dialogs.batch_audio_dialog import show_batch_audio_dialog
from app.ui.dialogs.batch_progress_dialog_v3 import BatchProgressDialogV3
from app.ui.dialogs.add_to_user_dictionary_dialog import show_add_to_user_dictionary_dialog
from app.ui.workers import UserDictionaryBulkAddWorker, BatchGenerateAudioWorker

logger = logging.getLogger(__name__)


class TermCardView(QWidget):
    """Term card curation view (M8)."""

    def __init__(self, project_id: int):
        super().__init__()
        self.project_id = project_id
        self.db_service = DBService.get_instance()
        self.audio_playback_service = AudioPlaybackService()
        self.card_service = TermCardService()
        self.user_dict_service = UserDictionaryService()
        self.settings = SettingsService.get_instance()
        self.batch_audio_worker: Optional[BatchGenerateAudioWorker] = None

        self.current_card: Optional[TermCardDTO] = None
        self.current_queue_index = -1

        self.init_ui()
        self.load_review_queue()

    def init_ui(self):
        """Initialize the UI."""
        main_layout = QVBoxLayout()

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("Term Curation")
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.load_review_queue)
        header_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(header_layout)

        # Splitter: Card display (top) + Review queue (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # ============================================
        # Top: Card Display + Actions
        # ============================================
        card_widget = QWidget()
        card_layout = QVBoxLayout()

        # Filters
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Status filter:"))
        self.status_filter_combo = QComboBox()
        self.status_filter_combo.addItems(["All", "auto", "needs_review", "approved", "rejected"])
        self.status_filter_combo.currentTextChanged.connect(self.load_review_queue)
        filter_layout.addWidget(self.status_filter_combo)

        filter_layout.addWidget(QLabel("Order by:"))
        self.order_combo = QComboBox()
        self.order_combo.addItems(["freq", "termhood", "weirdness", "pmi", "alpha"])
        self.order_combo.currentTextChanged.connect(self.load_review_queue)
        filter_layout.addWidget(self.order_combo)

        filter_layout.addWidget(QLabel("Min freq:"))
        self.min_freq_spin = QSpinBox()
        self.min_freq_spin.setRange(0, 1000)
        self.min_freq_spin.setValue(0)
        self.min_freq_spin.valueChanged.connect(self.load_review_queue)
        filter_layout.addWidget(self.min_freq_spin)

        filter_layout.addStretch()
        card_layout.addLayout(filter_layout)

        # Card display group
        card_group = QGroupBox("Term Card")
        card_group_layout = QVBoxLayout()

        # Term info (read-only)
        info_layout = QHBoxLayout()

        left_info = QVBoxLayout()
        self.term_label = QLabel("<b>Term:</b> (none)")
        self.lemma_label = QLabel("<b>Lemma:</b> (none)")
        self.freq_label = QLabel("<b>Frequency:</b> 0")
        self.status_label = QLabel("<b>Status:</b> auto")
        left_info.addWidget(self.term_label)
        left_info.addWidget(self.lemma_label)
        left_info.addWidget(self.freq_label)
        left_info.addWidget(self.status_label)
        info_layout.addLayout(left_info)

        right_info = QVBoxLayout()
        self.pinned_trans_label = QLabel("<b>Pinned Translation:</b> (none)")
        self.aliases_label = QLabel("<b>Aliases:</b> (none)")
        self.stopword_label = QLabel("<b>Stopword:</b> No")
        self.curated_label = QLabel("<b>Curated:</b> (never)")
        right_info.addWidget(self.pinned_trans_label)
        right_info.addWidget(self.aliases_label)
        right_info.addWidget(self.stopword_label)
        right_info.addWidget(self.curated_label)
        info_layout.addLayout(right_info)

        info_layout.addStretch()
        card_group_layout.addLayout(info_layout)

        # Notes display
        self.notes_label = QLabel("<b>Notes:</b> (none)")
        self.notes_label.setWordWrap(True)
        card_group_layout.addWidget(self.notes_label)

        # Pinned example
        self.example_label = QLabel("<b>Pinned Example:</b> (none)")
        self.example_label.setWordWrap(True)
        card_group_layout.addWidget(self.example_label)

        card_group.setLayout(card_group_layout)
        card_layout.addWidget(card_group)

        # Actions group
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout()

        # Status actions
        status_actions_layout = QHBoxLayout()
        status_actions_layout.addWidget(QLabel("Set Status:"))
        self.set_auto_btn = QPushButton("Auto")
        self.set_auto_btn.clicked.connect(lambda: self.set_status("auto"))
        status_actions_layout.addWidget(self.set_auto_btn)

        self.set_review_btn = QPushButton("Needs Review")
        self.set_review_btn.clicked.connect(lambda: self.set_status("needs_review"))
        status_actions_layout.addWidget(self.set_review_btn)

        self.set_approved_btn = QPushButton("Approved")
        self.set_approved_btn.clicked.connect(lambda: self.set_status("approved"))
        status_actions_layout.addWidget(self.set_approved_btn)

        self.set_rejected_btn = QPushButton("Rejected")
        self.set_rejected_btn.clicked.connect(lambda: self.set_status("rejected"))
        status_actions_layout.addWidget(self.set_rejected_btn)

        status_actions_layout.addStretch()
        actions_layout.addLayout(status_actions_layout)

        # Alias / Stopword / Pin actions
        other_actions_layout = QHBoxLayout()

        self.add_alias_btn = QPushButton("Add Alias")
        self.add_alias_btn.clicked.connect(self.add_alias)
        other_actions_layout.addWidget(self.add_alias_btn)

        self.remove_alias_btn = QPushButton("Remove Alias")
        self.remove_alias_btn.clicked.connect(self.remove_alias)
        other_actions_layout.addWidget(self.remove_alias_btn)

        self.toggle_stopword_btn = QPushButton("Toggle Stopword")
        self.toggle_stopword_btn.clicked.connect(self.toggle_stopword)
        other_actions_layout.addWidget(self.toggle_stopword_btn)

        self.pin_translation_btn = QPushButton("Pin Translation")
        self.pin_translation_btn.clicked.connect(self.pin_translation)
        other_actions_layout.addWidget(self.pin_translation_btn)

        self.unpin_translation_btn = QPushButton("Unpin Translation")
        self.unpin_translation_btn.clicked.connect(self.unpin_translation)
        other_actions_layout.addWidget(self.unpin_translation_btn)

        self.generate_audio_btn = QPushButton("Generate Audio...")
        self.generate_audio_btn.clicked.connect(self.on_generate_audio_selected)
        self.generate_audio_btn.setEnabled(False)
        other_actions_layout.addWidget(self.generate_audio_btn)

        self.play_audio_btn = QPushButton("Play Audio")
        self.play_audio_btn.clicked.connect(self.on_play_audio_selected)
        self.play_audio_btn.setEnabled(False)
        other_actions_layout.addWidget(self.play_audio_btn)

        other_actions_layout.addStretch()
        actions_layout.addLayout(other_actions_layout)

        actions_group.setLayout(actions_layout)
        card_layout.addWidget(actions_group)

        # Navigation
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("< Previous")
        self.prev_btn.clicked.connect(self.navigate_previous)
        nav_layout.addWidget(self.prev_btn)

        self.next_btn = QPushButton("Next >")
        self.next_btn.clicked.connect(self.navigate_next)
        nav_layout.addWidget(self.next_btn)

        nav_layout.addStretch()
        self.card_position_label = QLabel("0 / 0")
        nav_layout.addWidget(self.card_position_label)

        card_layout.addLayout(nav_layout)

        card_widget.setLayout(card_layout)
        splitter.addWidget(card_widget)

        # ============================================
        # Bottom: Review Queue Table
        # ============================================
        queue_widget = QWidget()
        queue_layout = QVBoxLayout()

        queue_label = QLabel("<b>Review Queue</b>")
        queue_layout.addWidget(queue_label)

        self.queue_model = TermCardTableModel()
        self.queue_table = QTableView()
        self.queue_table.setModel(self.queue_model)
        self.queue_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.queue_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.queue_table.setSortingEnabled(True)
        self.queue_table.clicked.connect(self.on_queue_item_clicked)
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self.on_queue_context_menu)
        self.queue_table.selectionModel().selectionChanged.connect(self.on_queue_selection_changed)

        self.table_layout_controller = TableLayoutController(
            settings=self.settings,
            table_id="term_card_view",
            table=self.queue_table,
            default_widths={
                0: 46,   # UD
                1: 260,  # Term
                2: 180,  # Lemma
                3: 90,   # Freq
                4: 100,  # DocFreq
                5: 120,  # Status
                6: 200,  # Pin Translation
                7: 200,  # Aliases
                8: 90,   # Stopword
                9: 110,  # Last Review
                10: 90,  # Audio
            },
        )
        self.table_layout_controller.install()
        self.audio_play_delegate = AudioPlayDelegate(
            self.queue_table,
            on_play_clicked=self.on_audio_cell_play_clicked,
        )
        self.queue_table.setItemDelegateForColumn(10, self.audio_play_delegate)

        queue_layout.addWidget(self.queue_table)

        self.queue_status_label = QLabel("No terms in queue")
        queue_layout.addWidget(self.queue_status_label)

        queue_widget.setLayout(queue_layout)
        splitter.addWidget(queue_widget)

        splitter.setStretchFactor(0, 1)  # Card display
        splitter.setStretchFactor(1, 1)  # Review queue

        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

    def load_review_queue(self):
        """Load review queue from database."""
        try:
            status_filter_text = self.status_filter_combo.currentText()
            status_filter = None if status_filter_text == "All" else status_filter_text

            order_by = self.order_combo.currentText()
            min_freq = self.min_freq_spin.value()

            with self.db_service.get_session() as session:
                cards = self.card_service.list_review_queue(
                    session,
                    self.project_id,
                    status_filter=status_filter,
                    min_freq=min_freq,
                    order_by=order_by,
                    limit=1000,
                )
                self._apply_study_overlays(session, cards)

                self.queue_model.update_cards(cards)
                self.queue_status_label.setText(f"Showing {len(cards)} terms")
                self.on_queue_selection_changed()

                # If there are cards and no current card, load first one
                if cards and not self.current_card:
                    self.current_queue_index = 0
                    self.load_card_at_index(0)
                elif not cards:
                    self.clear_card_display()

        except Exception as e:
            logger.exception("Failed to load review queue")
            show_error(self, "Error", f"Failed to load review queue: {e}")

    def _apply_study_overlays(self, session, cards: list) -> None:
        """Attach saved-to-UD + study tooltip metadata for visible review queue rows."""
        if not cards:
            return
        payloads = []
        for card in cards:
            src_norm = normalize_for_tm("he", card.representative_he, "term_cluster").norm
            payloads.append(
                {
                    "src_lang": "he",
                    "tgt_lang": "ru",
                    "kind": "term_cluster",
                    "src_text": card.representative_he,
                    "src_norm": src_norm,
                }
            )
        overlay_map = self.user_dict_service.resolve_cross_view_status(session, payloads)
        for card in cards:
            src_norm = normalize_for_tm("he", card.representative_he, "term_cluster").norm
            canonical_hash = self.user_dict_service.build_canonical_hash("he", "ru", "term_cluster", src_norm)
            overlay = overlay_map.get(canonical_hash) or {}
            card.in_user_dictionary_count = int(overlay.get("in_user_dictionary_count") or 0)
            card.study_tooltip = overlay.get("study_tooltip")
            card.study_state = overlay.get("study_state")
            card.study_due_human = overlay.get("study_due_human")
            card.last_grade = overlay.get("last_grade")
            card.last_graded_at = overlay.get("last_graded_at")
            card.audio_status = overlay.get("audio_status")

    def on_queue_item_clicked(self, index):
        """Handle click on review queue item."""
        row = index.row()
        self.current_queue_index = row
        self.load_card_at_index(row)

    def on_queue_selection_changed(self):
        """Enable/disable audio actions by queue selection."""
        selected_rows = self.queue_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        self.generate_audio_btn.setEnabled(has_selection)
        self.play_audio_btn.setEnabled(has_selection)

    def _selected_audio_items(self) -> list[dict]:
        """Build source-audio payloads from selected queue rows."""
        selected_rows = self.queue_table.selectionModel().selectedRows()
        items: list[dict] = []
        for index in sorted(selected_rows, key=lambda idx: idx.row()):
            card = self.queue_model.get_card(index.row())
            if not card:
                continue
            src_norm = normalize_for_tm("he", card.representative_he, "term_cluster").norm
            if not src_norm:
                continue
            items.append(
                {
                    "row_id": str(card.cluster_id),
                    "src_text": card.representative_he,
                    "src_lang": "he",
                    "src_norm": src_norm,
                }
            )
        return items

    def on_generate_audio_selected(self):
        """Generate source-audio for selected review-queue rows."""
        items = self._selected_audio_items()
        if not items:
            return

        accepted, provider_mode, write_mode, _scope = show_batch_audio_dialog(
            parent=self,
            selected_count=len(items),
            scope_enabled=False,
            filtered_count=len(items),
        )
        if not accepted:
            return

        progress_dialog = BatchProgressDialogV3(parent=self, total=len(items))
        progress_dialog.setWindowTitle("Batch Generate Source Audio")
        progress_dialog.show()

        worker = BatchGenerateAudioWorker(
            items=items,
            provider_mode=provider_mode,
            write_mode=write_mode,
            audio_chunk=25,
        )
        self.batch_audio_worker = worker
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
        worker.finished.connect(self.on_queue_selection_changed)
        worker.error.connect(self.on_queue_selection_changed)
        worker.start()

    def _on_generate_audio_finished(self, result: dict, progress_dialog: BatchProgressDialogV3):
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

        if self.batch_audio_worker:
            self.batch_audio_worker.deleteLater()
            self.batch_audio_worker = None
        self.load_review_queue()

    def _on_generate_audio_error(self, error_msg: str, progress_dialog: BatchProgressDialogV3):
        progress_dialog.reject()
        QMessageBox.warning(self, "Audio Generation Failed", error_msg)
        if self.batch_audio_worker:
            self.batch_audio_worker.deleteLater()
            self.batch_audio_worker = None
        self.on_queue_selection_changed()

    def on_play_audio_selected(self):
        """Play ready audio from selected rows using queue mode."""
        items = self._selected_audio_items()
        if not items:
            return
        self._play_audio_items(items, play_mode="enqueue")

    def on_audio_cell_play_clicked(self, index):
        """Delegate callback: play one row from Audio column."""
        card = self.queue_model.get_card(index.row())
        if not card:
            return
        src_norm = normalize_for_tm("he", card.representative_he, "term_cluster").norm
        if not src_norm:
            return
        self._play_audio_items(
            [
                {
                    "src_lang": "he",
                    "src_norm": src_norm,
                    "src_text": card.representative_he,
                }
            ],
            play_mode="interrupt",
        )

    def _play_audio_items(self, items: list[dict], *, play_mode: str):
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
            self.audio_playback_service.launch_audio_files(paths, labels=labels, play_mode=play_mode)
        except Exception as e:
            logger.error("Failed to play audio in Term Cards: %s", e, exc_info=True)
            QMessageBox.warning(self, "Playback Error", f"Failed to play audio:\n{e}")

    def on_edit_pronunciation_selected(self):
        """Open pronunciation editor for the first selected queue row."""
        items = self._selected_audio_items()
        if not items:
            return
        first = items[0]
        changed = show_edit_pronunciation_dialog(
            parent=self,
            src_lang=str(first.get("src_lang") or ""),
            src_norm=str(first.get("src_norm") or ""),
            src_text=str(first.get("src_text") or ""),
        )
        if changed:
            self.load_review_queue()

    def on_queue_context_menu(self, pos):
        """Context menu for review queue rows."""
        selected_rows = self.queue_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        count = len(selected_rows)
        menu = QMenu(self)
        generate_action = QAction(f"Generate Audio Selected ({count} rows)...", self)
        generate_action.triggered.connect(self.on_generate_audio_selected)
        menu.addAction(generate_action)
        play_action = QAction(f"Play Audio Selected ({count} rows)", self)
        play_action.triggered.connect(self.on_play_audio_selected)
        menu.addAction(play_action)
        menu.addSeparator()
        add_action = QAction(f"Add Selected to User Dictionary ({count} rows)...", self)
        add_action.triggered.connect(self.on_add_selected_to_user_dictionary)
        menu.addAction(add_action)
        edit_pron_action = QAction("Edit Pronunciation...", self)
        edit_pron_action.triggered.connect(self.on_edit_pronunciation_selected)
        menu.addAction(edit_pron_action)
        menu.exec(self.queue_table.viewport().mapToGlobal(pos))

    def on_add_selected_to_user_dictionary(self):
        """Add selected term-card rows to user dictionary."""
        selected_rows = self.queue_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        cluster_ids = []
        for index in selected_rows:
            card = self.queue_model.get_card(index.row())
            if card:
                cluster_ids.append(card.cluster_id)
        cluster_ids = sorted(set(cluster_ids))
        if not cluster_ids:
            return

        from sqlalchemy import select
        from app.infra.sa_models import TermCluster

        payloads = []
        with self.db_service.get_session() as session:
            stmt = select(TermCluster).where(TermCluster.cluster_id.in_(cluster_ids))
            for cluster in session.execute(stmt).scalars().all():
                src_norm = normalize_for_tm("he", cluster.representative_he, "term_cluster").norm
                payloads.append(
                    {
                        "kind": "term_cluster",
                        "src_lang": "he",
                        "tgt_lang": "ru",
                        "src_text": cluster.representative_he,
                        "src_norm": src_norm,
                        "is_noise": 1 if cluster.is_noise == 1 else 0,
                        "noise_reason": cluster.noise_reason,
                        "origin_project_id": self.project_id,
                        "origin_entity_type": "term_card",
                        "origin_entity_id": cluster.cluster_id,
                        "origin_source_ref": "term_card_view",
                    }
                )

        accepted, dictionary_id, options = show_add_to_user_dictionary_dialog(
            parent=self,
            selected_count=len(payloads),
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
        self._user_dict_add_worker = worker
        worker.progress.connect(lambda done, total: progress.setValue(done))
        worker.finished.connect(lambda result: self._on_user_dict_add_finished(result, progress))
        worker.error.connect(lambda err: self._on_user_dict_add_error(err, progress))
        progress.canceled.connect(worker.cancel)
        worker.start()

    def _on_user_dict_add_finished(self, result, progress_dialog):
        progress_dialog.close()
        show_info(
            self,
            "Add Complete",
            f"Added: {result.get('added', 0)}\n"
            f"Skipped: {result.get('skipped', 0)}\n"
            f"Failed: {result.get('failed', 0)}",
        )
        self._user_dict_add_worker = None

    def _on_user_dict_add_error(self, error_msg: str, progress_dialog):
        progress_dialog.close()
        show_error(self, "Add Failed", error_msg)
        self._user_dict_add_worker = None

    def load_card_at_index(self, index: int):
        """Load card at specific queue index."""
        card = self.queue_model.get_card(index)
        if card:
            self.current_card = card
            self.current_queue_index = index
            self.update_card_display()

    def update_card_display(self):
        """Update card display with current card data."""
        if not self.current_card:
            self.clear_card_display()
            return

        card = self.current_card

        # Update labels
        self.term_label.setText(f"<b>Term:</b> {card.representative_he}")
        self.lemma_label.setText(f"<b>Lemma:</b> {card.representative_lemma or '(none)'}")
        self.freq_label.setText(f"<b>Frequency:</b> {card.freq_abs} (docs: {card.doc_freq})")
        self.status_label.setText(f"<b>Status:</b> {card.curation_status}")

        self.pinned_trans_label.setText(
            f"<b>Pinned Translation:</b> {card.pinned_translation or '(none)'}"
        )

        aliases_text = ", ".join(card.aliases) if card.aliases else "(none)"
        self.aliases_label.setText(f"<b>Aliases:</b> {aliases_text}")

        self.stopword_label.setText(f"<b>Stopword:</b> {'Yes' if card.is_stopword else 'No'}")

        curated_text = "(never)"
        if card.curated_at and card.curated_by:
            curated_text = f"{card.curated_by} at {card.curated_at}"
        self.curated_label.setText(f"<b>Curated:</b> {curated_text}")

        self.notes_label.setText(f"<b>Notes:</b> {card.curation_notes or '(none)'}")

        self.example_label.setText(
            f"<b>Pinned Example:</b> {card.pinned_example_text or '(none)'}"
        )

        # Update navigation
        total = self.queue_model.rowCount()
        self.card_position_label.setText(f"{self.current_queue_index + 1} / {total}")
        self.prev_btn.setEnabled(self.current_queue_index > 0)
        self.next_btn.setEnabled(self.current_queue_index < total - 1)

    def clear_card_display(self):
        """Clear card display."""
        self.term_label.setText("<b>Term:</b> (none)")
        self.lemma_label.setText("<b>Lemma:</b> (none)")
        self.freq_label.setText("<b>Frequency:</b> 0")
        self.status_label.setText("<b>Status:</b> auto")
        self.pinned_trans_label.setText("<b>Pinned Translation:</b> (none)")
        self.aliases_label.setText("<b>Aliases:</b> (none)")
        self.stopword_label.setText("<b>Stopword:</b> No")
        self.curated_label.setText("<b>Curated:</b> (never)")
        self.notes_label.setText("<b>Notes:</b> (none)")
        self.example_label.setText("<b>Pinned Example:</b> (none)")
        self.card_position_label.setText("0 / 0")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

    def navigate_previous(self):
        """Navigate to previous card in queue."""
        if self.current_queue_index > 0:
            self.current_queue_index -= 1
            self.load_card_at_index(self.current_queue_index)

    def navigate_next(self):
        """Navigate to next card in queue."""
        total = self.queue_model.rowCount()
        if self.current_queue_index < total - 1:
            self.current_queue_index += 1
            self.load_card_at_index(self.current_queue_index)

    # ============================================
    # Actions
    # ============================================

    def set_status(self, status: str):
        """Set curation status for current term."""
        if not self.current_card:
            show_error(self, "No Term Selected", "Please select a term first.")
            return

        # Ask for notes
        notes, ok = QInputDialog.getText(
            self,
            "Curation Notes",
            f"Set status to '{status}'. Optional notes:",
        )

        if not ok:
            return

        try:
            with self.db_service.get_session() as session:
                success = self.card_service.set_status(
                    session,
                    self.current_card.cluster_id,
                    status,
                    curated_by="user",
                    notes=notes if notes.strip() else None,
                )
                session.commit()

                if success:
                    # Reload current card
                    self.reload_current_card()
                    show_info(self, "Success", f"Status set to '{status}'")
                else:
                    show_error(self, "Error", "Failed to set status")

        except Exception as e:
            logger.exception("Failed to set status")
            show_error(self, "Error", f"Failed to set status: {e}")

    def add_alias(self):
        """Add alias for current term."""
        if not self.current_card:
            show_error(self, "No Term Selected", "Please select a term first.")
            return

        variant, ok = QInputDialog.getText(
            self,
            "Add Alias",
            f"Enter variant form for '{self.current_card.representative_he}':",
        )

        if not ok or not variant.strip():
            return

        note, _ = QInputDialog.getText(
            self,
            "Alias Note",
            "Optional note about this alias:",
        )

        try:
            with self.db_service.get_session() as session:
                success = self.card_service.add_alias(
                    session,
                    self.project_id,
                    self.current_card.canonical_key,
                    variant.strip(),
                    note=note.strip() if note.strip() else None,
                )
                session.commit()

                if success:
                    self.reload_current_card()
                    show_info(self, "Success", "Alias added")
                else:
                    show_error(self, "Duplicate", "Alias already exists")

        except Exception as e:
            logger.exception("Failed to add alias")
            show_error(self, "Error", f"Failed to add alias: {e}")

    def remove_alias(self):
        """Remove alias for current term."""
        if not self.current_card or not self.current_card.aliases:
            show_error(self, "No Aliases", "This term has no aliases.")
            return

        variant, ok = QInputDialog.getItem(
            self,
            "Remove Alias",
            "Select alias to remove:",
            self.current_card.aliases,
            0,
            False,
        )

        if not ok:
            return

        try:
            with self.db_service.get_session() as session:
                success = self.card_service.remove_alias(
                    session,
                    self.project_id,
                    self.current_card.canonical_key,
                    variant,
                )
                session.commit()

                if success:
                    self.reload_current_card()
                    show_info(self, "Success", "Alias removed")
                else:
                    show_error(self, "Error", "Failed to remove alias")

        except Exception as e:
            logger.exception("Failed to remove alias")
            show_error(self, "Error", f"Failed to remove alias: {e}")

    def toggle_stopword(self):
        """Toggle stopword status for current term."""
        if not self.current_card:
            show_error(self, "No Term Selected", "Please select a term first.")
            return

        try:
            with self.db_service.get_session() as session:
                if self.current_card.is_stopword:
                    # Unset stopword
                    success = self.card_service.unset_stopword(
                        session,
                        self.project_id,
                        self.current_card.canonical_key,
                    )
                    action = "unmarked as stopword"
                else:
                    # Set stopword
                    reason, ok = QInputDialog.getText(
                        self,
                        "Stopword Reason",
                        "Why is this a stopword?",
                    )

                    if not ok:
                        return

                    success = self.card_service.set_stopword(
                        session,
                        self.project_id,
                        self.current_card.canonical_key,
                        reason=reason.strip() if reason.strip() else None,
                    )
                    action = "marked as stopword"

                session.commit()

                if success:
                    self.reload_current_card()
                    show_info(self, "Success", f"Term {action}")
                else:
                    show_error(self, "Error", f"Failed to toggle stopword")

        except Exception as e:
            logger.exception("Failed to toggle stopword")
            show_error(self, "Error", f"Failed to toggle stopword: {e}")

    def pin_translation(self):
        """Pin translation for current term."""
        if not self.current_card:
            show_error(self, "No Term Selected", "Please select a term first.")
            return

        translation, ok = QInputDialog.getText(
            self,
            "Pin Translation",
            f"Enter translation for '{self.current_card.representative_he}':",
            text=self.current_card.pinned_translation or "",
        )

        if not ok or not translation.strip():
            return

        try:
            with self.db_service.get_session() as session:
                success = self.card_service.pin_translation(
                    session,
                    self.current_card.cluster_id,
                    translation.strip(),
                    translation_lang="ru",
                )
                session.commit()

                if success:
                    self.reload_current_card()
                    show_info(self, "Success", "Translation pinned")
                else:
                    show_error(self, "Error", "Failed to pin translation")

        except Exception as e:
            logger.exception("Failed to pin translation")
            show_error(self, "Error", f"Failed to pin translation: {e}")

    def unpin_translation(self):
        """Unpin translation for current term."""
        if not self.current_card:
            show_error(self, "No Term Selected", "Please select a term first.")
            return

        if not self.current_card.pinned_translation:
            show_error(self, "No Pinned Translation", "This term has no pinned translation.")
            return

        reply = QMessageBox.question(
            self,
            "Unpin Translation",
            f"Unpin translation '{self.current_card.pinned_translation}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            with self.db_service.get_session() as session:
                success = self.card_service.unpin_translation(
                    session,
                    self.current_card.cluster_id,
                )
                session.commit()

                if success:
                    self.reload_current_card()
                    show_info(self, "Success", "Translation unpinned")
                else:
                    show_error(self, "Error", "Failed to unpin translation")

        except Exception as e:
            logger.exception("Failed to unpin translation")
            show_error(self, "Error", f"Failed to unpin translation: {e}")

    def reload_current_card(self):
        """Reload current card from database."""
        if not self.current_card:
            return

        try:
            with self.db_service.get_session() as session:
                card = self.card_service.get_card(
                    session,
                    self.project_id,
                    cluster_id=self.current_card.cluster_id,
                )
                if card:
                    self.current_card = card
                    self.update_card_display()
                    # Also refresh the queue to update the table
                    self.load_review_queue()

        except Exception as e:
            logger.exception("Failed to reload card")
            show_error(self, "Error", f"Failed to reload card: {e}")

    def closeEvent(self, event):
        """Persist term-card queue table layout on close."""
        if self.batch_audio_worker and self.batch_audio_worker.isRunning():
            logger.info("Stopping term-card batch audio worker on close")
            self.batch_audio_worker.cancel()
            self.batch_audio_worker.wait(1000)
            if self.batch_audio_worker.isRunning():
                self.batch_audio_worker.terminate()
        self.table_layout_controller.save_now()
        super().closeEvent(event)
