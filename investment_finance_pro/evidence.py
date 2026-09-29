from __future__ import annotations
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class EvidenceLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.path.parent / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _materialize_raw(self, value):
        if isinstance(value, list):
            return [self._materialize_raw(x) for x in value]
        if not isinstance(value, dict):
            return value
        out = {k:self._materialize_raw(v) for k,v in value.items() if k != "body_b64"}
        body = value.get("body_b64")
        if body is not None:
            raw = base64.b64decode(body.encode("ascii"))
            digest = hashlib.sha256(raw).hexdigest()
            expected = str(value.get("payload_hash") or value.get("sha256") or "")
            if expected and digest != expected:
                raise ValueError("raw evidence hash mismatch")
            target = self.raw_dir / f"{digest}.bin"
            if not target.exists():
                tmp = target.with_suffix(".tmp")
                tmp.write_bytes(raw)
                os.replace(tmp, target)
            out["raw_path"] = str(target)
            out["raw_sha256"] = digest
            out["raw_bytes"] = len(raw)
        return out

    def record(self, kind: str, status: str, **details):
        row = {
            "type": kind,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": self._materialize_raw(details),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
