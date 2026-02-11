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
    is_general_corpus: bool = False  # True if reference corpus (read-only documents)


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
    entity_class: Optional[str] = None
    is_noise: Optional[int] = None
    noise_reason: Optional[str] = None
    norm_text: Optional[str] = None


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
    np_chunks_extracted: int  # M5.3: NP chunks
    clusters_created: int
    success: bool
    error_message: Optional[str] = None


@dataclass
class ClusterStats:
    """Term cluster statistics (M5.1 + M5.4)."""

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
    # M5.4: Termhood metrics vs reference corpus
    weirdness: Optional[float] = None
    keyness_llr: Optional[float] = None
    termhood_score: Optional[float] = None
    # M7: Translation
    translation: Optional[str] = None
    translation_source: Optional[str] = None  # tm|dict|mt_cache|mt|none
    translation_status: Optional[str] = None  # approved|draft
    # Task 11: Entity classification
    entity_class: Optional[str] = None
    is_noise: Optional[int] = None
    noise_reason: Optional[str] = None
    norm_text: Optional[str] = None


@dataclass
class TranslationResultDTO:
    """M7 Translation result for UI layer."""

    translation: Optional[str] = None
    source: str = "none"  # tm|dict|mt_cache|mt|none
    status: Optional[str] = None  # approved|draft|rejected|deprecated
    confidence: Optional[float] = None
    origin: Optional[str] = None  # user_edit|import|mt_accept|mt_auto
    matched_on: Optional[str] = None  # src_norm|alias_norm|variant_norm
    match_key_used: Optional[str] = None
    provider: Optional[str] = None  # MT provider name
    dict_source_name: Optional[str] = None
    tm_id: Optional[int] = None
    notes: Optional[str] = None


# ============================================================================
# P2: Translation Management & QA/Coverage DTOs
# ============================================================================

@dataclass
class TMEntryDTO:
    """P2: TM Entry for management panel."""

    tm_id: int
    project_id: Optional[int]  # None = global
    kind: str  # lemma|ngram|term_cluster|surface
    src_lang: str
    tgt_lang: str
    src_text: str
    src_norm: str
    translation: str
    translation_norm: Optional[str]
    pos: Optional[str]
    domain: Optional[str]
    notes: Optional[str]
    status: str  # draft|approved|rejected|deprecated
    confidence: Optional[float]
    origin: str  # user_edit|import|mt_accept|mt_auto|merge
    source_ref: Optional[str]
    created_at: str
    updated_at: str
    approved_at: Optional[str]
    approved_by: Optional[str]


@dataclass
class TMHistoryDTO:
    """P2: TM History entry."""

    hist_id: int
    tm_id: int
    version: int
    translation: str
    notes: Optional[str]
    status: str
    origin: str
    changed_at: str
    change_kind: str  # edit|import|merge|revert|approve|reject|deprecate


@dataclass
class CoverageMetrics:
    """P2: Coverage metrics for lemmas or term clusters."""

    total: int
    covered: int
    uncovered: int
    coverage_pct: float


@dataclass
class LemmaCoverageRow:
    """P2: Untranslated lemma row."""

    lemma_id: int
    lemma_text: str
    pos: Optional[str]
    freq_abs: int
    doc_freq: int


@dataclass
class TermClusterCoverageRow:
    """P2: Untranslated term cluster row."""

    cluster_id: int
    representative_he: str
    canonical_key: str
    freq_abs: int
    doc_freq: int
    termhood_score: Optional[float]


# ============================================================================
# P3: Dictionary Import DTOs
# ============================================================================


@dataclass
class ImportRow:
    """P3: Parsed row from import file."""

    row_index: int
    kind: str
    src_lang: str
    tgt_lang: str
    src_text: str
    translation: str
    pos: Optional[str] = None
    domain: Optional[str] = None
    status: str = "approved"
    priority: Optional[int] = None
    notes: Optional[str] = None
    aliases: Optional[List[str]] = None  # Additional src_text variants


@dataclass
class ImportInvalidRow:
    """P3: Invalid row details."""

    row_index: int
    reason: str


@dataclass
class ImportConflict:
    """P3: Conflict details."""

    row_index: int
    src_text: str
    src_norm: str
    existing_translation: str
    incoming_translation: str
    action_taken: str  # "skipped", "overwritten", "kept_both"


@dataclass
class ImportReport:
    """P3: Import operation report."""

    total: int
    added: int
    updated: int
    skipped: int
    conflicts: int
    invalid: int
    invalid_rows: List[ImportInvalidRow]
    conflict_details: List[ImportConflict]
    dict_source_id: Optional[int]
    sha256: str
    elapsed_ms: float


@dataclass
class TermCardDTO:
    """M8: Term card with curation metadata."""

    cluster_id: int
    project_id: int
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
    tfidf: Optional[float]
    weirdness: Optional[float]
    source_kinds: Optional[str]
    curation_status: str  # auto/needs_review/approved/rejected
    pinned_translation: Optional[str]
    pinned_translation_lang: Optional[str]
    pinned_example_sent_id: Optional[int]
    pinned_example_text: Optional[str]
    curation_notes: Optional[str]
    curated_at: Optional[str]
    curated_by: Optional[str]
    aliases: List[str]  # Variant forms
    is_stopword: bool
    created_at: str
    updated_at: str
