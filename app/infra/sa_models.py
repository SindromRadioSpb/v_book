"""SQLAlchemy ORM models matching the database schema."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


def utc_now() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# -----------------------
# Library / Projects / Corpora
# -----------------------


class Library(Base):
    __tablename__ = "library"

    library_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now)

    projects = relationship("DictProject", back_populates="library", cascade="all, delete-orphan")


class DictProject(Base):
    __tablename__ = "dict_project"

    project_id = Column(Integer, primary_key=True)
    library_id = Column(Integer, ForeignKey("library.library_id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    src_lang = Column(String, nullable=False, default="he")
    tgt_lang = Column(String, nullable=False, default="ru")

    nlp_engine = Column(String, nullable=False, default="stanza")
    nlp_engine_version = Column(String)

    mwe_min_freq = Column(Integer, nullable=False, default=3)
    mwe_min_pmi = Column(Float, nullable=False, default=3.0)
    mwe_min_tscore = Column(Float, nullable=False, default=2.0)
    mwe_max_n = Column(Integer, nullable=False, default=3)

    # M5.4: General corpus support for termhood
    is_general_corpus = Column(Integer, nullable=False, default=0)
    general_corpus_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="SET NULL"))

    created_at = Column(String, nullable=False, default=utc_now)
    updated_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("library_id", "name", name="uq_project_library_name"),
        CheckConstraint("mwe_max_n IN (2, 3)", name="ck_mwe_max_n"),
        CheckConstraint("is_general_corpus IN (0, 1)", name="ck_is_general_corpus"),
        Index("idx_project_general", "is_general_corpus"),
    )

    library = relationship("Library", back_populates="projects")
    corpora = relationship("SourceCorpus", back_populates="project", cascade="all, delete-orphan")


class SourceCorpus(Base):
    __tablename__ = "source_corpus"

    corpus_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    watch_folder_path = Column(String)
    created_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_corpus_project_name"),)

    project = relationship("DictProject", back_populates="corpora")
    documents = relationship("SourceDocument", back_populates="corpus", cascade="all, delete-orphan")


# -----------------------
# Documents
# -----------------------


class SourceDocument(Base):
    __tablename__ = "source_document"

    doc_id = Column(Integer, primary_key=True)
    corpus_id = Column(Integer, ForeignKey("source_corpus.corpus_id", ondelete="CASCADE"), nullable=False)

    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    file_ext = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False, default=0)

    sha256 = Column(String, nullable=False)
    imported_at = Column(String, nullable=False, default=utc_now)
    processed_at = Column(String)
    file_mtime_utc = Column(String)

    status = Column(String, nullable=False, default="imported")
    error_message = Column(Text)

    # NLP processing metrics (Migration 003)
    sentence_count = Column(Integer, nullable=False, default=0)
    token_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("corpus_id", "sha256", name="uq_document_corpus_sha256"),
        CheckConstraint(
            "status IN ('imported','queued','processing','processed','failed')",
            name="ck_document_status",
        ),
        Index("idx_doc_corpus_status", "corpus_id", "status"),
    )

    corpus = relationship("SourceCorpus", back_populates="documents")
    text = relationship("DocumentText", back_populates="document", uselist=False, cascade="all, delete-orphan")
    sentences = relationship("DocumentSentence", back_populates="document", cascade="all, delete-orphan")


class DocumentText(Base):
    __tablename__ = "document_text"

    doc_id = Column(Integer, ForeignKey("source_document.doc_id", ondelete="CASCADE"), primary_key=True)
    raw_text = Column(Text)
    cleaned_text = Column(Text)
    ocr_used = Column(Integer, nullable=False, default=0)

    __table_args__ = (CheckConstraint("ocr_used IN (0, 1)", name="ck_ocr_used"),)

    document = relationship("SourceDocument", back_populates="text")


class DocumentSentence(Base):
    __tablename__ = "document_sentence"

    sentence_id = Column(Integer, primary_key=True)
    doc_id = Column(Integer, ForeignKey("source_document.doc_id", ondelete="CASCADE"), nullable=False)
    sent_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("doc_id", "sent_index", name="uq_sentence_doc_index"),
        Index("idx_sentence_doc", "doc_id", "sent_index"),
    )

    document = relationship("SourceDocument", back_populates="sentences")


# -----------------------
# Normalization / Stopwords
# -----------------------


class TermAlias(Base):
    __tablename__ = "term_alias"

    alias_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    variant = Column(String, nullable=False)
    canonical = Column(String, nullable=False)
    note = Column(Text)

    __table_args__ = (UniqueConstraint("project_id", "variant", name="uq_alias_project_variant"),)


class StopwordSet(Base):
    __tablename__ = "stopword_set"

    stopset_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False, default="default")
    created_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_stopset_project_name"),)

    items = relationship("StopwordItem", back_populates="stopset", cascade="all, delete-orphan")


class StopwordItem(Base):
    __tablename__ = "stopword_item"

    stopitem_id = Column(Integer, primary_key=True)
    stopset_id = Column(Integer, ForeignKey("stopword_set.stopset_id", ondelete="CASCADE"), nullable=False)
    surface = Column(String)
    lemma_text = Column(String)
    lemma_id = Column(Integer)
    reason = Column(Text)

    stopset = relationship("StopwordSet", back_populates="items")


# -----------------------
# Lemmas
# -----------------------


class Lemma(Base):
    __tablename__ = "lemma"

    lemma_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    lemma_text = Column(String, nullable=False)
    pos = Column(String)
    morph_json = Column(Text)
    created_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("project_id", "lemma_text", name="uq_lemma_project_text"),
        Index("idx_lemma_project_text", "project_id", "lemma_text"),
    )


class LemmaDocStat(Base):
    __tablename__ = "lemma_doc_stat"

    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), primary_key=True)
    doc_id = Column(Integer, ForeignKey("source_document.doc_id", ondelete="CASCADE"), primary_key=True)
    lemma_id = Column(Integer, ForeignKey("lemma.lemma_id", ondelete="CASCADE"), primary_key=True)
    freq_abs = Column(Integer, nullable=False)
    sample_sentence_id = Column(Integer, ForeignKey("document_sentence.sentence_id", ondelete="SET NULL"))

    __table_args__ = (
        CheckConstraint("freq_abs >= 0", name="ck_lemma_doc_freq_abs"),
        Index("idx_lemma_doc_doc", "doc_id"),
    )


class LemmaProjectStat(Base):
    __tablename__ = "lemma_project_stat"

    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), primary_key=True)
    lemma_id = Column(Integer, ForeignKey("lemma.lemma_id", ondelete="CASCADE"), primary_key=True)
    freq_abs = Column(Integer, nullable=False)
    doc_freq = Column(Integer, nullable=False, default=0)
    sample_sentence_id = Column(Integer, ForeignKey("document_sentence.sentence_id", ondelete="SET NULL"))
    updated_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("freq_abs >= 0", name="ck_lemma_proj_freq_abs"),
        CheckConstraint("doc_freq >= 0", name="ck_lemma_proj_doc_freq"),
        Index("idx_lemma_proj_freq", "project_id", "freq_abs", "lemma_id", postgresql_using="btree"),
    )


# -----------------------
# Ngrams / MWEs
# -----------------------


class Ngram(Base):
    __tablename__ = "ngram"

    ngram_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    n = Column(Integer, nullable=False)
    surface_text = Column(String, nullable=False)
    he_canonical = Column(Text)  # M5: Canonical key for clustering
    lemma_phrase = Column(Text)  # M5: Lemma representation
    source_kind = Column(String, nullable=False, default="ngram")  # M5: 'ngram' or 'np'
    pattern_type = Column(String)
    pos_pattern = Column(String)
    created_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("n IN (2, 3, 4, 5)", name="ck_ngram_n"),
        CheckConstraint("source_kind IN ('ngram', 'np')", name="ck_ngram_source_kind"),
        UniqueConstraint("project_id", "n", "surface_text", "source_kind", name="uq_ngram_project_n_surface"),
        Index("idx_ngram_project_surface", "project_id", "n", "surface_text"),
        Index("idx_ngram_canonical", "project_id", "he_canonical"),
        Index("idx_ngram_lemma_phrase", "project_id", "lemma_phrase"),
    )


class NgramComponent(Base):
    __tablename__ = "ngram_component"

    ngram_id = Column(Integer, ForeignKey("ngram.ngram_id", ondelete="CASCADE"), primary_key=True)
    position = Column(Integer, primary_key=True)
    lemma_id = Column(Integer, ForeignKey("lemma.lemma_id", ondelete="CASCADE"), nullable=False)
    surface_token = Column(String)

    __table_args__ = (CheckConstraint("position >= 0", name="ck_ngram_component_position"),)


class NgramDocStat(Base):
    __tablename__ = "ngram_doc_stat"

    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), primary_key=True)
    doc_id = Column(Integer, ForeignKey("source_document.doc_id", ondelete="CASCADE"), primary_key=True)
    ngram_id = Column(Integer, ForeignKey("ngram.ngram_id", ondelete="CASCADE"), primary_key=True)
    freq_abs = Column(Integer, nullable=False)
    sample_sentence_id = Column(Integer, ForeignKey("document_sentence.sentence_id", ondelete="SET NULL"))

    __table_args__ = (CheckConstraint("freq_abs >= 0", name="ck_ngram_doc_freq_abs"),)


class NgramProjectStat(Base):
    __tablename__ = "ngram_project_stat"

    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), primary_key=True)
    ngram_id = Column(Integer, ForeignKey("ngram.ngram_id", ondelete="CASCADE"), primary_key=True)
    freq_abs = Column(Integer, nullable=False)
    doc_freq = Column(Integer, nullable=False, default=0)
    pmi_cache = Column(Float)
    tscore_cache = Column(Float)
    llr_cache = Column(Float)  # M5: Log-likelihood ratio
    dice_cache = Column(Float)  # M5: Dice coefficient
    tfidf = Column(Float)  # M5: TF-IDF score
    weirdness = Column(Float)  # M5: Weirdness ratio vs general corpus
    sample_sentence_id = Column(Integer, ForeignKey("document_sentence.sentence_id", ondelete="SET NULL"))
    updated_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("freq_abs >= 0", name="ck_ngram_proj_freq_abs"),
        CheckConstraint("doc_freq >= 0", name="ck_ngram_proj_doc_freq"),
        Index("idx_ngram_proj_freq", "project_id", "freq_abs", "ngram_id", postgresql_using="btree"),
        Index("idx_ngram_stat_llr", "project_id", "llr_cache"),
        Index("idx_ngram_stat_dice", "project_id", "dice_cache"),
    )


# -----------------------
# Term cards / Translation
# -----------------------


class TermCard(Base):
    __tablename__ = "term_card"

    term_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)
    lemma_id = Column(Integer, ForeignKey("lemma.lemma_id", ondelete="CASCADE"))
    ngram_id = Column(Integer, ForeignKey("ngram.ngram_id", ondelete="CASCADE"))
    status = Column(String, nullable=False, default="auto")
    quality_score = Column(Integer)
    notes = Column(Text)
    pinned_sentence_id = Column(Integer, ForeignKey("document_sentence.sentence_id", ondelete="SET NULL"))
    created_at = Column(String, nullable=False, default=utc_now)
    updated_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("kind IN ('lemma', 'ngram')", name="ck_term_card_kind"),
        CheckConstraint("status IN ('auto','needs_review','approved','rejected')", name="ck_term_card_status"),
        CheckConstraint("quality_score BETWEEN 0 AND 100", name="ck_term_card_quality"),
        UniqueConstraint("project_id", "kind", "lemma_id", "ngram_id", name="uq_term_card"),
        Index("idx_term_card_status", "project_id", "status"),
    )


class TranslationMemory(Base):
    __tablename__ = "translation_memory"

    tm_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    lemma_id = Column(Integer, ForeignKey("lemma.lemma_id", ondelete="CASCADE"))
    ngram_id = Column(Integer, ForeignKey("ngram.ngram_id", ondelete="CASCADE"))
    translation = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    confidence = Column(Float)
    is_override = Column(Integer, nullable=False, default=0)
    updated_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("source IN ('auto','user','import')", name="ck_tm_source"),
        CheckConstraint("is_override IN (0, 1)", name="ck_tm_is_override"),
        UniqueConstraint("project_id", "lemma_id", "ngram_id", name="uq_tm"),
        Index("idx_tm_lookup_lemma", "project_id", "lemma_id", sqlite_where="lemma_id IS NOT NULL"),
        Index("idx_tm_lookup_ngram", "project_id", "ngram_id", sqlite_where="ngram_id IS NOT NULL"),
    )


# -----------------------
# Processing / Tasks
# -----------------------


class ProcessorRun(Base):
    __tablename__ = "processor_run"

    run_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    started_at = Column(String, nullable=False, default=utc_now)
    finished_at = Column(String)
    engine = Column(String, nullable=False)
    engine_version = Column(String)
    docs_processed = Column(Integer, nullable=False, default=0)
    tokens_total = Column(Integer, nullable=False, default=0)
    lemmas_total = Column(Integer, nullable=False, default=0)
    ngrams_total = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="running")
    note = Column(Text)

    __table_args__ = (CheckConstraint("status IN ('running','ok','failed')", name="ck_run_status"),)


class RunError(Base):
    __tablename__ = "run_error"

    error_id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("processor_run.run_id", ondelete="CASCADE"), nullable=False)
    doc_id = Column(Integer, ForeignKey("source_document.doc_id", ondelete="SET NULL"))
    stage = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now)


class TaskQueue(Base):
    __tablename__ = "task_queue"

    task_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    doc_id = Column(Integer, ForeignKey("source_document.doc_id", ondelete="CASCADE"))
    op = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
    priority = Column(Integer, nullable=False, default=100)
    created_at = Column(String, nullable=False, default=utc_now)
    started_at = Column(String)
    finished_at = Column(String)
    error_message = Column(Text)

    __table_args__ = (
        CheckConstraint("op IN ('add','update','remove')", name="ck_task_op"),
        CheckConstraint("status IN ('queued','running','done','failed','canceled')", name="ck_task_status"),
        Index("idx_task_queue_status", "project_id", "status", "priority", "created_at"),
    )


class ProjectSnapshot(Base):
    __tablename__ = "project_snapshot"

    snapshot_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    label = Column(String, nullable=False)
    note = Column(Text)
    created_at = Column(String, nullable=False, default=utc_now)
    engine = Column(String, nullable=False)
    engine_version = Column(String)


# -----------------------
# Term search (materialized view)
# -----------------------


class TermSearch(Base):
    __tablename__ = "term_search"

    term_rowid = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)
    lemma_id = Column(Integer)
    ngram_id = Column(Integer)
    he_term = Column(Text, nullable=False)
    ru_translation = Column(Text)
    notes = Column(Text)

    __table_args__ = (CheckConstraint("kind IN ('lemma', 'ngram')", name="ck_term_search_kind"),)


# -----------------------
# Term Clusters (M5.1)
# -----------------------


class TermCluster(Base):
    """Term cluster for canonicalized term grouping (M5.1)."""

    __tablename__ = "term_cluster"

    cluster_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"), nullable=False)

    canonical_key = Column(String, nullable=False)
    representative_he = Column(Text, nullable=False)
    representative_lemma = Column(Text)

    freq_abs = Column(Integer, nullable=False, default=0)
    doc_freq = Column(Integer, nullable=False, default=0)
    members_count = Column(Integer, nullable=False, default=1)

    best_pmi = Column(Float)
    best_llr = Column(Float)
    best_dice = Column(Float)
    best_tscore = Column(Float)

    tfidf = Column(Float)
    weirdness = Column(Float)

    source_kinds = Column(String)
    created_at = Column(String, nullable=False, default=utc_now)
    updated_at = Column(String, nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("project_id", "canonical_key", name="uq_cluster_canonical"),
    )


class TermClusterMember(Base):
    """Term cluster membership (M5.1)."""

    __tablename__ = "term_cluster_member"

    cluster_id = Column(Integer, ForeignKey("term_cluster.cluster_id", ondelete="CASCADE"), primary_key=True)
    ngram_id = Column(Integer, ForeignKey("ngram.ngram_id", ondelete="CASCADE"), primary_key=True)

    member_freq_abs = Column(Integer, nullable=False, default=0)


# -----------------------
# M7: Translation Memory
# -----------------------


class TMEntry(Base):
    """Translation Memory entry with versioning and provenance."""

    __tablename__ = "tm_entry"

    tm_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"))
    kind = Column(String, nullable=False)  # lemma|ngram|term_cluster|surface
    src_lang = Column(String, nullable=False)
    tgt_lang = Column(String, nullable=False)
    src_text = Column(Text, nullable=False)
    src_norm = Column(Text, nullable=False)
    translation = Column(Text, nullable=False)
    translation_norm = Column(Text)
    pos = Column(String)
    domain = Column(String)
    notes = Column(Text)
    status = Column(String, nullable=False, default="draft")  # draft|approved|rejected|deprecated
    confidence = Column(Float)
    origin = Column(String, nullable=False)  # user_edit|import|mt_accept|mt_auto|merge|revert
    source_ref = Column(Text)
    created_at = Column(String, nullable=False, default=utc_now)
    updated_at = Column(String, nullable=False, default=utc_now)
    approved_at = Column(String)
    approved_by = Column(String)

    __table_args__ = (
        UniqueConstraint("project_id", "kind", "src_lang", "tgt_lang", "src_norm", name="uq_tm_entry"),
        CheckConstraint("kind IN ('lemma', 'ngram', 'term_cluster', 'surface')", name="ck_tm_kind"),
        CheckConstraint("status IN ('draft', 'approved', 'rejected', 'deprecated')", name="ck_tm_status"),
        CheckConstraint(
            "origin IN ('user_edit', 'import', 'mt_accept', 'mt_auto', 'merge', 'revert')", name="ck_tm_origin"
        ),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_tm_confidence"),
    )


class TMEntryHistory(Base):
    """Translation Memory history for audit trail."""

    __tablename__ = "tm_entry_history"

    hist_id = Column(Integer, primary_key=True)
    tm_id = Column(Integer, ForeignKey("tm_entry.tm_id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    translation = Column(Text, nullable=False)
    notes = Column(Text)
    status = Column(String, nullable=False)
    origin = Column(String, nullable=False)
    changed_at = Column(String, nullable=False, default=utc_now)
    change_kind = Column(String, nullable=False)  # edit|import|merge|revert|approve|reject|deprecate

    __table_args__ = (
        CheckConstraint(
            "change_kind IN ('edit', 'import', 'merge', 'revert', 'approve', 'reject', 'deprecate')",
            name="ck_tm_hist_change_kind",
        ),
    )


class TMAlias(Base):
    """Translation Memory aliases for variant matching."""

    __tablename__ = "tm_alias"

    alias_id = Column(Integer, primary_key=True)
    tm_id = Column(Integer, ForeignKey("tm_entry.tm_id", ondelete="CASCADE"), nullable=False)
    alias_text = Column(Text, nullable=False)
    alias_norm = Column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("tm_id", "alias_norm", name="uq_tm_alias"),)


class DictSource(Base):
    """Offline dictionary source metadata."""

    __tablename__ = "dict_source"

    dict_source_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"))
    name = Column(String, nullable=False)
    format = Column(String, nullable=False)  # csv|xlsx|json
    file_path = Column(Text)
    sha256 = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=utc_now)
    row_count = Column(Integer, nullable=False, default=0)
    notes = Column(Text)

    __table_args__ = (CheckConstraint("format IN ('csv', 'xlsx', 'json')", name="ck_dict_source_format"),)


class DictEntry(Base):
    """Offline dictionary entry (imported from files)."""

    __tablename__ = "dict_entry"

    dict_entry_id = Column(Integer, primary_key=True)
    dict_source_id = Column(Integer, ForeignKey("dict_source.dict_source_id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)  # lemma|ngram|term_cluster|surface
    src_lang = Column(String, nullable=False)
    tgt_lang = Column(String, nullable=False)
    src_text = Column(Text, nullable=False)
    src_norm = Column(Text, nullable=False)
    translation = Column(Text, nullable=False)
    pos = Column(String)
    domain = Column(String)
    status = Column(String, nullable=False, default="approved")  # approved|draft|deprecated
    priority = Column(Integer, nullable=False, default=0)
    notes = Column(Text)

    __table_args__ = (
        UniqueConstraint(
            "dict_source_id", "kind", "src_lang", "tgt_lang", "src_norm", "translation", name="uq_dict_entry"
        ),
        CheckConstraint("kind IN ('lemma', 'ngram', 'term_cluster', 'surface')", name="ck_dict_kind"),
        CheckConstraint("status IN ('approved', 'draft', 'deprecated')", name="ck_dict_status"),
    )


class MTCache(Base):
    """Machine Translation cache for API results."""

    __tablename__ = "mt_cache"

    cache_id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("dict_project.project_id", ondelete="CASCADE"))
    provider = Column(String, nullable=False)
    src_lang = Column(String, nullable=False)
    tgt_lang = Column(String, nullable=False)
    request_key = Column(String, nullable=False)
    src_text = Column(Text, nullable=False)
    src_norm = Column(Text, nullable=False)
    glossary_hash = Column(String)
    translation = Column(Text, nullable=False)
    confidence = Column(Float)
    created_at = Column(String, nullable=False, default=utc_now)
    expires_at = Column(String)

    __table_args__ = (
        UniqueConstraint("provider", "src_lang", "tgt_lang", "request_key", name="uq_mt_cache_request"),
    )
    member_doc_freq = Column(Integer, nullable=False, default=0)
