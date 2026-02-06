"""Input sanitization utilities for HDLE Premium.

Sanitizers transform potentially dangerous input into safe forms.
All sanitization failures should be logged via audit module.
"""

import re
from typing import Optional

from .policy import (
    FTS5_SPECIAL_CHARS,
    FTS5_RESERVED_WORDS,
    LOG_SANITIZE_CHARS,
    MAX_LOG_INPUT_LENGTH,
    MAX_QUERY_LENGTH,
)
from .errors import SanitizationError, QueryComplexityError


def sanitize_fts5_query(query: str, strict: bool = True) -> str:
    """
    Sanitize FTS5 full-text search query to prevent syntax injection.

    Strategy:
    - Escape special FTS5 characters: " * ( ) [ ] { }
    - Block/escape reserved words: AND OR NOT NEAR
    - Enforce length limit

    Args:
        query: User search query (Hebrew text, keywords, etc.)
        strict: If True, block reserved words; if False, escape them

    Returns:
        Sanitized query safe for FTS5 MATCH

    Raises:
        QueryComplexityError: If query exceeds length limit
        SanitizationError: If query cannot be safely sanitized
    """
    if not query or not query.strip():
        return '""'  # Empty query returns no results

    query = query.strip()

    # 1. Length limit
    if len(query) > MAX_QUERY_LENGTH:
        raise QueryComplexityError(
            f"Query too long (max {MAX_QUERY_LENGTH} chars)",
            query=query[:100] + "...",
            reason="LENGTH_EXCEEDED",
        )

    # 2. Escape special characters
    escaped = query
    for char in FTS5_SPECIAL_CHARS:
        # Escape by doubling quotes or removing special chars
        if char == '"':
            # Double quotes: "hello" -> ""hello""
            escaped = escaped.replace('"', '""')
        else:
            # Remove other special chars
            escaped = escaped.replace(char, '')

    # 3. Handle reserved words
    if strict:
        # Block queries containing FTS5 operators (whole words only)
        query_upper = escaped.upper()
        for word in FTS5_RESERVED_WORDS:
            # Match whole words only, not substrings
            pattern = r'\b' + word + r'\b'
            if re.search(pattern, query_upper):
                raise QueryComplexityError(
                    f"FTS5 operators not allowed: {word}",
                    query=query[:100],
                    reason="OPERATOR_BLOCKED",
                )
    else:
        # Escape reserved words by quoting them
        for word in FTS5_RESERVED_WORDS:
            # Replace standalone words only (not substrings)
            pattern = r'\b' + word + r'\b'
            escaped = re.sub(pattern, f'"{word}"', escaped, flags=re.IGNORECASE)

    # 4. Wrap in quotes for exact phrase matching
    # This prevents most injection attacks
    sanitized = f'"{escaped}"'

    return sanitized


def sanitize_csv_cell(cell_value: str) -> str:
    """
    Neutralize CSV injection (formula execution) in cell values.

    Dangerous prefixes: = + - @ (can trigger formula execution in Excel/Calc)

    Strategy: Prefix dangerous chars with single quote

    Args:
        cell_value: Cell content to sanitize

    Returns:
        Safe cell value (prefixed with ' if needed)
    """
    if not cell_value:
        return cell_value

    # Check if first character is dangerous
    if cell_value[0] in "=+-@":
        return "'" + cell_value

    return cell_value


def sanitize_for_log(user_input: str, max_length: Optional[int] = None) -> str:
    """
    Sanitize user input for safe logging (prevent log injection/forging).

    Mitigations:
    - Replace CRLF with underscore (prevents log forging)
    - Replace tabs with space
    - Truncate to max length
    - Remove non-printable characters

    Args:
        user_input: User-provided string to log
        max_length: Maximum length (default: MAX_LOG_INPUT_LENGTH)

    Returns:
        Sanitized string safe for logging
    """
    if not user_input:
        return ""

    if max_length is None:
        max_length = MAX_LOG_INPUT_LENGTH

    # 1. Replace CRLF and tabs
    sanitized = user_input
    for char, replacement in LOG_SANITIZE_CHARS.items():
        sanitized = sanitized.replace(char, replacement)

    # 2. Remove non-printable characters (except space)
    sanitized = ''.join(c if c.isprintable() or c == ' ' else '.' for c in sanitized)

    # 3. Truncate
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + '...'

    return sanitized


def sanitize_xml_text(text: str) -> str:
    """
    Remove invalid XML characters for TBX/TMX export.

    XML 1.0 valid chars: https://www.w3.org/TR/xml/#charsets
    - #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]

    Args:
        text: Text to sanitize for XML

    Returns:
        XML-safe text with invalid chars removed
    """
    if not text:
        return text

    # Filter invalid XML chars
    def is_valid_xml_char(char: str) -> bool:
        codepoint = ord(char)
        return (
            codepoint == 0x9
            or codepoint == 0xA
            or codepoint == 0xD
            or (0x20 <= codepoint <= 0xD7FF)
            or (0xE000 <= codepoint <= 0xFFFD)
            or (0x10000 <= codepoint <= 0x10FFFF)
        )

    return ''.join(c for c in text if is_valid_xml_char(c))


def sanitize_filename(filename: str) -> str:
    r"""
    Sanitize filename to remove path traversal and dangerous characters.

    Strategy:
    - Remove path separators (/ \)
    - Remove null bytes
    - Remove control characters
    - Limit length

    Args:
        filename: Proposed filename

    Returns:
        Safe filename (basename only, no path components)

    Raises:
        SanitizationError: If filename cannot be sanitized
    """
    if not filename:
        raise SanitizationError("Empty filename", reason="EMPTY")

    # Remove path separators (prevent directory traversal)
    sanitized = filename.replace('/', '_').replace('\\', '_')

    # Remove null bytes
    sanitized = sanitized.replace('\0', '')

    # Remove control characters
    sanitized = ''.join(c if c.isprintable() else '_' for c in sanitized)

    # Trim whitespace
    sanitized = sanitized.strip()

    # Length limit
    if len(sanitized) > 255:
        # Keep extension
        name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
        sanitized = name[:250] + ('.' + ext if ext else '')

    if not sanitized:
        raise SanitizationError("Filename became empty after sanitization", reason="EMPTY_AFTER_SANITIZATION")

    return sanitized
