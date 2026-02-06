"""Security-related exceptions for HDLE Premium."""


class SecurityError(Exception):
    """Base exception for all security-related errors."""

    pass


class ValidationError(SecurityError):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: str = None, value: str = None):
        super().__init__(message)
        self.field = field
        self.value = value


class SanitizationError(SecurityError):
    """Raised when input cannot be safely sanitized."""

    def __init__(self, message: str, reason: str = None):
        super().__init__(message)
        self.reason = reason


class PathSecurityError(ValidationError):
    """Raised when file path fails security validation."""

    def __init__(self, message: str, path: str = None, reason: str = None):
        super().__init__(message, field="path", value=path)
        self.reason = reason


class QueryComplexityError(ValidationError):
    """Raised when search query exceeds complexity limits."""

    def __init__(self, message: str, query: str = None, reason: str = None):
        super().__init__(message, field="query", value=query)
        self.reason = reason


class CredentialStoreError(SecurityError):
    """Raised when credential storage/retrieval fails."""

    def __init__(self, message: str, operation: str = None):
        super().__init__(message)
        self.operation = operation
