from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from glp.domain import Draw
from glp.research_v2_audit import audit_feature_utility
from glp.util import sha256_json


def main() -> None:
    seed_path = ROOT / "src" / "resources" / "official_seed.json"
    value = json.loads(seed_path.read_text(encoding="utf-8"))
    draws = [Draw.from_dict(item) for item in value["draws"]]
    actual_hash = sha256_json([draw.to_dict() for draw in draws])
    expected_hash = str(value.get("canonical_hash", ""))
    if actual_hash != expected_hash:
        raise SystemExit("official_seed canonical hash mismatch")

    result = audit_feature_utility(draws, eval_points=360)
    result["canonical_hash"] = actual_hash

    out_dir = ROOT / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "research_v2_feature_audit.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("DLT_V2_FEATURE_AUDIT=PASS")
    print("PREDICTIVE_EDGE_CLAIM=NOT_VERIFIED")
    print("PRODUCTION_RHO=0")
    for name, row in result["combined"].items():
        print(f"FEATURE {name}: front={row['front']} back={row['back']} overall={row['overall']}")
    print(f"EVIDENCE={out_path}")


if __name__ == "__main__":
    main()
