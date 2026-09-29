from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from service import create_service

ROOT = Path(__file__).resolve().parent

def main() -> int:
    with tempfile.TemporaryDirectory(prefix="eri-business-") as td:
        svc = create_service(Path(td))
        known = svc.analyze("predict")
        unknown = svc.analyze("zzqvunknown")
        today = svc.today_roots(3)
        checks = {
            "known_word_has_high_confidence": float(known.get("confidence", 0)) >= 0.9,
            "known_word_has_segmentation": bool(known.get("segmentation")),
            "unknown_word_is_not_overclaimed": float(unknown.get("confidence", 1)) <= 0.45,
            "unknown_word_requests_context": "需要结合词典语境确认" in str(unknown.get("meaning", "")),
            "counterexample_reverses_confidence": float(known.get("confidence", 0)) > float(unknown.get("confidence", 1)),
            "daily_learning_has_three_items": len(today) == 3,
            "daily_items_have_chunks": all(len(x.get("chunks") or []) >= 3 for x in today),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        report = {
            "schema": "english-root-business-validation-v1",
            "status": status,
            "github_sha": os.environ.get("GITHUB_SHA"),
            "business_validation": status,
            "counterexample_validation": status if checks["unknown_word_is_not_overclaimed"] else "FAIL",
            "reversal_validation": status if checks["counterexample_reverses_confidence"] else "FAIL",
            "checks": checks,
        }
    (ROOT / "business_validation_gate.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if status == "PASS" else 2

if __name__ == "__main__":
    raise SystemExit(main())
