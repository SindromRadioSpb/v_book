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
    """Model for lemma/dictionary table."""

    def __init__(self, lemmas: List[LemmaStats] = None):
        super().__init__()
        self.lemmas = lemmas or []
        self.headers = ["Lemma", "POS", "Frequency", "Doc Freq", "Translation", "Status"]

    def rowCount(self, parent=QModelIndex()):
        return len(self.lemmas)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None

        lemma = self.lemmas[index.row()]
        col = index.column()

        if col == 0:
            return lemma.lemma_text
        elif col == 1:
            return lemma.pos or ""
        elif col == 2:
            return str(lemma.freq_abs)
        elif col == 3:
            return str(lemma.doc_freq)
        elif col == 4:
            return lemma.translation or ""
        elif col == 5:
            return lemma.status

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return None

    def update_lemmas(self, lemmas: List[LemmaStats]):
        """Update the lemma list."""
        self.beginResetModel()
        self.lemmas = lemmas
        self.endResetModel()

    def get_lemma(self, row: int) -> LemmaStats:
        """Get lemma at row."""
        if 0 <= row < len(self.lemmas):
            return self.lemmas[row]
        return None
