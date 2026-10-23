"""Optional RFC3161 sidecar for V4.7 SHADOW, NOT formal timestamp admission.

RFC3161 token checks use the installed OpenSSL CLI to verify request nonce,
message imprint, TSA signature and a chain to a CALLER-SUPPLIED root. Roots,
revocation status, official sales cutoffs and upstream custody have NOT been
independently accepted by this client. All results are A=0/NO_EDGE.

This sidecar never modifies prediction databases, model code or frozen records.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .core import GateError, dt
from .prospective_cycle import build_predraw_commitment, verify_predraw_commitment

MAX_QUERY_BYTES = 65536
MAX_REPLY_BYTES = 2_000_000


def _run_openssl(args: list[str], *, timeout: int = 25) -> bytes:
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("TSA_OPENSSL_EXECUTION_FAILED") from exc
    if result.returncode != 0:
        raise GateError("TSA_OPENSSL_VERIFICATION_FAILED")
    return result.stdout


def make_query(database, commitment, *, openssl="openssl") -> bytes:
    """Generate a DER RFC3161 request with OpenSSL's default random nonce.

    This is the real SHA256 digest of BOTH frozen SSQ+DLT prediction batches.
    It is not signed and cannot serve as evidence of time until a TSA replies.
    """
    verify_predraw_commitment(database, commitment)
    digest_hex = commitment["message_imprint_sha256"]
    if not isinstance(digest_hex, str) or len(digest_hex) != 64:
        raise GateError("TSA_SHA256_DIGEST_REQUIRED")
    query = _run_openssl(
        [openssl, "ts", "-query", "-sha256", "-digest", digest_hex, "-cert"]
    )
    if not query or len(query) > MAX_QUERY_BYTES or query[:1] != b"\x30":
        raise GateError("TSA_QUERY_INVALID_DER")
    return query


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _valid_https_endpoint(url: str) -> None:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise GateError("TSA_HTTPS_URL_REQUIRED") from exc
    if (parsed.scheme != "https" or not host or not parsed.netloc or
            port not in (None, 443) or parsed.username or parsed.password or
            parsed.fragment or host == "localhost" or host.endswith(".localhost") or
            host.endswith(".local") or host.endswith(".internal")):
        raise GateError("TSA_HTTPS_URL_REQUIRED")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise GateError("TSA_HTTPS_URL_REQUIRED")


def submit_query_https(url: str, query_der: bytes, *, timeout: int = 20) -> bytes:
    """Opt-in real HTTPS POST, no redirects, no insecure certificate bypass.

    No timestamp is accepted based on this network response alone.
    The caller must persist original TSQ/TSR bytes and verify separately.
    """
    _valid_https_endpoint(url)
    if (not isinstance(query_der, bytes) or not query_der or
            len(query_der) > MAX_QUERY_BYTES or query_der[:1] != b"\x30"):
        raise GateError("TSA_QUERY_INVALID_DER")
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise GateError("TSA_INVALID_NETWORK_TIMEOUT")
    req = urllib.request.Request(
        url,
        data=query_der,
        method="POST",
        headers={"Content-Type": "application/timestamp-query",
                 "Accept": "application/timestamp-reply"},
    )
    opener = urllib.request.build_opener(_RejectRedirect)
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.status != 200:
                raise GateError("TSA_HTTP_NOT_SUCCESS")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/timestamp-reply":
                raise GateError("TSA_RESPONSE_CONTENT_TYPE_INVALID")
            data = response.read(MAX_REPLY_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GateError("TSA_NETWORK_REQUEST_FAILED") from exc
    if not data or len(data) > MAX_REPLY_BYTES or data[:1] != b"\x30":
        raise GateError("TSA_RESPONSE_INVALID_OR_OVERSIZED")
    return data


def _require_pem(path_value, *, error_code: str) -> Path:
    if not isinstance(path_value, (str, Path)) or not str(path_value):
        raise GateError(error_code)
    path = Path(path_value)
    if not path.is_file():
        raise GateError(error_code)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GateError(error_code) from exc
    if not data.startswith(b"-----BEGIN CERTIFICATE-----") or len(data) > 2_000_000:
        raise GateError(error_code)
    return path


def _parse_gentime(reply_text: bytes) -> datetime:
    try:
        printable = reply_text.decode("utf-8", errors="strict")
        matches = re.findall(r"^\s*Time stamp:\s*(.*?)\s*$", printable, flags=re.MULTILINE)
        if len(matches) != 1:
            raise ValueError("missing or ambiguous timestamp")
        stamp = datetime.strptime(matches[0], "%b %d %H:%M:%S %Y GMT")
        return stamp.replace(tzinfo=timezone.utc)
    except (UnicodeDecodeError, ValueError) as exc:
        raise GateError("TSA_GENTIME_PARSE_BLOCKED") from exc


def verify_response(database, commitment, query_der: bytes, response_der: bytes, *,
                    ca_file, untrusted_file=None, openssl="openssl") -> dict:
    """Cryptographically verify a TSA response, but do NOT confer research admission.

    Check 1 binds signature+chain+nonce to the original DER request.
    Check 2 binds signature+chain+imprint to the frozen two-game SHA256.
    Afterwards, compare genTime to the *declared* cutoffs; independently
    authenticated official cutoffs and root-approval are separate gates.
    """
    verify_predraw_commitment(database, commitment)
    anchor = _require_pem(ca_file, error_code="TSA_TRUST_ANCHOR_REQUIRED")
    chain = (_require_pem(untrusted_file, error_code="TSA_UNTRUSTED_CHAIN_INVALID")
             if untrusted_file is not None else None)
    if (not isinstance(query_der, bytes) or len(query_der) > MAX_QUERY_BYTES
            or not query_der or query_der[:1] != b"\x30"):
        raise GateError("TSA_QUERY_INVALID_DER")
    if (not isinstance(response_der, bytes) or len(response_der) > MAX_REPLY_BYTES
            or not response_der or response_der[:1] != b"\x30"):
        raise GateError("TSA_RESPONSE_INVALID_OR_OVERSIZED")
    imprint = commitment["message_imprint_sha256"]
    with tempfile.TemporaryDirectory(prefix="v47-tsa-verify-") as directory:
        root = Path(directory)
        q = root / "request.tsq"
        r = root / "response.tsr"
        q.write_bytes(query_der)
        r.write_bytes(response_der)
        base = [openssl, "ts", "-verify"]
        ca_options = ["-CAfile", str(anchor)]
        if chain is not None:
            ca_options += ["-untrusted", str(chain)]
        _run_openssl(base + ["-queryfile", str(q), "-in", str(r)] + ca_options)
        _run_openssl(base + ["-digest", imprint, "-in", str(r)] + ca_options)
        output = _run_openssl([openssl, "ts", "-reply", "-in", str(r), "-text"])
    signed_time = _parse_gentime(output)
    declared_cutoffs = [
        dt(commitment["preimage"]["games"][game]["sales_cutoff"])
        for game in ("SSQ", "DLT")
    ]
    if any(signed_time >= cutoff for cutoff in declared_cutoffs):
        raise GateError("TSA_AFTER_DECLARED_SALES_CUTOFF")
    return {
        "schema": "V47-RFC3161-CRYPTO-REPORT-1",
        "run_id": commitment["preimage"]["run_id"],
        "message_imprint_sha256": imprint,
        "query_sha256": hashlib.sha256(query_der).hexdigest(),
        "response_sha256": hashlib.sha256(response_der).hexdigest(),
        "caller_ca_file_sha256": hashlib.sha256(anchor.read_bytes()).hexdigest(),
        "gen_time_utc": signed_time.isoformat(),
        "cutoff_relation": "BEFORE_BOTH_DECLARED_CUTOFFS_UNVERIFIED",
        "cryptographic_check": "PASS_CALLER_ANCHOR",
        "trusted_tsa_identity_independently_approved": False,
        "trust_anchor_independently_approved": False,
        "certificate_revocation_verified": False,
        "independent_cutoff_authenticated": False,
        "outside_custody_verified": False,
        "research_admission": "BLOCKED",
        "formal_A": 0,
        "decision": "NO_EDGE",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="V4.7 RFC3161 SHADOW helper: never formal-A")
    sub = parser.add_subparsers(dest="action", required=True)
    request = sub.add_parser("request", help="Create nonce-bearing DER query and POST to HTTPS TSA")
    verify = sub.add_parser("verify", help="Verify response using explicitly supplied caller trust root")
    for p in (request, verify):
        p.add_argument("--database", required=True)
        p.add_argument("--commitment-file", required=True)
        p.add_argument("--openssl", default="openssl")
    request.add_argument("--tsa-url", required=True)
    request.add_argument("--query-out", required=True)
    request.add_argument("--response-out", required=True)
    verify.add_argument("--query-file", required=True)
    verify.add_argument("--response-file", required=True)
    verify.add_argument("--ca-file", required=True)
    verify.add_argument("--untrusted-file")
    args = parser.parse_args(argv)
    try:
        commitment = json.loads(Path(args.commitment_file).read_text(encoding="utf-8"))
        if args.action == "request":
            if Path(args.query_out).resolve() == Path(args.response_out).resolve():
                raise GateError("TSA_QUERY_REPLY_PATH_CONFLICT")
            query = make_query(args.database, commitment, openssl=args.openssl)
            with open(args.query_out, "xb") as out:
                out.write(query)
            reply = submit_query_https(args.tsa_url, query)
            with open(args.response_out, "xb") as out:
                out.write(reply)
            result = {"query_sha256": hashlib.sha256(query).hexdigest(),
                      "response_sha256": hashlib.sha256(reply).hexdigest(),
                      "response_received_not_verified": True,
                      "formal_A": 0, "decision": "NO_EDGE"}
        else:
            result = verify_response(
                args.database, commitment,
                Path(args.query_file).read_bytes(), Path(args.response_file).read_bytes(),
                ca_file=args.ca_file, untrusted_file=args.untrusted_file, openssl=args.openssl,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (GateError, OSError, ValueError, TypeError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
