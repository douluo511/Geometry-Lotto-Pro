"""Allowlisted HTTPS raw-source fetcher; no parsing or authenticity claims."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .core import MAX_RAW_SOURCE_BYTES, SOURCE_HOSTS_BY_GAME, GateError


def _allowed_root(game: str, url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError) as exc:
        raise GateError("INVALID_SOURCE_URL") from exc
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or parsed.fragment):
        raise GateError("HTTPS_SOURCE_URL_REQUIRED")
    for root in SOURCE_HOSTS_BY_GAME[game]:
        if host == root or host.endswith("." + root):
            return host, root
    raise GateError("SOURCE_HOST_NOT_ALLOWLISTED_FOR_GAME")


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Refuse redirects outside the game-specific official host allowlist."""
    def __init__(self, game: str):
        super().__init__()
        self.game = game
        self.redirect_chain: list[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _allowed_root(self.game, newurl)
        self.redirect_chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_raw_source(game: str, url: str, *, timeout: float = 15.0,
                     max_bytes: int = MAX_RAW_SOURCE_BYTES) -> dict:
    """Fetch bytes from an allowlisted HTTPS host.

    The fetched-at timestamp is the local process clock, not a trusted timestamp.
    HTTP Last-Modified is returned as a separate header claim and is NOT treated
    as page publication time. This function does not parse, verify, or admit data.
    """
    if game not in SOURCE_HOSTS_BY_GAME:
        raise GateError("UNKNOWN_LOTTERY_FOR_SOURCE_FETCH")
    if type(timeout) not in (int, float) or timeout <= 0:
        raise GateError("INVALID_FETCH_TIMEOUT")
    if type(max_bytes) is not int or max_bytes < 1 or max_bytes > MAX_RAW_SOURCE_BYTES:
        raise GateError("INVALID_RAW_SOURCE_LIMIT")
    _allowed_root(game, url)
    redirects = _SafeRedirectHandler(game)
    opener = build_opener(redirects)
    request = Request(
        url,
        headers={
            "User-Agent": "SSQ-DLT-V47-Research/1.0 (+source-audit; no-purchase)",
            "Accept": "text/html,application/json,application/xml;q=0.9,*/*;q=0.5",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        response = opener.open(request, timeout=timeout)
        with response:
            status = getattr(response, "status", response.getcode())
            final_url = response.geturl()
            _allowed_root(game, final_url)
            if status != 200:
                raise GateError("SOURCE_HTTP_STATUS_NOT_200")
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    if int(length) > max_bytes:
                        raise GateError("RAW_SOURCE_TOO_LARGE")
                except ValueError:
                    pass
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise GateError("RAW_SOURCE_TOO_LARGE")
            if not raw:
                raise GateError("EMPTY_RAW_SOURCE_RESPONSE")
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            last_modified = response.headers.get("Last-Modified")
    except GateError:
        raise
    except Exception as exc:
        raise GateError("RAW_SOURCE_FETCH_FAILED:" + type(exc).__name__) from exc
    return {
        "requested_url": url,
        "final_url": final_url,
        "final_host": urlsplit(final_url).hostname,
        "redirect_chain": list(redirects.redirect_chain),
        "http_status": status,
        "content_type": content_type,
        "http_last_modified_header_claim": last_modified,
        "raw_bytes": raw,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "fetched_at_utc_local_untrusted": datetime.now(timezone.utc).isoformat(),
        "source_authenticity": "NOT_VERIFIED",
        "published_at": None,
        "official_admission": "BLOCKED",
    }
