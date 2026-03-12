"""Data Transfer Objects."""
from dataclasses import dataclass, field
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
    saved_to_ud: bool = False
    in_user_dictionary_count: int = 0
    study_state: Optional[str] = None
    study_due_human: Optional[str] = None
    last_grade: Optional[str] = None
    last_graded_at: Optional[str] = None
    translation_tier: Optional[str] = None
    audio_status: Optional[str] = None
    study_tooltip: Optional[str] = None
    pronunciation_text: Optional[str] = None
    pronunciation_source: Optional[str] = None
    pronunciation_confidence: Optional[float] = None
    pronunciation_qc: Optional[str] = None


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
class DocumentDTO:
    """Document metadata DTO (Migration 023 fields included)."""

    doc_id: int
    corpus_id: int
    file_name: str
    file_path: str
    file_size_bytes: int
    status: str
    sentence_count: int
    token_count: int
    imported_at: str
    processed_at: Optional[str] = None
    # Metadata fields (Migration 023)
    tag: Optional[str] = None
    link_url: Optional[str] = None
    level: Optional[str] = None    # aleph | bet | gimel | he
    topic: Optional[str] = None


@dataclass
class SentenceNiqqudOverlay:
    """Sentence-level niqqud overlay from sentence_pronunciation table (Migration 024)."""

    sentence_id: int
    niqqud_text: Optional[str]
    qc_status: str          # ok | auto_fixed | partial | rejected | failed | pending
    qc_reason: Optional[str]
    source: str             # auto_phonikud | manual | import_csv
    confidence: Optional[float]
    niqqud_coverage: Optional[float]
    is_override: bool
    review_status: str      # auto | pending_review | approved | rejected_by_user


@dataclass
class SentenceDTO:
    """A single sentence from document_sentence with overlay data."""

    sentence_id: int
    doc_id: int
    doc_name: str
    sent_index: int
    text: str
    # TM overlay
    translation: Optional[str] = None
    translation_status: Optional[str] = None
    translation_source: Optional[str] = None
    # Sentence niqqud overlay (sentence_pronunciation table, Migration 024)
    pronunciation_text: Optional[str] = None   # effective niqqud_text
    niqqud_qc: Optional[str] = None            # qc_status badge
    niqqud_source: Optional[str] = None
    niqqud_confidence: Optional[float] = None
    niqqud_coverage: Optional[float] = None
    niqqud_is_override: bool = False
    niqqud_review: Optional[str] = None
    # Audio overlay
    audio_status: Optional[str] = None


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
    cancelled: bool = False
    run_id: Optional[int] = None
    docs_processed: int = 0
    docs_total: int = 0
    snapshot_rows_used: int = 0
    reparsed_sentences: int = 0
    snapshot_reuse_pct: Optional[float] = None


@dataclass
class SnapshotReadinessSummaryDTO:
    """Read-only snapshot coverage and latest backfill readiness summary."""

    project_id: int
    project_name: str
    is_general_corpus: bool
    is_reference_project: bool
    processed_docs: int
    fully_covered_docs: int
    zero_snapshot_docs: int
    partial_snapshot_docs: int
    remaining_uncovered_docs: int
    sentence_count_total: int
    snapshot_count_total: int
    sentence_coverage_pct: Optional[float]
    doc_coverage_pct: Optional[float]
    stats_valid_docs: int = 0
    stats_unknown_docs: int = 0
    stats_invalid_docs: int = 0
    coverage_is_degraded: bool = False
    coverage_source: str = "snapshot_doc_stats"
    latest_backfill_run_id: Optional[int] = None
    latest_backfill_status: Optional[str] = None
    latest_backfill_stage: Optional[str] = None
    latest_backfill_last_doc_id: Optional[int] = None
    latest_backfill_finished_at: Optional[str] = None
    latest_backfill_docs_processed: int = 0
    latest_backfill_docs_total: int = 0
    contract_state: str = "no_snapshot_coverage"
    contract_note: Optional[str] = None
    summary_note: Optional[str] = None
    last_refreshed_at: Optional[str] = None


