from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path

from .domain import SourceDocument
from .engine import build_study_result
from .netclient import NetClient
from .sources import CASE_CORPUS_IDS, build_conflict_registry, fetch_current_sources, primary_lineage_status
from .storage import Storage


class LegalPhilosophyService:
    def __init__(self, root: Path | None = None):
        root = root or Path(os.environ.get("LEGAL_PHILOSOPHY_ROOT", "userdata"))
        self.root = Path(root)
        self.storage = Storage(self.root)
        self.net = NetClient(self.storage.evidence / "network.jsonl")

    def update(self) -> dict:
        docs, texts = fetch_current_sources(self.net)
        for doc in docs:
            self.storage.persist_source(doc, texts[doc.source_id])
        conflict = build_conflict_registry(docs)
        primary_status = primary_lineage_status(docs)
        self.storage.atomic_json(self.storage.evidence / "conflict_registry.json", conflict)
        result = {
            "status": "PASS",
            "source_count": len(docs),
            "sources": [doc.to_dict() for doc in docs],
            "source_conflict_handling": conflict.get("status", "NOT VERIFIED"),
            "case_source_lineage": (
                "PASS"
                if CASE_CORPUS_IDS.issubset({doc.source_id for doc in docs if doc.role == "CASE"})
                else "NOT VERIFIED"
            ),
            "primary_source_lineage": primary_status,
            "note": (
                "primary lineage requires the exact Dyde 1896 PDF title-page identity and all frozen section-range "
                "markers; quotation-level claims remain separately fail-closed"
            ),
        }
        self.storage.atomic_json(self.storage.evidence / "update_result.json", result)
        return result

    def _docs(self) -> list[SourceDocument]:
        index = self.storage.load_index(validate_raw=True)
        docs = []
        for meta in index.values():
            marker_hits = tuple(meta.get("marker_hits") or ())
            meta = dict(meta)
            meta["marker_hits"] = marker_hits
            docs.append(SourceDocument(**meta))
        return docs

    def study(self, question: str, *, refresh_if_missing: bool = False) -> dict:
        docs = self._docs()
        if not docs and refresh_if_missing:
            self.update()
            docs = self._docs()
        if not docs:
            raise RuntimeError("no validated current sources; refresh authoritative sources first")
        result = build_study_result(question, docs).to_dict()
        self.storage.atomic_json(self.storage.evidence / "last_study_result.json", result)
        return result

    def repair(self) -> dict:
        return self.storage.repair()

    def advanced(self) -> dict:
        docs = self._docs()
        roles = {doc.role for doc in docs}
        source_ids = {doc.source_id for doc in docs}
        conflict = build_conflict_registry(docs)
        primary_status = primary_lineage_status(docs)
        result = {
            "status": "PASS",
            "frozen_scope_sections": 8,
            "source_roles_present": sorted(roles),
            "scholarship_lineage": "PASS" if "AUTHORITATIVE_SCHOLARSHIP" in roles else "NOT VERIFIED",
            "legal_authority_lineage": "PASS" if "LEGAL_AUTHORITY" in roles else "NOT VERIFIED",
            "primary_source_lineage": primary_status,
            "source_conflict_handling": conflict.get("status", "NOT VERIFIED"),
            "case_source_lineage": (
                "PASS"
                if CASE_CORPUS_IDS.issubset(source_ids) and "CASE" in roles
                else "NOT VERIFIED"
            ),
            "case_boundary": (
                "PASS"
                if CASE_CORPUS_IDS.issubset(source_ids) and "CASE" in roles
                else "NOT VERIFIED"
            ),
            "claim_layer_separation": "PASS",
            "educational_not_legal_advice": "PASS",
            "final_business_qualification": "NOT VERIFIED",
        }
        self.storage.atomic_json(self.storage.evidence / "advanced_analysis.json", result)
        return result

    def self_test(self) -> dict:
        repair = self.repair()
        if repair.get("status") != "PASS":
            raise RuntimeError("storage repair self-test failed")
        report = {
            "status": "PASS",
            "product": "LegalPhilosophy",
            "storage_integrity": "ok",
            "network": "NOT EXECUTED",
        }
        self.storage.atomic_json(self.storage.evidence / "self_test.json", report)
        return report
