"""Data Transfer Objects."""

from dataclasses import dataclass, field


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
    pos: str | None
    freq_abs: int
    doc_freq: int
    translation: str | None = None
    status: str = "auto"
    entity_class: str | None = None
    is_noise: int | None = None
    noise_reason: str | None = None
    norm_text: str | None = None
    saved_to_ud: bool = False
    in_user_dictionary_count: int = 0
    study_state: str | None = None
    study_due_human: str | None = None
    last_grade: str | None = None
    last_graded_at: str | None = None
    translation_tier: str | None = None
    audio_status: str | None = None
    study_tooltip: str | None = None
    pronunciation_text: str | None = None
    pronunciation_source: str | None = None
    pronunciation_confidence: float | None = None
    pronunciation_qc: str | None = None


@dataclass
class NgramStats:
    """N-gram statistics."""

    ngram_id: int
    surface_text: str
    n: int
    freq_abs: int
    doc_freq: int
    pmi: float | None
    tscore: float | None
    translation: str | None = None
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
    processed_at: str | None = None
    # Metadata fields (Migration 023)
    tag: str | None = None
    link_url: str | None = None
    level: str | None = None  # aleph | bet | gimel | he
    topic: str | None = None


@dataclass
class SentenceNiqqudOverlay:
    """Sentence-level niqqud overlay from sentence_pronunciation table (Migration 024)."""

    sentence_id: int
    niqqud_text: str | None
    qc_status: str  # ok | auto_fixed | partial | rejected | failed | pending
    qc_reason: str | None
    source: str  # auto_phonikud | manual | import_csv
    confidence: float | None
    niqqud_coverage: float | None
    is_override: bool
    review_status: str  # auto | pending_review | approved | rejected_by_user


@dataclass
class SentenceDTO:
    """A single sentence from document_sentence with overlay data."""

    sentence_id: int
    doc_id: int
    doc_name: str
    sent_index: int
    text: str
    # TM overlay
    translation: str | None = None
    translation_status: str | None = None
    translation_source: str | None = None
    # Sentence niqqud overlay (sentence_pronunciation table, Migration 024)
    pronunciation_text: str | None = None  # effective niqqud_text
    niqqud_qc: str | None = None  # qc_status badge
    niqqud_source: str | None = None
    niqqud_confidence: float | None = None
    niqqud_coverage: float | None = None
    niqqud_is_override: bool = False
    niqqud_review: str | None = None
    # Audio overlay
    audio_status: str | None = None


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
    error_message: str | None = None


@dataclass
class ExtractReport:
    """Report of term extraction results (M5)."""

    project_id: int
    ngrams_extracted: int
    np_chunks_extracted: int  # M5.3: NP chunks
    clusters_created: int
    success: bool
    error_message: str | None = None
    cancelled: bool = False
    run_id: int | None = None
    docs_processed: int = 0
    docs_total: int = 0
    snapshot_rows_used: int = 0
    reparsed_sentences: int = 0
    snapshot_reuse_pct: float | None = None


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
    sentence_coverage_pct: float | None
    doc_coverage_pct: float | None
    stats_valid_docs: int = 0
    stats_unknown_docs: int = 0
    stats_invalid_docs: int = 0
    coverage_is_degraded: bool = False
    coverage_source: str = "snapshot_doc_stats"
    latest_backfill_run_id: int | None = None
    latest_backfill_status: str | None = None
    latest_backfill_stage: str | None = None
    latest_backfill_last_doc_id: int | None = None
    latest_backfill_finished_at: str | None = None
    latest_backfill_docs_processed: int = 0
    latest_backfill_docs_total: int = 0
    contract_state: str = "no_snapshot_coverage"
    contract_note: str | None = None
    summary_note: str | None = None
    last_refreshed_at: str | None = None


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
    detail_lines: list[str] = field(default_factory=list)
    maintenance_mode: str | None = None
    maintenance_note: str | None = None
    maintenance_cli_hint: str | None = None
    maintenance_preflight_hint: str | None = None


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
    snapshot_sentence_coverage_pct: float | None = None
    snapshot_doc_coverage_pct: float | None = None
    lifecycle_note: str | None = None
    snapshot_contract_note: str | None = None
    last_refreshed_at: str | None = None
    artifacts: list[DerivedArtifactMetricDTO] = field(default_factory=list)


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
    oldest_prunable_run_id: int | None = None
    newest_prunable_run_id: int | None = None
    applied: bool = False
    deleted_runs: int = 0
    deleted_run_errors: int = 0
    summary_note: str | None = None
    vacuum_note: str | None = None


