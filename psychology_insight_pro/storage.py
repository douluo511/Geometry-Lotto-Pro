from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable

from contracts import validate_knowledge
from domain import SourceRecord


class KnowledgeStorage:
    def __init__(self, local_path: Path, bundled_path: Path):
        self.local_path = Path(local_path)
        self.bundled_path = Path(bundled_path)

    @property
    def evidence_path(self) -> Path:
        return self.local_path.with_suffix(".source.json")

    def _load(self, path: Path) -> Dict:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        validate_knowledge(data)
        return data

    def ensure(self) -> Dict:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._load(self.local_path)
        except Exception:
            self.repair_knowledge()
            return self._load(self.local_path)

    def load_knowledge(self) -> Dict:
        return self.ensure()

    @staticmethod
    def _json_bytes(value) -> bytes:
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    @staticmethod
    def _stage(path: Path, payload: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".stage", dir=str(path.parent))
        tmp_path = Path(tmp)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            return tmp_path
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _commit_replace(staged: Path, target: Path) -> None:
        os.replace(staged, target)

    @staticmethod
    def _restore(path: Path, previous: bytes | None) -> None:
        if previous is None:
            path.unlink(missing_ok=True)
            return
        staged = KnowledgeStorage._stage(path, previous)
        KnowledgeStorage._commit_replace(staged, path)

    def replace_knowledge(
        self,
        payload: Dict,
        sources: SourceRecord | Iterable[SourceRecord] | None = None,
    ) -> None:
        validate_knowledge(payload)
        self.local_path.parent.mkdir(parents=True, exist_ok=True)

        if sources is None:
            source_list: list[SourceRecord] = []
        elif isinstance(sources, SourceRecord):
            source_list = [sources]
        else:
            source_list = list(sources)

        knowledge_bytes = self._json_bytes(payload)
        knowledge_sha = hashlib.sha256(knowledge_bytes).hexdigest()
        evidence_core = {
            "schema": "psychology-source-evidence-v2",
            "knowledge_sha256": knowledge_sha,
            "knowledge_version": payload.get("version"),
            "source_count": len(source_list),
            "sources": [asdict(s) for s in source_list],
        }
        commit_id = hashlib.sha256(
            self._json_bytes(evidence_core) + knowledge_sha.encode("ascii")
        ).hexdigest()
        evidence_payload = {**evidence_core, "commit_id": commit_id}

        old_knowledge = self.local_path.read_bytes() if self.local_path.exists() else None
        old_evidence = self.evidence_path.read_bytes() if self.evidence_path.exists() else None
        staged_knowledge: Path | None = None
        staged_evidence: Path | None = None
        evidence_committed = False
        try:
            # Stage and validate the exact bytes before mutating production state.
            staged_knowledge = self._stage(self.local_path, knowledge_bytes)
            self._load(staged_knowledge)
            staged_evidence = self._stage(self.evidence_path, self._json_bytes(evidence_payload))

            # Evidence first, canonical knowledge last. If the canonical replace
            # fails, evidence is rolled back. Missing evidence can never be PASS.
            self._commit_replace(staged_evidence, self.evidence_path)
            staged_evidence = None
            evidence_committed = True
            self._commit_replace(staged_knowledge, self.local_path)
            staged_knowledge = None

            self._load(self.local_path)
            saved_evidence = json.loads(self.evidence_path.read_text(encoding="utf-8"))
            if saved_evidence.get("commit_id") != commit_id:
                raise RuntimeError("source evidence commit_id mismatch")
            if hashlib.sha256(self.local_path.read_bytes()).hexdigest() != knowledge_sha:
                raise RuntimeError("knowledge hash mismatch after commit")
        except Exception:
            if evidence_committed:
                self._restore(self.evidence_path, old_evidence)
            current = self.local_path.read_bytes() if self.local_path.exists() else None
            if current != old_knowledge:
                self._restore(self.local_path, old_knowledge)
            raise
        finally:
            if staged_knowledge is not None:
                staged_knowledge.unlink(missing_ok=True)
            if staged_evidence is not None:
                staged_evidence.unlink(missing_ok=True)

    def repair_knowledge(self) -> Dict:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._load(self.local_path)
            return {"knowledge": "PASS", "repair_action": "NO_REPAIR_NEEDED"}
        except Exception:
            # Validate the known-good bundle before preserving or changing local
            # state. Keep exact corrupt bytes and provenance for user recovery.
            bundled = self._load(self.bundled_path)
            old = self.local_path.read_bytes() if self.local_path.exists() else None
            old_evidence = self.evidence_path.read_bytes() if self.evidence_path.exists() else None
            backups = {}
            for path, raw in ((self.local_path, old), (self.evidence_path, old_evidence)):
                if raw is not None:
                    digest = hashlib.sha256(raw).hexdigest()
                    backup = self.local_path.parent / "repair_backups" / (path.name + "." + digest + ".bak")
                    staged = self._stage(backup, raw)
                    try:
                        self._commit_replace(staged, backup)
                    finally:
                        staged.unlink(missing_ok=True)
                    backups[path.name] = str(backup)
            staged = self._stage(self.local_path, self._json_bytes(bundled))
            try:
                self._load(staged)
                self._commit_replace(staged, self.local_path)
                self._load(self.local_path)
                # A bundle restoration is local repair, not a network receipt.
                self.evidence_path.unlink(missing_ok=True)
            except Exception:
                self._restore(self.local_path, old)
                self._restore(self.evidence_path, old_evidence)
                raise
            finally:
                staged.unlink(missing_ok=True)
            return {"knowledge": "PASS", "repair_action": "RESTORED_VALIDATED_BUNDLE", "backups": backups,
                    "source_evidence": "NOT VERIFIED", "user_data_preserved": True}
