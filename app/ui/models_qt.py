"""Qt models for tables and lists."""
import logging
from typing import List

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from app.domain.dto import (
    ProjectStats,
    LemmaStats,
    UserDictionaryDTO,
    UserDictionaryItemDTO,
)
from app.ui.study_status_ui import (
    audio_status_brush,
    compose_status_icons,
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

    def __init__(self, projects: List[ProjectStats] = None):
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

    def update_projects(self, projects: List[ProjectStats]):
        """Update the project list."""
        self.beginResetModel()
        self.projects = projects
        self.endResetModel()


class LemmaTableModel(QAbstractTableModel):
    """Model for lemma/dictionary table with M7 translation support."""

    def __init__(self, lemmas: List[LemmaStats] = None):
        super().__init__()
        self.lemmas = lemmas or []
        # M7: Added Source column between Translation and Status
        # Added Noise column for is_noise visualization
        self.headers = ["UD", "Lemma", "POS", "Frequency", "Doc Freq", "Translation", "Source", "Status", "Noise"]
        # M7: Store full TranslationResult for each lemma (for Why dialog)
        from app.services.translation_service import TranslationResult
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
            if lemma.study_tooltip and int(getattr(lemma, "in_user_dictionary_count", 0) or 0) > 0:
                return lemma.study_tooltip
            return None

        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            return ud_indicator_brush(
                int(getattr(lemma, "in_user_dictionary_count", 0) or 0),
                getattr(lemma, "study_state", None),
            )

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
                # Noise column
                if lemma.is_noise == 1:
                    return "Noise"
                elif lemma.is_noise == 0:
                    return "Valid"
                else:
                    return ""  # NULL - legacy records

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

    def update_lemmas(self, lemmas: List[LemmaStats]):
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

    def __init__(self, clusters: List = None):
        super().__init__()
        from app.domain.dto import ClusterStats
        self.clusters: List[ClusterStats] = clusters or []
        # M7: Added Translation, Source, Status columns
        # Added Noise column for is_noise visualization
        self.headers = [
            "UD", "Term", "Lemma", "Freq", "DocFreq", "Members", "PMI", "LLR", "Dice",
            "Weirdness", "Keyness", "Termhood", "Translation", "Source", "Status", "Noise"
        ]
        # M7: Store full TranslationResult for each cluster
        from app.services.translation_service import TranslationResult
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
            if cluster.study_tooltip and int(getattr(cluster, "in_user_dictionary_count", 0) or 0) > 0:
                return cluster.study_tooltip
            return None

        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            return ud_indicator_brush(
                int(getattr(cluster, "in_user_dictionary_count", 0) or 0),
                getattr(cluster, "study_state", None),
            )

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
                return f"{cluster.keyness_llr:.2f}" if cluster.keyness_llr else "N/A"
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

    def update_clusters(self, clusters: List):
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

    def __init__(self, entries: List = None):
        super().__init__()
        from app.domain.dto import TMEntryDTO
        self.entries: List[TMEntryDTO] = entries or []
        # Added Noise column for is_noise visualization
        self.headers = [
            "UD", "ID", "Kind", "Source", "Translation", "Status",
            "Scope", "Origin", "Source Ref", "Updated", "Noise"
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
            if entry.study_tooltip and int(getattr(entry, "in_user_dictionary_count", 0) or 0) > 0:
                return entry.study_tooltip
            return None

        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            return ud_indicator_brush(
                int(getattr(entry, "in_user_dictionary_count", 0) or 0),
                getattr(entry, "study_state", None),
            )

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

    def update_entries(self, entries: List, total_count: int):
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

    def __init__(self, cards: List = None):
        super().__init__()
        from app.domain.dto import TermCardDTO
        self.cards: List[TermCardDTO] = cards or []
        self.headers = [
            "UD", "Term", "Lemma", "Freq", "DocFreq", "Status",
            "Pin Translation", "Aliases", "Stopword"
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
            study_tooltip = getattr(card, "study_tooltip", None)
            if study_tooltip and int(getattr(card, "in_user_dictionary_count", 0) or 0) > 0:
                return study_tooltip
            return None

        if role == Qt.ItemDataRole.ForegroundRole and col == 0:
            return ud_indicator_brush(
                int(getattr(card, "in_user_dictionary_count", 0) or 0),
                getattr(card, "study_state", None),
            )

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

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def update_cards(self, cards: List):
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

    def __init__(self, dictionaries: List[UserDictionaryDTO] = None):
        super().__init__()
        self.dictionaries: List[UserDictionaryDTO] = dictionaries or []
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

    def update_dictionaries(self, dictionaries: List[UserDictionaryDTO]):
        self.beginResetModel()
        self.dictionaries = dictionaries
        self.endResetModel()

    def get_dictionary(self, row: int) -> UserDictionaryDTO | None:
        if 0 <= row < len(self.dictionaries):
            return self.dictionaries[row]
        return None


class UserDictionaryItemsTableModel(QAbstractTableModel):
    """Model for user dictionary items table."""

    def __init__(self, items: List[UserDictionaryItemDTO] = None):
        super().__init__()
        self.items: List[UserDictionaryItemDTO] = items or []
        self.headers = [
            "Kind",
            "Source",
            "Translation",
            "Status",
            "Noise",
            "Study",
            "Origin",
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
            if item.status_tooltip:
                return item.status_tooltip
            return None

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 3:
                return translation_tier_brush(item.translation_tier)
            if col == 4:
                return noise_brush(item.is_noise)
            if col == 5:
                return study_brush(item.computed_study_state)
            if col == 6:
                return origin_brush(item.origin_kind)
            if col == 7:
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
                return origin_marker(item.origin_kind)
            if col == 7:
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

    def update_items(self, items: List[UserDictionaryItemDTO], total_count: int):
        self.beginResetModel()
        self.items = items
        self.total_count = total_count
        self.endResetModel()

    def get_item(self, row: int) -> UserDictionaryItemDTO | None:
        if 0 <= row < len(self.items):
            return self.items[row]
        return None
