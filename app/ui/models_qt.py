"""Qt models for tables and lists."""
import logging

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor

from app.domain.dto import (
    DocumentDTO,
    LemmaStats,
    ProjectStats,
    SentenceDTO,
    UserDictionaryDTO,
    UserDictionaryItemDTO,
)
from app.ui.study_status_ui import (
    audio_status_brush,
    compose_status_icons,
    get_last_grade_cell_brush,
    get_last_grade_row_brush,
    last_review_label,
    noise_brush,
    origin_brush,
    origin_marker,
    study_brush,
    study_chip,
    translation_tier_brush,
    ud_indicator_brush,
    ud_indicator_text,
)

logger = logging.getLogger(__name__)


class ProjectListModel(QAbstractTableModel):
    """Model for project list table."""

    def __init__(self, projects: list[ProjectStats] = None):
        super().__init__()
        self.projects = projects or []
        self.headers = ["ID", "Name", "Documents", "Processed", "Lemmas", "N-grams"]

    def rowCount(self, parent=QModelIndex()):
        return len(self.projects)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        # Support both DisplayRole and EditRole
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None

        project = self.projects[index.row()]
        col = index.column()

        if col == 0:
            return str(project.project_id)
        elif col == 1:
            # EditRole: return raw name (for editing, no 🌐 prefix)
            if role == Qt.ItemDataRole.EditRole:
                return project.name
            # DisplayRole: add 🌐 marker for reference corpus
            if project.is_general_corpus:
                return f"🌐 {project.name}"
            return project.name
        elif col == 2:
            return str(project.total_docs)
        elif col == 3:
            return str(project.processed_docs)
        elif col == 4:
            return str(project.total_lemmas)
        elif col == 5:
            return str(project.total_ngrams)

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def flags(self, index):
        """Make Name column (column 1) editable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)

        # Column 1 (Name) is editable
        if index.column() == 1:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """Handle inline edit of project name."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() == 1:  # Name column
            # Update DTO (actual save happens in view's handler)
            project = self.projects[index.row()]
            project.name = value

            # Emit data changed
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            return True

        return False

    def update_projects(self, projects: list[ProjectStats]):
        """Update the project list."""
        self.beginResetModel()
        self.projects = projects
        self.endResetModel()


