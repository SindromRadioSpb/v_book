"""Machine Translation provider infrastructure."""

from .base_provider import (
    BaseProvider,
    TranslationErrorKind,
    TranslationRequest,
    TranslationResult,
)

__all__ = [
    "TranslationRequest",
    "TranslationResult",
    "TranslationErrorKind",
    "BaseProvider",
]
