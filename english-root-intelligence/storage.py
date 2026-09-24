from __future__ import annotations
import json
import os
import shutil
from pathlib import Path

from core import Store, bundled_path
from contracts import validate_roots

class RootStorage:
    def __init__(self, root: Path | None = None):
        self.store = Store(root)

    @property
    def root(self):
        return self.store.root

    def load_roots(self):
        return self.store.load_roots()

    def load_progress(self):
        return self.store.load_progress()

    def mark_practiced(self, mapping):
        return self.store.mark_practiced(mapping)

    def bump_analysis(self):
        return self.store.bump_analysis()

    def save_progress(self, value):
        return self.store.save_progress(value)

    def replace_roots(self, raw: bytes) -> dict:
        value = validate_roots(json.loads(raw.decode("utf-8-sig")))
        path = self.store.roots_path
        stage = path.with_suffix(".staging")
        backup = path.with_suffix(".backup")
        with stage.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        validate_roots(json.loads(stage.read_text(encoding="utf-8")))
        shutil.copy2(path, backup)
        try:
            os.replace(stage, path)
            self.store.load_roots()
        except Exception:
            if backup.exists():
                shutil.copy2(backup, path)
            raise
        return value

    def repair(self):
        checks = []
        try:
            roots = self.store.load_roots()
            checks.append(("Knowledge DB", "PASS", f'{len(roots["roots"])} roots'))
        except Exception as exc:
            shutil.copy2(bundled_path("data", "roots.json"), self.store.roots_path)
            self.store.load_roots()
            checks.append(("Knowledge DB", "REPAIRED", str(exc)))
        try:
            progress = self.store.load_progress()
            checks.append(("User Progress", "PASS", f'{len(progress.get("practiced", {}))} practiced roots'))
        except Exception as exc:
            self.store.save_progress({"schema": 1, "practiced": {}, "analyses": 0, "last_update": None})
            checks.append(("User Progress", "REPAIRED", str(exc)))
        try:
            self.store.load_roots()
            self.store.load_progress()
            status = "PASS"
        except Exception as exc:
            checks.append(("Final Gate", "FAIL", str(exc)))
            status = "FAIL"
        return {"status": status, "checks": checks}
