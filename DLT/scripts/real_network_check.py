from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from glp.sources import build_canonical


def main() -> int:
    out = ROOT / "artifacts" / "real_network_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
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
