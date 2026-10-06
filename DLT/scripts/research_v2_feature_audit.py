from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from glp.research_v2_audit import audit_feature_utility
from glp.sources import build_canonical


def main() -> None:
    dataset, source_evidence = build_canonical()
    if source_evidence.get("network_gate") != "PASS":
        raise SystemExit("live canonical network_gate is not PASS")
    if source_evidence.get("freshness_gate") != "PASS":
        raise SystemExit("live canonical freshness_gate is not PASS")
    if source_evidence.get("crosscheck_status") != "PASS":
        raise SystemExit("live canonical crosscheck_status is not PASS")
    if dataset.crosscheck_status != "PASS":
        raise SystemExit("live canonical dataset crosscheck_status is not PASS")
    if not dataset.draws:
        raise SystemExit("live canonical dataset is empty")

    result = audit_feature_utility(dataset.draws, eval_points=360)
    result["canonical_hash"] = dataset.canonical_hash
    result["data_source"] = "LIVE_OFFICIAL_CANONICAL"
    result["source_mode"] = source_evidence.get("source_mode")
    result["network_gate"] = source_evidence.get("network_gate")
    result["freshness_gate"] = source_evidence.get("freshness_gate")
    result["crosscheck_status"] = source_evidence.get("crosscheck_status")
    result["crosscheck_count"] = dataset.crosscheck_count

    out_dir = ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "research_v2_feature_audit.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("DLT_V2_FEATURE_AUDIT=PASS")
    print(f"LATEST_ISSUE={result['latest_issue']}")
    print(f"CANONICAL_HASH={result['canonical_hash']}")
    print(f"SOURCE_MODE={result['source_mode']}")
    print("PREDICTIVE_EDGE_CLAIM=NOT_VERIFIED")
    print("PRODUCTION_RHO=0")
    for name, row in result["combined"].items():
        print(
            f"FEATURE {name}: front={row['front']} "
            f"back={row['back']} overall={row['overall']}"
        )
    print(f"EVIDENCE={out_path}")


if __name__ == "__main__":
    main()
