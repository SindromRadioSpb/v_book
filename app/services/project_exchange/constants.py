"""Constants for project exchange (bundle format, table metadata)."""

# Bundle format version (increment on breaking changes)
BUNDLE_FORMAT_VERSION = 1

# File extension for bundles
BUNDLE_EXTENSION = ".hdleproj"

# Bundle contents
MANIFEST_FILENAME = "manifest.json"
PAYLOAD_FILENAME = "payload.sqlite"
CHECKSUMS_FILENAME = "checksums.json"
PRONUNCIATION_METADATA_FILENAME = "pronunciation_metadata.tsv"

# Tables to EXCLUDE from export (system/operational/security)
EXCLUDED_TABLES = {
    "credentials",           # Security: encrypted API keys
    "security_audit_log",    # Operational: security logs
    "mt_cache",              # Ephemeral: translation cache
    "mt_usage",              # Operational: provider usage tracking
    "audio_usage",           # Operational: audio provider usage tracking
    "schema_meta",           # System: migration version tracker
    "task_queue",            # Transient: job queue state
    "processor_run",         # Operational: processing run logs
    "run_error",             # Operational: processing error logs
    "sentence_fts",          # Virtual: FTS5 table (rebuilt on import)
    "term_fts",              # Virtual: FTS5 table (rebuilt on import)
    "pronunciation_entry",   # Global metadata layer (export/import via dedicated pronunciation exchange)
}

# Topological order for import (respects FK constraints)
# Parents must come before children
TABLE_INSERT_ORDER = [
    "library",
    "dict_project",
    "source_corpus",
    "source_document",
    "document_text",
    "document_sentence",
    "lemma",
    "ngram",
    "ngram_component",
    "lemma_doc_stat",
    "lemma_project_stat",
    "ngram_doc_stat",
    "ngram_project_stat",
    "term_cluster",
    "term_cluster_member",
    "term_card",
    "translation_memory",
    "tm_global",
    "tm_entry",
    "tm_entry_history",
    "tm_alias",
    "dict_source",
    "dict_entry",
    "term_alias",
    "stopword_set",
    "stopword_item",
    "term_search",
    "project_snapshot",
]