@dataclass
class DerivedArtifactMetricDTO:
    """Read-only governance summary for one derived processing artifact."""

    artifact_key: str
    display_name: str
    ownership: str
    quantity_value: int
    quantity_unit: str
    quantity_basis: str
    status: str
    summary: str
    detail_lines: List[str] = field(default_factory=list)
    maintenance_mode: Optional[str] = None
    maintenance_note: Optional[str] = None
    maintenance_cli_hint: Optional[str] = None
    maintenance_preflight_hint: Optional[str] = None


@dataclass
class DerivedArtifactGovernanceSummaryDTO:
    """Read-only project-scoped governance summary for heavy derived artifacts."""

    project_id: int
    project_name: str
    is_reference_project: bool
    total_docs: int
    processed_docs: int
    observability_note: str
    storage_note: str
    snapshot_sentence_coverage_pct: Optional[float] = None
    snapshot_doc_coverage_pct: Optional[float] = None
    lifecycle_note: Optional[str] = None
    snapshot_contract_note: Optional[str] = None
    last_refreshed_at: Optional[str] = None
    artifacts: List[DerivedArtifactMetricDTO] = field(default_factory=list)


@dataclass
class ProjectTelemetryRetentionSummaryDTO:
    """Dry-run/apply summary for project-scoped processor telemetry retention."""

    project_id: int
    project_name: str
    keep_latest_ok: int
    total_runs: int
    ok_runs: int
    non_ok_runs: int
    noted_ok_runs: int
    kept_recent_ok_runs: int
    prunable_ok_runs: int
    prunable_run_error_rows: int
    oldest_prunable_run_id: Optional[int] = None
    newest_prunable_run_id: Optional[int] = None
    applied: bool = False
    deleted_runs: int = 0
    deleted_run_errors: int = 0
    summary_note: Optional[str] = None
    vacuum_note: Optional[str] = None


@dataclass
class NLPProcessRunState:
    """Structured NLP processing run state for staged/resumable flows."""

    run_id: int
    project_id: int
    status: str
    stage: Optional[str]
    docs_total: int
    docs_processed: int
    docs_failed: int
    chunks_total: int
    chunks_completed: int
    last_doc_id: Optional[int] = None
    params_hash: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class TermExtractionRunState:
    """Structured staged term extraction run state."""

    run_id: int
    project_id: int
    status: str
    stage: Optional[str]
    docs_total: int
    docs_processed: int
    docs_failed: int
    chunks_total: int
    chunks_completed: int
    last_doc_id: Optional[int] = None
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
    saved_to_ud: bool = False
    in_user_dictionary_count: int = 0
    study_state: Optional[str] = None
    study_due_human: Optional[str] = None
    last_grade: Optional[str] = None
    last_graded_at: Optional[str] = None
    translation_tier: Optional[str] = None
    audio_status: Optional[str] = None
    study_tooltip: Optional[str] = None
    pronunciation_text: Optional[str] = None
    pronunciation_source: Optional[str] = None
    pronunciation_confidence: Optional[float] = None
    pronunciation_qc: Optional[str] = None


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
    is_noise: Optional[int]  # 0=not noise, 1=noise, None=legacy
    noise_reason: Optional[str]  # NOISE_PUNCT_ONLY, NOISE_NUMBER_ONLY, etc.
    norm_text: Optional[str]  # Normalized text for noise detection
    # Source entity links (for is_noise synchronization)
    lemma_id: Optional[int]
    cluster_id: Optional[int]
    ngram_id: Optional[int]
    # Global TM canonical link (Task 19)
    tm_global_id: Optional[int] = None
    # Study/meta indicators (non-intrusive overlays)
    in_user_dictionary_count: int = 0
    study_state: Optional[str] = None
    study_due_human: Optional[str] = None
    last_grade: Optional[str] = None
    last_graded_at: Optional[str] = None
    study_tooltip: Optional[str] = None
    audio_status: Optional[str] = None
    pronunciation_text: Optional[str] = None
    pronunciation_source: Optional[str] = None
    pronunciation_confidence: Optional[float] = None
    pronunciation_qc: Optional[str] = None
    raw_src_norm: Optional[str] = None