@dataclass
class NLPProcessRunState:
    """Structured NLP processing run state for staged/resumable flows."""

    run_id: int
    project_id: int
    status: str
    stage: str | None
    docs_total: int
    docs_processed: int
    docs_failed: int
    chunks_total: int
    chunks_completed: int
    last_doc_id: int | None = None
    params_hash: str | None = None
    error_message: str | None = None


@dataclass
class TermExtractionRunState:
    """Structured staged term extraction run state."""

    run_id: int
    project_id: int
    status: str
    stage: str | None
    docs_total: int
    docs_processed: int
    docs_failed: int
    chunks_total: int
    chunks_completed: int
    last_doc_id: int | None = None
    params_hash: str | None = None
    error_message: str | None = None


@dataclass
class ClusterStats:
    """Term cluster statistics (M5.1 + M5.4)."""

    cluster_id: int
    canonical_key: str
    representative_he: str
    representative_lemma: str | None
    freq_abs: int
    doc_freq: int
    members_count: int
    best_pmi: float | None
    best_llr: float | None
    best_dice: float | None
    best_tscore: float | None
    # M5.4: Termhood metrics vs reference corpus
    weirdness: float | None = None
    # best_keyness: stored at extraction time (NULL = not computed; 0.0 = zero).
    # Prefer over keyness_llr (query-time) when available.
    best_keyness: float | None = None
    keyness_llr: float | None = None
    termhood_score: float | None = None
    # M7: Translation
    translation: str | None = None
    translation_source: str | None = None  # tm|dict|mt_cache|mt|none
    translation_status: str | None = None  # approved|draft
    # Task 11: Entity classification
    entity_class: str | None = None
    is_noise: int | None = None
    noise_reason: str | None = None
    norm_text: str | None = None
    saved_to_ud: bool = False
    in_user_dictionary_count: int = 0
    study_state: str | None = None
    study_due_human: str | None = None
    last_grade: str | None = None
    last_graded_at: str | None = None
    translation_tier: str | None = None
    audio_status: str | None = None
    study_tooltip: str | None = None
    pronunciation_text: str | None = None
    pronunciation_source: str | None = None
    pronunciation_confidence: float | None = None
    pronunciation_qc: str | None = None


@dataclass
class TranslationResultDTO:
    """M7 Translation result for UI layer."""

    translation: str | None = None
    source: str = "none"  # tm|dict|mt_cache|mt|none
    status: str | None = None  # approved|draft|rejected|deprecated
    confidence: float | None = None
    origin: str | None = None  # user_edit|import|mt_accept|mt_auto
    matched_on: str | None = None  # src_norm|alias_norm|variant_norm
    match_key_used: str | None = None
    provider: str | None = None  # MT provider name
    dict_source_name: str | None = None
    tm_id: int | None = None
    notes: str | None = None


# ============================================================================
# P2: Translation Management & QA/Coverage DTOs
# ============================================================================


@dataclass
class TMEntryDTO:
    """P2: TM Entry for management panel."""

    tm_id: int
    project_id: int | None  # None = global
    kind: str  # lemma|ngram|term_cluster|surface
    src_lang: str
    tgt_lang: str
    src_text: str
    src_norm: str
    translation: str
    translation_norm: str | None
    pos: str | None
    domain: str | None
    notes: str | None
    status: str  # draft|approved|rejected|deprecated
    confidence: float | None
    origin: str  # user_edit|import|mt_accept|mt_auto|merge
    source_ref: str | None
    created_at: str
    updated_at: str
    approved_at: str | None
    approved_by: str | None
    is_noise: int | None  # 0=not noise, 1=noise, None=legacy
    noise_reason: str | None  # NOISE_PUNCT_ONLY, NOISE_NUMBER_ONLY, etc.
    norm_text: str | None  # Normalized text for noise detection
    # Source entity links (for is_noise synchronization)
    lemma_id: int | None
    cluster_id: int | None
    ngram_id: int | None
    # Global TM canonical link (Task 19)
    tm_global_id: int | None = None
    # Study/meta indicators (non-intrusive overlays)
    in_user_dictionary_count: int = 0
    study_state: str | None = None
    study_due_human: str | None = None
    last_grade: str | None = None
    last_graded_at: str | None = None
    study_tooltip: str | None = None
    audio_status: str | None = None
    pronunciation_text: str | None = None
    pronunciation_source: str | None = None
    pronunciation_confidence: float | None = None
    pronunciation_qc: str | None = None
    raw_src_norm: str | None = None


