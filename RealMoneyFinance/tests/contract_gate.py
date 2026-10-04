from __future__ import annotations

from pathlib import Path
import ast
import json
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace

from app.domain import DailyBar
from app.engine import analyze_observable_activity, reverse_validation
from app.source_eastmoney import fetch_daily_bars
from app.source_tencent import fetch_daily_bars_tencent
from app.storage import Storage


class FakeClient:
    def get_json(self, url, params):
        meta = SimpleNamespace(
            status=200,
            payload_sha256="a" * 64,
            retrieved_at_unix=1.0,
            url=url,
        )
        rows = []
        start = date(2026, 7, 1)
        for i in range(40):
            day = (start + timedelta(days=i)).isoformat()
            rows.append(f"{day},10,10.1,10.2,9.9,{1000+i},{100000+i*1000},1,1.0,0.1,{2.0+i/100}")
        return {"data": {"klines": rows}}, meta



class FakeTencentClient:
    def get_json(self, url, params, headers=None, allow_mislabeled_json=False):
        meta = SimpleNamespace(
            status=200,
            payload_sha256="b" * 64,
            retrieved_at_unix=2.0,
            url=url,
            content_type="text/html; charset=utf-8",
            content_type_policy="provider-mislabeled-strict-json-body",
        )
        rows = []
        start = date(2026, 7, 1)
        for i in range(40):
            day = (start + timedelta(days=i)).isoformat()
            rows.append([day, "10", "10.1", "10.2", "9.9", str(1000+i), {"meta": i}])
        return {"data": {"sh600000": {"qfqday": rows}}}, meta


def _class_methods(path: str, class_name: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return set()


def _module_classes(path: str) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def governance_contract() -> dict:
    governance = json.loads(Path("GOVERNANCE_EVIDENCE.json").read_text(encoding="utf-8"))
    assert governance.get("schema_version") == 1 and governance.get("project") == "RealMoneyFinance"

    purpose = governance.get("requirements_purpose_model", {})
    entries = purpose.get("desktop_entries", [])
    assert entries == ["资金变化", "一键更新", "一键修复", "高级分析"]
    assert purpose.get("business_purpose") and purpose.get("requirements")
    assert purpose.get("success_criteria") and purpose.get("failure_criteria")
    ui_text = Path("app/ui.py").read_text(encoding="utf-8")
    assert all(label in ui_text for label in entries)

    five_why = governance.get("five_why", [])
    assert len(five_why) == 5
    assert [item.get("why") for item in five_why] == [1, 2, 3, 4, 5]
    assert all(item.get("question") and item.get("answer") for item in five_why)

    domain = governance.get("domain_model", {})
    domain_classes = _module_classes("app/domain.py")
    assert set(domain.get("classes", [])) <= domain_classes
    assert len(domain.get("invariants", [])) >= 3

    architecture = governance.get("architecture", {})
    expected_layers = ["Product", "Governance", "Domain", "Source", "NetClient", "Storage",
                       "Engine", "Validation", "Evidence", "Service", "UI", "Acceptance/Release"]
    assert architecture.get("layers") == expected_layers
    mapping = architecture.get("mapping", {})
    assert set(mapping) == set(expected_layers)
    for layer in expected_layers:
        assert mapping[layer] and all(Path(path).is_file() for path in mapping[layer]), layer

    inventory = governance.get("function_inventory", [])
    required_features = {"核心功能/资金变化", "核心真实数据刷新", "一键更新", "一键修复", "高级分析"}
    assert {item.get("feature") for item in inventory} == required_features
    for item in inventory:
        methods = _class_methods(item["module"], item["class"])
        assert item["method"] in methods, item
        assert item.get("input") and item.get("output") and item.get("exception_behavior") and item.get("acceptance")

    return {
        "requirements_purpose_model": "PASS",
        "five_why": "PASS",
        "domain_model": "PASS",
        "architecture": "PASS",
        "function_inventory": "PASS",
        "governance_evidence": "PASS",
    }


def main() -> int:
    governance = governance_contract()
    bars, meta = fetch_daily_bars(FakeClient(), "600000", 40)
    assert len(bars) == 40
    assert meta["provider"] == "eastmoney_public_l1"

    tencent_bars, tmeta = fetch_daily_bars_tencent(FakeTencentClient(), "600000", 40)
    assert len(tencent_bars) == 40
    assert all(x.amount == 0.0 for x in tencent_bars)
    assert all(x.raw_sha256 == "b" * 64 for x in tencent_bars)
    assert tmeta["provider"] == "tencent_public_kline"

    obs = analyze_observable_activity(bars)
    assert obs.true_capital_identity == "UNAVAILABLE_FROM_PUBLIC_LEVEL1"
    rv = reverse_validation(obs)
    assert rv["production_identity_claim_allowed"] is False

    with tempfile.TemporaryDirectory() as td:
        s = Storage(Path(td))
        assert s.integrity_check() == "ok"
        assert s.upsert_bars(bars) == 40
        loaded = s.load_bars("600000")
        assert len(loaded) == 40
        s.save_observation(obs)

    evidence = {
        "status": "PASS",
        "contract": "public L1 stays non-identity-grade",
        "storage": "PASS",
        "engine_boundary": "PASS",
        **governance,
    }
    Path("contract_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
