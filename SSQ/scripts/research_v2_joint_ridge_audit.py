from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "SSQ"
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

from glp.research_v2_model_audit import audit_joint_ridge
from glp.sources import MAX_LATEST_AGE_DAYS, build_canonical


def main() -> None:
    dataset, evidence = build_canonical()
    if dataset.crosscheck_status != "PASS":
        raise SystemExit("dataset crosscheck_status is not PASS")
    if evidence.get("crosscheck_status") != "PASS":
        raise SystemExit("evidence crosscheck_status is not PASS")
    passed_receipts = [
        row for row in evidence.get("source_receipts", [])
        if isinstance(row, dict) and row.get("status") == "PASS"
    ]
    if len(passed_receipts) < 2:
        raise SystemExit("official source quorum is below two PASS receipts")

    latest = evidence.get("latest") or {}
    latest_day = date.fromisoformat(str(latest.get("draw_date")))
    age_days = (datetime.now(timezone.utc).date() - latest_day).days
    if not (-1 <= age_days <= int(MAX_LATEST_AGE_DAYS)):
        raise SystemExit(f"latest official draw is stale/future: age_days={age_days}")

    result = audit_joint_ridge(dataset.draws, eval_points=120, train_points=120)
    result["canonical_hash"] = dataset.canonical_hash
    result["data_source"] = "LIVE_OFFICIAL_CANONICAL"
    result["network_gate"] = "PASS"
    result["freshness_gate"] = "PASS"
    result["freshness_age_days"] = age_days
    result["crosscheck_status"] = evidence.get("crosscheck_status")
    result["crosscheck_count"] = dataset.crosscheck_count
    result["source_verification"] = evidence.get("verification")
    result["pass_source_receipts"] = len(passed_receipts)

    out = ROOT / "artifacts" / "research_v2_joint_ridge_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("SSQ_V2_JOINT_RIDGE_AUDIT=PASS")
    print(f"LATEST_ISSUE={result['latest_issue']}")
    print(f"SHADOW_DECISION={result['shadow_decision']}")
    print("PREDICTIVE_EDGE_CLAIM=NOT_VERIFIED")
    print("PRODUCTION_RHO=0")
    for name, row in result["metrics"].items():
        print(
            f"METRIC {name}: mean={row['mean']:.12g} "
            f"lower95={row['bootstrap95'][0]:.12g} "
            f"p={row['permutation_p']:.12g} pass={row['pass']}"
        )
    print(f"EVIDENCE={out}")


if __name__ == "__main__":
    main()
