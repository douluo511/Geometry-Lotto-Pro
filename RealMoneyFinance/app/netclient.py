from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import random
import time
from typing import Any

import requests


@dataclass(frozen=True)
class ResponseMeta:
    url: str
    status: int
    content_type: str
    retrieved_at_unix: float
    payload_sha256: str
    attempts: int


class NetClient:
    def __init__(self, evidence_path: Path, connect_timeout: float = 5.0, read_timeout: float = 15.0,
                 max_attempts: int = 3, backoff_base: float = 0.6):
        self.evidence_path = evidence_path
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_attempts = int(max_attempts)
        self.backoff_base = float(backoff_base)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "RealMoneyFinance/0.1 strict-validation"})

    def _record(self, row: dict[str, Any]) -> None:
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with self.evidence_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def get_json(self, url: str, params: dict[str, Any]) -> tuple[dict[str, Any], ResponseMeta]:
        if not str(url).lower().startswith("https://"):
            raise ValueError("production network requests require HTTPS")
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.time()
            try:
                r = self.session.get(
                    url,
                    params=params,
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=True,
                )
                status = int(r.status_code)
                ctype = str(r.headers.get("content-type", "")).lower()
                if status == 429 or 500 <= status <= 599:
                    raise requests.HTTPError(f"retryable HTTP {status}", response=r)
                r.raise_for_status()
                if "json" not in ctype and "javascript" not in ctype and "text/plain" not in ctype:
                    raise ValueError(f"unexpected Content-Type: {ctype}")
                body = r.content
                if not body:
                    raise ValueError("empty response")
                digest = hashlib.sha256(body).hexdigest()
                obj = r.json()
                if not isinstance(obj, dict):
                    raise ValueError("JSON root must be an object")
                meta = ResponseMeta(str(r.url), status, ctype, time.time(), digest, attempt)
                self._record({
                    "status": "PASS",
                    "url": str(r.url),
                    "http_status": status,
                    "content_type": ctype,
                    "payload_sha256": digest,
                    "attempt": attempt,
                    "elapsed_seconds": round(time.time() - started, 6),
                })
                return obj, meta
            except Exception as exc:
                last_error = exc
                self._record({
                    "status": "FAIL",
                    "url": url,
                    "attempt": attempt,
                    "error": repr(exc),
                    "elapsed_seconds": round(time.time() - started, 6),
                })
                if attempt >= self.max_attempts:
                    break
                sleep_s = self.backoff_base * (2 ** (attempt - 1)) + random.uniform(0, self.backoff_base)
                time.sleep(sleep_s)
        raise RuntimeError(f"network request failed after {self.max_attempts} attempts") from last_error
