from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "SSQ"))

from glp.net_client import NetClient
from glp.sources import SourceError, _validate_http_payload
from glp.util import sha256_bytes


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.outcomes:
            raise AssertionError("unexpected extra request")
        value = self.outcomes.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def _run() -> dict:
    checks: dict[str, dict] = {}

    def record(name: str, ok: bool, detail):
        checks[name] = {"status": "PASS" if ok else "FAIL", "detail": detail}

    try:
        NetClient().get("http://example.invalid")
        record("https_only", False, "HTTP URL unexpectedly accepted")
    except ValueError as exc:
        record("https_only", True, str(exc))
    except Exception as exc:
        record("https_only", False, f"{type(exc).__name__}: {exc}")

    try:
        NetClient().get("https://example.invalid", timeout=30)
        record("timeout_pair_required", False, "scalar timeout unexpectedly accepted")
    except ValueError as exc:
        record("timeout_pair_required", True, str(exc))
    except Exception as exc:
        record("timeout_pair_required", False, f"{type(exc).__name__}: {exc}")

    sleeps = []
    session = FakeSession([
        FakeResponse(429, headers={"Content-Type": "application/json"}),
        FakeResponse(200, content=b'{"ok":true}', headers={"Content-Type": "application/json"}),
    ])
    client = NetClient(
        connect_timeout=1,
        read_timeout=2,
        max_attempts=3,
        backoff_base=0.4,
        session=session,
        sleeper=sleeps.append,
        rng=random.Random(7),
    )
    response = client.get("https://example.invalid/data")
    ledger = list(getattr(response, "glp_attempts", ()))
    record(
        "429_retry_then_success",
        response.status_code == 200
        and len(session.calls) == 2
        and len(ledger) == 2
        and ledger[0]["outcome"] == "RETRY_HTTP"
        and ledger[1]["outcome"] == "HTTP_RESPONSE"
        and len(sleeps) == 1
        and sleeps[0] > 0,
        {"calls": len(session.calls), "ledger": ledger, "sleeps": sleeps},
    )
    record(
        "separate_connect_read_timeout",
        all(call.get("timeout") == (1.0, 2.0) for call in session.calls),
        [call.get("timeout") for call in session.calls],
    )

    sleeps = []
    session = FakeSession([
        requests.Timeout("t1"),
        requests.ConnectionError("c2"),
        requests.Timeout("t3"),
    ])
    client = NetClient(
        connect_timeout=1,
        read_timeout=2,
        max_attempts=3,
        backoff_base=0.1,
        session=session,
        sleeper=sleeps.append,
        rng=random.Random(1),
    )
    try:
        client.get("https://example.invalid/data")
        record("retry_cap_exception_fail_closed", False, "exception path unexpectedly returned")
    except requests.Timeout as exc:
        ledger = list(getattr(exc, "glp_attempts", ()))
        record(
            "retry_cap_exception_fail_closed",
            len(session.calls) == 3
            and len(sleeps) == 2
            and len(ledger) == 3
            and ledger[-1]["outcome"] == "FINAL_EXCEPTION",
            {"calls": len(session.calls), "sleeps": sleeps, "ledger": ledger},
        )
    except Exception as exc:
        record("retry_cap_exception_fail_closed", False, f"{type(exc).__name__}: {exc}")

    sleeps = []
    session = FakeSession([
        FakeResponse(503, headers={"Content-Type": "application/json", "Retry-After": "99"}),
        FakeResponse(200, headers={"Content-Type": "application/json"}),
    ])
    response = NetClient(
        max_attempts=2,
        max_retry_after=5,
        session=session,
        sleeper=sleeps.append,
        rng=random.Random(2),
    ).get("https://example.invalid/data")
    record("retry_after_hard_cap", sleeps == [5.0] and response.status_code == 200, sleeps)

    good = FakeResponse(200, b'{"x":1}', {"Content-Type": "application/json; charset=utf-8"})
    good.glp_attempts = ({"attempt": 1, "outcome": "HTTP_RESPONSE"},)
    try:
        meta = _validate_http_payload(good, good.content, expected="json")
        record(
            "raw_payload_evidence",
            meta["sha256"] == sha256_bytes(good.content)
            and bool(meta["body_b64"])
            and meta["attempts"][0]["attempt"] == 1,
            meta,
        )
    except Exception as exc:
        record("raw_payload_evidence", False, f"{type(exc).__name__}: {exc}")

    bad_type = FakeResponse(200, b"<html></html>", {"Content-Type": "text/html"})
    try:
        _validate_http_payload(bad_type, bad_type.content, expected="json")
        record("wrong_content_type_fail_closed", False, "wrong type unexpectedly accepted")
    except SourceError as exc:
        record("wrong_content_type_fail_closed", True, str(exc))
    except Exception as exc:
        record("wrong_content_type_fail_closed", False, f"{type(exc).__name__}: {exc}")

    empty = FakeResponse(200, b"", {"Content-Type": "application/json"})
    try:
        _validate_http_payload(empty, empty.content, expected="json")
        record("empty_payload_fail_closed", False, "empty response unexpectedly accepted")
    except SourceError as exc:
        record("empty_payload_fail_closed", True, str(exc))
    except Exception as exc:
        record("empty_payload_fail_closed", False, f"{type(exc).__name__}: {exc}")

    failures = [name for name, row in checks.items() if row["status"] != "PASS"]
    return {
        "schema": "ssq-netclient-contract-gate-v1",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "failures": failures,
        "checks": checks,
    }


def main() -> int:
    report = _run()
    out = ROOT / "evidence" / "SSQ" / "NETCLIENT_CONTRACT_GATE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
