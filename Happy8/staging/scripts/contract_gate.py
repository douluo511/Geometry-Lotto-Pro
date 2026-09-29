from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.domain import Draw
from happy8.net_client import NetClient


class FakeResponse:
    def __init__(self, status_code=200, url="https://example.invalid/data", headers=None):
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def main() -> int:
    checks = {}

    valid = Draw.from_values(
        "2026261", "2026-09-28",
        [2, 7, 16, 19, 21, 25, 30, 31, 33, 35, 42, 45, 50, 52, 53, 55, 56, 60, 63, 72],
    )
    checks["domain_valid_20_of_80"] = {"status": "PASS", "issue": valid.issue}

    try:
        Draw.from_values("2026261", "2026-09-28", [1] * 20)
        raise AssertionError("duplicate numbers accepted")
    except ValueError:
        checks["domain_duplicate_fail_closed"] = {"status": "PASS"}

    try:
        NetClient().get("http://example.invalid")
        raise AssertionError("HTTP accepted")
    except ValueError:
        checks["https_only"] = {"status": "PASS"}

    sleeps = []
    session = FakeSession([FakeResponse(429), FakeResponse(200)])
    client = NetClient(
        connect_timeout=1,
        read_timeout=2,
        max_attempts=2,
        backoff_base=0.01,
        session=session,
        sleeper=sleeps.append,
        rng=random.Random(7),
    )
    response = client.get("https://example.invalid/data")
    if response.status_code != 200 or len(session.calls) != 2 or len(sleeps) != 1:
        raise AssertionError("429 retry contract failed")
    checks["429_retry_then_success"] = {
        "status": "PASS",
        "calls": len(session.calls),
        "attempts": list(getattr(response, "happy8_attempts", ())),
    }

    session = FakeSession([FakeResponse(200, url="http://example.invalid/downgrade")])
    try:
        NetClient(session=session, max_attempts=1).get("https://example.invalid/data")
        raise AssertionError("HTTPS downgrade accepted")
    except requests.RequestException:
        checks["redirect_downgrade_fail_closed"] = {"status": "PASS"}

    report = {
        "schema": "happy8-staging-contract-v1",
        "status": "PASS" if all(x["status"] == "PASS" for x in checks.values()) else "FAIL",
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
