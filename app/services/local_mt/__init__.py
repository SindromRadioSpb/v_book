"""Local MT services (segmentation, glossary postprocess)."""

from .segmentation import segment_text, reassemble_text, TextSegment
from .glossary_postprocess import (
    apply_glossary,
    apply_glossary_to_text,
    AppliedTerm,
    PostprocessResult,
    normalize_text,
)

__all__ = [
    # Segmentation
    "segment_text",
    "reassemble_text",
    "TextSegment",
    # Glossary postprocess
    "apply_glossary",
    "apply_glossary_to_text",
    "AppliedTerm",
    "PostprocessResult",
    "normalize_text",
]
