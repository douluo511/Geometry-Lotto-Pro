"""Backward-compatible imports for the domain model.

New code should import from head_intelligence.domain.
"""

from head_intelligence.domain import InformationItem, RawDocument, Source, SourceHealth, UpdateReport

__all__ = [
    "Source",
    "RawDocument",
    "InformationItem",
    "SourceHealth",
    "UpdateReport",
]
