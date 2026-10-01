from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests


class OperationDeadlineExceeded(requests.Timeout):
    """The bounded end-to-end HTTP operation budget was exhausted."""


class ResponseTooLarge(requests.RequestException):
    """The response body exceeded the configured streaming byte limit."""


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    outcome: str
    status_code: int | None
    error_type: str | None
    retry_delay: float
    url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NetClient:
    """Fail-closed, bounded HTTPS GET client for official lottery sources."""

    def __init__(
        self,
        connect_timeout: float = 12.0,
        read_timeout: float = 30.0,
        max_attempts: int = 3,
        backoff_base: float = 0.35,
        session: requests.Session | None = None,
        sleeper=time.sleep,
        jitter_source=None,
        clock=time.time,
        max_retry_delay: float = 30.0,
        max_redirects: int = 3,
        rng: random.Random | None = None,
        total_timeout: float = 120.0,
        max_response_bytes: int = 8 * 1024 * 1024,
    ):
        self.connect_timeout = self._positive_finite(connect_timeout, "connect_timeout")
        self.read_timeout = self._positive_finite(read_timeout, "read_timeout")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 4:
            raise ValueError("max_attempts must be an integer from 1 to 4")
        self.max_attempts = max_attempts
        self.backoff_base = self._positive_finite(backoff_base, "backoff_base")
        self.max_retry_delay = self._positive_finite(max_retry_delay, "max_retry_delay")
        if self.backoff_base > self.max_retry_delay:
            raise ValueError("backoff_base must not exceed max_retry_delay")
        if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or not 0 <= max_redirects <= 5:
            raise ValueError("max_redirects must be an integer from 0 to 5")
        self.max_redirects = max_redirects
        self.total_timeout = self._positive_finite(total_timeout, "total_timeout")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or not 1 <= max_response_bytes <= 64 * 1024 * 1024:
            raise ValueError("max_response_bytes must be an integer from 1 byte to 64 MiB")
        self.max_response_bytes = max_response_bytes
        self.session = session
        self.sleeper = sleeper
        if jitter_source is not None and not callable(jitter_source):
            raise ValueError("jitter_source must be callable")
        # Keep production jitter independent of model code that may seed the
        # process-global random generator for deterministic research runs.
        self.jitter_source = rng.random if rng is not None else (
            jitter_source if jitter_source is not None else random.Random().random
        )
        self.clock = clock

    @staticmethod
    def _attach_ledger(target, attempts: list[AttemptRecord]):
        target.glp_attempts = tuple(record.to_dict() for record in attempts)
        return target

    @staticmethod
    def _positive_finite(value, name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be positive and finite")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be positive and finite") from exc
        if not math.isfinite(result) or result <= 0:
            raise ValueError(f"{name} must be positive and finite")
        return result

    @staticmethod
    def _require_https(url: str):
        try:
            parts = urlsplit(url)
            valid = (
                parts.scheme.lower() == "https"
                and bool(parts.hostname)
                and parts.port in (None, 443)
                and not parts.username
                and not parts.password
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("production sources must use an absolute HTTPS URL on port 443 without credentials")
        return parts

    def _remaining(self, deadline: float) -> float:
        remaining = float(deadline) - float(self.clock())
        if not math.isfinite(remaining) or remaining <= 0:
            raise OperationDeadlineExceeded("official HTTPS GET exceeded total operation timeout")
        return remaining

    def _bounded_timeout_pair(self, timeout_pair: tuple[float, float], deadline: float) -> tuple[float, float]:
        remaining = self._remaining(deadline)
        # Requests applies connect and read timeouts independently. Allocate at
        # most half the remaining end-to-end budget to either blocking phase so
        # a single attempt cannot consume twice the remaining operation budget.
        if remaining <= 0.002:
            raise OperationDeadlineExceeded("official HTTPS GET exceeded total operation timeout")
        phase_budget = remaining / 2.0
        return min(timeout_pair[0], phase_budget), min(timeout_pair[1], phase_budget)

    def _sleep_with_deadline(self, delay: float, deadline: float) -> None:
        remaining = self._remaining(deadline)
        if delay >= remaining:
            raise OperationDeadlineExceeded("retry delay would exceed total operation timeout")
        self.sleeper(delay)
        self._remaining(deadline)

    def _read_response_body(
        self, response, *, deadline: float, attempt: int, ledger: list[AttemptRecord]
    ) -> bytes:
        cached = getattr(response, "_content", False)
        if isinstance(cached, (bytes, bytearray)):
            data = bytes(cached)
            if len(data) > self.max_response_bytes:
                ledger.append(AttemptRecord(
                    attempt, "BODY_TOO_LARGE", int(response.status_code), "ResponseTooLarge", 0.0,
                    str(getattr(response, "url", "")),
                ))
                error = ResponseTooLarge(
                    f"official HTTPS response exceeded {self.max_response_bytes} bytes", response=response
                )
                raise self._attach_ledger(error, ledger)
            self._remaining(deadline)
            return data

        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                self._remaining(deadline)
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.max_response_bytes:
                    ledger.append(AttemptRecord(
                        attempt, "BODY_TOO_LARGE", int(response.status_code), "ResponseTooLarge", 0.0,
                        str(getattr(response, "url", "")),
                    ))
                    error = ResponseTooLarge(
                        f"official HTTPS response exceeded {self.max_response_bytes} bytes", response=response
                    )
                    raise self._attach_ledger(error, ledger)
                chunks.append(bytes(chunk))
        finally:
            if total > self.max_response_bytes:
                response.close()
        data = b"".join(chunks)
        response._content = data
        response._content_consumed = True
        self._remaining(deadline)
        return data

    def _request_one_attempt(self, getter, url, *, params, headers, timeout_pair, allow_redirects,
                             attempt: int, ledger: list[AttemptRecord], deadline: float):
        official_host = self._require_https(url).hostname
        current_url = url
        current_params = params
        for redirect_count in range(self.max_redirects + 1):
            # Never delegate redirect traversal to Requests: its built-in
            # redirect handler could send an HTTPS -> HTTP hop before we see it.
            response = getter(
                current_url,
                params=current_params,
                headers=headers,
                timeout=self._bounded_timeout_pair(timeout_pair, deadline),
                allow_redirects=False,
                stream=True,
            )
            if response.history:
                ledger.append(AttemptRecord(attempt, "REJECTED_HISTORY", None, "ValueError", 0.0, current_url))
                raise ValueError("transport followed a redirect without authorization")
            actual_url = str(getattr(response, "url", ""))
            try:
                actual = self._require_https(actual_url)
            except ValueError as exc:
                # Record the observed URL, not merely the requested one. This
                # catches a non-conforming transport that ignored our explicit
                # allow_redirects=False without claiming the hop was safe.
                ledger.append(AttemptRecord(attempt, "FINAL_INSECURE_REDIRECT", int(response.status_code),
                                            "RequestException", 0.0, actual_url))
                raise requests.RequestException(f"official response URL is not HTTPS: {actual_url}") from exc
            if actual.hostname != official_host:
                ledger.append(AttemptRecord(attempt, "REJECTED_RESPONSE_URL", int(response.status_code),
                                            "ValueError", 0.0, actual_url))
                raise ValueError("official response left its configured HTTPS host")

            status = int(response.status_code)
            if status in (301, 302, 303, 307, 308) and allow_redirects:
                location = response.headers.get("Location")
                if not location or any(ord(char) < 32 or ord(char) == 127 for char in location):
                    ledger.append(AttemptRecord(attempt, "REJECTED_REDIRECT", status, "MissingLocation", 0.0, current_url))
                    raise requests.HTTPError("official HTTPS redirect has no valid Location", response=response)
                next_url = urljoin(response.url, location)
                try:
                    target = self._require_https(next_url)
                except ValueError:
                    ledger.append(AttemptRecord(attempt, "REJECTED_REDIRECT", status, "ValueError", 0.0, current_url))
                    raise
                if target.hostname != official_host:
                    ledger.append(AttemptRecord(attempt, "REJECTED_REDIRECT", status, "ValueError", 0.0, current_url))
                    raise ValueError("official redirect left its configured HTTPS host")
                if redirect_count >= self.max_redirects:
                    ledger.append(AttemptRecord(attempt, "REDIRECT_LIMIT", status, "TooManyRedirects", 0.0, current_url))
                    raise requests.TooManyRedirects("official HTTPS redirect limit exceeded", response=response)
                ledger.append(AttemptRecord(attempt, "REDIRECT_HTTPS", status, None, 0.0, current_url))
                response.close()
                current_url = next_url
                current_params = None  # Location is authoritative after the first request.
                continue
            return response
        raise RuntimeError("redirect traversal ended without a response")

    def _timeout_pair(self, timeout) -> tuple[float, float]:
        if timeout is None:
            return self.connect_timeout, self.read_timeout
        if not isinstance(timeout, (tuple, list)) or len(timeout) != 2:
            raise ValueError("timeout must specify independent connect and read values")
        return (
            self._positive_finite(timeout[0], "connect_timeout"),
            self._positive_finite(timeout[1], "read_timeout"),
        )

    def _retry_after_seconds(self, header: str | None) -> float | None:
        if header is None:
            return None
        value = str(header).strip()
        try:
            seconds = float(value)
        except ValueError:
            try:
                target = parsedate_to_datetime(value)
                if target.tzinfo is None:
                    return None
                seconds = target.timestamp() - self.clock()
            except (TypeError, ValueError, OverflowError):
                return None
        if not math.isfinite(seconds):
            return None
        return max(0.0, seconds)

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float | None:
        exponential = min(self.max_retry_delay, self.backoff_base * (2 ** (attempt - 1)))
        jitter = float(self.jitter_source())
        if not math.isfinite(jitter) or not 0 <= jitter < 1:
            raise ValueError("jitter source must return a finite number in [0, 1)")
        delay = exponential + jitter * min(exponential, self.max_retry_delay - exponential)
        server_delay = self._retry_after_seconds(retry_after)
        if server_delay is not None:
            if server_delay > self.max_retry_delay:
                return None  # Do not violate a server's rate-limit delay to force a retry.
            delay = max(delay, server_delay)
        return delay

    def get(self, url: str, *, params=None, headers=None, timeout=None, allow_redirects=True):
        self._require_https(url)
        timeout_pair = self._timeout_pair(timeout)
        getter = self.session.get if self.session is not None else requests.get
        ledger: list[AttemptRecord] = []
        deadline = float(self.clock()) + self.total_timeout

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._request_one_attempt(
                    getter,
                    url,
                    params=params,
                    headers=headers,
                    timeout_pair=timeout_pair,
                    allow_redirects=allow_redirects,
                    attempt=attempt,
                    ledger=ledger,
                    deadline=deadline,
                )
                status = int(response.status_code)
                self._read_response_body(response, deadline=deadline, attempt=attempt, ledger=ledger)
                if status == 200:
                    ledger.append(AttemptRecord(attempt, "HTTP_RESPONSE", status, None, 0.0, response.url))
                    return self._attach_ledger(response, ledger)

                retryable = status in (408, 429) or 500 <= status <= 599
                if retryable and attempt < self.max_attempts:
                    delay = self._retry_delay(attempt, response.headers.get("Retry-After"))
                    if delay is not None:
                        ledger.append(AttemptRecord(attempt, "RETRY_HTTP", status, None, delay, response.url))
                        response.close()
                        self._sleep_with_deadline(delay, deadline)
                        continue
                ledger.append(AttemptRecord(attempt, "FINAL_HTTP", status, None, 0.0, response.url))
                error = requests.HTTPError(f"official HTTPS GET returned HTTP {status}", response=response)
                raise self._attach_ledger(error, ledger)
            except OperationDeadlineExceeded as exc:
                if not ledger or ledger[-1].outcome != "OPERATION_DEADLINE":
                    ledger.append(AttemptRecord(attempt, "OPERATION_DEADLINE", None, type(exc).__name__, 0.0, url))
                self._attach_ledger(exc, ledger)
                raise
            except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as exc:
                if attempt >= self.max_attempts:
                    ledger.append(AttemptRecord(attempt, "FINAL_EXCEPTION", None, type(exc).__name__, 0.0, url))
                    self._attach_ledger(exc, ledger)
                    raise
                delay = self._retry_delay(attempt, None)
                ledger.append(AttemptRecord(attempt, "RETRY_EXCEPTION", None, type(exc).__name__, delay, url))
                self._sleep_with_deadline(delay, deadline)
            except Exception as exc:
                if not getattr(exc, "glp_attempts", None):
                    if not ledger or ledger[-1].outcome not in {
                        "REJECTED_HISTORY", "REJECTED_RESPONSE_URL", "REJECTED_REDIRECT", "REDIRECT_LIMIT",
                        "FINAL_INSECURE_REDIRECT",
                    }:
                        ledger.append(AttemptRecord(attempt, "FINAL_EXCEPTION", None, type(exc).__name__, 0.0, url))
                    self._attach_ledger(exc, ledger)
                raise

        raise RuntimeError("GET failed without response")
