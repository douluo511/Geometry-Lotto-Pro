from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import glp.sources as sources
from glp.net_client import NetClient
from glp.sources import SourceError, _validate_response


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None, url="https://example.invalid/data"):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}
        self.url = url
        self.encoding = "utf-8"

    @property
    def text(self):
        return self.content.decode(self.encoding or "utf-8")

    def json(self):
        return json.loads(self.content.decode("utf-8"))


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


def main() -> int:
    checks = {}

    def record(name, ok, detail):
        checks[name] = {"status": "PASS" if ok else "FAIL", "detail": detail}

    try:
        NetClient().get("http://example.invalid")
        record("https_only", False, "HTTP URL accepted")
    except ValueError as exc:
        record("https_only", True, str(exc))

    sleeps = []
    session = FakeSession([
        FakeResponse(429, headers={"Content-Type": "application/json"}),
        FakeResponse(200, b'{"ok":true}', {"Content-Type": "application/json"}),
    ])
    response = NetClient(
        connect_timeout=1,
        read_timeout=2,
        max_attempts=3,
        backoff_base=0.1,
        session=session,
        sleeper=sleeps.append,
        rng=random.Random(7),
    ).get("https://example.invalid/data")
    ledger = list(getattr(response, "glp_attempts", ()))
    record(
        "429_retry_then_success",
        response.status_code == 200
        and len(session.calls) == 2
        and session.calls[0]["timeout"] == (1.0, 2.0)
        and ledger[0]["outcome"] == "RETRY_HTTP"
        and ledger[-1]["outcome"] == "HTTP_RESPONSE",
        {"calls": session.calls, "ledger": ledger, "sleeps": sleeps},
    )

    insecure = FakeSession([
        FakeResponse(200, b"{}", {"Content-Type": "application/json"}, "http://example.invalid/data")
    ])
    try:
        NetClient(session=insecure, sleeper=lambda _: None).get("https://example.invalid/data")
        record("redirect_downgrade", False, "insecure redirect accepted")
    except requests.RequestException as exc:
        ledger = list(getattr(exc, "glp_attempts", ()))
        record("redirect_downgrade", bool(ledger) and ledger[-1]["outcome"] == "FINAL_INSECURE_REDIRECT", ledger)

    wrong = FakeResponse(200, b"<html></html>", {"Content-Type": "text/html"})
    try:
        _validate_response(wrong, wrong.content, expected="json")
        record("wrong_content_type", False, "HTML accepted as JSON")
    except SourceError as exc:
        record("wrong_content_type", True, str(exc))

    good = FakeResponse(200, b'{"x":1}', {"Content-Type": "application/json"})
    good.glp_attempts = ({"attempt": 1, "outcome": "HTTP_RESPONSE"},)
    meta = _validate_response(good, good.content, expected="json")
    record(
        "raw_provenance",
        meta["validation_result"] == "PASS"
        and bool(meta["body_b64"])
        and bool(meta["sha256"])
        and bool(meta["fetched_at"])
        and bool(meta["parser_version"])
        and meta["final_url"].startswith("https://"),
        meta,
    )

    malformed_payload = (
        b'{"success":true,"value":{"pages":1,"total":2,"list":['
        b'{"lotteryDrawNum":"26100","lotteryDrawTime":"2026-09-01","lotteryDrawResult":"01 02 03 04 05 01 02"},'
        b'{"lotteryDrawNum":"bad","lotteryDrawTime":"2026-09-04","lotteryDrawResult":"01 02 03 04 05 01 02"}]}}'
    )
    try:
        sources.fetch_national_page(1, session=FakeSession([
            FakeResponse(200, malformed_payload, {"Content-Type": "application/json"})
        ]))
        record("malformed_row_fail_closed", False, "bad row was skipped")
    except SourceError as exc:
        record("malformed_row_fail_closed", True, str(exc))

    bad_jiangsu = """
    <table>
      <tr><td>2026-09-01</td><td>26100</td><td>01 02 03 04 05 01</td></tr>
    </table>
    """
    try:
        sources._parse_jiangsu_html(bad_jiangsu)
        record("jiangsu_malformed_row_fail_closed", False, "bad Jiangsu row was skipped")
    except SourceError as exc:
        record("jiangsu_malformed_row_fail_closed", True, str(exc))

    duplicate_jiangsu = """
    <table>
      <tr><td>2026-09-01</td><td>26100</td><td>01 02 03 04 05 01 02</td></tr>
      <tr><td>2026-09-01</td><td>26100</td><td>01 02 03 04 05 01 02</td></tr>
    </table>
    """
    try:
        sources._parse_jiangsu_html(duplicate_jiangsu)
        record("jiangsu_duplicate_issue_fail_closed", False, "duplicate Jiangsu issue accepted")
    except SourceError as exc:
        record("jiangsu_duplicate_issue_fail_closed", True, str(exc))

    gd_html = """
    <html><body>
      <h1>中国体育彩票超级大乐透</h1>
      <h2>第26111期开奖公告</h2>
      <p>开奖日期：2026年9月28日</p>
      <div>本期开奖号码：10 11 17 26 29 01 03</div>
      <div>本期中奖情况</div>
    </body></html>
    """
    try:
        gd = sources._parse_guangdong_announcement(gd_html, "26111")
        record(
            "guangdong_official_parser",
            gd.issue == "26111"
            and gd.draw_date == "2026-09-28"
            and gd.front == (10, 11, 17, 26, 29)
            and gd.back == (1, 3),
            gd.to_dict(),
        )
    except Exception as exc:
        record("guangdong_official_parser", False, f"{type(exc).__name__}: {exc}")

    try:
        sources._parse_guangdong_announcement(gd_html, "26110")
        record("guangdong_issue_mismatch_fail_closed", False, "wrong issue accepted")
    except SourceError as exc:
        record("guangdong_issue_mismatch_fail_closed", True, str(exc))

    primary = [
        sources._parse_result("26110", "2026-09-26", "03 24 25 26 35 07 09"),
        sources._parse_result("26111", "2026-09-28", "10 11 17 26 29 01 03"),
    ]
    secondary = list(primary)
    try:
        count = sources._crosscheck(primary, secondary, minimum=2)
        record("independent_source_crosscheck", count == 2, {"overlap": count})
    except Exception as exc:
        record("independent_source_crosscheck", False, f"{type(exc).__name__}: {exc}")

    conflict = [
        sources._parse_result("26110", "2026-09-26", "03 24 25 26 35 07 09"),
        sources._parse_result("26111", "2026-09-28", "10 11 17 26 30 01 03"),
    ]
    try:
        sources._crosscheck(primary, conflict, minimum=2)
        record("independent_source_conflict_fail_closed", False, "conflicting official data accepted")
    except SourceError as exc:
        record("independent_source_conflict_fail_closed", True, str(exc))

    failures = [name for name, row in checks.items() if row["status"] != "PASS"]
    report = {
        "schema": "dlt-network-contract-gate-v1",
        "status": "PASS" if not failures else "FAIL",
        "hard_fail_count": len(failures),
        "failures": failures,
        "checks": checks,
    }
    out = ROOT / "artifacts" / "network_contract_gate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