@dataclass
class UserDictionaryDTO:
    """User dictionary metadata for UI."""

    dictionary_id: int
    name: str
    description: str | None
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
    notes: str | None
    is_noise: int
    noise_reason: str | None
    study_state: str
    study_progress_id: int | None
    is_suspended: int
    suspended_reason: str | None
    last_seen_at: str | None
    seen_count: int
    origin_project_id: int | None
    origin_project_name: str | None
    origin_entity_type: str | None
    origin_entity_id: str | None
    origin_tm_entry_id: int | None
    origin_doc_id: int | None
    origin_source_ref: str | None
    created_at: str
    updated_at: str
    translation: str | None = None
    translation_status: str | None = None
    translation_origin: str | None = None
    translation_confidence: float | None = None
    tm_global_id: int | None = None
    audio_status: str = "missing"
    origin_kind: str = "manual"
    computed_study_state: str = "new"
    study_due_human: str | None = None
    study_due_at: str | None = None
    study_review_count: int = 0
    study_lapse_count: int = 0
    study_interval_days: int = 0
    study_ease_factor: float = 2.5
    last_grade: str | None = None
    last_graded_at: str | None = None
    translation_tier: str = "missing"
    status_tooltip: str | None = None
    pronunciation_text: str | None = None
    pronunciation_source: str | None = None
    pronunciation_confidence: float | None = None
    pronunciation_qc: str | None = None


@dataclass
class PronunciationEntryDTO:
    """Pronunciation entry payload."""

    entry_id: int | None
    lang: str
    src_norm: str
    niqqud_text: str | None
    ipa: str | None
    reading_text: str | None
    source: str
    confidence: float | None
    is_override: int
    notes: str | None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class StudyProgressSummaryDTO:
    """Computed SRS summary for one canonical hash."""

    progress_id: int | None
    canonical_hash: str
    first_seen_at: str | None
    last_review_at: str | None
    due_at: str | None
    review_count: int
    lapse_count: int
    interval_days: int
    ease_factor: float
    last_quality: int | None
    last_grade: str | None = None
    last_graded_at: str | None = None
    is_suspended: bool = False
    study_state: str = "new"
    due_human: str | None = None


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
    due_human: str | None
    progress_id: int | None
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
    notes: str | None
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
    pos: str | None
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
    termhood_score: float | None


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
    pos: str | None = None
    domain: str | None = None
    status: str = "approved"
    priority: int | None = None
    notes: str | None = None
    aliases: list[str] | None = None  # Additional src_text variants


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
    invalid_rows: list[ImportInvalidRow]
    conflict_details: list[ImportConflict]
    dict_source_id: int | None
    sha256: str
    elapsed_ms: float


@dataclass
class TermCardDTO:
    """M8: Term card with curation metadata."""

    cluster_id: int
    project_id: int
    canonical_key: str
    representative_he: str
    representative_lemma: str | None
    freq_abs: int
    doc_freq: int
    members_count: int
    best_pmi: float | None
    best_llr: float | None
    best_dice: float | None
    best_tscore: float | None
    tfidf: float | None
    weirdness: float | None
    source_kinds: str | None
    curation_status: str  # auto/needs_review/approved/rejected
    pinned_translation: str | None
    pinned_translation_lang: str | None
    pinned_example_sent_id: int | None
    pinned_example_text: str | None
    curation_notes: str | None
    curated_at: str | None
    curated_by: str | None
    aliases: list[str]  # Variant forms
    is_stopword: bool
    created_at: str
    updated_at: str
    in_user_dictionary_count: int = 0
    study_state: str | None = None
    study_due_human: str | None = None
    last_grade: str | None = None
    last_graded_at: str | None = None
    study_tooltip: str | None = None
    audio_status: str | None = None
    pronunciation_text: str | None = None
    pronunciation_source: str | None = None
    pronunciation_confidence: float | None = None
    pronunciation_qc: str | None = None
