from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = ROOT / "StockAIPro" / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
OUT = Path("stock_historical_pit_consumption_contract.json")

CONFIG = PRODUCT / "config.default.json"
BACKTEST = PRODUCT / "stock_ai" / "backtest.py"
FEATURES = PRODUCT / "stock_ai" / "features.py"
AUDIT = PRODUCT / "stock_ai" / "audit.py"
HISTORICAL_PIT = PRODUCT / "stock_ai" / "historical_pit.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function_source(path: Path, name: str) -> tuple[str, ast.FunctionDef]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            if segment is None:
                raise RuntimeError(f"cannot recover source segment for {name}")
            return segment, node
    raise RuntimeError(f"function not found: {path}:{name}")


def call_names(node: ast.AST) -> list[str]:
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            fn = n.func
            if isinstance(fn, ast.Name):
                out.append(fn.id)
            elif isinstance(fn, ast.Attribute):
                parts = []
                cur = fn
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                out.append(".".join(reversed(parts)))
    return sorted(set(out))


def string_constants(node: ast.AST) -> list[str]:
    vals = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            vals.append(n.value)
    return sorted(set(vals))


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    exclude_st = bool((cfg.get("universe") or {}).get("exclude_st"))

    pool_src, pool_node = function_source(BACKTEST, "_historical_candidate_pool")
    build_src, build_node = function_source(FEATURES, "build_dataset")
    audit_src, audit_node = function_source(AUDIT, "run_audit")

    pool_calls = call_names(pool_node)
    pool_strings = string_constants(pool_node)
    build_strings = string_constants(build_node)
    audit_calls = call_names(audit_node)

    product_py = sorted((PRODUCT / "stock_ai").glob("*.py"))
    evaluator_call_sites = []
    for path in product_py:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "evaluate_historical_st_pit(" in line and not line.lstrip().startswith("def evaluate_historical_st_pit"):
                evaluator_call_sites.append({
                    "path": str(path.relative_to(ROOT)),
                    "line": lineno,
                    "text": line.strip(),
                })

    pool_consumes_pit = any(
        token in pool_src
        for token in (
            "historical_pit",
            "historical_st_pit",
            "suspended",
            "exclude_st",
            "st_identity",
        )
    )
    dataset_carries_pit = any(
        value in {"st", "is_st", "st_identity", "suspended", "suspension_state"}
        for value in build_strings
    )
    audit_consumes_pit = "evaluate_historical_st_pit" in audit_calls
    only_audit_calls_evaluator = (
        len(evaluator_call_sites) == 1
        and evaluator_call_sites[0]["path"].endswith("/stock_ai/audit.py")
    )

    gap_confirmed = (
        exclude_st
        and audit_consumes_pit
        and only_audit_calls_evaluator
        and not pool_consumes_pit
        and not dataset_carries_pit
    )

    report = {
        "schema": "stock-historical-pit-consumption-contract-v1",
        "product_authority": "7f270b9ab58e11fd8129053a65e000c90ff9d8c1",
        "files": {
            "config": {"path": str(CONFIG.relative_to(ROOT)), "sha256": sha256(CONFIG)},
            "backtest": {"path": str(BACKTEST.relative_to(ROOT)), "sha256": sha256(BACKTEST)},
            "features": {"path": str(FEATURES.relative_to(ROOT)), "sha256": sha256(FEATURES)},
            "audit": {"path": str(AUDIT.relative_to(ROOT)), "sha256": sha256(AUDIT)},
            "historical_pit": {"path": str(HISTORICAL_PIT.relative_to(ROOT)), "sha256": sha256(HISTORICAL_PIT)},
        },
        "observations": {
            "production_exclude_st": exclude_st,
            "historical_candidate_pool_calls": pool_calls,
            "historical_candidate_pool_string_constants": pool_strings,
            "historical_candidate_pool_consumes_pit": pool_consumes_pit,
            "build_dataset_string_constants": build_strings,
            "dataset_carries_historical_st_or_suspension_state": dataset_carries_pit,
            "audit_calls": audit_calls,
            "audit_consumes_historical_pit_evaluator": audit_consumes_pit,
            "historical_pit_evaluator_call_sites": evaluator_call_sites,
            "only_audit_calls_historical_pit_evaluator": only_audit_calls_evaluator,
        },
        "adjudication": {
            "production_exclude_st_policy": "PASS" if exclude_st else "NOT VERIFIED",
            "historical_pit_evidence_gate_present": "PASS" if audit_consumes_pit else "NOT VERIFIED",
            "historical_candidate_pool_consumes_pit": "PASS" if pool_consumes_pit else "FAIL",
            "historical_dataset_carries_pit_state": "PASS" if dataset_carries_pit else "FAIL",
            "production_backtest_st_policy_parity": "NOT VERIFIED" if gap_confirmed else "UNKNOWN",
            "behavior_gap_confirmed": gap_confirmed,
            "advanced_business": "NOT VERIFIED",
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "This is a source-level behavior contract against the exact Stock product bytes. "
            "It does not claim that historical ST/PIT evidence is complete. It only determines "
            "whether the backtest path can consume such evidence when it becomes available."
        ),
    }

    OUT.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "observations": report["observations"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=True, sort_keys=True))

    # Diagnostic execution succeeds only when the suspected gap is reproduced
    # exactly; a changed product that closes the gap must invalidate this evidence.
    return 0 if gap_confirmed else 2


if __name__ == "__main__":
    raise SystemExit(main())
