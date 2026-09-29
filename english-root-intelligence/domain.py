from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class SourceReceipt:
    source_id: str
    url: str
    final_url: str
    status_code: int
    content_type: str
    sha256: str
    fetched_at: str
    byte_count: int
    attempts: int
    attempt_ledger: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    raw_b64: str = ""

@dataclass(frozen=True)
class UpdateResult:
    status: str
    version: str
    roots: int
    sha256: str
    sources: tuple[SourceReceipt, ...]
