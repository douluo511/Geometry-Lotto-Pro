from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .domain import SourceDocument, validate_source


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.raw = self.root / "raw"
        self.canonical = self.root / "canonical"
        self.evidence = self.root / "evidence"
        for folder in (self.raw, self.canonical, self.evidence):
            folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def atomic_bytes(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass

    @classmethod
    def atomic_json(cls, path: Path, obj: object) -> None:
        cls.atomic_bytes(
            path,
            (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )

    def persist_binary_artifact(self, name: str, data: bytes, expected_sha256: str) -> Path:
        if not name or "/" in name or "\\" in name:
            raise ValueError("binary artifact name must be a simple filename")
        actual = self.sha256_bytes(data)
        if actual != expected_sha256 or len(expected_sha256) != 64:
            raise ValueError("binary artifact SHA-256 mismatch")
        path = self.raw / name
        self.atomic_bytes(path, data)
        if self.sha256_bytes(path.read_bytes()) != expected_sha256:
            raise ValueError("binary artifact post-write integrity mismatch")
        return path

    def persist_source(self, doc: SourceDocument, text: str) -> None:
        validate_source(doc)
        raw_bytes = text.encode("utf-8")
        if self.sha256_bytes(raw_bytes) != doc.text_sha256:
            raise ValueError("canonical text hash mismatch")
        raw_path = self.raw / f"{doc.source_id}-{doc.text_sha256}.txt"
        self.atomic_bytes(raw_path, raw_bytes)
        current = self.load_index(validate_raw=False)
        current[doc.source_id] = doc.to_dict()
        self.atomic_json(self.canonical / "sources.json", current)

    def load_index(self, *, validate_raw: bool = True) -> dict[str, dict]:
        path = self.canonical / "sources.json"
        if not path.exists():
            return {}
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("source index root must be object")
        if validate_raw:
            for source_id, meta in obj.items():
                if not isinstance(meta, dict) or meta.get("source_id") != source_id:
                    raise ValueError("source index identity mismatch")
                text_hash = str(meta.get("text_sha256", ""))
                raw_path = self.raw / f"{source_id}-{text_hash}.txt"
                if not raw_path.is_file() or self.sha256_bytes(raw_path.read_bytes()) != text_hash:
                    raise ValueError(f"raw/canonical integrity mismatch for {source_id}")
        return obj

    def repair(self) -> dict:
        repaired = []
        path = self.canonical / "sources.json"
        try:
            self.load_index(validate_raw=True)
        except Exception as exc:
            backup = self.evidence / "repair-invalid-sources.json"
            if path.exists():
                self.atomic_bytes(backup, path.read_bytes())
                path.unlink()
            repaired.append({"item": "canonical_source_index", "action": "quarantined", "reason": repr(exc)})
        for folder in (self.raw, self.canonical, self.evidence):
            folder.mkdir(parents=True, exist_ok=True)
        report = {"status": "PASS", "repaired": repaired, "user_data_deleted": False}
        self.atomic_json(self.evidence / "repair_result.json", report)
        return report
