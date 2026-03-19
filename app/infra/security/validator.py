"""Input validation utilities for HDLE Premium.

Validators check if input meets security requirements, raising errors if not.
All validation failures should be logged via audit module.
"""

import re
from pathlib import Path

from .errors import PathSecurityError, QueryComplexityError, ValidationError
from .policy import (
    MAX_DOCUMENT_SIZE,
    MAX_FTS5_OPERATORS,
    MAX_FTS5_PARENTHESES,
    MAX_FTS5_WILDCARDS,
    MAX_QUERY_LENGTH,
    SYSTEM_DIRECTORIES,
)


def validate_file_size(
    file_path: Path,
    max_size: int | None = None,
    file_type: str = "document",
) -> None:
    """
    Validate file size against security limits.

    Args:
        file_path: Path to file to validate
        max_size: Maximum size in bytes (default: MAX_DOCUMENT_SIZE)
        file_type: Type of file for error messages

    Raises:
        ValidationError: If file size exceeds limit
        FileNotFoundError: If file does not exist
    """
    if max_size is None:
        max_size = MAX_DOCUMENT_SIZE

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    file_size = file_path.stat().st_size

    if file_size > max_size:
        raise ValidationError(
            f"{file_type.capitalize()} file too large: "
            f"{file_size / 1024 / 1024:.1f} MB (max {max_size / 1024 / 1024:.1f} MB)",
            field="file_size",
            value=str(file_size),
        )


def is_unc_path(path: Path) -> bool:
    r"""
    Check if path is a UNC path (\\server\share).

    UNC paths are blocked for security (network access control).

    Args:
        path: Path to check

    Returns:
        True if path is UNC path
    """
    path_str = str(path)
    # Windows UNC: \\server\share or //server/share
    return path_str.startswith("\\\\") or path_str.startswith("//")


def is_system_path(path: Path) -> bool:
    """
    Check if path is in a protected system directory.

    System directories are forbidden to prevent accidental damage.

    Args:
        path: Path to check

    Returns:
        True if path is in system directory
    """
    try:
        # Resolve to absolute path for comparison
        abs_path = path.resolve()

        for system_dir in SYSTEM_DIRECTORIES:
            try:
                # Check if path is relative to system directory
                abs_path.relative_to(system_dir.resolve())
                return True
            except ValueError:
                # Not relative to this system dir, continue
                continue

        return False
    except (OSError, RuntimeError):
        # resolve() can fail for invalid paths, treat as potentially unsafe
        return True


def validate_path_security(path: Path, operation: str = "access") -> Path:
    """
    Validate file path against security requirements.

    Checks:
    - UNC paths (blocked)
    - System directories (blocked)
    - Symlink resolution (resolve to real path)
    - Path traversal (resolved to absolute)

    Args:
        path: Path to validate
        operation: Operation description for error messages

    Returns:
        Resolved absolute path (safe to use)

    Raises:
        PathSecurityError: If path fails security validation
    """
    # 1. Block UNC paths
    if is_unc_path(path):
        raise PathSecurityError(
            f"UNC paths not allowed for {operation}",
            path=str(path),
            reason="UNC_PATH",
        )

    # 2. Resolve symlinks and make absolute
    try:
        resolved_path = path.resolve()
    except (OSError, RuntimeError) as e:
        raise PathSecurityError(
            f"Cannot resolve path for {operation}: {e}",
            path=str(path),
            reason="RESOLVE_FAILED",
        )

    # 3. Block system directories
    if is_system_path(resolved_path):
        raise PathSecurityError(
            f"System directory access denied for {operation}",
            path=str(resolved_path),
            reason="SYSTEM_DIRECTORY",
        )

    return resolved_path


def validate_query_complexity(query: str) -> None:
    """
    Validate FTS5 query complexity to prevent DoS attacks.

    Checks:
    - Length limit
    - Wildcard count
    - Operator count
    - Parentheses depth

    Args:
        query: FTS5 query to validate

    Raises:
        QueryComplexityError: If query is too complex
    """
    # 1. Length check
    if len(query) > MAX_QUERY_LENGTH:
        raise QueryComplexityError(
            f"Query too long (max {MAX_QUERY_LENGTH} chars)",
            query=query[:100] + "...",
            reason="LENGTH_EXCEEDED",
        )

    # 2. Wildcard count
    wildcard_count = query.count("*")
    if wildcard_count > MAX_FTS5_WILDCARDS:
        raise QueryComplexityError(
            f"Too many wildcards: {wildcard_count} (max {MAX_FTS5_WILDCARDS})",
            query=query[:100],
            reason="WILDCARD_LIMIT",
        )

    # 3. Operator count
    query_upper = query.upper()
    operator_count = sum(
        len(re.findall(r"\b" + op + r"\b", query_upper)) for op in ["AND", "OR", "NOT", "NEAR"]
    )
    if operator_count > MAX_FTS5_OPERATORS:
        raise QueryComplexityError(
            f"Too many operators: {operator_count} (max {MAX_FTS5_OPERATORS})",
            query=query[:100],
            reason="OPERATOR_LIMIT",
        )

    # 4. Parentheses depth
    max_depth = 0
    current_depth = 0
    for char in query:
        if char == "(":
            current_depth += 1
            max_depth = max(max_depth, current_depth)
        elif char == ")":
            current_depth -= 1

    if max_depth > MAX_FTS5_PARENTHESES:
        raise QueryComplexityError(
            f"Parentheses too deep: {max_depth} (max {MAX_FTS5_PARENTHESES})",
            query=query[:100],
            reason="PARENTHESES_DEPTH",
        )

    # Check for unbalanced parentheses
    if current_depth != 0:
        raise QueryComplexityError(
            "Unbalanced parentheses in query",
            query=query[:100],
            reason="UNBALANCED_PARENTHESES",
        )
