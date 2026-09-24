from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, Tuple

from contracts import validate_knowledge
from domain import SourceRecord


class NetError(RuntimeError):
    pass


class NetClient:
    def __init__(self, timeout: float = 12.0, retries: int = 2, max_bytes: int = 2_000_000):
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.max_bytes = int(max_bytes)

    def get_json(
        self,
        url: str,
        validator: Callable[[Dict], None] = validate_knowledge,
        opener=None,
        sleeper=time.sleep,
    ) -> Tuple[Dict, SourceRecord]:
        if not url.lower().startswith("https://"):
            raise NetError("HTTPS is required")

        opener = opener or urllib.request.urlopen
        last_error = None

        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, headers={"User-Agent": "Psychology-Insight-Pro/0.2.0"})
            try:
                with opener(req, timeout=self.timeout) as resp:
                    status = int(getattr(resp, "status", 200))
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if status == 429 or 500 <= status <= 599:
                        raise urllib.error.HTTPError(url, status, "transient", resp.headers, None)
                    if status < 200 or status >= 300:
                        raise NetError(f"HTTP {status}")
                    if "json" not in ctype and "text/plain" not in ctype and ctype:
                        raise NetError(f"unexpected content-type: {ctype}")
                    raw = resp.read(self.max_bytes + 1)
                    if len(raw) > self.max_bytes:
                        raise NetError("response too large")
                    digest = hashlib.sha256(raw).hexdigest()
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except Exception as exc:
                        raise NetError("invalid UTF-8 JSON") from exc
                    validator(payload)
                    source = SourceRecord(
                        url=url,
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        http_status=status,
                        sha256=digest,
                        bytes_count=len(raw),
                    )
                    return payload, source
            except urllib.error.HTTPError as exc:
                last_error = exc
                transient = exc.code == 429 or 500 <= exc.code <= 599
                if not transient or attempt >= self.retries:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
            except NetError:
                raise

            delay = min(2.0, 0.25 * (2 ** attempt)) + random.uniform(0.0, 0.1)
            sleeper(delay)

        raise NetError(f"network request failed: {last_error}")
