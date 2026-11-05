from __future__ import annotations

import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from glp import sources
from glp.sources import build_canonical


def _write_failure_receipt(artifacts_dir: Path, observations: list[dict], error: Exception) -> dict:
    """Create-only audit trail for actual parser-observed failed-run GET entities.

    Hash equality proves artifact integrity, not source origin or publication
    time. Distinct URLs with identical bodies remain separate response records.
    """
    root = artifacts_dir / "real_network_failed" / secrets.token_hex(12)
    root.mkdir(parents=True, exist_ok=False)
    raw_dir = root / "raw_responses"
    raw_dir.mkdir()
    records = []
    for observation in observations:
        raw = observation["raw"]
        digest = hashlib.sha256(raw).hexdigest()
        target = raw_dir / (digest + ".bin")
        if not target.exists():
            with target.open("xb") as handle:
                handle.write(raw)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("FAILED_NETWORK_RAW_BYTES_SHA_MISMATCH")
        records.append({
            **{key: value for key, value in observation.items() if key != "raw"},
            "artifact": "raw_responses/" + digest + ".bin",
            "sha256": digest, "bytes": len(raw),
            "request_method": "GET",
        })
    receipt = {
        "schema": "DLT-G00-G01-LIVE-FAILURE-RAW-1",
        "status": "BLOCKED", "error_type": type(error).__name__,
        "error": str(error)[:1024],
        "parser_version": sources.PARSER_VERSION,
        "raw_responses": records,
        "source_origin_authenticity": "NOT_CRYPTOGRAPHICALLY_VERIFIED",
        "history_asof_authenticity": "NOT_VERIFIED",
        "timestamp_trust": "LOCAL_CLOCK_UNTRUSTED",
        "official_target_admission": "BLOCKED",
        "external_tsa": "NOT_RUN", "formal_A": 0, "decision": "NO_EDGE",
    }
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8") + b"\n"
    manifest = root / "failure.json"
    with manifest.open("xb") as handle:
        handle.write(payload)
    if manifest.read_bytes() != payload:
        raise ValueError("FAILED_NETWORK_RECEIPT_READBACK_MISMATCH")
    return {
        "path": manifest.relative_to(artifacts_dir).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "evidence_class": "SHADOW",
        "raw_response_count": len(records),
    }


def main() -> int:
    out = ROOT / "artifacts" / "real_network_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Observe the exact entity bytes returned to the installed DLT source
    # parser in this *same* native network run. Never turn a failure into PASS.
    observed: list[dict] = []
    original_get = sources.NET.get

    def recording_get(url, *args, **kwargs):
        response = original_get(url, *args, **kwargs)
        try:
            raw = bytes(response.content)
            total = sum(len(item["raw"]) for item in observed if "raw" in item)
            if len(raw) <= sources.MAX_PAYLOAD_BYTES and total + len(raw) <= 25_000_000:
                observed.append({
                    "raw": raw,
                    "requested_url": str(url),
                    "url": str(getattr(response, "url", "") or url),
                    "request_params": kwargs.get("params") or {},
                    "http_status": int(getattr(response, "status_code", 0)),
                    "content_type": str(getattr(response, "headers", {}).get("Content-Type", "")),
                    "fetched_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
                    "parser_version": sources.PARSER_VERSION,
                })
        except (TypeError, ValueError, AttributeError):
            # Never change production transport/parser behavior just to produce
            # forensic metadata. If capture fails, source admission stays blocked.
            pass
        return response

    sources.NET.get = recording_get
    try:
        dataset, evidence = build_canonical()
        source_mode = evidence.get("source_mode")
        if source_mode == "national_plus_jiangsu":
            source_evidence_ok = bool(evidence.get("national_raw_manifest")) and bool(evidence.get("jiangsu_raw_evidence"))
        elif source_mode == "jiangsu_full_plus_gansu":
            source_evidence_ok = (
                bool(evidence.get("national_failure"))
                and bool(evidence.get("jiangsu_full_raw_manifest"))
                and bool(evidence.get("gansu_raw_evidence"))
            )
        else:
            source_evidence_ok = False
        ok = (
            dataset.crosscheck_status == "PASS"
            and evidence.get("network_gate") == "PASS"
            and evidence.get("freshness_gate") == "PASS"
            and evidence.get("crosscheck_status") == "PASS"
            and source_evidence_ok
        )
        report = {
            "schema": "dlt-real-network-check-v1",
            "status": "PASS" if ok else "FAIL",
            "latest_issue": dataset.draws[-1].issue if dataset.draws else None,
            "draw_count": len(dataset.draws),
            "canonical_hash": dataset.canonical_hash,
            "source_mode": evidence.get("source_mode"),
            "crosscheck_count": dataset.crosscheck_count,
            "crosscheck_status": dataset.crosscheck_status,
            "evidence": evidence,
        }
    except Exception as exc:
        report = {
            "schema": "dlt-real-network-check-v1",
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if observed:
            try:
                report["failure_receipt"] = _write_failure_receipt(
                    out.parent, observed, exc)
            except Exception as custody_exc:
                report["failure_receipt_status"] = (
                    "BLOCKED_CUSTODY_WRITE_FAILED:" + type(custody_exc).__name__)
        else:
            report["failure_receipt_status"] = "NO_HTTP_RESPONSE_ENTITY_CAPTURED"
    finally:
        sources.NET.get = original_get
    # This script checks live historical HTTP/data cross-checks only. Even a
    # network PASS cannot authenticate publication as-of, a future target,
    # a trusted predraw freeze, or independent post-draw outcomes.
    report.update({
        "gate_scope": "LIVE_HISTORY_NETWORK_CROSSCHECK_ONLY",
        "evidence_class": "SHADOW",
        "history_asof_authenticity": "NOT_VERIFIED",
        "source_origin_authenticity": "NOT_CRYPTOGRAPHICALLY_VERIFIED",
        "official_target_admission": "BLOCKED",
        "external_predraw_tsa": "NOT_VERIFIED",
        "official_outcome_authenticity": "NOT_VERIFIED",
        "prospective_verified": False,
        "formal_A": 0,
        "decision": "NO_EDGE",
    })
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
