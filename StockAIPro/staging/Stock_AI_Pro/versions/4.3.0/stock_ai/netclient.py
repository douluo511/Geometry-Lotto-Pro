from __future__ import annotations

from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import threading
import time
from urllib.parse import urlsplit

import requests


class NetClientError(RuntimeError):
    pass


class NetClientPolicyError(NetClientError):
    pass


class RetryableHTTPError(NetClientError):
    def __init__(self, status_code: int, url: str):
        super().__init__(f"retryable HTTP status={status_code} url={url}")
        self.status_code = int(status_code)
        self.url = str(url)


_PATCH_LOCK = threading.RLock()
_PATCH_LOCAL = threading.local()
_PATCH_ACTIVE = 0
_PATCH_ORIGINAL = None
_EVIDENCE_LOCK = threading.Lock()


def _dispatch_request(session, method, url, **kwargs):
    stack = getattr(_PATCH_LOCAL, "guards", ())
    if stack:
        return stack[-1](session, method, url, **kwargs)
    return _PATCH_ORIGINAL(session, method, url, **kwargs)


def _is_retryable(exc: Exception) -> bool:
    # Parser/schema failures, HTTP 4xx (except configured retry statuses), and
    # TLS policy failures cannot be repaired by repeating the same retrieval.
    if isinstance(exc, requests.exceptions.SSLError):
        return False
    return isinstance(exc, (RetryableHTTPError, requests.Timeout, requests.ConnectionError))
_HTTP_TO_HTTPS_UPGRADE_HOSTS = {
    "vip.stock.finance.sina.com.cn",
}
_READ_ONLY_POST_ALLOWLIST = {
    ("stock_info_a_code_name", "www.bse.cn", "/nqxxController/nqxxCnzq.do"),
}


