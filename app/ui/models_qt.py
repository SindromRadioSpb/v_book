"""Qt models for tables and lists."""
import logging
from typing import List

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex
from app.domain.dto import ProjectStats, LemmaStats

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
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None

        project = self.projects[index.row()]
        col = index.column()

        if col == 0:
            return str(project.project_id)
        elif col == 1:
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
        self.headers = ["Lemma", "POS", "Frequency", "Doc Freq", "Translation", "Source", "Status"]
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

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == 0:
                return lemma.lemma_text
            elif col == 1:
                return lemma.pos or ""
            elif col == 2:
                return str(lemma.freq_abs)
            elif col == 3:
                return str(lemma.doc_freq)
            elif col == 4:
                # M7: Translation from DTO
                return lemma.translation or ""
            elif col == 5:
                # M7: Source (tm|dict|mt_cache|mt|none)
                tr_result = self.translation_results.get(index.row())
                if tr_result:
                    return tr_result.source
                return "none"
            elif col == 6:
                # M7: Status
                return lemma.status

        return None

    def flags(self, index):
        """M7: Make Translation column editable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)

        # Column 4 (Translation) is editable
        if index.column() == 4:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """M7: Handle inline edit of translation."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() == 4:  # Translation column
            # Update DTO
            lemma = self.lemmas[index.row()]
            lemma.translation = value
            lemma.status = "draft"  # User edit → draft status

            # Emit data changed
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

            # Also emit for Status column (col 6) since it changed
            status_idx = self.index(index.row(), 6)
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
                trans_idx = self.index(row, 4)
                status_idx = self.index(row, 6)
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
        self.headers = [
            "Term", "Lemma", "Freq", "DocFreq", "Members", "PMI", "LLR", "Dice",
            "Weirdness", "Keyness", "Termhood", "Translation", "Source", "Status"
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

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if col == 0:
                return cluster.representative_he
            elif col == 1:
                return cluster.representative_lemma or ""
            elif col == 2:
                return str(cluster.freq_abs)
            elif col == 3:
                return str(cluster.doc_freq)
            elif col == 4:
                return str(cluster.members_count)
            elif col == 5:
                return f"{cluster.best_pmi:.2f}" if cluster.best_pmi else "N/A"
            elif col == 6:
                return f"{cluster.best_llr:.2f}" if cluster.best_llr else "N/A"
            elif col == 7:
                return f"{cluster.best_dice:.3f}" if cluster.best_dice else "N/A"
            elif col == 8:
                return f"{cluster.weirdness:.2f}" if cluster.weirdness else "N/A"
            elif col == 9:
                return f"{cluster.keyness_llr:.2f}" if cluster.keyness_llr else "N/A"
            elif col == 10:
                return f"{cluster.termhood_score:.2f}" if cluster.termhood_score else "N/A"
            elif col == 11:
                # M7: Translation
                return cluster.translation or ""
            elif col == 12:
                # M7: Source
                return cluster.translation_source or "none"
            elif col == 13:
                # M7: Status
                return cluster.translation_status or "none"

        return None

    def flags(self, index):
        """M7: Make Translation column editable."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags

        flags = super().flags(index)

        # Column 11 (Translation) is editable
        if index.column() == 11:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """M7: Handle inline edit of translation."""
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        if index.column() == 11:  # Translation column
            # Update DTO
            cluster = self.clusters[index.row()]
            cluster.translation = value
            cluster.translation_status = "draft"  # User edit → draft

            # Emit data changed
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])

            # Also emit for Status column (col 13)
            status_idx = self.index(index.row(), 13)
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
            # Use canonical_key for matching (since that's what normalization produces)
            key = (cluster.canonical_key, "term_cluster")
            if key in results:
                tr_result = results[key]

                # Update DTO
                cluster.translation = tr_result.translation
                cluster.translation_source = tr_result.source
                cluster.translation_status = tr_result.status or "none"

                # Cache full result for Why dialog
                self.translation_results[row] = tr_result

                # Emit dataChanged for Translation, Source, Status columns
                trans_idx = self.index(row, 11)
                status_idx = self.index(row, 13)
                self.dataChanged.emit(trans_idx, status_idx, [Qt.ItemDataRole.DisplayRole])

    def get_cluster(self, row: int):
        """Get cluster at row."""
        if 0 <= row < len(self.clusters):
            return self.clusters[row]
        return None

    def get_translation_result(self, row: int):
        """M7: Get cached TranslationResult for Why dialog."""
        return self.translation_results.get(row)
