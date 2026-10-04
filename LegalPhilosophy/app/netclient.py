from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import time
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class NetReceipt:
    url: str
    final_url: str | None
    status: int | None
    retrieved_at: str
    content_type: str | None
    payload_sha256: str | None
    bytes: int | None
    attempt: int
    result: str
    error: str | None

    def to_dict(self) -> dict:
        return asdict(self)


class NetClient:
    def __init__(
        self,
        evidence_path: Path,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_attempts: int = 3,
        max_bytes: int = 2_500_000,
    ):
        self.evidence_path = Path(evidence_path)
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_attempts = int(max_attempts)
        self.max_bytes = int(max_bytes)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "LegalPhilosophyStudySystem/0.1 (+evidence-first educational client)",
            "Accept": "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.2",
        })

    def _record(self, receipt: NetReceipt) -> None:
        with self.evidence_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _https(url: str) -> bool:
        return urlparse(url).scheme.lower() == "https"

    def get_bytes(
        self,
        url: str,
        *,
        allowed_content_types: tuple[str, ...],
        max_bytes: int | None = None,
        accept: str | None = None,
    ) -> tuple[bytes, NetReceipt]:
        if not self._https(url):
            raise ValueError("HTTPS-only source policy")
        limit = int(max_bytes or self.max_bytes)
        last_error: Exception | None = None
        retryable_status = {429, 500, 502, 503, 504}
        for attempt in range(1, self.max_attempts + 1):
            now = datetime.now(timezone.utc).isoformat()
            try:
                headers = {"Accept": accept} if accept else None
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=True,
                )
                chain = [item.url for item in response.history] + [response.url]
                if any(not self._https(item) for item in chain):
                    raise RuntimeError("HTTPS downgrade/redirect rejected")
                content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if response.status_code in retryable_status:
                    raise requests.HTTPError(f"retryable HTTP {response.status_code}", response=response)
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                if content_type not in allowed_content_types:
                    raise RuntimeError(f"unexpected Content-Type {content_type!r}")
                raw = response.content
                if not raw or len(raw) > limit:
                    raise RuntimeError(f"invalid payload size {len(raw)}")
                receipt = NetReceipt(
                    url=url,
                    final_url=response.url,
                    status=response.status_code,
                    retrieved_at=now,
                    content_type=content_type,
                    payload_sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),
                    attempt=attempt,
                    result="PASS",
                    error=None,
                )
                self._record(receipt)
                return raw, receipt
            except Exception as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self._record(NetReceipt(
                    url=url,
                    final_url=None,
                    status=status,
                    retrieved_at=now,
                    content_type=None,
                    payload_sha256=None,
                    bytes=None,
                    attempt=attempt,
                    result="FAIL",
                    error=repr(exc),
                ))
                retryable = isinstance(exc, (requests.ConnectionError, requests.Timeout, requests.HTTPError))
                if attempt >= self.max_attempts or not retryable:
                    break
                time.sleep(min(2.0, 0.25 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.15))
        raise RuntimeError(f"binary network request failed after {self.max_attempts} bounded attempts: {last_error!r}")

    def get_text(self, url: str, *, allowed_content_types: tuple[str, ...] = ("text/html", "text/plain", "application/xhtml+xml")) -> tuple[str, NetReceipt]:
        if not self._https(url):
            raise ValueError("HTTPS-only source policy")
        last_error: Exception | None = None
        retryable_status = {429, 500, 502, 503, 504}
        for attempt in range(1, self.max_attempts + 1):
            now = datetime.now(timezone.utc).isoformat()
            try:
                response = self.session.get(
                    url,
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=True,
                )
                chain = [item.url for item in response.history] + [response.url]
                if any(not self._https(item) for item in chain):
                    raise RuntimeError("HTTPS downgrade/redirect rejected")
                content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
                if response.status_code in retryable_status:
                    raise requests.HTTPError(f"retryable HTTP {response.status_code}", response=response)
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                if content_type not in allowed_content_types:
                    raise RuntimeError(f"unexpected Content-Type {content_type!r}")
                raw = response.content
                if not raw or len(raw) > self.max_bytes:
                    raise RuntimeError(f"invalid payload size {len(raw)}")
                payload_hash = hashlib.sha256(raw).hexdigest()
                text = raw.decode(response.encoding or "utf-8", errors="replace")
                receipt = NetReceipt(
                    url=url,
                    final_url=response.url,
                    status=response.status_code,
                    retrieved_at=now,
                    content_type=content_type,
                    payload_sha256=payload_hash,
                    bytes=len(raw),
                    attempt=attempt,
                    result="PASS",
                    error=None,
                )
                self._record(receipt)
                return text, receipt
            except Exception as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                receipt = NetReceipt(
                    url=url,
                    final_url=None,
                    status=status,
                    retrieved_at=now,
                    content_type=None,
                    payload_sha256=None,
                    bytes=None,
                    attempt=attempt,
                    result="FAIL",
                    error=repr(exc),
                )
                self._record(receipt)
                retryable = isinstance(exc, (requests.ConnectionError, requests.Timeout, requests.HTTPError))
                if attempt >= self.max_attempts or not retryable:
                    break
                time.sleep(min(2.0, 0.25 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.15))
        raise RuntimeError(f"network request failed after {self.max_attempts} bounded attempts: {last_error!r}")
