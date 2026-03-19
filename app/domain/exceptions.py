"""Domain exceptions for HDLE Premium."""


class ReferenceCorpusReadonlyError(Exception):
    """Raised when attempting to modify a reference corpus.

    Reference corpora (is_general_corpus=1) are read-only for document operations
    and cannot be deleted.
    """

    pass
