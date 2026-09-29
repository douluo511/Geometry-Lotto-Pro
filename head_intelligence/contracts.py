from __future__ import annotations

from pathlib import Path
from typing import Protocol

from head_intelligence.domain import RawDocument, Source


class NetClientContract(Protocol):
    def fetch(self, source: Source) -> RawDocument:
        ...


class StorageContract(Protocol):
    @property
    def data_dir(self) -> Path:
        ...

    def save_raw(self, document: RawDocument) -> Path:
        ...

    def save_json_atomic(self, relative_name: str, payload: dict) -> Path:
        ...

    def read_json(self, relative_name: str) -> dict | None:
        ...


class EvidenceContract(Protocol):
    def normalize_title(self, text: str) -> str:
        ...
