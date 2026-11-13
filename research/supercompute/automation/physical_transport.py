"""Bounded, auditable issuer transport (never changes authenticity policy).

Retries transient failures, not malformed draw data. Alternate endpoints
must be on the explicit official-host allowlist. Certificate verification stays
enabled. No third-party outcome is ever substituted for an issuer document.
"""
from __future__ import annotations
from hashlib import sha256
from http.client import HTTPException
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_BYTES = 1_200_000
RETRYABLE = {408, 425, 429, 500, 502, 503, 504, 567}
UA = "Geometry-Lotto-Pro-Issuer-Evidence/2.0"


class TransportExhausted(OSError):
    def __init__(self, attempts, raw_bodies=None):
        super().__init__("OFFICIAL_SOURCE_ATTEMPTS_EXHAUSTED")
        self.attempts = attempts
        self.raw_bodies = dict(raw_bodies or {})


def resilient_fetch(url: str, *, alternates=(), opener=urlopen,
                    sleeper=time.sleep, max_attempts=4,
                    delay_seconds=0.25):
    """Return (status, final_url, raw_bytes, attempt_receipts).

    On failure, raise TransportExhausted containing all bounded attempt
    metadata. Returned bytes are preserved by calling collectors. Host
    allowlisting is enforced both before connection and after redirect.
    """
    initial = urlsplit(url)
    if initial.scheme != "https" or not initial.hostname:
        raise ValueError("HTTPS_SOURCE_REQUIRED")
    urls = (url, *alternates)
    allowed = {urlsplit(u).hostname for u in urls}
    for candidate in urls:
        p = urlsplit(candidate)
        if p.scheme != "https" or not p.hostname or p.path != initial.path:
            raise ValueError("UNTRUSTED_OFFICIAL_ALTERNATE")
    if max_attempts < 1 or max_attempts > 8:
        raise ValueError("ATTEMPT_LIMIT_INVALID")
    attempts = []
    raw_bodies = {}
    for i in range(max_attempts):
        target = urls[i % len(urls)]
        record = {"attempt": i + 1, "url": target, "http_status": None,
                  "final_url": None, "response_sha256": None,
                  "reason": None}
        try:
            req = Request(target, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
            })
            try:
                with opener(req, timeout=12) as resp:
                    code, resolved = int(resp.status), resp.geturl()
                    raw = resp.read(MAX_BYTES + 1)
            except HTTPError as exc:
                code, resolved = int(exc.code), exc.geturl()
                raw = exc.read(MAX_BYTES + 1)
            record["http_status"], record["final_url"] = code, resolved
            if isinstance(raw, bytes):
                record["response_sha256"] = sha256(raw).hexdigest()
                if raw:
                    raw_bodies[record["response_sha256"]] = raw
            destination = urlsplit(resolved)
            if (destination.scheme != "https" or destination.hostname not in allowed
                    or destination.path != initial.path
                    or destination.query != urlsplit(target).query):
                record["reason"] = "UNTRUSTED_REDIRECT"
                attempts.append(record)
                # Never retry a potentially untrusted endpoint.
                raise TransportExhausted(attempts, raw_bodies)
            if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
                record["reason"] = "RESPONSE_BYTES_INVALID"
                attempts.append(record)
                raise TransportExhausted(attempts, raw_bodies)
            if code == 200:
                record["reason"] = "HTTP_200"
                attempts.append(record)
                return code, resolved, raw, attempts, raw_bodies
            record["reason"] = "HTTP_NON_200"
            attempts.append(record)
            if code not in RETRYABLE:
                raise TransportExhausted(attempts, raw_bodies)
        except TransportExhausted:
            raise
        except (URLError, TimeoutError, OSError, HTTPException) as exc:
            record["reason"] = "NETWORK_" + type(exc).__name__
            attempts.append(record)
        # An HTTP 403 is not treated as a transient status. Never evade
        # access restrictions with proxies, randomized agents or TLS bypass.
        if i + 1 < max_attempts:
            sleeper(min(delay_seconds * 2 ** i, 2))
    raise TransportExhausted(attempts, raw_bodies)


def dlt_fetch(url: str, **kwargs):
    """Try two domain aliases belonging to Guangdong's official issuer site."""
    from urllib.parse import urlunsplit
    p = urlsplit(url)
    if p.hostname != "www.gdlottery.cn":
        raise ValueError("DLT_ISSUER_URL_INVALID")
    alternate = urlunsplit((p.scheme, "gdlottery.cn", p.path, p.query, ""))
    return resilient_fetch(url, alternates=(alternate,), **kwargs)


def ssq_fetch(url: str, **kwargs):
    if urlsplit(url).hostname != "www.swlc.net.cn":
        raise ValueError("SSQ_ISSUER_URL_INVALID")
    return resilient_fetch(url, **kwargs)
