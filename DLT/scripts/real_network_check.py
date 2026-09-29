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
        ok = (
            dataset.crosscheck_status == "PASS"
            and evidence.get("network_gate") == "PASS"
            and evidence.get("crosscheck_status") == "PASS"
            and bool(evidence.get("national_raw_manifest"))
            and bool(evidence.get("jiangsu_raw_evidence"))
        )
        report = {
            "schema": "dlt-real-network-check-v1",
            "status": "PASS" if ok else "FAIL",
            "latest_issue": dataset.draws[-1].issue if dataset.draws else None,
            "draw_count": len(dataset.draws),
            "canonical_hash": dataset.canonical_hash,
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
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
