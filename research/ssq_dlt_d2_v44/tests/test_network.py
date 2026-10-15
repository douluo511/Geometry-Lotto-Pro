import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from research.ssq_dlt_d2_v44.network import (
    ANYSEARCH_URL, AnySearchDiscovery, SameHostRedirect, bounded_request, validate_url,
)
from research.ssq_dlt_d2_v44.scoring import AdmissionBlocked


class Response(io.BytesIO):
    status = 200
    headers = {"Content-Type":"application/json"}
    def geturl(self):
        return "https://www.cwl.gov.cn/original"


class TestNetwork(unittest.TestCase):
    def test_exact_official_host_no_credentials_or_fragment(self):
        for url in ("http://www.cwl.gov.cn/x", "https://www.cwl.gov.cn.evil/x",
                    "https://evil@www.cwl.gov.cn/x", "https://www.cwl.gov.cn:444/x",
                    "https://api.anysearch.com/mcp", "https://www.cwl.gov.cn/x#fake",
                    "https://www.cwl.gov.cn/a\nb", "https://www.cwl.gov.cn/a\x00b"):
            with self.subTest(url=url), self.assertRaises(AdmissionBlocked):
                validate_url(url,{"www.cwl.gov.cn"})

    def test_redirect_refused_before_following_unofficial_host(self):
        with self.assertRaises(AdmissionBlocked):
            SameHostRedirect().redirect_request(Request("https://www.cwl.gov.cn/x"),None,302,"",{},"https://evil.test/x")

    def test_bounded_timeout_retry_then_success(self):
        class Transport:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise URLError("offline")
                return Response(b'{"synthetic":true}')
        transport = Transport()
        body, receipt = bounded_request("https://www.cwl.gov.cn/original", allowed_hosts={"www.cwl.gov.cn"},
                                        opener=transport,pause=lambda _:None)
        self.assertEqual(transport.calls,2)
        self.assertEqual(receipt["admission"],"BLOCKED")
        self.assertFalse(receipt["publication_verified"])

    def test_authentication_errors_not_retried_or_leaked(self):
        class Transport:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise HTTPError(request.full_url,401,"private-token",{},None)
        transport = Transport()
        with self.assertRaises(AdmissionBlocked) as caught:
            bounded_request(ANYSEARCH_URL,allowed_hosts={"api.anysearch.com"},opener=transport,pause=lambda _:None)
        self.assertEqual(transport.calls,1)
        self.assertNotIn("private-token",str(caught.exception))

    def test_retry_exhaustion(self):
        class Transport:
            calls = 0
            def open(self,request,timeout):
                self.calls += 1
                raise TimeoutError("synthetic")
        transport=Transport()
        with self.assertRaises(AdmissionBlocked):
            bounded_request(ANYSEARCH_URL,allowed_hosts={"api.anysearch.com"},opener=transport,pause=lambda _:None)
        self.assertEqual(transport.calls,2)

    def test_oversized_body_rejected(self):
        class Transport:
            def open(self,request,timeout):
                return Response(b"123456")
        with self.assertRaises(AdmissionBlocked):
            bounded_request("https://www.cwl.gov.cn/original",allowed_hosts={"www.cwl.gov.cn"},
                            opener=Transport(),max_bytes=5)

    def test_deadline_checked_after_eof_return(self):
        clock=[0]
        class SlowEOF(Response):
            def read1(self,size):
                value=super().read1(size)
                if not value:
                    clock[0]=2
                return value
        class Transport:
            def open(self,request,timeout):
                return SlowEOF(b"body")
        with patch("research.ssq_dlt_d2_v44.network.time.monotonic",side_effect=lambda:clock[0]):
            with self.assertRaises(AdmissionBlocked):
                bounded_request("https://www.cwl.gov.cn/original",allowed_hosts={"www.cwl.gov.cn"},
                                opener=Transport(),attempts=1,timeout=1)

    def test_unsupported_protocol_is_not_initialized(self):
        def transport(*args,**kwargs):
            return b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"unknown"}}', {"content_type":"application/json"}
        client=AnySearchDiscovery(request=transport)
        with self.assertRaises(AdmissionBlocked):
            client.rpc("initialize",{})
        self.assertFalse(client.initialized)

    def test_search_result_cannot_be_official_admission(self):
        def transport(*args,**kwargs):
            request = json.loads(kwargs["data"])
            result = {"protocolVersion":"2024-11-05"} if request["method"] == "initialize" else {"tools":[{"name":"search"}]} if request["method"] == "tools/list" else {"hits":["synthetic"]}
            return json.dumps(dict(jsonrpc="2.0",id=request["id"],result=result)).encode(), {"content_type":"application/json"}
        client=AnySearchDiscovery(request=transport)
        client.rpc("initialize", {})
        client.rpc("tools/list", {})
        output=client.rpc("tools/call", {"name":"search","arguments":{}})
        self.assertEqual(output["scope"],"SOURCE_DISCOVERY_ONLY")
        self.assertFalse(output["may_admit_official_data"])
        self.assertEqual(output["formal_A"],0)

    def test_only_discovery_tools_allowed(self):
        with self.assertRaises(AdmissionBlocked):
            AnySearchDiscovery().rpc("tools/call", {"name":"send_message","arguments":{}})

    def test_unlisted_tool_and_malformed_rpc_refused(self):
        def malformed(*args, **kwargs):
            return b'{"jsonrpc":"wrong","id":true,"result":{"protocolVersion":"x"}}', {"content_type":"application/json"}
        with self.assertRaises(AdmissionBlocked):
            AnySearchDiscovery(request=malformed).rpc("initialize", {})
        client=AnySearchDiscovery()
        client.initialized=True
        with self.assertRaises(AdmissionBlocked):
            client.rpc("tools/call", {"name":"search","arguments":{}})


if __name__ == "__main__":
    unittest.main()
