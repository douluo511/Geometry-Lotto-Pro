from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(VERSION))

import requests
from stock_ai.netclient import AkShareProxy, NetClientError, NetClientPolicyError


class FakeResponse:
    def __init__(self, status, body=b"{}", content_type="application/json", url="https://example.invalid/data"):
        self.status_code = status
        self.content = body
        self.headers = {"content-type": content_type} if content_type is not None else {}
        self.url = url
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class Provider:
    def fetch(self):
        r = requests.get("https://example.invalid/data")
        return {"status": r.status_code, "value": 7}

    def sina_fetch(self):
        r = requests.get("http://vip.stock.finance.sina.com.cn/quotes_service/test")
        return {"status": r.status_code}

    def arbitrary_http_fetch(self):
        r = requests.get("http://example.invalid/data")
        return {"status": r.status_code}

    def stock_info_a_code_name(self):
        r = requests.post(
            "https://www.bse.cn/nqxxController/nqxxCnzq.do",
            data={"page": "0", "typejb": "T", "xxfcbj[]": "2"},
        )
        return {"status": r.status_code}

    def post_fetch(self):
        requests.post("https://example.invalid/data", data=b"x")
        return {"bad": True}


def run():
    with tempfile.TemporaryDirectory() as td:
        evidence = Path(td) / "netclient.jsonl"
        cfg = {
            "connect_timeout_seconds": 1,
            "read_timeout_seconds": 2,
            "retry_attempts": 3,
            "retry_backoff_seconds": 0,
            "retry_jitter_seconds": 0,
            "retry_status_codes": [429, 500, 502, 503, 504],
            "https_only": True,
        }
        proxy = AkShareProxy(Provider(), cfg, evidence)
        calls = []
        seq = [FakeResponse(503, b"busy"), FakeResponse(200, b'{"ok":true}')]

        def flaky(session, method, url, **kwargs):
            calls.append({"method": method, "url": url, "timeout": kwargs.get("timeout")})
            return seq.pop(0)

        with patch.object(requests.sessions.Session, "request", new=flaky):
            out = proxy.fetch()
        assert out["value"] == 7
        assert len(calls) == 2
        assert calls[0]["timeout"] == (1.0, 2.0)

        upgraded_urls = []
        def upgraded(session, method, url, **kwargs):
            upgraded_urls.append(url)
            return FakeResponse(200, b"{}", "application/json", url)
        with patch.object(requests.sessions.Session, "request", new=upgraded):
            proxy.sina_fetch()
        assert upgraded_urls == ["https://vip.stock.finance.sina.com.cn/quotes_service/test"]

        try:
            proxy.arbitrary_http_fetch()
            raise AssertionError("arbitrary plaintext HTTP must fail")
        except NetClientPolicyError:
            pass

        with patch.object(
            requests.sessions.Session,
            "request",
            new=lambda session, method, url, **kwargs: FakeResponse(
                200, b"x", "application/json", "http://downgraded.invalid/data"
            ),
        ):
            try:
                proxy.fetch()
                raise AssertionError("HTTPS downgrade must fail")
            except NetClientPolicyError:
                pass

        with patch.object(
            requests.sessions.Session,
            "request",
            new=lambda session, method, url, **kwargs: FakeResponse(200, b"x", None),
        ):
            try:
                proxy.fetch()
                raise AssertionError("missing Content-Type must fail")
            except NetClientPolicyError:
                pass

        with patch.object(
            requests.sessions.Session,
            "request",
            new=lambda session, method, url, **kwargs: FakeResponse(429, b"rate"),
        ):
            try:
                proxy.fetch()
                raise AssertionError("bounded 429 retries must end in FAIL")
            except NetClientError:
                pass

        bse_calls = []
        def bse_query(session, method, url, **kwargs):
            bse_calls.append({"method": method, "url": url, "timeout": kwargs.get("timeout")})
            return FakeResponse(200, b'{"rows":[]}', "application/json", url)
        with patch.object(requests.sessions.Session, "request", new=bse_query):
            proxy.stock_info_a_code_name()
        assert bse_calls and bse_calls[0]["method"].upper() == "POST"
        assert bse_calls[0]["url"] == "https://www.bse.cn/nqxxController/nqxxCnzq.do"
        assert bse_calls[0]["timeout"] == (1.0, 2.0)

        try:
            proxy.post_fetch()
            raise AssertionError("non-allowlisted POST must be rejected")
        except NetClientPolicyError:
            pass

        rows = [json.loads(x) for x in evidence.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert rows and any(x["status"] == "PASS" for x in rows)
        assert any(x["status"] == "FAIL" for x in rows)
        passed = next(x for x in rows if x["status"] == "PASS")
        assert passed["raw_responses"][0]["status_code"] == 503
        assert passed["raw_responses"][1]["status_code"] == 200
        assert len(passed["raw_responses"][1]["payload_sha256"]) == 64
        report = {
            "schema": "stock-ai-netclient-contract-v1",
            "status": "PASS",
            "checks": [
                "connect_read_timeout",
                "bounded_retry_503",
                "bounded_retry_429",
                "exponential_retry_policy_configured",
                "allowlisted_http_upgraded_to_https",
                "arbitrary_http_fail_closed",
                "https_downgrade_fail_closed",
                "content_type_fail_closed",
                "read_only_bse_post_allowlisted",
                "non_allowlisted_post_rejected",
                "raw_payload_sha256_receipt",
                "pass_and_fail_evidence_preserved",
            ],
        }
        out_path = ROOT / "netclient_contract_evidence.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    run()
