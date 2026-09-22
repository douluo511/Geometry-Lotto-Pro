from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def next_draw_date(after: date) -> date:
    cur = after + timedelta(days=1)
    while cur.weekday() not in (0, 2, 5):  # Mon/Wed/Sat
        cur += timedelta(days=1)
    return cur


def next_issue(latest_issue: str, latest_date: str) -> str:
    d = parse_date(latest_date)
    nxt = next_draw_date(d)
    yy = nxt.year % 100
    current_year = int(latest_issue[:2])
    seq = int(latest_issue[2:])
    return f"{yy:02d}{1 if yy != current_year else seq + 1:03d}"


def zscores(values: Iterable[float]) -> list[float]:
    vals = [float(v) for v in values]
    if not vals:
        return []
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    if var <= 1e-15:
        return [0.0 for _ in vals]
    sd = var ** 0.5
    return [(v - mean) / sd for v in vals]


def app_data_dir() -> Path:
    override = os.environ.get("GLP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return (base / "GeometryLottoPro").resolve()


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
