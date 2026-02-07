"""Local MT services (segmentation, glossary postprocess)."""

from .segmentation import segment_text, reassemble_text, TextSegment

__all__ = [
    "segment_text",
    "reassemble_text",
    "TextSegment",
]
