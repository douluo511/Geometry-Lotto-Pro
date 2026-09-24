from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict

from contracts import validate_knowledge
from domain import SourceRecord


class KnowledgeStorage:
    def __init__(self, local_path: Path, bundled_path: Path):
        self.local_path = Path(local_path)
        self.bundled_path = Path(bundled_path)

    def _load(self, path: Path) -> Dict:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        validate_knowledge(data)
        return data

    def ensure(self) -> Dict:
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.local_path.exists():
            shutil.copy2(self.bundled_path, self.local_path)
        try:
            return self._load(self.local_path)
        except Exception:
            shutil.copy2(self.bundled_path, self.local_path)
            return self._load(self.local_path)

    def load_knowledge(self) -> Dict:
        return self.ensure()

    def replace_knowledge(self, payload: Dict, source: SourceRecord | None = None) -> None:
        validate_knowledge(payload)
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        backup = self.local_path.with_suffix(".json.bak")
        if self.local_path.exists():
            shutil.copy2(self.local_path, backup)

        fd, tmp = tempfile.mkstemp(prefix="pip_", suffix=".json", dir=str(self.local_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.local_path)
            self._load(self.local_path)
            if source is not None:
                evidence_path = self.local_path.with_suffix(".source.json")
                with evidence_path.open("w", encoding="utf-8") as f:
                    json.dump(source.__dict__, f, ensure_ascii=False, indent=2)
        except Exception:
            if backup.exists():
                shutil.copy2(backup, self.local_path)
            raise
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def repair_knowledge(self) -> Dict[str, str]:
        try:
            self._load(self.local_path)
            return {"knowledge": "PASS"}
        except Exception:
            shutil.copy2(self.bundled_path, self.local_path)
            self._load(self.local_path)
            return {"knowledge": "REPAIRED"}