class LemmaTableModel(QAbstractTableModel):
    """Model for lemma/dictionary table with M7 translation support."""

    def __init__(self, lemmas: list[LemmaStats] = None):
        super().__init__()
        self.lemmas = lemmas or []
        # M7: Added Source column between Translation and Status
        # Added Noise column for is_noise visualization
        # Epic 6B: Added Entity Class column (col 9); Niqqud→11, Audio→12
        self.headers = [
            "UD",           # 0
            "Lemma",        # 1
            "POS",          # 2
            "Frequency",    # 3
            "Doc Freq",     # 4
            "Translation",  # 5  (editable)
            "Source",       # 6
            "Status",       # 7
            "Noise",        # 8
            "Entity Class", # 9  (Epic 6B)
            "Last Review",  # 10 (was 9)
            "Niqqud",       # 11 (was 10)
            "Audio",        # 12 (was 11)
        ]
        # M7: Store full TranslationResult for each lemma (for Why dialog)
        self.translation_results = {}  # row_index -> TranslationResult

    def rowCount(self, parent=QModelIndex()):
        return len(self.lemmas)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        lemma = self.lemmas[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 11 and getattr(lemma, "pronunciation_text", None):
                source = getattr(lemma, "pronunciation_source", None) or "none"
                confidence = getattr(lemma, "pronunciation_confidence", None)
                qc = getattr(lemma, "pronunciation_qc", None) or "ok"
                conf_text = f"{float(confidence):.2f}" if confidence is not None else "n/a"
                return f"Niqqud: {lemma.pronunciation_text}\nSource: {source}\nConfidence: {conf_text}\nQC: {qc}"
            if col == 12 and getattr(lemma, "audio_status", None):
                return f"Audio: {lemma.audio_status}"
            if lemma.study_tooltip and int(getattr(lemma, "in_user_dictionary_count", 0) or 0) > 0:
                return lemma.study_tooltip
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            return get_last_grade_row_brush(
                in_user_dictionary_count=int(getattr(lemma, "in_user_dictionary_count", 0) or 0),
                last_grade=getattr(lemma, "last_grade", None),
            )

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return ud_indicator_brush(
                    int(getattr(lemma, "in_user_dictionary_count", 0) or 0),
                    getattr(lemma, "study_state", None),
                )
            if col == 12 and getattr(lemma, "audio_status", None):
                return audio_status_brush(getattr(lemma, "audio_status", None))

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == 0:
                return ud_indicator_text(
                    int(getattr(lemma, "in_user_dictionary_count", 0) or 0),
                    getattr(lemma, "study_state", None),
                )
            elif col == 1:
                return lemma.lemma_text
            elif col == 2:
                return lemma.pos or ""
            elif col == 3:
                return str(lemma.freq_abs)
            elif col == 4:
                return str(lemma.doc_freq)
            elif col == 5:
                # M7: Translation from DTO
                return lemma.translation or ""
            elif col == 6:
                # M7: Source (tm|dict|mt_cache|mt|none)
                tr_result = self.translation_results.get(index.row())
                if tr_result:
                    return tr_result.source
                return "none"
            elif col == 7:
                # M7: Status
                return lemma.status
            elif col == 8:
                # Noise column — Epic 6B: show noise_source provenance
                ns = getattr(lemma, "noise_source", None)
                suffix = f" ({ns})" if ns else ""
                if lemma.is_noise == 1:
                    return f"Noise{suffix}"
                elif lemma.is_noise == 0:
                    return f"Valid{suffix}"
                return ""  # NULL - legacy records
            elif col == 9:
                # Epic 6B: Entity Class
                return getattr(lemma, "entity_class", None) or ""
            elif col == 10:
                if int(getattr(lemma, "in_user_dictionary_count", 0) or 0) <= 0:
                    return ""
                return last_review_label(getattr(lemma, "last_grade", None))
            elif col == 11:
                return getattr(lemma, "pronunciation_text", "") or ""
            elif col == 12:
                return getattr(lemma, "audio_status", "") or ""

        return None

    def flags(self, index):
        """M7: Make Translation column editable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)

        # Column 5 (Translation) is editable
        if index.column() == 5:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """M7: Handle inline edit of translation."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() == 5:  # Translation column
            # Update DTO
            lemma = self.lemmas[index.row()]
            lemma.translation = value
            lemma.status = "draft"  # User edit → draft status

            # Emit data changed
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

            # Also emit for Status column (col 7) since it changed
            status_idx = self.index(index.row(), 7)
            self.dataChanged.emit(status_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

            return True

        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def update_lemmas(self, lemmas: list[LemmaStats]):
        """Update the lemma list."""
        self.beginResetModel()
        self.lemmas = lemmas
        self.translation_results.clear()  # Clear cached results
        self.endResetModel()

    def update_translations(self, results: dict):
        """M7: Update translations from TranslationResolveWorker results.

        Args:
            results: dict[(src_text, kind)] -> TranslationResult
        """
        for row, lemma in enumerate(self.lemmas):
            key = (lemma.lemma_text, "lemma")
            if key in results:
                tr_result = results[key]

                # Update DTO
                lemma.translation = tr_result.translation
                lemma.status = tr_result.status or "none"

                # Cache full result for Why dialog
                self.translation_results[row] = tr_result

                # Emit dataChanged for Translation, Source, Status columns
                trans_idx = self.index(row, 5)
                status_idx = self.index(row, 7)
                self.dataChanged.emit(trans_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

    def get_lemma(self, row: int) -> LemmaStats:
        """Get lemma at row."""
        if 0 <= row < len(self.lemmas):
            return self.lemmas[row]
        return None

    def get_translation_result(self, row: int):
        """M7: Get cached TranslationResult for Why dialog."""
        return self.translation_results.get(row)


class TermClusterTableModel(QAbstractTableModel):
    """Model for term cluster table with M7 translation support."""

    def __init__(self, clusters: list = None):
        super().__init__()
        from app.domain.dto import ClusterStats
        self.clusters: list[ClusterStats] = clusters or []
        # M7: Added Translation, Source, Status columns
        # Added Noise column for is_noise visualization
        self.headers = [
            "UD", "Term", "Lemma", "Freq", "DocFreq", "Members", "PMI", "LLR", "Dice",
            "Weirdness", "Keyness", "Termhood", "Translation", "Source", "Status", "Noise", "Last Review", "Niqqud", "Audio"
        ]
        # M7: Store full TranslationResult for each cluster
        self.translation_results = {}  # row_index -> TranslationResult

    def rowCount(self, parent=QModelIndex()):
        return len(self.clusters)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        cluster = self.clusters[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 9:
                return (
                    "Weirdness — domain specificity vs reference corpus.\n"
                    "> 1.0: term is more frequent in this domain than in the reference.\n"
                    "Requires a reference corpus to be set (Termhood preset).\n"
                    "Stored at extraction time when reference corpus is configured."
                )
            if col == 10:
                kval = getattr(cluster, "best_keyness", None)
                src = "stored" if kval is not None else "query-time"
                return (
                    f"Keyness (LLR) — statistical significance of domain frequency vs reference.\n"
                    f"Higher = more statistically distinctive in this domain.\n"
                    f"Source: {src}. Requires a reference corpus.\n"
                    "Stored at extraction time; sortable without re-computing."
                )
            if col == 11:
                return (
                    "Termhood — composite score: log(Keyness) × log(Weirdness) × log(Freq).\n"
                    "Combines statistical significance, domain specificity, and frequency.\n"
                    "Used by the 'termhood' preset for ranking."
                )
            if col == 17 and getattr(cluster, "pronunciation_text", None):
                source = getattr(cluster, "pronunciation_source", None) or "none"
                confidence = getattr(cluster, "pronunciation_confidence", None)
                qc = getattr(cluster, "pronunciation_qc", None) or "ok"
                conf_text = f"{float(confidence):.2f}" if confidence is not None else "n/a"
                return f"Niqqud: {cluster.pronunciation_text}\nSource: {source}\nConfidence: {conf_text}\nQC: {qc}"
            if col == 18 and getattr(cluster, "audio_status", None):
                return f"Audio: {cluster.audio_status}"
            if cluster.study_tooltip and int(getattr(cluster, "in_user_dictionary_count", 0) or 0) > 0:
                return cluster.study_tooltip
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            return get_last_grade_row_brush(
                in_user_dictionary_count=int(getattr(cluster, "in_user_dictionary_count", 0) or 0),
                last_grade=getattr(cluster, "last_grade", None),
            )

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return ud_indicator_brush(
                    int(getattr(cluster, "in_user_dictionary_count", 0) or 0),
                    getattr(cluster, "study_state", None),
                )
            if col == 18 and getattr(cluster, "audio_status", None):
                return audio_status_brush(getattr(cluster, "audio_status", None))

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == 0:
                return ud_indicator_text(
                    int(getattr(cluster, "in_user_dictionary_count", 0) or 0),
                    getattr(cluster, "study_state", None),
                )
            elif col == 1:
                return cluster.representative_he
            elif col == 2:
                return cluster.representative_lemma or ""
            elif col == 3:
                return str(cluster.freq_abs)
            elif col == 4:
                return str(cluster.doc_freq)
            elif col == 5:
                return str(cluster.members_count)
            elif col == 6:
                return f"{cluster.best_pmi:.2f}" if cluster.best_pmi else "N/A"
            elif col == 7:
                return f"{cluster.best_llr:.2f}" if cluster.best_llr else "N/A"
            elif col == 8:
                return f"{cluster.best_dice:.3f}" if cluster.best_dice else "N/A"
            elif col == 9:
                return f"{cluster.weirdness:.2f}" if cluster.weirdness else "N/A"
            elif col == 10:
                # Prefer stored best_keyness (set during extraction) over query-time keyness_llr
                kval = getattr(cluster, "best_keyness", None)
                if kval is None:
                    kval = cluster.keyness_llr
                return f"{kval:.2f}" if kval is not None else "N/A"
            elif col == 11:
                return f"{cluster.termhood_score:.2f}" if cluster.termhood_score else "N/A"
            elif col == 12:
                # M7: Translation
                return cluster.translation or ""
            elif col == 13:
                # M7: Source
                return cluster.translation_source or "none"
            elif col == 14:
                # M7: Status
                return cluster.translation_status or "none"
            elif col == 15:
                # Noise column
                if cluster.is_noise == 1:
                    return "Noise"
                elif cluster.is_noise == 0:
                    return "Valid"
                else:
                    return ""  # NULL - legacy records
            elif col == 16:
                if int(getattr(cluster, "in_user_dictionary_count", 0) or 0) <= 0:
                    return ""
                return last_review_label(getattr(cluster, "last_grade", None))
            elif col == 17:
                return getattr(cluster, "pronunciation_text", "") or ""
            elif col == 18:
                return getattr(cluster, "audio_status", "") or ""

        return None

    def flags(self, index):
        """M7: Make Translation column editable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)

        # Column 12 (Translation) is editable
        if index.column() == 12:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """M7: Handle inline edit of translation."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() == 12:  # Translation column
            # Update DTO
            cluster = self.clusters[index.row()]
            cluster.translation = value
            cluster.translation_status = "draft"  # User edit → draft

            # Emit data changed
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

            # Also emit for Status column (col 14)
            status_idx = self.index(index.row(), 14)
            self.dataChanged.emit(status_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

            return True

        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def update_clusters(self, clusters: list):
        """Update the cluster list."""
        self.beginResetModel()
        self.clusters = clusters
        self.translation_results.clear()
        self.endResetModel()

    def update_translations(self, results: dict):
        """M7: Update translations from TranslationResolveWorker results.

        Args:
            results: dict[(src_text, kind)] -> TranslationResult
        """
        for row, cluster in enumerate(self.clusters):
            # Use representative_he for matching (worker uses it as key)
            key = (cluster.representative_he, "term_cluster")
            if key in results:
                tr_result = results[key]

                # Update DTO
                cluster.translation = tr_result.translation
                cluster.translation_source = tr_result.source
                cluster.translation_status = tr_result.status or "none"

                # Cache full result for Why dialog
                self.translation_results[row] = tr_result

                # Emit dataChanged for Translation, Source, Status columns
                trans_idx = self.index(row, 12)
                status_idx = self.index(row, 14)
                self.dataChanged.emit(trans_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

    def get_cluster(self, row: int):
        """Get cluster at row."""
        if 0 <= row < len(self.clusters):
            return self.clusters[row]
        return None

    def get_translation_result(self, row: int):
        """M7: Get cached TranslationResult for Why dialog."""
        return self.translation_results.get(row)


# ============================================================================
# P2: Translation Management Table Model
# ============================================================================

class TranslationManagementTableModel(QAbstractTableModel):
    """P2: Model for Translation Management panel."""

    def __init__(self, entries: list = None):
        super().__init__()
        from app.domain.dto import TMEntryDTO
        self.entries: list[TMEntryDTO] = entries or []
        # Added Noise column for is_noise visualization
        self.headers = [
            "UD", "ID", "Kind", "Source", "Translation", "Status",
            "Scope", "Origin", "Source Ref", "Updated", "Noise", "Last Review", "Niqqud", "Audio",
            "Src",  # Epic 5A: source_status indicator (col 14)
        ]
        self.total_count = 0  # Total matching entries (for pagination)

    def rowCount(self, parent=QModelIndex()):
        return len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        entry = self.entries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 12 and getattr(entry, "pronunciation_text", None):
                source = getattr(entry, "pronunciation_source", None) or "none"
                confidence = getattr(entry, "pronunciation_confidence", None)
                qc = getattr(entry, "pronunciation_qc", None) or "ok"
                conf_text = f"{float(confidence):.2f}" if confidence is not None else "n/a"
                return f"Niqqud: {entry.pronunciation_text}\nSource: {source}\nConfidence: {conf_text}\nQC: {qc}"
            if col == 13 and getattr(entry, "audio_status", None):
                return f"Audio: {entry.audio_status}"
            if col == 14 and entry.kind == "term_cluster":
                status = entry.source_status
                if status == "linked":
                    return "Cluster is active in the current extraction"
                if status == "source_cluster_missing":
                    pfid = getattr(entry, "promoted_from_cluster_id", None)
                    phash = getattr(entry, "promoted_at_params_hash", None) or "?"
                    parts = ["Source cluster was deleted during re-extraction. Entry preserved."]
                    if pfid:
                        parts.append(f"Original cluster: #{pfid}")
                    parts.append(f"Extracted with params: {phash}")
                    return "\n".join(parts)
                return "Added manually — no cluster source"
            if entry.study_tooltip and int(getattr(entry, "in_user_dictionary_count", 0) or 0) > 0:
                return entry.study_tooltip
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            return get_last_grade_row_brush(
                in_user_dictionary_count=int(getattr(entry, "in_user_dictionary_count", 0) or 0),
                last_grade=getattr(entry, "last_grade", None),
            )

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return ud_indicator_brush(
                    int(getattr(entry, "in_user_dictionary_count", 0) or 0),
                    getattr(entry, "study_state", None),
                )
            if col == 13 and getattr(entry, "audio_status", None):
                return audio_status_brush(getattr(entry, "audio_status", None))
            if col == 14 and entry.kind == "term_cluster":
                from PyQt6.QtGui import QColor

                status = entry.source_status
                if status == "linked":
                    return QColor("#16a34a")  # green
                if status == "source_cluster_missing":
                    return QColor("#dc2626")  # red
                return QColor("#6b7280")  # gray (manual)

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == 0:
                return ud_indicator_text(
                    int(getattr(entry, "in_user_dictionary_count", 0) or 0),
                    getattr(entry, "study_state", None),
                )
            elif col == 1:
                return str(entry.tm_id)
            elif col == 2:
                return entry.kind
            elif col == 3:
                return entry.src_text
            elif col == 4:
                return entry.translation
            elif col == 5:
                return entry.status
            elif col == 6:
                return "Global" if entry.project_id is None else f"Project {entry.project_id}"
            elif col == 7:
                return entry.origin
            elif col == 8:
                return entry.source_ref or ""
            elif col == 9:
                # Show just date part of updated_at
                if entry.updated_at:
                    return entry.updated_at.split("T")[0]
                return ""
            elif col == 10:
                # Noise column
                if entry.is_noise == 1:
                    return "Noise"
                elif entry.is_noise == 0:
                    return "Valid"
                else:
                    return ""  # NULL - legacy records
            elif col == 11:
                if int(getattr(entry, "in_user_dictionary_count", 0) or 0) <= 0:
                    return ""
                return last_review_label(getattr(entry, "last_grade", None))
            elif col == 12:
                return getattr(entry, "pronunciation_text", "") or ""
            elif col == 13:
                return getattr(entry, "audio_status", "") or ""
            elif col == 14:
                # source_status indicator — only meaningful for term_cluster entries
                if entry.kind != "term_cluster":
                    return ""
                status = entry.source_status
                if status == "linked":
                    return "\u25cf"  # ● green
                if status == "source_cluster_missing":
                    return "\u25cf"  # ● red
                return "\u25cf"  # ● gray (manual)

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def flags(self, index):
        """P2: Translation column editable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)

        # Column 4 (Translation) is editable
        if index.column() == 4:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """P2: Handle inline edit of translation."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() == 4:  # Translation column
            # Update DTO
            entry = self.entries[index.row()]
            entry.translation = value

            # Emit data changed
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            return True

        return False

    def update_entries(self, entries: list, total_count: int):
        """Update the entry list and total count."""
        self.beginResetModel()
        self.entries = entries
        self.total_count = total_count
        self.endResetModel()

    def get_entry(self, row: int):
        """Get entry at row."""
        if 0 <= row < len(self.entries):
            return self.entries[row]
        return None


# ============================================================================
# M8: Term Card Table Model
# ============================================================================

class TermCardTableModel(QAbstractTableModel):
    """M8: Model for term card review queue."""

    def __init__(self, cards: list = None):
        super().__init__()
        from app.domain.dto import TermCardDTO
        self.cards: list[TermCardDTO] = cards or []
        self.headers = [
            "UD", "Term", "Lemma", "Freq", "DocFreq", "Status",
            "Pin Translation", "Aliases", "Stopword", "Last Review", "Niqqud", "Audio"
        ]

    def rowCount(self, parent=QModelIndex()):
        return len(self.cards)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        card = self.cards[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 10 and getattr(card, "pronunciation_text", None):
                source = getattr(card, "pronunciation_source", None) or "none"
                confidence = getattr(card, "pronunciation_confidence", None)
                qc = getattr(card, "pronunciation_qc", None) or "ok"
                conf_text = f"{float(confidence):.2f}" if confidence is not None else "n/a"
                return f"Niqqud: {card.pronunciation_text}\nSource: {source}\nConfidence: {conf_text}\nQC: {qc}"
            if col == 11 and getattr(card, "audio_status", None):
                return f"Audio: {card.audio_status}"
            study_tooltip = getattr(card, "study_tooltip", None)
            if study_tooltip and int(getattr(card, "in_user_dictionary_count", 0) or 0) > 0:
                return study_tooltip
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            return get_last_grade_row_brush(
                in_user_dictionary_count=int(getattr(card, "in_user_dictionary_count", 0) or 0),
                last_grade=getattr(card, "last_grade", None),
            )

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return ud_indicator_brush(
                    int(getattr(card, "in_user_dictionary_count", 0) or 0),
                    getattr(card, "study_state", None),
                )
            if col == 11 and getattr(card, "audio_status", None):
                return audio_status_brush(getattr(card, "audio_status", None))

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return ud_indicator_text(
                    int(getattr(card, "in_user_dictionary_count", 0) or 0),
                    getattr(card, "study_state", None),
                )
            elif col == 1:
                return card.representative_he
            elif col == 2:
                return card.representative_lemma or ""
            elif col == 3:
                return str(card.freq_abs)
            elif col == 4:
                return str(card.doc_freq)
            elif col == 5:
                return card.curation_status
            elif col == 6:
                return card.pinned_translation or ""
            elif col == 7:
                return ", ".join(card.aliases) if card.aliases else ""
            elif col == 8:
                return "Yes" if card.is_stopword else "No"
            elif col == 9:
                if int(getattr(card, "in_user_dictionary_count", 0) or 0) <= 0:
                    return ""
                return last_review_label(getattr(card, "last_grade", None))
            elif col == 10:
                return getattr(card, "pronunciation_text", "") or ""
            elif col == 11:
                return getattr(card, "audio_status", "") or ""

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def update_cards(self, cards: list):
        """Update the card list."""
        self.beginResetModel()
        self.cards = cards
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        """Enable deterministic header-click sorting for term cards."""
        if not self.cards:
            return

        reverse = order == Qt.SortOrder.DescendingOrder

        def _text(value) -> str:
            return str(value or "").casefold()

        def _key(card):
            if column == 0:
                return (int(getattr(card, "in_user_dictionary_count", 0) or 0), _text(card.representative_he), card.cluster_id)
            if column == 1:
                return (_text(card.representative_he), card.cluster_id)
            if column == 2:
                return (_text(card.representative_lemma), card.cluster_id)
            if column == 3:
                return (int(card.freq_abs or 0), card.cluster_id)
            if column == 4:
                return (int(card.doc_freq or 0), card.cluster_id)
            if column == 5:
                return (_text(card.curation_status), card.cluster_id)
            if column == 6:
                return (_text(card.pinned_translation), card.cluster_id)
            if column == 7:
                aliases = ", ".join(card.aliases) if card.aliases else ""
                return (_text(aliases), card.cluster_id)
            if column == 8:
                return (1 if card.is_stopword else 0, card.cluster_id)
            if column == 9:
                return (_text(last_review_label(getattr(card, "last_grade", None))), card.cluster_id)
            if column == 10:
                return (_text(getattr(card, "pronunciation_text", None)), card.cluster_id)
            if column == 11:
                return (_text(getattr(card, "audio_status", None)), card.cluster_id)
            return (card.cluster_id,)

        self.layoutAboutToBeChanged.emit()
        try:
            self.cards.sort(key=_key, reverse=reverse)
        finally:
            self.layoutChanged.emit()

    def get_card(self, row: int):
        """Get card at row."""
        if 0 <= row < len(self.cards):
            return self.cards[row]
        return None


class UserDictionaryListModel(QAbstractTableModel):
    """Model for user dictionaries list panel."""

    def __init__(self, dictionaries: list[UserDictionaryDTO] = None):
        super().__init__()
        self.dictionaries: list[UserDictionaryDTO] = dictionaries or []
        self.headers = ["Dictionary", "Items"]

    def rowCount(self, parent=QModelIndex()):
        return len(self.dictionaries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        dictionary = self.dictionaries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                pin = "[PIN] " if dictionary.is_pinned else ""
                return f"{pin}{dictionary.name}"
            if col == 1:
                return f"{dictionary.item_count:,}"
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def update_dictionaries(self, dictionaries: list[UserDictionaryDTO]):
        self.beginResetModel()
        self.dictionaries = dictionaries
        self.endResetModel()

    def get_dictionary(self, row: int) -> UserDictionaryDTO | None:
        if 0 <= row < len(self.dictionaries):
            return self.dictionaries[row]
        return None


class UserDictionaryItemsTableModel(QAbstractTableModel):
    """Model for user dictionary items table."""

    def __init__(self, items: list[UserDictionaryItemDTO] = None):
        super().__init__()
        self.items: list[UserDictionaryItemDTO] = items or []
        self.headers = [
            "Kind",
            "Source",
            "Translation",
            "Status",
            "Noise",
            "Study Status",
            "Last Review",
            "Project ID",
            "Project",
            "Origin",
            "Niqqud",
            "Audio",
        ]
        self.total_count = 0

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        item = self.items[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 6:
                last_review = last_review_label(item.last_grade, item.study_review_count)
                graded_at = item.last_graded_at or "n/a"
                due_at = item.study_due_at or "n/a"
                tooltip = (
                    f"Last review: {last_review}\n"
                    f"Last graded at: {graded_at}\n"
                    f"Review count: {item.study_review_count}\n"
                    f"Due at: {due_at}"
                )
                if int(item.is_noise or 0) == 1:
                    tooltip += "\nNoise: yes"
                if int(item.is_suspended or 0) == 1:
                    tooltip += "\nSuspended: yes"
                return tooltip
            if col == 10 and getattr(item, "pronunciation_text", None):
                source = getattr(item, "pronunciation_source", None) or "none"
                confidence = getattr(item, "pronunciation_confidence", None)
                qc = getattr(item, "pronunciation_qc", None) or "ok"
                conf_text = f"{float(confidence):.2f}" if confidence is not None else "n/a"
                return (
                    f"Niqqud: {item.pronunciation_text}\n"
                    f"Source: {source}\n"
                    f"Confidence: {conf_text}\n"
                    f"QC: {qc}"
                )
            if item.status_tooltip:
                return item.status_tooltip
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            if col == 6:
                return get_last_grade_cell_brush(item.last_grade, review_count=item.study_review_count)
            return None

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 3:
                return translation_tier_brush(item.translation_tier)
            if col == 4:
                return noise_brush(item.is_noise)
            if col == 5:
                return study_brush(item.computed_study_state)
            if col == 7:
                return origin_brush(item.origin_kind)
            if col == 11:
                return audio_status_brush(item.audio_status)
            return None

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return item.kind
            if col == 1:
                return item.src_text
            if col == 2:
                return item.translation or ""
            if col == 3:
                return compose_status_icons(
                    translation_tier=item.translation_tier,
                    audio_status=item.audio_status,
                    is_noise=item.is_noise,
                )
            if col == 4:
                return "Noise" if item.is_noise == 1 else "Valid"
            if col == 5:
                return study_chip(item.computed_study_state)
            if col == 6:
                return last_review_label(item.last_grade, item.study_review_count)
            if col == 7:
                return str(item.origin_project_id) if item.origin_project_id is not None else "-"
            if col == 8:
                if item.origin_project_name:
                    return item.origin_project_name
                if item.origin_project_id is not None:
                    return f"Project #{int(item.origin_project_id)}"
                return "-"
            if col == 9:
                return origin_marker(item.origin_kind)
            if col == 10:
                return item.pronunciation_text or ""
            if col == 11:
                return item.audio_status
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)
        if index.column() == 2:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() != 2:
            return False

        item = self.items[index.row()]
        item.translation = "" if value is None else str(value)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        return True

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def update_items(self, items: list[UserDictionaryItemDTO], total_count: int):
        self.beginResetModel()
        self.items = items
        self.total_count = total_count
        self.endResetModel()

    def get_item(self, row: int) -> UserDictionaryItemDTO | None:
        if 0 <= row < len(self.items):
            return self.items[row]
        return None


# ---------------------------------------------------------------------------
# PATCH-G: DocumentsTableModel
# ---------------------------------------------------------------------------

class DocumentsTableModel(QAbstractTableModel):
    """Model for the Documents tab table (12 columns).

    Replaces QTableWidget in DocumentsView, enabling Qt virtualized rendering.
    COL_NAME (1) is editable — rename triggers rename_committed signal.
    """

    COL_ID = 0
    COL_NAME = 1
    COL_SIZE = 2
    COL_STATUS = 3
    COL_SENTENCES = 4
    COL_TOKENS = 5
    COL_IMPORTED = 6
    COL_PATH = 7
    COL_TAG = 8
    COL_LINK = 9
    COL_LEVEL = 10
    COL_TOPIC = 11

    HEADERS = [
        "ID", "File Name", "Size (KB)", "Status", "Sentences", "Tokens",
        "Imported", "Path", "Tag", "Link", "Level", "Topic",
    ]

    # Emitted by setData when user commits a rename; view handles the DB write.
    rename_committed = pyqtSignal(int, str)  # doc_id, new_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[DocumentDTO] = []
        self._sort_col: int = -1
        self._sort_dir: str = "asc"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_rows(self, dtos: list[DocumentDTO]) -> None:
        self.beginResetModel()
        self._rows = list(dtos)
        self.endResetModel()

    def set_sort_indicator(self, col: int, direction: str) -> None:
        """Update header sort arrow without resetting row data."""
        self._sort_col = col
        self._sort_dir = direction
        self.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, len(self.HEADERS) - 1
        )

    def get_dto(self, row: int) -> DocumentDTO | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    # ------------------------------------------------------------------
    # QAbstractTableModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            base = self.HEADERS[section]
            if self._sort_col == section:
                indicator = " \u25b2" if self._sort_dir == "asc" else " \u25bc"
                return base + indicator
            return base
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row >= len(self._rows):
            return None
        dto = self._rows[row]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == self.COL_ID:        return str(dto.doc_id)
            if col == self.COL_NAME:      return dto.file_name
            if col == self.COL_SIZE:      return f"{dto.file_size_bytes / 1024:.1f}"
            if col == self.COL_STATUS:    return dto.status
            if col == self.COL_SENTENCES: return str(dto.sentence_count) if dto.sentence_count else ""
            if col == self.COL_TOKENS:    return str(dto.token_count) if dto.token_count else ""
            if col == self.COL_IMPORTED:  return (dto.imported_at or "")[:19]
            if col == self.COL_PATH:      return dto.file_path or ""
            if col == self.COL_TAG:       return dto.tag or ""
            if col == self.COL_LINK:      return dto.link_url or ""
            if col == self.COL_LEVEL:     return dto.level or ""
            if col == self.COL_TOPIC:     return dto.topic or ""

        if role == Qt.ItemDataRole.UserRole:
            return dto.doc_id  # row → doc_id for all columns

        if role == Qt.ItemDataRole.UserRole + 1:
            if col == self.COL_LINK:
                return dto.link_url  # raw URL for click handler

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == self.COL_LINK and dto.link_url:
                return QColor(Qt.GlobalColor.blue)

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_LINK and dto.link_url:
                return f"Click to open: {dto.link_url}"

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == self.COL_NAME:
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.EditRole and index.column() == self.COL_NAME:
            row = index.row()
            if 0 <= row < len(self._rows):
                new_name = str(value).strip()
                if new_name and new_name != self._rows[row].file_name:
                    self.rename_committed.emit(self._rows[row].doc_id, new_name)
                return True
        return False


# ---------------------------------------------------------------------------
# PATCH-G: SentencesTableModel
# ---------------------------------------------------------------------------

class SentencesTableModel(QAbstractTableModel):
    """Model for the Sentences workspace table (8 columns, read-only).

    Replaces QTableWidget in SentencesView. Handles QC badge colours,
    audio status colours, and niqqud tooltip without per-cell QTableWidgetItems.
    """

    COL_ID = 0
    COL_DOC = 1
    COL_IDX = 2
    COL_TEXT = 3
    COL_TRANSLATION = 4
    COL_NIQQUD = 5
    COL_QC = 6
    COL_AUDIO = 7

    HEADERS = ["ID", "Document", "#", "Sentence Text", "Translation", "Niqqud", "QC", "Audio"]

    _QC_MAP = {
        "ok":        ("\u2713", "darkGreen"),
        "auto_fixed": ("~",     "olive"),
        "partial":   ("~",      "darkorange"),
        "rejected":  ("\u2717", "red"),
        "failed":    ("!",      "red"),
        "pending":   ("\u2026", "gray"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[SentenceDTO] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_rows(self, dtos: list[SentenceDTO]) -> None:
        self.beginResetModel()
        self._rows = list(dtos)
        self.endResetModel()

    def get_dto(self, row: int) -> SentenceDTO | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    # ------------------------------------------------------------------
    # QAbstractTableModel interface
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row >= len(self._rows):
            return None
        dto = self._rows[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_ID:          return str(dto.sentence_id)
            if col == self.COL_DOC:         return dto.doc_name
            if col == self.COL_IDX:         return str(dto.sent_index)
            if col == self.COL_TEXT:        return dto.text
            if col == self.COL_TRANSLATION: return dto.translation or ""
            if col == self.COL_NIQQUD:      return dto.pronunciation_text or ""
            if col == self.COL_AUDIO:       return dto.audio_status or "\u2014"
            if col == self.COL_QC:
                badge, _ = self._QC_MAP.get(dto.niqqud_qc, (dto.niqqud_qc[:2] if dto.niqqud_qc else "\u2014", None))
                return badge

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == self.COL_QC:
                _, color_name = self._QC_MAP.get(dto.niqqud_qc, (None, None))
                if color_name:
                    return QColor(color_name)
            if col == self.COL_AUDIO:
                if dto.audio_status == "ready":  return QColor(Qt.GlobalColor.darkGreen)
                if dto.audio_status == "failed": return QColor(Qt.GlobalColor.red)

        if role == Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_NIQQUD and dto.pronunciation_text:
                cov = f"{dto.niqqud_coverage * 100:.0f}%" if dto.niqqud_coverage is not None else "\u2014"
                conf = f"{dto.niqqud_confidence:.2f}" if dto.niqqud_confidence is not None else "\u2014"
                override = "manual override" if dto.niqqud_is_override else "auto"
                em = "\u2014"
                return "\n".join([
                    f"Source: {dto.niqqud_source or em}  ({override})",
                    f"Confidence: {conf}",
                    f"Coverage: {cov}",
                    f"QC: {dto.niqqud_qc or em}",
                ])
            if col == self.COL_QC and dto.niqqud_qc:
                return f"QC status: {dto.niqqud_qc}"

        if role == Qt.ItemDataRole.UserRole:
            return dto.sentence_id

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
