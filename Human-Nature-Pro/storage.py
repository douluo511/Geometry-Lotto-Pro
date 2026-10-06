from __future__ import annotations
import json
import os
import shutil
from pathlib import Path

from contracts import validate_knowledge

class KnowledgeStorage:
    def __init__(self, root: Path, bundled_path: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "knowledge_base.json"
        self.bundled_path = Path(bundled_path)
        if not self.path.exists():
            shutil.copy2(self.bundled_path, self.path)

    def load(self):
        return validate_knowledge(json.loads(self.path.read_text(encoding="utf-8")))

    def replace(self, raw: bytes):
        data = validate_knowledge(json.loads(raw.decode("utf-8-sig")))
        stage = self.path.with_suffix(".staging")
        backup = self.path.with_suffix(".backup")
        with stage.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        validate_knowledge(json.loads(stage.read_text(encoding="utf-8")))
        shutil.copy2(self.path, backup)
        try:
            os.replace(stage, self.path)
            self.load()
        except Exception:
            if backup.exists():
                shutil.copy2(backup, self.path)
            raise
        return data

    def repair(self):
        try:
            self.load()
            return {"status": "PASS", "action": "checked", "path": str(self.path)}
        except Exception as exc:
            shutil.copy2(self.bundled_path, self.path)
            self.load()
            return {
                "status": "PASS",
                "action": "restored",
                "path": str(self.path),
                "detail": str(exc),
            }