def _safe_url(url: str) -> dict:
    p = urlsplit(str(url))
    return {
        "scheme": p.scheme.lower(),
        "host": p.hostname or "",
        "port": p.port,
        "path": p.path,
        "query_keys": sorted(
            {piece.split("=", 1)[0] for piece in p.query.split("&") if piece}
        ),
    }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _append_jsonl(path: Path | None, obj: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with _EVIDENCE_LOCK:
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


class AkShareProxy:
    """Fail-closed network boundary around AkShare retrieval calls.

    AkShare remains the provider adapter. This proxy owns transport policy,
    bounded retries and evidence. Provider-specific schema validation stays in
    data_source.py so RAW transport evidence and VALIDATED canonical evidence
    remain separate.
    """

    def __init__(self, module, network_cfg: dict | None = None, evidence_path: Path | None = None):
        cfg = dict(network_cfg or {})
        legacy = float(cfg.get("timeout_seconds", 15))
        self.module = module
        self.connect_timeout = float(cfg.get("connect_timeout_seconds", min(5.0, legacy)))
        self.read_timeout = float(cfg.get("read_timeout_seconds", legacy))
        self.attempts = max(1, int(cfg.get("retry_attempts", 3)))
        self.backoff = max(0.0, float(cfg.get("retry_backoff_seconds", 0.8)))
        self.jitter = max(0.0, float(cfg.get("retry_jitter_seconds", 0.2)))
        self.retry_status = {
            int(x) for x in cfg.get("retry_status_codes", [429, 500, 502, 503, 504])
        }
        self.https_only = bool(cfg.get("https_only", True))
        self.evidence_path = Path(evidence_path) if evidence_path else None
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("NetClient connect/read timeout must be > 0")

    def __getattr__(self, name: str):
        target = getattr(self.module, name)
        if not callable(target):
            return target

        def wrapped(*args, **kwargs):
            return self.call(name, target, *args, **kwargs)

        wrapped.__name__ = getattr(target, "__name__", name)
        wrapped.__doc__ = getattr(target, "__doc__", None)
        return wrapped

    def _result_receipt(self, value) -> dict:
        if value is None:
            raise NetClientError("provider returned None")
        if hasattr(value, "empty") and bool(value.empty):
            raise NetClientError("provider returned empty dataframe")
        if hasattr(value, "to_csv"):
            raw = value.to_csv(index=False).encode("utf-8")
            return {
                "kind": "dataframe",
                "rows": int(len(value)),
                "columns": [str(x) for x in value.columns],
                "payload_bytes": len(raw),
                "payload_sha256": _sha256_bytes(raw),
            }
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return {
            "kind": type(value).__name__,
            "payload_bytes": len(raw),
            "payload_sha256": _sha256_bytes(raw),
        }

    @contextmanager
    def _instrument_requests(self, operation: str, attempt: int, raw_receipts: list[dict]):
        global _PATCH_ACTIVE, _PATCH_ORIGINAL

        # Install one dispatcher for all active retrievals. Each worker's guard
        # and receipts remain thread-local; unrelated requests use the original
        # transport. Hold the lock only while installing/restoring the patch.
        with _PATCH_LOCK:
            if _PATCH_ACTIVE == 0:
                _PATCH_ORIGINAL = requests.sessions.Session.request
                requests.sessions.Session.request = _dispatch_request
            original = _PATCH_ORIGINAL
            _PATCH_ACTIVE += 1

        def guarded(session, method, url, **kwargs):
            verb = str(method).upper()
            original_url = str(url)
            parsed = urlsplit(original_url)
            read_only_post = False
            if verb == "POST":
                key = (operation, (parsed.hostname or "").lower(), parsed.path)
                read_only_post = key in _READ_ONLY_POST_ALLOWLIST
                if not read_only_post:
                    raise NetClientPolicyError(
                        f"non-idempotent POST rejected: operation={operation} host={parsed.hostname} path={parsed.path}"
                    )
            elif verb not in {"GET", "HEAD"}:
                raise NetClientPolicyError(f"non-idempotent method rejected: {verb}")
            effective_url = original_url
            upgraded_from_http = False
            if self.https_only and parsed.scheme.lower() != "https":
                if (
                    parsed.scheme.lower() == "http"
                    and (parsed.hostname or "").lower() in _HTTP_TO_HTTPS_UPGRADE_HOSTS
                ):
                    effective_url = parsed._replace(scheme="https").geturl()
                    upgraded_from_http = True
                else:
                    raise NetClientPolicyError(f"non-HTTPS production request rejected: {url}")
            supplied = kwargs.get("timeout")
            if isinstance(supplied, (tuple, list)) and len(supplied) == 2:
                connect, read = supplied
            else:
                connect = read = supplied
            kwargs["timeout"] = (
                self.connect_timeout if connect is None else min(float(connect), self.connect_timeout),
                self.read_timeout if read is None else min(float(read), self.read_timeout),
            )
            response = original(session, method, effective_url, **kwargs)
            final = urlsplit(str(getattr(response, "url", effective_url)))
            if self.https_only and final.scheme.lower() != "https":
                raise NetClientPolicyError(
                    f"HTTPS request redirected to insecure URL: {getattr(response, 'url', '')}"
                )
            body = bytes(getattr(response, "content", b"") or b"")
            content_type = str(getattr(response, "headers", {}).get("content-type", "") or "").lower()
            if not content_type:
                raise NetClientPolicyError("response Content-Type is missing")
            receipt = {
                "operation": operation,
                "attempt": attempt,
                "method": verb,
                "read_only_post_allowlisted": read_only_post,
                "original_request": _safe_url(original_url),
                "request": _safe_url(effective_url),
                "upgraded_from_http": upgraded_from_http,
                "final_url": _safe_url(str(getattr(response, "url", effective_url))),
                "status_code": int(getattr(response, "status_code", 0) or 0),
                "content_type": content_type,
                "payload_bytes": len(body),
                "payload_sha256": _sha256_bytes(body),
                "fetched_at_unix": time.time(),
            }
            raw_receipts.append(receipt)
            status = receipt["status_code"]
            if status in self.retry_status:
                raise RetryableHTTPError(status, str(getattr(response, "url", effective_url)))
            if status >= 400:
                response.raise_for_status()
            return response

        stack = getattr(_PATCH_LOCAL, "guards", None)
        if stack is None:
            stack = _PATCH_LOCAL.guards = []
        stack.append(guarded)
        try:
            yield
        finally:
            stack.pop()
            with _PATCH_LOCK:
                _PATCH_ACTIVE -= 1
                if _PATCH_ACTIVE == 0:
                    requests.sessions.Session.request = _PATCH_ORIGINAL

    def _inject_provider_timeout(self, target, kwargs: dict) -> dict:
        out = dict(kwargs)
        if "timeout" in out:
            return out
        try:
            sig = inspect.signature(target)
            if "timeout" in sig.parameters:
                out["timeout"] = self.read_timeout
        except (TypeError, ValueError):
            pass
        return out

    def call(self, operation: str, target, *args, **kwargs):
        started = time.monotonic()
        failures: list[dict] = []
        all_raw: list[dict] = []
        for attempt in range(1, self.attempts + 1):
            raw_receipts: list[dict] = []
            try:
                call_kwargs = self._inject_provider_timeout(target, kwargs)
                with self._instrument_requests(operation, attempt, raw_receipts):
                    value = target(*args, **call_kwargs)
                all_raw.extend(raw_receipts)
                result = self._result_receipt(value)
                evidence = {
                    "schema": "stock-ai-netclient-call-v1",
                    "status": "PASS",
                    "operation": operation,
                    "attempts_used": attempt,
                    "connect_timeout_seconds": self.connect_timeout,
                    "read_timeout_seconds": self.read_timeout,
                    "https_only": self.https_only,
                    "raw_responses": all_raw,
                    "result": result,
                    "recorded_at_unix": time.time(),
                    "elapsed_seconds": time.monotonic() - started,
                }
                _append_jsonl(self.evidence_path, evidence)
                return value
            except NetClientPolicyError as exc:
                all_raw.extend(raw_receipts)
                evidence = {
                    "schema": "stock-ai-netclient-call-v1",
                    "status": "FAIL",
                    "operation": operation,
                    "attempts_used": attempt,
                    "retryable": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "raw_responses": all_raw,
                    "recorded_at_unix": time.time(),
                    "elapsed_seconds": time.monotonic() - started,
                }
                _append_jsonl(self.evidence_path, evidence)
                raise
            except Exception as exc:
                all_raw.extend(raw_receipts)
                failures.append({
                    "attempt": attempt,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
                retryable = _is_retryable(exc)
                if not retryable or attempt >= self.attempts:
                    evidence = {
                        "schema": "stock-ai-netclient-call-v1",
                        "status": "FAIL",
                        "operation": operation,
                        "attempts_used": attempt,
                        "retryable": retryable,
                        "failures": failures,
                        "raw_responses": all_raw,
                        "recorded_at_unix": time.time(),
                        "elapsed_seconds": time.monotonic() - started,
                    }
                    _append_jsonl(self.evidence_path, evidence)
                    raise NetClientError(
                        f"{operation} failed after {attempt} bounded attempts: {exc}"
                    ) from exc
                delay = self.backoff * (2 ** (attempt - 1))
                if self.jitter:
                    delay += random.uniform(0.0, self.jitter)
                if delay > 0:
                    time.sleep(delay)
        raise AssertionError("unreachable")
