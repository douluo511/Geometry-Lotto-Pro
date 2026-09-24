from __future__ import annotations
import json, os, shutil, sys
from pathlib import Path
from typing import Any
from domain import sha256_bytes, validate_knowledge, validate_state

def bundled_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)

def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

class Store:
    def __init__(self, root: Path | None = None):
        if root is None:
            appdata = os.environ.get("APPDATA")
            root = Path(appdata) / "GuoxueZhice" if appdata else Path.home() / ".guoxue-zhice"
        self.root = Path(root)
        self.data_dir = self.root / "data"
        self.knowledge_path = self.data_dir / "knowledge.json"
        self.state_path = self.root / "state.json"
        self.evidence_path = self.root / "evidence.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_seed()

    def _ensure_seed(self):
        if not self.knowledge_path.exists():
            shutil.copy2(bundled_path("data", "knowledge.json"), self.knowledge_path)
        if not self.state_path.exists():
            atomic_json(self.state_path, {"schema": 1, "analyses": [], "reviews": [], "last_update": None})
        if not self.evidence_path.exists():
            atomic_json(self.evidence_path, {"schema": 1, "events": []})

    def load_knowledge(self):
        return validate_knowledge(json.loads(self.knowledge_path.read_text(encoding="utf-8")))

    def load_state(self):
        return validate_state(json.loads(self.state_path.read_text(encoding="utf-8")))

    def save_state(self, value):
        validate_state(value)
        atomic_json(self.state_path, value)

    def append_analysis(self, item):
        state = self.load_state()
        state["analyses"] = (state["analyses"] + [item])[-100:]
        self.save_state(state)

    def append_review(self, item):
        state = self.load_state()
        state["reviews"] = (state["reviews"] + [item])[-200:]
        self.save_state(state)

    def replace_knowledge(self, raw: bytes) -> str:
        validate_knowledge(json.loads(raw.decode("utf-8")))
        staging = self.data_dir / "knowledge.json.staging"
        backup = self.data_dir / "knowledge.json.backup"
        staging.write_bytes(raw)
        validate_knowledge(json.loads(staging.read_text(encoding="utf-8")))
        if self.knowledge_path.exists():
            shutil.copy2(self.knowledge_path, backup)
        try:
            os.replace(staging, self.knowledge_path)
            self.load_knowledge()
        except Exception:
            if backup.exists():
                shutil.copy2(backup, self.knowledge_path)
            raise
        return sha256_bytes(raw)

    def repair(self):
        checks = []
        try:
            kb = self.load_knowledge()
            checks.append(("Knowledge DB", "PASS", f'{len(kb["classics"])} classics'))
        except Exception as exc:
            shutil.copy2(bundled_path("data", "knowledge.json"), self.knowledge_path)
            self.load_knowledge()
            checks.append(("Knowledge DB", "REPAIRED", str(exc)))
        try:
            state = self.load_state()
            checks.append(("State DB", "PASS", f'{len(state["reviews"])} reviews'))
        except Exception as exc:
            atomic_json(self.state_path, {"schema": 1, "analyses": [], "reviews": [], "last_update": None})
            self.load_state()
            checks.append(("State DB", "REPAIRED", str(exc)))
        try:
            self.load_knowledge(); self.load_state()
            final = "PASS"
        except Exception as exc:
            checks.append(("Final Gate", "FAIL", str(exc)))
            final = "FAIL"
        return {"status": final, "checks": checks}
