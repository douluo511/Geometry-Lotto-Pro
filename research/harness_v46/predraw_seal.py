"""Portable frozen-ledger RFC3161 requests and verification, still SHADOW.

An explicitly pinned caller CA is not an independently approved trust policy.
No result here authenticates a lottery source, target, cutoff or formal A.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import (RULES, GateError, canon, dt, load_registered_snapshot,
                   validate_run_manifest_record)
from .convergence import check_complete_batch


def _pin(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise GateError("EXPLICIT_SHA256_TRUST_ROOT_PIN_REQUIRED")
    return value


def _clock(value):
    value = value if value is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise GateError("SEAL_REQUIRES_AWARE_CLOCK")
    return value


def _openssl(executable, *args):
    executable = executable or shutil.which("openssl")
    fallback = Path("C:/Program Files/Git/usr/bin/openssl.exe")
    if not executable and os.name == "nt" and fallback.is_file():
        executable = str(fallback)
    if not executable:
        raise GateError("OPENSSL_REQUIRED_NO_FAKE_TIMESTAMP_FALLBACK")
    try:
        result = subprocess.run(
            [str(executable), *map(str, args)], capture_output=True, timeout=30,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("OPENSSL_EXECUTION_FAILED") from exc
    if result.returncode:
        raise GateError("RFC3161_VERIFY_FAILED:" + result.stderr.decode(errors="replace")[-1000:])
    return result.stdout


def frozen_seal_payload(database, run_id, trust_root_sha256):
    """Recheck both original batches and export complete preimages, read-only."""
    _pin(trust_root_sha256)
    if not isinstance(run_id, str) or not run_id.startswith("V47-"):
        raise GateError("DUAL_GAME_V47_RUN_ID_REQUIRED")
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        registered = validate_run_manifest_record(conn, run_id)
        snapshots, games = {}, {}
        for game in RULES:
            batch = check_complete_batch(conn, run_id, game)
            snapshots[game] = load_registered_snapshot(conn, run_id, game)
            rows = conn.execute(
                "SELECT model,payload,prediction_sha256,frozen_at,evidence_class "
                "FROM predictions WHERE run_id=? AND lottery=? ORDER BY model",
                (run_id, game),
            ).fetchall()
            games[game] = {
                "prediction_batch_sha256": batch,
                "predictions": [{"model": model, "payload": json.loads(payload),
                                 "prediction_sha256": sha,
                                 "frozen_at_local_untrusted": stamp,
                                 "evidence_class": klass}
                                for model, payload, sha, stamp, klass in rows],
            }
        return {
            "schema": "V47-FROZEN-SEAL-PAYLOAD-1", "run_id": run_id,
            "manifest": registered, "snapshots": snapshots, "games": games,
            "trust_root_sha256": trust_root_sha256,
            "trust_policy": "CALLER_SUPPLIED_UNVERIFIED",
            "official_source_authenticity": "CALLER_UNVERIFIED",
            "official_target_admission": "BLOCKED",
            "formal_A": 0, "decision": "NO_EDGE",
        }
    finally:
        conn.close()


def prepare_request(database, run_id, output_dir, *, trust_root_sha256,
                    openssl=None, now=None):
    """Create a new directory only; SHA256 imprint plus OpenSSL random nonce."""
    observed = _clock(now)
    payload = frozen_seal_payload(database, run_id, trust_root_sha256)
    for snapshot in payload["snapshots"].values():
        if observed >= dt(snapshot["sales_cutoff"]):
            raise GateError("SEAL_REQUEST_AFTER_CUTOFF")
        if observed < dt(snapshot["as_of"]):
            raise GateError("SEAL_REQUEST_BEFORE_ASOF")
    for game in payload["games"].values():
        if any(dt(p["frozen_at_local_untrusted"]) > observed for p in game["predictions"]):
            raise GateError("SEAL_REQUEST_BEFORE_LOCAL_FREEZE")
    raw = canon(payload).encode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        request = Path(tmp) / "request.tsq"
        _openssl(openssl, "ts", "-query", "-digest", hashlib.sha256(raw).hexdigest(),
                 "-sha256", "-cert", "-out", request)
        request_bytes = request.read_bytes()
    root = Path(output_dir)
    root.mkdir()  # Never replace an earlier request or any preserved evidence.
    (root / "payload.json").write_bytes(raw)
    (root / "request.tsq").write_bytes(request_bytes)
    return {"schema": "V47-SEAL-REQUEST-1", "run_id": run_id,
            "payload_sha256": hashlib.sha256(raw).hexdigest(),
            "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "trust_root_sha256": trust_root_sha256,
            "external_tsa": "REQUEST_ONLY_NOT_VERIFIED",
            "formal_A": 0, "decision": "NO_EDGE"}


def _signed_time_bounds(text):
    """Read only OpenSSL-decoded signed fields, after cryptographic verification."""
    times = re.findall(r"^Time stamp: (.+)$", text, re.MULTILINE)
    accuracies = re.findall(r"^Accuracy: (.+)$", text, re.MULTILINE)
    if len(times) != 1 or len(accuracies) != 1:
        raise GateError("RFC3161_TIME_OR_ACCURACY_MISSING")
    stamp = None
    for fmt in ("%b %d %H:%M:%S %Y GMT", "%b %d %H:%M:%S.%f %Y GMT"):
        try:
            stamp = datetime.strptime(times[0].strip(), fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            pass
    match = re.fullmatch(r"(\w+) seconds, (\w+) millis, (\w+) micros", accuracies[0].strip())
    if stamp is None or match is None or all(x == "unspecified" for x in match.groups()):
        raise GateError("RFC3161_TIME_OR_ACCURACY_UNSUPPORTED")
    try:
        values = [0 if x == "unspecified" else int(x, 16) for x in match.groups()]
        if values[1] > 999 or values[2] > 999:
            raise ValueError("invalid RFC3161 fractional accuracy")
        accuracy = timedelta(seconds=values[0], milliseconds=values[1], microseconds=values[2])
        return stamp, stamp - accuracy, stamp + accuracy
    except (ValueError, OverflowError) as exc:
        raise GateError("RFC3161_TIME_OR_ACCURACY_UNSUPPORTED") from exc


def verify_response(database, run_id, seal_dir, response_file, ca_file, *,
                    trust_root_sha256, openssl=None, observed_at=None):
    """Verify exact bytes, nonce, signature/chain, pin and conservative time bound.

    The caller's CA pin and claimed cutoff remain unapproved external inputs.
    This receipt cannot grant the harness's formal TSA/G01 admission gates.
    """
    observed = _clock(observed_at)
    expected = frozen_seal_payload(database, run_id, trust_root_sha256)
    raw = (Path(seal_dir) / "payload.json").read_bytes()
    if raw != canon(expected).encode("utf-8"):
        raise GateError("SEAL_PAYLOAD_DIFFERS_FROM_LEDGER")
    ca = Path(ca_file).read_bytes()
    if hashlib.sha256(ca).hexdigest() != trust_root_sha256:
        raise GateError("TRUST_ROOT_PIN_MISMATCH")
    request = (Path(seal_dir) / "request.tsq").read_bytes()
    response = Path(response_file).read_bytes()
    if any(not b or len(b) > 1_000_000 for b in (ca, request, response)):
        raise GateError("INVALID_OR_OVERSIZED_RFC3161_EVIDENCE")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, content in (("payload", raw), ("ca.pem", ca),
                              ("request.tsq", request), ("response.tsr", response)):
            (root / name).write_bytes(content)
        (root / "empty-ca-dir").mkdir()
        common = ("-in", root / "response.tsr", "-CAfile", root / "ca.pem",
                  "-CApath", root / "empty-ca-dir", "-CAstore", root / "ca.pem")
        # Both are necessary: one binds data, the other checks the request nonce.
        _openssl(openssl, "ts", "-verify", "-data", root / "payload", *common)
        _openssl(openssl, "ts", "-verify", "-queryfile", root / "request.tsq", *common)
        decoded = _openssl(openssl, "ts", "-reply", "-in", root / "response.tsr", "-text")
        query = _openssl(openssl, "ts", "-query", "-in", root / "request.tsq", "-text")
    texts = [value.decode("ascii", errors="strict") for value in (query, decoded)]
    for text in texts:
        if len(re.findall(r"^Nonce: 0x[0-9a-fA-F]+\s*$", text, re.MULTILINE)) != 1:
            raise GateError("RFC3161_NONCE_REQUIRED")
        if re.findall(r"^Hash Algorithm: (.+)$", text, re.MULTILINE) != ["sha256"]:
            raise GateError("RFC3161_SHA256_REQUIRED")
    stamp, lower, upper = _signed_time_bounds(texts[1])
    if stamp > observed:
        raise GateError("RFC3161_SIGNED_TIME_IN_FUTURE")
    for snapshot in expected["snapshots"].values():
        if upper >= dt(snapshot["sales_cutoff"]):
            raise GateError("TOKEN_NOT_STRICTLY_PREDRAW")
    for game in expected["games"].values():
        if any(lower < dt(p["frozen_at_local_untrusted"]) for p in game["predictions"]):
            raise GateError("TOKEN_PRECEDES_LOCAL_FREEZE_CLAIM")
    return {"schema": "V47-SEAL-VERIFY-1", "run_id": run_id,
            "payload_sha256": hashlib.sha256(raw).hexdigest(),
            "request_sha256": hashlib.sha256(request).hexdigest(),
            "response_sha256": hashlib.sha256(response).hexdigest(),
            "trust_root_sha256": trust_root_sha256,
            "signed_at": stamp.isoformat(), "latest_possible_signed_at": upper.isoformat(),
            "cryptographic_verification": "PASS_UNDER_CALLER_PIN",
            "predraw_time_bound": "BEFORE_BOTH_CLAIMED_CUTOFFS",
            "trust_policy": "CALLER_SUPPLIED_UNVERIFIED",
            "official_source_authenticity": "CALLER_UNVERIFIED",
            "official_target_admission": "BLOCKED", "external_tsa_formal_admission": "BLOCKED",
            "formal_A": 0, "decision": "NO_EDGE"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="SHADOW frozen-ledger RFC3161 evidence")
    parser.add_argument("command", choices=("request", "verify"))
    parser.add_argument("--database", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seal-dir", required=True)
    parser.add_argument("--trust-root-sha256", required=True)
    parser.add_argument("--response")
    parser.add_argument("--ca-file")
    parser.add_argument("--openssl")
    args = parser.parse_args(argv)
    try:
        common = {"trust_root_sha256": args.trust_root_sha256, "openssl": args.openssl}
        if args.command == "request":
            result = prepare_request(args.database, args.run_id, args.seal_dir, **common)
        else:
            if not args.response or not args.ca_file:
                raise GateError("VERIFY_REQUIRES_RESPONSE_AND_CA_FILE")
            result = verify_response(args.database, args.run_id, args.seal_dir,
                                     args.response, args.ca_file, **common)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (GateError, OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
