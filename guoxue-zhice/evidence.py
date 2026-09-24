from __future__ import annotations
import datetime as dt, json
from pathlib import Path
from storage import atomic_json

class EvidenceLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
    def _load(self):
        if not self.path.exists():
            return {"schema": 1, "events": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != 1 or not isinstance(value.get("events"), list):
            raise ValueError("evidence ledger corrupt")
        return value
    def record(self, kind: str, status: str, **details):
        if status not in {"PASS", "FAIL", "REPAIRED", "INFO"}:
            raise ValueError("invalid evidence status")
        event = {"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "kind": kind, "status": status, "details": details}
        value = self._load()
        value["events"] = (value["events"] + [event])[-300:]
        atomic_json(self.path, value)
        return event
    def recent(self, limit=20):
        return list(reversed(self._load()["events"][-limit:]))
