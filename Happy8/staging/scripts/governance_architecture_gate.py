from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
REPO = PROJECT.parent

REQUIRED_LAYERS = {
    "Product/Governance", "Domain", "Source", "NetClient", "Storage",
    "Engine/Validation", "Evidence", "Service", "UI", "Acceptance/Release",
}
REQUIRED_FEATURES = {"预测下一期", "一键更新", "一键修复", "高级分析"}
REQUIRED_CHAIN = ["RAW", "VALIDATED", "CANONICAL", "FEATURE/KNOWLEDGE", "RESULT", "EVIDENCE"]


def main() -> int:
    path = PROJECT / "ARCHITECTURE_SCOPE.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    checks: dict[str, str] = {}
    checks["schema"] = "PASS" if value.get("schema") == "happy8-architecture-scope-v1" else "FAIL"
    checks["five_why"] = "PASS" if len(value.get("five_why") or []) == 5 else "FAIL"
    checks["risk_boundaries"] = "PASS" if len(value.get("risk_boundaries") or []) >= 6 else "FAIL"
    checks["data_chain"] = "PASS" if value.get("data_chain") == REQUIRED_CHAIN else "FAIL"

    layers = value.get("architecture") or []
    layer_names = {x.get("layer") for x in layers if isinstance(x, dict)}
    checks["architecture_layers"] = "PASS" if layer_names == REQUIRED_LAYERS else "FAIL"

    missing_paths = []
    for layer in layers:
        for raw in layer.get("implementation") or []:
            if "*" in raw:
                continue
            candidate = REPO / raw
            if not candidate.exists():
                missing_paths.append(raw)
    checks["implementation_paths"] = "PASS" if not missing_paths else "FAIL"

    functions = value.get("functions") or []
    features = {x.get("feature") for x in functions if isinstance(x, dict)}
    services = {x.get("service") for x in functions if isinstance(x, dict)}
    checks["four_features"] = "PASS" if features == REQUIRED_FEATURES else "FAIL"
    checks["service_boundary"] = "PASS" if services == {
        "Happy8Service.predict_next",
        "Happy8Service.software_update",
        "Happy8Service.repair",
        "Happy8Service.advanced_analysis",
    } else "FAIL"
    checks["acceptance_baselines"] = "PASS" if (
        (PROJECT / "ENGINEERING_ACCEPTANCE_BASELINE.json").exists()
        and (PROJECT / "BUSINESS_ACCEPTANCE_BASELINE.json").exists()
    ) else "FAIL"
    status = "PASS" if all(x == "PASS" for x in checks.values()) else "FAIL"
    report = {
        "schema": "happy8-governance-architecture-gate-v1",
        "status": status,
        "checks": checks,
        "missing_paths": missing_paths,
    }
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
