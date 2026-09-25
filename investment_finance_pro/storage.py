from __future__ import annotations
from pathlib import Path
import legacy_backend as legacy
from contracts import validate_snapshot

class SnapshotStorage:
    def path(self) -> Path:
        return legacy.cache_path()

    def read(self):
        p = self.path()
        if not p.exists():
            return None
        return validate_snapshot(legacy.read_json(p))

    def write(self, data: dict):
        validate_snapshot(data)
        legacy.atomic_json_write(self.path(), data)
        return self.read()

    def repair(self):
        result = legacy.repair_system()
        status = "PASS" if result.get("overall") == "PASS" else "FAIL"
        return {"status": status, **result}
