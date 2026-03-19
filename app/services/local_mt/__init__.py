"""Local MT services (segmentation, glossary postprocess)."""

from .glossary_postprocess import (
    AppliedTerm,
    PostprocessResult,
    apply_glossary,
    apply_glossary_to_text,
    normalize_text,
)
from .segmentation import TextSegment, reassemble_text, segment_text

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
