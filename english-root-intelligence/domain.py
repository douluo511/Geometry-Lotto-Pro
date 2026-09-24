from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SourceReceipt:
    url: str
    status_code: int
    content_type: str
    sha256: str
    fetched_at: str
    attempts: int

@dataclass(frozen=True)
class UpdateResult:
    status: str
    version: str
    roots: int
    sha256: str
    source: SourceReceipt
