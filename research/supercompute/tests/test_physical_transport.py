"""Offline retry/host-safety tests. Zero internet or sleep."""
import io
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError
import unittest

from research.supercompute.automation.dlt_physical_source import collect as collect_dlt
from research.supercompute.automation.physical_transport import (
    TransportExhausted, resilient_fetch, dlt_fetch, ssq_fetch,
)


class Response:
    def __init__(self, url, body=b"<html>official</html>", status=200):
        self.url, self.body, self.status = url, body, status
    def geturl(self):
        return self.url
    def read(self, maximum):
        return self.body[:maximum]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class TransportTest(unittest.TestCase):
    def test_network_retry_then_official_apex_success(self):
        seen = []
        def opener(req, timeout=12):
            url = req.full_url
            seen.append(url)
            if len(seen) < 2:
                raise URLError("synthetic network interruption")
            return Response(url)
        args = dict(opener=opener, sleeper=lambda delay: None, max_attempts=4)
        result = dlt_fetch("https://www.gdlottery.cn/f_html/kjgg/P085_26105.html", **args)
        self.assertEqual(200, result[0])
        self.assertEqual(2, len(result[3]))
        self.assertEqual("NETWORK_URLError", result[3][0]["reason"])
        self.assertEqual("gdlottery.cn", result[1].split("/")[2])

    def test_ssq_transient_http_then_success(self):
        calls = 0
        def opener(req, timeout=12):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b"service down"))
            return Response(req.full_url)
        result = ssq_fetch("https://www.swlc.net.cn/lottery/ssq.html?limit=50&view=previous",
                           opener=opener, sleeper=lambda delay: None)
        self.assertEqual(2, calls)
        self.assertEqual(503, result[3][0]["http_status"])
        self.assertEqual("HTTP_200", result[3][1]["reason"])

    def test_403_no_retries_or_evasion(self):
        count = 0
        def opener(req, timeout=12):
            nonlocal count
            count += 1
            raise HTTPError(req.full_url, 403, "forbidden", {}, io.BytesIO(b"no"))
        with self.assertRaises(TransportExhausted) as ctx:
            dlt_fetch("https://www.gdlottery.cn/f_html/kjgg/P085_26105.html",
                      opener=opener, sleeper=lambda _: None)
        self.assertEqual(1, count)
        self.assertEqual(403, ctx.exception.attempts[0]["http_status"])

    def test_untrusted_redirect_stops_without_follow_on(self):
        calls = 0
        def opener(req, timeout=12):
            nonlocal calls
            calls += 1
            return Response("https://example.com/something")
        with self.assertRaises(TransportExhausted) as ctx:
            resilient_fetch("https://www.swlc.net.cn/lottery/ssq.html",
                            opener=opener, sleeper=lambda _: None)
        self.assertEqual(1, calls)
        self.assertEqual("UNTRUSTED_REDIRECT", ctx.exception.attempts[0]["reason"])

    def test_exhaustion_keeps_all_four_attempts(self):
        with self.assertRaises(TransportExhausted) as ctx:
            resilient_fetch("https://www.swlc.net.cn/lottery/ssq.html",
                opener=lambda req, timeout: (_ for _ in ()).throw(URLError("offline")),
                sleeper=lambda _: None)
        self.assertEqual(4, len(ctx.exception.attempts))
        self.assertTrue(all(x["reason"] == "NETWORK_URLError" for x in ctx.exception.attempts))

    def test_all_non200_raw_bytes_persist_with_attempt_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp)
            raw = b"issuer temporary 503 response"
            def server_error(req, timeout=12):
                raise HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(raw))
            result = collect_dlt("26105", ledger, fetcher=lambda url: dlt_fetch(
                url, opener=server_error, sleeper=lambda _: None, max_attempts=2))
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual(2, len(result["transport_attempts"]))
            self.assertEqual(503, result["http_status"])
            self.assertEqual(2, len(result["transport_attempts"]))
            digest = result["response_sha256"]
            self.assertEqual(raw, (ledger/"raw"/(digest+".bin")).read_bytes())
            self.assertEqual(1, len(list((ledger/"attempts"/"26105").glob("*.json"))))

    def test_bad_transport_limits_and_alternates(self):
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_OFFICIAL_ALTERNATE"):
            resilient_fetch("https://www.gdlottery.cn/f_html/kjgg/P085_26105.html",
                alternates=("https://example.com/f_html/kjgg/wrong.html",))
        with self.assertRaisesRegex(ValueError, "ATTEMPT_LIMIT_INVALID"):
            resilient_fetch("https://www.swlc.net.cn/lottery/ssq.html",
                            max_attempts=0)


if __name__ == "__main__":
    unittest.main()
