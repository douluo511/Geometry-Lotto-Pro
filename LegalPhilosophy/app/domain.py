from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


SourceRole = Literal[
    "PRIMARY_TEXT",
    "AUTHORITATIVE_SCHOLARSHIP",
    "LEGAL_AUTHORITY",
    "CASE",
]


@dataclass(frozen=True)
class SourceDocument:
    source_id: str
    title: str
    url: str
    role: SourceRole
    retrieved_at: str
    payload_sha256: str
    text_sha256: str
    content_type: str
    validation_status: str
    marker_hits: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StudyResult:
    question: str
    section: str
    status: str
    source_refs: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    five_why: tuple[str, ...]
    reversal_tests: tuple[str, ...]
    counterexample_prompts: tuple[str, ...]
    model_inference: str
    boundary: str

    def to_dict(self) -> dict:
        return asdict(self)


FROZEN_SECTIONS = (
    "Preface / Introduction",
    "Abstract Right",
    "Morality",
    "Family",
    "Civil Society",
    "State",
    "International Law",
    "World History",
)


def validate_source(doc: SourceDocument) -> None:
    if not doc.source_id or not doc.title:
        raise ValueError("source identity is required")
    if not doc.url.startswith("https://"):
        raise ValueError("source URL must be HTTPS")
    if len(doc.payload_sha256) != 64 or len(doc.text_sha256) != 64:
        raise ValueError("source hashes must be SHA-256")
    if doc.validation_status != "PASS":
        raise ValueError("unvalidated source cannot enter canonical evidence")
    if doc.role not in {"PRIMARY_TEXT", "AUTHORITATIVE_SCHOLARSHIP", "LEGAL_AUTHORITY", "CASE"}:
        raise ValueError("unknown source role")


def validate_result(result: StudyResult) -> None:
    if result.section not in FROZEN_SECTIONS:
        raise ValueError("result section outside frozen scope")
    if result.status not in {"PASS", "NOT VERIFIED"}:
        raise ValueError("invalid study result status")
    if not result.boundary or "legal advice" not in result.boundary.lower():
        raise ValueError("educational/legal-advice boundary missing")
    if len(result.five_why) < 5 or not result.reversal_tests:
        raise ValueError("5 Why and reversal evidence are mandatory")
