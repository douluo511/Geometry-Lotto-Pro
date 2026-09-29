from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

class EvidenceLedger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def make_row(self, kind: str, status: str, **details):
        return {
            "type": kind,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details,
        }

    def record(self, kind: str, status: str, **details):
        row = self.make_row(kind, status, **details)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
        return row
