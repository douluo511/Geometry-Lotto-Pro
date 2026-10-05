from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ARCHITECTURE = [
    "Product/Governance", "Domain", "Source", "NetClient", "Storage", "Engine",
    "Validation", "Evidence", "Service", "UI", "Acceptance/Release",
]
EXPECTED_LABELS = {"资金变化", "一键更新", "一键修复", "高级分析"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classes_and_methods(path: Path) -> tuple[set[str], dict[str, set[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes: set[str] = set()
    methods: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.add(node.name)
            methods[node.name] = {
                item.name for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return classes, methods


def string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def main() -> int:
    source_sha = os.environ["SOURCE_SHA"]
    spec_path = ROOT / "GOVERNANCE_SPEC.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    assert spec.get("schema_version") == 1
    assert spec.get("product") == "RealMoneyFinance"
    assert isinstance(spec.get("purpose"), str) and len(spec["purpose"]) >= 80
    assert len(spec.get("requirements", [])) >= 7
    assert len(spec.get("five_why", [])) == 5
    assert all(isinstance(x, str) and x.startswith("Why ") for x in spec["five_why"])
    assert len(spec.get("risk_boundaries", [])) >= 5
    assert spec.get("architecture") == EXPECTED_ARCHITECTURE

    verified_files: dict[str, str] = {}
    for layer in EXPECTED_ARCHITECTURE:
        paths = spec.get("architecture_files", {}).get(layer)
        assert isinstance(paths, list) and paths, f"missing files for architecture layer {layer}"
        for rel in paths:
            path = ROOT / rel
            assert path.is_file(), f"missing architecture file: {rel}"
            verified_files[rel] = sha256(path)

    domain_classes, _ = classes_and_methods(ROOT / "app/domain.py")
    service_classes, service_methods = classes_and_methods(ROOT / "app/service.py")
    net_classes, _ = classes_and_methods(ROOT / "app/netclient.py")
    storage_classes, _ = classes_and_methods(ROOT / "app/storage.py")
    ui_classes, ui_methods = classes_and_methods(ROOT / "app/ui.py")

    model = spec["domain_model"]
    assert set(model["entities"]).issubset(domain_classes)
    assert set(model["services"]).issubset(service_classes)
    assert "NetClient" in net_classes and "Storage" in storage_classes
    assert "FinanceDesktop" in ui_classes

    labels = string_constants(ROOT / "app/ui.py")
    assert EXPECTED_LABELS.issubset(labels)
    inventory = spec.get("function_inventory", {})
    assert set(inventory) == EXPECTED_LABELS

    for label, contract in inventory.items():
        services = contract.get("service_functions", [])
        assert services, f"{label} has no service function"
        for qualified in services:
            class_name, method = qualified.split(".", 1)
            assert class_name == "FinanceService"
            assert method in service_methods["FinanceService"], f"missing service method {qualified}"
        assert contract.get("input") and contract.get("output") and contract.get("failure")

    assert "_core" in ui_methods["FinanceDesktop"]
    assert "_advanced" in ui_methods["FinanceDesktop"]

    evidence = {
        "status": "PASS",
        "source_sha": source_sha,
        "spec_sha256": sha256(spec_path),
        "verified_files": verified_files,
        "gates": {
            "requirements_purpose_model": "PASS",
            "five_why": "PASS",
            "domain_model": "PASS",
            "architecture": "PASS",
            "function_inventory": "PASS",
        },
        "rule": "This gate verifies frozen governance structure and code-to-contract linkage only; functional behavior remains governed by separate runtime gates.",
    }
    Path("governance_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
