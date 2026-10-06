from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from glp.research_v2_model_audit import audit_joint_ridge
from glp.sources import build_canonical


def main() -> None:
    dataset, evidence = build_canonical()
    for key in ("network_gate", "freshness_gate", "crosscheck_status"):
        if evidence.get(key) != "PASS":
            raise SystemExit(f"{key} is not PASS")
    if dataset.crosscheck_status != "PASS":
        raise SystemExit("dataset crosscheck_status is not PASS")

    result = audit_joint_ridge(dataset.draws, eval_points=120, train_points=120)
    result["canonical_hash"] = dataset.canonical_hash
    result["data_source"] = "LIVE_OFFICIAL_CANONICAL"
    result["source_mode"] = evidence.get("source_mode")
    result["network_gate"] = evidence.get("network_gate")
    result["freshness_gate"] = evidence.get("freshness_gate")
    result["crosscheck_status"] = evidence.get("crosscheck_status")
    result["crosscheck_count"] = dataset.crosscheck_count

    out = ROOT / "artifacts" / "research_v2_joint_ridge_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("DLT_V2_JOINT_RIDGE_AUDIT=PASS")
    print(f"LATEST_ISSUE={result['latest_issue']}")
    print(f"SHADOW_DECISION={result['shadow_decision']}")
    print("PREDICTIVE_EDGE_CLAIM=NOT_VERIFIED")
    print("PRODUCTION_RHO=0")
    for area, row in result["areas"].items():
        print(
            f"AREA {area}: decision={row['decision']} "
            f"brier_gain={row['brier_gain_vs_uniform']['mean']:.12g} "
            f"recall_gain={row['recall_gain_vs_random']['mean']:.12g}"
        )
    print(f"EVIDENCE={out}")


if __name__ == "__main__":
    main()
