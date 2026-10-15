"""Bounded official-original capture and discovery-only AnySearch transport.

HTTP success never establishes draw authenticity, publication time, or A admission.
No credential is printed or persisted. Redirects outside the exact host are refused.
"""
from __future__ import annotations

import hashlib
import base64
import json
import socket
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .scoring import AdmissionBlocked

OFFICIAL_HOSTS = {
    "SSQ": frozenset(("www.cwl.gov.cn", "www.swlc.net.cn", "www.yzfcw.com")),
    "DLT": frozenset(("webapi.sporttery.cn", "api.js-lottery.com", "www.gstc.org.cn")),
}
ANYSEARCH_URL = "https://api.anysearch.com/mcp"


def validate_url(url, allowed_hosts):
    if type(url) is not str or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise AdmissionBlocked("INVALID_URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise AdmissionBlocked("INVALID_URL") from exc
    if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts
            or parsed.username is not None or parsed.password is not None
            or port not in (None,443) or parsed.fragment):
        raise AdmissionBlocked("URL_NOT_WHITELISTED")
    return parsed.hostname


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, {urlsplit(req.full_url).hostname})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def bounded_request(url, *, allowed_hosts, data=None, headers=None, timeout=5,
                    attempts=2, max_bytes=2*1024*1024, opener=None, pause=time.sleep):
    validate_url(url, allowed_hosts)
    if (type(attempts) is not int or not 1 <= attempts <= 3
            or type(timeout) not in (int,float) or not 0 < timeout <= 10
            or type(max_bytes) is not int or not 1 <= max_bytes <= 8*1024*1024):
        raise AdmissionBlocked("INVALID_NETWORK_BOUNDS")
    transport = opener or build_opener(SameHostRedirect())
    traces = []
    for attempt in range(1,attempts+1):
        try:
            deadline = time.monotonic() + timeout
            request_headers = {"User-Agent":"GLP-V44-Research/1", **(headers or {})}
            req = Request(url, data=data, headers=request_headers)
            with transport.open(req, timeout=timeout) as response:
                validate_url(response.geturl(), {urlsplit(url).hostname})
                status = response.status
                chunks, size = [], 0
                # read1 does a single underlying read, so a slow trickle cannot
                # keep one large read alive indefinitely. Socket timeout still
                # bounds each blocking operation; DNS is OS-resolver dependent.
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError("RESPONSE_DEADLINE")
                    chunk = response.read1(min(65536, max_bytes + 1 - size))
                    if time.monotonic() > deadline:
                        raise TimeoutError("RESPONSE_DEADLINE")
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > max_bytes:
                        raise AdmissionBlocked("EMPTY_OVERSIZED_OR_BAD_HTTP")
                body = b"".join(chunks)
                if status != 200 or not body or len(body) > max_bytes:
                    raise AdmissionBlocked("EMPTY_OVERSIZED_OR_BAD_HTTP")
                return body, dict(requested_url=url, final_url=response.geturl(), http_status=status,
                                  content_type=response.headers.get("Content-Type", ""),
                                  fetched_at=datetime.now(timezone.utc).isoformat(),
                                  sha256=hashlib.sha256(body).hexdigest(), bytes=len(body),
                                  attempts=traces+[dict(attempt=attempt,status="HTTP_OK")],
                                  admission="BLOCKED", publication_verified=False)
        except HTTPError as exc:
            # Authentication and other client errors are never blindly retried.
            traces.append(dict(attempt=attempt,status=f"HTTP_{exc.code}"))
            if exc.code not in (429,500,502,503,504):
                break
        except (URLError,TimeoutError,socket.timeout) as exc:
            traces.append(dict(attempt=attempt,status=type(exc).__name__))
        if attempt < attempts:
            pause(0.1*attempt)
    raise AdmissionBlocked("NETWORK_UNAVAILABLE:"+json.dumps(traces,separators=(",",":")))


def fetch_official(game, url, **kwargs):
    if type(game) is not str or game not in OFFICIAL_HOSTS:
        raise AdmissionBlocked("UNKNOWN_GAME")
    return bounded_request(url, allowed_hosts=OFFICIAL_HOSTS[game], **kwargs)


class AnySearchDiscovery:
    """JSON-RPC discovery transport; its return type cannot become official data.

    Tool names and arguments must come from an actual tools/list response. The
    caller decides which discovered read-only search tool to call. No model
    output or search hit is parsed as an official draw by this class.
    """
    def __init__(self, token=None, request=bounded_request):
        self.token = token
        self.request = request
        self.initialized = False
        self.available_tools = set()

    def rpc(self, method, params, request_id=1):
        if method not in ("initialize", "tools/list", "tools/call"):
            raise AdmissionBlocked("DISCOVERY_METHOD_NOT_ALLOWED")
        if method == "initialize":
            self.initialized = False
            self.available_tools = set()
        if type(request_id) is not int or request_id < 1:
            raise AdmissionBlocked("INVALID_RPC_ID")
        if method != "initialize" and not self.initialized:
            raise AdmissionBlocked("DISCOVERY_INITIALIZE_REQUIRED")
        if method == "tools/call" and (type(params) is not dict
                or params.get("name") not in {"search","batch_search","extract","get_sub_domains"}
                or params.get("name") not in self.available_tools):
            raise AdmissionBlocked("DISCOVERY_TOOL_NOT_ALLOWED")
        headers = {"Content-Type":"application/json", "Accept":"application/json, text/event-stream"}
        if self.token:
            headers["Authorization"] = "Bearer "+self.token
        raw, receipt = self.request(ANYSEARCH_URL, allowed_hosts={"api.anysearch.com"},
                                    data=json.dumps(dict(jsonrpc="2.0",id=request_id,method=method,params=params)).encode(),
                                    headers=headers)
        try:
            # Preserve SSE support without executing or interpreting server text.
            payload = raw.decode("utf-8")
            if receipt["content_type"].startswith("text/event-stream"):
                messages = [json.loads(line[5:].strip()) for line in payload.splitlines() if line.startswith("data:")]
                matching = [message for message in messages if type(message) is dict
                            and type(message.get("id")) is int and message.get("id") == request_id]
                result = matching[-1] if matching else {}
            else:
                result = json.loads(payload)
            if (type(result) is not dict or result.get("jsonrpc") != "2.0"
                    or type(result.get("id")) is not int or result.get("id") != request_id
                    or "error" in result or "result" not in result):
                raise ValueError("invalid RPC response")
        except (ValueError,UnicodeError) as exc:
            raise AdmissionBlocked("INVALID_DISCOVERY_RPC_RESPONSE") from exc
        if method == "initialize":
            if (type(result["result"]) is not dict
                    or result["result"].get("protocolVersion") != "2024-11-05"):
                raise AdmissionBlocked("INVALID_DISCOVERY_INITIALIZE")
            self.initialized = True
        if method == "tools/list":
            value = result["result"]
            if type(value) is not dict or type(value.get("tools")) is not list:
                raise AdmissionBlocked("INVALID_DISCOVERY_TOOL_LIST")
            self.available_tools = {item["name"] for item in value["tools"]
                                    if type(item) is dict and type(item.get("name")) is str}
        return dict(scope="SOURCE_DISCOVERY_ONLY", may_admit_official_data=False,
                    formal_A=0, result=result["result"], receipt=receipt,
                    raw_response_b64=base64.b64encode(raw).decode("ascii"))
