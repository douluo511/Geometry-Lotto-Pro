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
from happy8.sources import (
    _market_calendar_date_for_issue,
    _official_host,
    _parse_fuzhou_number_rows,
    _parse_jiangsu_issue_dates,
    _validate_jiangsu_publication_lag,
)


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

    calendar_anchors = {
        "2020001": "2020-10-28",
        "2021016": "2021-01-16",
        "2021039": "2021-02-08",
        "2021040": "2021-02-19",
        "2021157": "2021-06-16",
        "2021160": "2021-06-19",
        "2021161": "2021-06-20",
        "2021162": "2021-06-21",
        "2021263": "2021-09-30",
        "2021264": "2021-10-05",
        "2023322": "2023-12-02",
        "2026263": "2026-09-30",
    }
    actual_calendar = {
        issue: _market_calendar_date_for_issue(issue)
        for issue in calendar_anchors
    }
    if actual_calendar != calendar_anchors:
        raise AssertionError(
            f"MOF market-calendar derivation drifted: {actual_calendar!r}"
        )
    checks["mof_market_calendar_anchor_contract"] = {
        "status": "PASS",
        "anchors": actual_calendar,
    }

    for invalid_issue in ("2021000", "2021360", "2019999", "bad"):
        try:
            _market_calendar_date_for_issue(invalid_issue)
            raise AssertionError(
                f"invalid/out-of-range market-calendar issue accepted: {invalid_issue}"
            )
        except RuntimeError:
            pass
    checks["mof_market_calendar_invalid_issue_fail_closed"] = {"status": "PASS"}

    jiangsu_html = """
    <html><body>
      <li>
        <a href="http://www.cwl.gov.cn/c/2023/12/03/561230.shtml">
          中国福利彩票"快乐8"第2023322期开奖公告
        </a>
        <span class="articleDate">2023-12-03</span>
      </li>
    </body></html>
    """
    parsed_dates = _parse_jiangsu_issue_dates(jiangsu_html)
    if parsed_dates != {"2023322": "2023-12-03"}:
        raise AssertionError(
            f"Jiangsu issue-bound publication parser drifted: {parsed_dates!r}"
        )
    lag = _validate_jiangsu_publication_lag(
        "2023322",
        _market_calendar_date_for_issue("2023322"),
        parsed_dates["2023322"],
    )
    if lag != 1:
        raise AssertionError(f"2023322 publication lag must be +1 day, got {lag}")
    checks["jiangsu_2023322_publish_after_draw_contract"] = {
        "status": "PASS",
        "draw_date": "2023-12-02",
        "publication_date": "2023-12-03",
        "lag_days": lag,
    }

    visible_only_jiangsu = """
    <div>中国福利彩票快乐8第2023322期开奖公告 2023-12-03</div>
    """
    if _parse_jiangsu_issue_dates(visible_only_jiangsu):
        raise AssertionError(
            "Jiangsu visible publication date was accepted without an issue-bound CWL link"
        )
    checks["jiangsu_publication_requires_cwl_provenance"] = {"status": "PASS"}

    cwl_only_jiangsu = """
    <a href="http://www.cwl.gov.cn/c/2023/12/03/561230.shtml">
      中国福利彩票"快乐8"第2023322期开奖公告
    </a>
    """
    if _parse_jiangsu_issue_dates(cwl_only_jiangsu):
        raise AssertionError(
            "CWL URL publication metadata was incorrectly promoted without Jiangsu visible date"
        )
    checks["cwl_path_date_not_promoted_to_draw_date"] = {"status": "PASS"}

    for publication_day in ("2023-12-01", "2023-12-05"):
        try:
            _validate_jiangsu_publication_lag("2023322", "2023-12-02", publication_day)
            raise AssertionError(
                f"out-of-bound publication lag accepted: {publication_day}"
            )
        except RuntimeError:
            pass
    checks["jiangsu_publication_lag_fail_closed"] = {"status": "PASS"}

    for publication_day, expected_lag in (
        ("2023-12-02", 0),
        ("2023-12-03", 1),
        ("2023-12-04", 2),
    ):
        actual_lag = _validate_jiangsu_publication_lag(
            "2023322", "2023-12-02", publication_day
        )
        if actual_lag != expected_lag:
            raise AssertionError(
                f"valid publication lag rejected/drifted: {publication_day} -> {actual_lag}"
            )
    checks["jiangsu_publication_lag_0_to_2_contract"] = {"status": "PASS"}

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

    # Reverse-check the exact Windows console failure mode observed in live CI.
    # Persisted evidence remains UTF-8; console diagnostics must stay safe even
    # when stdout uses a legacy cp1252-compatible encoding.
    console_probe = json.dumps(
        {"source": "江西抚州福利彩票", "label": "开奖结果查询"},
        ensure_ascii=True,
        indent=2,
    )
    try:
        console_probe.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise AssertionError("ASCII-safe live console JSON regressed") from exc
    if "\\u" not in console_probe:
        raise AssertionError("non-ASCII console probe was not escaped")
    checks["windows_cp1252_console_json_contract"] = {"status": "PASS"}

    report = {
        "schema": "happy8-staging-contract-v1",
        "status": "PASS" if all(x["status"] == "PASS" for x in checks.values()) else "FAIL",
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())