@dataclass
class UserDictionaryDTO:
    """User dictionary metadata for UI."""

    dictionary_id: int
    name: str
    description: Optional[str]
    is_pinned: int
    sort_order: int
    created_at: str
    updated_at: str
    item_count: int = 0


@dataclass
class UserDictionaryItemDTO:
    """User dictionary item with resolved canonical translation fields."""

    item_id: int
    dictionary_id: int
    kind: str
    src_lang: str
    tgt_lang: str
    src_text: str
    src_norm: str
    canonical_hash: str
    tags_json: str
    notes: Optional[str]
    is_noise: int
    noise_reason: Optional[str]
    study_state: str
    study_progress_id: Optional[int]
    is_suspended: int
    suspended_reason: Optional[str]
    last_seen_at: Optional[str]
    seen_count: int
    origin_project_id: Optional[int]
    origin_project_name: Optional[str]
    origin_entity_type: Optional[str]
    origin_entity_id: Optional[str]
    origin_tm_entry_id: Optional[int]
    origin_doc_id: Optional[int]
    origin_source_ref: Optional[str]
    created_at: str
    updated_at: str
    translation: Optional[str] = None
    translation_status: Optional[str] = None
    translation_origin: Optional[str] = None
    translation_confidence: Optional[float] = None
    tm_global_id: Optional[int] = None
    audio_status: str = "missing"
    origin_kind: str = "manual"
    computed_study_state: str = "new"
    study_due_human: Optional[str] = None
    study_due_at: Optional[str] = None
    study_review_count: int = 0
    study_lapse_count: int = 0
    study_interval_days: int = 0
    study_ease_factor: float = 2.5
    last_grade: Optional[str] = None
    last_graded_at: Optional[str] = None
    translation_tier: str = "missing"
    status_tooltip: Optional[str] = None
    pronunciation_text: Optional[str] = None
    pronunciation_source: Optional[str] = None
    pronunciation_confidence: Optional[float] = None
    pronunciation_qc: Optional[str] = None


@dataclass
class PronunciationEntryDTO:
    """Pronunciation entry payload."""

    entry_id: Optional[int]
    lang: str
    src_norm: str
    niqqud_text: Optional[str]
    ipa: Optional[str]
    reading_text: Optional[str]
    source: str
    confidence: Optional[float]
    is_override: int
    notes: Optional[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class StudyProgressSummaryDTO:
    """Computed SRS summary for one canonical hash."""

    progress_id: Optional[int]
    canonical_hash: str
    first_seen_at: Optional[str]
    last_review_at: Optional[str]
    due_at: Optional[str]
    review_count: int
    lapse_count: int
    interval_days: int
    ease_factor: float
    last_quality: Optional[int]
    last_grade: Optional[str] = None
    last_graded_at: Optional[str] = None
    is_suspended: bool = False
    study_state: str = "new"
    due_human: Optional[str] = None


@dataclass
class StudyCardDTO:
    """Review queue card payload."""

    item_id: int
    dictionary_id: int
    canonical_hash: str
    kind: str
    src_lang: str
    tgt_lang: str
    src_text: str
    src_norm: str
    translation: str
    translation_tier: str
    origin_kind: str
    study_state: str
    due_human: Optional[str]
    progress_id: Optional[int]
    review_count: int
    lapse_count: int
    interval_days: int
    ease_factor: float


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
    in_user_dictionary_count: int = 0
    study_state: Optional[str] = None
    study_due_human: Optional[str] = None
    last_grade: Optional[str] = None
    last_graded_at: Optional[str] = None
    study_tooltip: Optional[str] = None
    audio_status: Optional[str] = None
    pronunciation_text: Optional[str] = None
    pronunciation_source: Optional[str] = None
    pronunciation_confidence: Optional[float] = None
    pronunciation_qc: Optional[str] = None
