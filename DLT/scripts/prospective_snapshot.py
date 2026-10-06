from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from glp.prospective import run_prospective_cycle
from glp.sources import build_canonical
from glp.util import atomic_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger-dir", required=True)
    parser.add_argument("--source-commit", default=os.environ.get("GLP_SOURCE_COMMIT", ""))
    args = parser.parse_args()

    dataset, evidence = build_canonical()
    required = {
        "network_gate": evidence.get("network_gate"),
        "freshness_gate": evidence.get("freshness_gate"),
        "crosscheck_status": evidence.get("crosscheck_status"),
    }
    if any(value != "PASS" for value in required.values()):
        raise SystemExit(f"live official canonical gates are not all PASS: {required}")
    if dataset.crosscheck_status != "PASS":
        raise SystemExit("live official canonical dataset crosscheck is not PASS")
    if not dataset.draws:
        raise SystemExit("live official canonical dataset is empty")

    ledger = Path(args.ledger_dir).resolve()
    result = run_prospective_cycle(
        dataset.draws,
        dataset.canonical_hash,
        ledger_root=ledger,
        source_commit=args.source_commit,
    )
    result["live_source"] = {
        "latest_issue": dataset.draws[-1].issue,
        "draw_count": len(dataset.draws),
        "canonical_hash": dataset.canonical_hash,
        "source_mode": evidence.get("source_mode"),
        "crosscheck_count": dataset.crosscheck_count,
        **required,
    }
    report_path = ledger / "last_cycle.json"
    atomic_json(report_path, result)

    freeze = result["freeze"]
    status = result["status"]
    print("DLT_PROSPECTIVE_CYCLE=PASS")
    print(f"CYCLE_SOURCE_COMMIT={result['cycle_source_commit']}")
    print(f"INITIAL_SOURCE_COMMIT={result['cohort']['initial_source_commit']}")
    print(f"BEHAVIOR_HASH={result['behavior_hash']}")
    print(f"COHORT_ID={result['cohort']['cohort_id']}")
    print(f"PROTOCOL_HASH={result['cohort']['protocol_hash']}")
    print(f"MODEL_HASH={result['cohort']['model_hash']}")
    print(f"SELECTOR_HASH={result['cohort']['selector_hash']}")
    print(f"LATEST_OFFICIAL_ISSUE={dataset.draws[-1].issue}")
    print(f"TARGET_ISSUE={freeze['target_issue']}")
    print(f"FREEZE_HASH={freeze['prediction']['freeze_hash']}")
    print(f"FREEZE_RECORD_HASH={freeze['record_hash']}")
    print(f"VALID_REPLAYS={status['valid_replays']}")
    print(f"FREEZE_COUNT={status['freeze_count']}")
    print(f"QUALIFICATION={status['qualification']['decision']}")
    print("EDGE_STATE=NO_EDGE")
    print("DAN_STATE=NULL_DAN")
    print("PRODUCTION_RHO=0")
    print("PROMOTION_AUTHORIZED=false")
    print("PROSPECTIVE_FREEZE_JSON=" + json.dumps(freeze, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    print(f"LEDGER_DIR={ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
