"""Offline unit tests for allowlisted raw-source acquisition."""
import hashlib
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from urllib.request import Request

from research.harness_v46.core import GateError
from research.harness_v46.source_fetch import _SafeRedirectHandler, fetch_raw_source


class FakeResponse:
    def __init__(self, body=b"<html>source fixture</html>", url="https://www.swlc.net.cn/index.html",
                 status=200, headers=None):
        self.body = body
        self.url = url
        self.status = status
        self.headers = headers or {
            "Content-Length": str(len(body)),
            "Content-Type": "text/html; charset=utf-8",
            "Last-Modified": "Wed, 21 Oct 2026 00:00:00 GMT",
        }

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def read(self, limit=-1):
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, timeout=0):
        self.request = request
        self.timeout = timeout
        return self.response


class SourceFetchTests(unittest.TestCase):
    def test_allowed_https_fetch_preserves_bytes_and_does_not_claim_publication_time(self):
        raw = b'{"synthetic":"not official data"}'
        response = FakeResponse(raw)
        opener = FakeOpener(response)
        with patch("research.harness_v46.source_fetch.build_opener", return_value=opener):
            result = fetch_raw_source("SSQ", "https://www.swlc.net.cn/index.html")
        self.assertEqual(result["raw_bytes"], raw)
        self.assertEqual(result["raw_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["size_bytes"], len(raw))
        self.assertEqual(result["source_authenticity"], "NOT_VERIFIED")
        self.assertEqual(result["official_admission"], "BLOCKED")
        self.assertIsNone(result["published_at"])
        self.assertEqual(result["http_last_modified_header_claim"], "Wed, 21 Oct 2026 00:00:00 GMT")
        self.assertEqual(opener.timeout, 15.0)
        self.assertEqual(opener.request.get_method(), "GET")

    def test_unapproved_host_is_rejected_before_network_call(self):
        with patch("research.harness_v46.source_fetch.build_opener") as builder:
            with self.assertRaisesRegex(GateError, "HOST_NOT_ALLOWLISTED"):
                fetch_raw_source("SSQ", "https://example.org/ssq")
            builder.assert_not_called()

    def test_non_https_url_is_rejected(self):
        with self.assertRaisesRegex(GateError, "HTTPS_SOURCE_URL_REQUIRED"):
            fetch_raw_source("DLT", "http://www.gstc.org.cn/wanfa/dlt_history")

    def test_redirect_outside_allowlist_is_rejected(self):
        handler = _SafeRedirectHandler("SSQ")
        request = Request("https://www.swlc.net.cn/start")
        with self.assertRaisesRegex(GateError, "HOST_NOT_ALLOWLISTED"):
            handler.redirect_request(request, None, 302, "Found", {}, "https://attacker.example/landing")

    def test_redirect_to_allowed_independent_root_is_recorded_for_later_independence_check(self):
        handler = _SafeRedirectHandler("SSQ")
        request = Request("https://www.swlc.net.cn/start")
        redirected = handler.redirect_request(request, None, 302, "Found", {},
                                              "https://www.cwl.gov.cn/landing")
        self.assertIsNotNone(redirected)
        self.assertEqual(handler.redirect_chain, ["https://www.cwl.gov.cn/landing"])

    def test_response_size_limit_blocks_large_bytes(self):
        response = FakeResponse(b"0123456789")
        with patch("research.harness_v46.source_fetch.build_opener", return_value=FakeOpener(response)):
            with self.assertRaisesRegex(GateError, "RAW_SOURCE_TOO_LARGE"):
                fetch_raw_source("SSQ", "https://www.swlc.net.cn/index.html", max_bytes=5)

    def test_non_200_response_blocks(self):
        response = FakeResponse(status=403)
        with patch("research.harness_v46.source_fetch.build_opener", return_value=FakeOpener(response)):
            with self.assertRaisesRegex(GateError, "HTTP_STATUS_NOT_200"):
                fetch_raw_source("SSQ", "https://www.swlc.net.cn/index.html")

    def test_http_error_preserves_status_code(self):
        error = HTTPError("https://www.swlc.net.cn/index.html", 403, "Forbidden", {}, None)
        with patch("research.harness_v46.source_fetch.build_opener") as builder:
            builder.return_value.open.side_effect = error
            with self.assertRaisesRegex(GateError, "SOURCE_HTTP_STATUS_NOT_200:403"):
                fetch_raw_source("SSQ", "https://www.swlc.net.cn/index.html")

    def test_unknown_game_and_invalid_timeout_block(self):
        with self.assertRaisesRegex(GateError, "UNKNOWN_LOTTERY"):
            fetch_raw_source("KENO", "https://www.swlc.net.cn/index.html")
        with self.assertRaisesRegex(GateError, "INVALID_FETCH_TIMEOUT"):
            fetch_raw_source("SSQ", "https://www.swlc.net.cn/index.html", timeout=0)


if __name__ == "__main__":
    unittest.main()