# Table schema metadata: PK column and FK mappings
# Format: {table_name: {"pk": "pk_column_name", "fks": {fk_col: parent_table}}}
# Composite PK tables have pk=None
TABLE_SCHEMA = {
    "library": {
        "pk": "library_id",
        "fks": {},
    },
    "dict_project": {
        "pk": "project_id",
        "fks": {
            "library_id": "library",
            "general_corpus_id": "dict_project",  # Self-FK
        },
    },
    "source_corpus": {
        "pk": "corpus_id",
        "fks": {
            "project_id": "dict_project",
        },
    },
    "source_document": {
        "pk": "doc_id",
        "fks": {
            "corpus_id": "source_corpus",
        },
    },
    "document_text": {
        "pk": None,  # PK = FK (1:1), no separate offset needed
        "fks": {
            "doc_id": "source_document",
        },
    },
    "document_sentence": {
        "pk": "sentence_id",
        "fks": {
            "doc_id": "source_document",
        },
    },
    "lemma": {
        "pk": "lemma_id",
        "fks": {
            "project_id": "dict_project",
        },
    },
    "ngram": {
        "pk": "ngram_id",
        "fks": {
            "project_id": "dict_project",
        },
    },
    "ngram_component": {
        "pk": None,  # Composite PK (ngram_id, position)
        "fks": {
            "ngram_id": "ngram",
            "lemma_id": "lemma",
        },
    },
    "lemma_doc_stat": {
        "pk": None,  # Composite PK (project_id, doc_id, lemma_id)
        "fks": {
            "project_id": "dict_project",
            "doc_id": "source_document",
            "lemma_id": "lemma",
            "sample_sentence_id": "document_sentence",
        },
    },
    "lemma_project_stat": {
        "pk": None,  # Composite PK (project_id, lemma_id)
        "fks": {
            "project_id": "dict_project",
            "lemma_id": "lemma",
            "sample_sentence_id": "document_sentence",
        },
    },
    "ngram_doc_stat": {
        "pk": None,  # Composite PK (project_id, doc_id, ngram_id)
        "fks": {
            "project_id": "dict_project",
            "doc_id": "source_document",
            "ngram_id": "ngram",
            "sample_sentence_id": "document_sentence",
        },
    },
    "ngram_project_stat": {
        "pk": None,  # Composite PK (project_id, ngram_id)
        "fks": {
            "project_id": "dict_project",
            "ngram_id": "ngram",
            "sample_sentence_id": "document_sentence",
        },
    },
    "term_cluster": {
        "pk": "cluster_id",
        "fks": {
            "project_id": "dict_project",
            "pinned_example_sent_id": "document_sentence",
        },
    },
    "term_cluster_member": {
        "pk": None,  # Composite PK (cluster_id, ngram_id)
        "fks": {
            "cluster_id": "term_cluster",
            "ngram_id": "ngram",
        },
    },
    "term_card": {
        "pk": "term_id",
        "fks": {
            "project_id": "dict_project",
            "lemma_id": "lemma",        # Nullable (mutually exclusive with ngram_id)
            "ngram_id": "ngram",        # Nullable (mutually exclusive with lemma_id)
            "pinned_sentence_id": "document_sentence",
        },
    },
    "translation_memory": {
        "pk": "tm_id",
        "fks": {
            "project_id": "dict_project",
            "lemma_id": "lemma",        # Nullable
            "ngram_id": "ngram",        # Nullable
        },
    },
    "tm_global": {
        "pk": "tm_global_id",
        "fks": {},
    },
    "tm_entry": {
        "pk": "tm_id",
        "fks": {
            "project_id": "dict_project",  # Nullable (global TM)
            "lemma_id": "lemma",           # Nullable
            "cluster_id": "term_cluster",  # Nullable
            "ngram_id": "ngram",           # Nullable
            "tm_global_id": "tm_global",   # Nullable
        },
    },
    "tm_entry_history": {
        "pk": "hist_id",
        "fks": {
            "tm_id": "tm_entry",
        },
    },
    "tm_alias": {
        "pk": "alias_id",
        "fks": {
            "tm_id": "tm_entry",
        },
    },
    "dict_source": {
        "pk": "dict_source_id",
        "fks": {
            "project_id": "dict_project",  # Nullable (global dict)
        },
    },
    "dict_entry": {
        "pk": "dict_entry_id",
        "fks": {
            "dict_source_id": "dict_source",
        },
    },
    "term_alias": {
        "pk": "alias_id",
        "fks": {
            "project_id": "dict_project",
        },
    },
    "stopword_set": {
        "pk": "stopset_id",
        "fks": {
            "project_id": "dict_project",
        },
    },
    "stopword_item": {
        "pk": "stopitem_id",
        "fks": {
            "stopset_id": "stopword_set",
        },
    },
    "term_search": {
        "pk": "term_rowid",
        "fks": {
            "project_id": "dict_project",
            # lemma_id and ngram_id are present but not FKs in the ORM (nullable, no constraint)
        },
    },
    "project_snapshot": {
        "pk": "snapshot_id",
        "fks": {
            "project_id": "dict_project",
        },
    },
}

# Nullable FK columns (only remap if value is not NULL)
NULLABLE_FK_COLUMNS = {
    "dict_project": {"general_corpus_id"},
    "lemma_doc_stat": {"sample_sentence_id"},
    "lemma_project_stat": {"sample_sentence_id"},
    "ngram_doc_stat": {"sample_sentence_id"},
    "ngram_project_stat": {"sample_sentence_id"},
    "term_cluster": {"pinned_example_sent_id"},
    "term_card": {"lemma_id", "ngram_id", "pinned_sentence_id"},
    "translation_memory": {"lemma_id", "ngram_id"},
    "tm_entry": {"project_id", "lemma_id", "cluster_id", "ngram_id", "tm_global_id"},
    "dict_source": {"project_id"},
}
