"""Security module for HDLE Premium.

Provides input sanitization, validation, cryptography, and credential storage.

Usage:
    from app.infra.security import (
        sanitize_fts5_query,
        validate_file_size,
        validate_path_security,
        CredentialStore,
        PathSecurityError,
    )

    # Sanitize user search query
    safe_query = sanitize_fts5_query(user_input, strict=True)

    # Validate file before processing
    validate_file_size(file_path, MAX_DOCUMENT_SIZE)
    safe_path = validate_path_security(file_path, operation="import")

    # Sanitize for logging
    from app.infra.security import sanitize_for_log
    logger.info(f"User search: {sanitize_for_log(user_query)}")

    # Store credentials securely
    store = CredentialStore()
    store.set_credential("api_key", "secret", storage=my_dict)
    api_key = store.get_credential("api_key", storage=my_dict)
"""

# Exceptions
# Audit Logging
from .audit import AuditLogger

# Credential Storage
from .credentials import CredentialStore

# Cryptography
from .crypto import (
    decrypt,
    encrypt,
    generate_key,
)
from .errors import (
    CredentialStoreError,
    PathSecurityError,
    QueryComplexityError,
    SanitizationError,
    SecurityError,
    ValidationError,
)

# Policy constants (commonly needed)
from .policy import (
    MAX_DICTIONARY_SIZE,
    MAX_DOCUMENT_SIZE,
    MAX_LOG_INPUT_LENGTH,
    MAX_QUERY_LENGTH,
)

# Rate Limiting
from .rate_limiter import RateLimiter, get_export_limiter, get_import_limiter

# Sanitizers
from .sanitizer import (
    sanitize_csv_cell,
    sanitize_filename,
    sanitize_for_log,
    sanitize_fts5_query,
    sanitize_xml_text,
)

# Validators
from .validator import (
    is_system_path,
    is_unc_path,
    validate_file_size,
    validate_path_security,
    validate_query_complexity,
)

__all__ = [
    # Exceptions
    "SecurityError",
    "ValidationError",
    "SanitizationError",
    "PathSecurityError",
    "QueryComplexityError",
    "CredentialStoreError",
    # Sanitizers
    "sanitize_fts5_query",
    "sanitize_csv_cell",
    "sanitize_for_log",
    "sanitize_xml_text",
    "sanitize_filename",
    # Validators
    "validate_file_size",
    "validate_path_security",
    "validate_query_complexity",
    "is_unc_path",
    "is_system_path",
    # Cryptography
    "generate_key",
    "encrypt",
    "decrypt",
    # Credential Storage
    "CredentialStore",
    # Audit Logging
    "AuditLogger",
    # Rate Limiting
    "RateLimiter",
    "get_import_limiter",
    "get_export_limiter",
    # Policy constants
    "MAX_DOCUMENT_SIZE",
    "MAX_DICTIONARY_SIZE",
    "MAX_QUERY_LENGTH",
    "MAX_LOG_INPUT_LENGTH",
]
