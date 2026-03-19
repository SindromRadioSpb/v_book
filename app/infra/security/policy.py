"""Security policy configuration for HDLE Premium.

All security limits, thresholds, and policies in one place.
"""

import sys
from pathlib import Path

# =============================================================================
# FILE SIZE LIMITS (bytes)
# =============================================================================

MAX_DOCUMENT_SIZE = 100 * 1024 * 1024  # 100 MB for TXT/DOCX/PDF
MAX_DICTIONARY_SIZE = 10 * 1024 * 1024  # 10 MB for CSV/XLSX
MAX_BUNDLE_SIZE = 1024 * 1024 * 1024  # 1 GB for .hdleproj bundles (large reference corpora)
MAX_UPLOAD_SIZE = MAX_DOCUMENT_SIZE  # Default max size

# =============================================================================
# TEXT FIELD LIMITS
# =============================================================================

MAX_QUERY_LENGTH = 500  # Maximum search query length
MAX_TEXT_FIELD_LENGTH = 10_000  # Maximum chars in text input fields
MAX_LOG_INPUT_LENGTH = 100  # Maximum user input length in logs

# =============================================================================
# FTS5 QUERY LIMITS
# =============================================================================

MAX_FTS5_OPERATORS = 10  # Maximum AND/OR/NOT/NEAR operators in query
MAX_FTS5_WILDCARDS = 5  # Maximum * wildcards in query
MAX_FTS5_PARENTHESES = 10  # Maximum nested parentheses depth

FTS5_SPECIAL_CHARS = ['"', "*", "(", ")", "[", "]", "{", "}"]
FTS5_RESERVED_WORDS = ["AND", "OR", "NOT", "NEAR"]

# =============================================================================
# PATH SECURITY
# =============================================================================

# System directories that are FORBIDDEN for file operations
if sys.platform == "win32":
    SYSTEM_DIRECTORIES = [
        Path("C:/Windows"),
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path("C:/ProgramData"),
    ]
elif sys.platform == "darwin":
    SYSTEM_DIRECTORIES = [
        Path("/System"),
        Path("/Library"),
        Path("/Applications"),
        Path("/bin"),
        Path("/sbin"),
        Path("/usr/bin"),
        Path("/usr/sbin"),
    ]
else:  # Linux
    SYSTEM_DIRECTORIES = [
        Path("/bin"),
        Path("/boot"),
        Path("/dev"),
        Path("/etc"),
        Path("/lib"),
        Path("/lib64"),
        Path("/proc"),
        Path("/root"),
        Path("/sbin"),
        Path("/sys"),
        Path("/usr/bin"),
        Path("/usr/sbin"),
    ]

# =============================================================================
# LOGGING SECURITY
# =============================================================================

LOG_SANITIZE_CHARS = {
    "\r": "_",
    "\n": "_",
    "\t": " ",
}

# =============================================================================
# RATE LIMITING
# =============================================================================

MAX_IMPORTS_PER_MINUTE = 100  # Maximum file imports per minute per project
MAX_EXPORTS_PER_MINUTE = 50  # Maximum exports per minute

# =============================================================================
# AUDIT LOG OUTCOMES
# =============================================================================

OUTCOME_ALLOW = "ALLOW"
OUTCOME_BLOCK = "BLOCK"
OUTCOME_FAIL = "FAIL"

# =============================================================================
# CREDENTIAL STORAGE
# =============================================================================

CREDENTIAL_KEY_MAX_LENGTH = 256  # Maximum credential key name length
CREDENTIAL_VALUE_MAX_LENGTH = 4096  # Maximum secret value length (4 KB)

# AES-GCM parameters
AES_KEY_SIZE = 32  # 256 bits
AES_NONCE_SIZE = 12  # 96 bits (recommended for GCM)
AES_TAG_SIZE = 16  # 128 bits
