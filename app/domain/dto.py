"""Data Transfer Objects."""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ProjectStats:
    """Project statistics."""

    project_id: int
    name: str
    total_docs: int
    processed_docs: int
    total_lemmas: int
    total_ngrams: int


@dataclass
class LemmaStats:
    """Lemma statistics."""

    lemma_id: int
    lemma_text: str
    pos: Optional[str]
    freq_abs: int
    doc_freq: int
    translation: Optional[str] = None
    status: str = "auto"


@dataclass
class NgramStats:
    """N-gram statistics."""

    ngram_id: int
    surface_text: str
    n: int
    freq_abs: int
    doc_freq: int
    pmi: Optional[float]
    tscore: Optional[float]
    translation: Optional[str] = None
    status: str = "auto"


@dataclass
class KWICResult:
    """KWIC concordance result."""

    sentence_id: int
    doc_id: int
    doc_name: str
    left_context: str
    match: str
    right_context: str


@dataclass
class DeleteReport:
    """Report of project deletion results."""

    project_id: int
    project_name: str
    corpora_deleted: int
    documents_deleted: int
    sentences_deleted: int
    lemmas_deleted: int
    ngrams_deleted: int
    term_cards_deleted: int
    success: bool
    error_message: Optional[str] = None


@dataclass
class ExtractReport:
    """Report of term extraction results (M5)."""

    project_id: int
    ngrams_extracted: int
    clusters_created: int
    success: bool
    error_message: Optional[str] = None


@dataclass
class ClusterStats:
    """Term cluster statistics (M5.1)."""

    cluster_id: int
    canonical_key: str
    representative_he: str
    representative_lemma: Optional[str]
    freq_abs: int
    doc_freq: int
    members_count: int
    best_pmi: Optional[float]
    best_llr: Optional[float]
    best_dice: Optional[float]
    best_tscore: Optional[float]
