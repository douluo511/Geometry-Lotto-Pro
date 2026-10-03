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
from happy8.sources import _official_host, _parse_fuzhou_number_rows, _parse_jiangsu_issue_dates


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

    jiangsu_html = """
    <html><body>
      <div>中国福利彩票快乐8第2021001期开奖公告 2021-01-01</div>
      <a href="https://www.cwl.gov.cn/c/2021/01/02/123.shtml">第2021001期开奖公告</a>
    </body></html>
    """
    parsed_dates = _parse_jiangsu_issue_dates(jiangsu_html)
    if parsed_dates != {"2021001": "2021-01-01"}:
        raise AssertionError(f"Jiangsu visible issue-date parser drifted: {parsed_dates!r}")
    checks["jiangsu_visible_issue_date_contract"] = {"status": "PASS"}

    conflicting_jiangsu = """
    <div>第2021001期开奖公告 2021-01-01</div>
    <div>第2021001期开奖公告 2021-01-02</div>
    """
    try:
        _parse_jiangsu_issue_dates(conflicting_jiangsu)
        raise AssertionError("Jiangsu issue-date conflict accepted")
    except RuntimeError:
        checks["jiangsu_date_conflict_fail_closed"] = {"status": "PASS"}

    cells_a = "".join(f"<td>{n:02d}</td>" for n in range(1, 21))
    cells_b = "".join(f"<td>{n:02d}</td>" for n in range(2, 22))
    fuzhou_html = f"<table><tr><td>2021001</td>{cells_a}</tr></table>"
    parsed_numbers = _parse_fuzhou_number_rows(fuzhou_html)
    if parsed_numbers.get("2021001") != tuple(range(1, 21)):
        raise AssertionError("Fuzhou 20-number row parser drifted")
    checks["fuzhou_20_number_contract"] = {"status": "PASS"}

    conflicting_fuzhou = (
        f"<table><tr><td>2021001</td>{cells_a}</tr>"
        f"<tr><td>2021001</td>{cells_b}</tr></table>"
    )
    try:
        _parse_fuzhou_number_rows(conflicting_fuzhou)
        raise AssertionError("Fuzhou conflicting duplicate accepted")
    except RuntimeError:
        checks["fuzhou_conflict_fail_closed"] = {"status": "PASS"}

    if not _official_host("https://www.jslottery.com/path", {"www.jslottery.com"}):
        raise AssertionError("official HTTPS host rejected")
    if _official_host("http://www.jslottery.com/path", {"www.jslottery.com"}):
        raise AssertionError("official host accepted HTTP downgrade")
    checks["provincial_official_https_host_contract"] = {"status": "PASS"}

    report = {
        "schema": "happy8-staging-contract-v1",
        "status": "PASS" if all(x["status"] == "PASS" for x in checks.values()) else "FAIL",
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
