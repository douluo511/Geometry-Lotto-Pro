from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from head_intelligence.domain import RawDocument


class AtomicStorage:
    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self._data_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    def save_raw(self, document: RawDocument) -> Path:
        path = self.raw_dir / f"{document.source_id}_{document.payload_hash[:12]}.xml"
        if not path.exists():
            self._atomic_write_bytes(path, document.payload)
        return path

    def save_json_atomic(self, relative_name: str, payload: dict) -> Path:
        path = self._data_dir / relative_name
        text = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._atomic_write_bytes(path, text)
        return path

    def read_json(self, relative_name: str) -> dict | None:
        path = self._data_dir / relative_name
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _atomic_write_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
