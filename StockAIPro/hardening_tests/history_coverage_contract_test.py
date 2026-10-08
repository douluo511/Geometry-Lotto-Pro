from __future__ import annotations
import copy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(VERSION))
from stock_ai import data_source

CFG = json.loads((VERSION / "config.default.json").read_text(encoding="utf-8"))


def canonical(code="000001", rows=240):
    prices = 10.0 + np.arange(rows) * 0.01
    return pd.DataFrame({
        "date": pd.bdate_range("2024-01-02", periods=rows),
        "code": [code] * rows, "open": prices, "close": prices,
        "high": prices + 0.1, "low": prices - 0.1,
        "volume": [1000.0] * rows, "amount": [10000.0] * rows,
        "turnover_rate": [0.01] * rows, "schema_version": [3] * rows,
        "provider": ["eastmoney"] * rows, "adjust_mode": ["hfq"] * rows,
    })


def reject(folder, name, frame):
    path = folder / (name + ".csv")
    frame.to_csv(path, index=False)
    with patch.object(data_source, "load_config", return_value=CFG):
        assert not data_source._history_cache_entry_valid(path, "000001"), name


def capped_coverage(folder, daily=False):
    history = folder / "data" / "history"
    history.mkdir(parents=True)
    canonical().to_csv(history / "000001.csv", index=False)
    master = pd.DataFrame({"code": ["000001", "000002"], "status": ["current", "current"]})
    cfg = copy.deepcopy(CFG)
    cfg["universe"]["bootstrap_max_symbols"] = 1
    cfg["universe"]["qualification_bootstrap_max_seconds"] = 60
    def unavailable(codes, *args, **kwargs):
        return [(str(code), None, "fixture unavailable") for code in codes]
    with patch.object(data_source, "ROOT", folder), \
            patch.object(data_source, "load_config", return_value=cfg), \
            patch.object(data_source, "_run_history_batch", side_effect=unavailable):
        if daily:
            status = data_source.bootstrap_research_pool(master, cfg)
        else:
            status = data_source.qualify_research_pool_coverage(master, cfg)
    assert status["target_symbols"] == 2, status
    assert status["covered_symbols"] == 1 and status["coverage"] == 0.5, status
    if not daily:
        assert status["qualification_status"] == "NOT VERIFIED", status


def daily_invalid_cache(folder):
    history = folder / "data" / "history"
    history.mkdir(parents=True)
    canonical(rows=40).to_csv(history / "000001.csv", index=False)
    master = pd.DataFrame({"code": ["000001"], "status": ["current"]})
    with patch.object(data_source, "ROOT", folder), \
            patch.object(data_source, "load_config", return_value=CFG), \
            patch.object(data_source, "_run_history_batch", return_value=[]):
        status = data_source.bootstrap_research_pool(master, CFG)
    assert status["covered_symbols"] == 0 and status["coverage"] == 0, status


def independent_current_coverage(folder):
    history = folder / "data" / "history"
    history.mkdir(parents=True)
    codes = [str(i).zfill(6) for i in range(1, 21)]
    # Overall 18/20=90%, delisted 10/10=100%, current 8/10=80%.
    for code in codes[:8] + codes[10:]:
        canonical(code).to_csv(history / (code + ".csv"), index=False)
    master = pd.DataFrame({"code": codes, "status": ["current"] * 10 + ["delisted"] * 10})
    def unavailable(selected, *args, **kwargs):
        return [(code, None, "fixture unavailable") for code in selected]
    with patch.object(data_source, "ROOT", folder), \
            patch.object(data_source, "_run_history_batch", side_effect=unavailable):
        status = data_source.qualify_research_pool_coverage(master, CFG)
    assert status["coverage"] == 0.90 and status["current_coverage"] == 0.80, status
    assert status["qualification_status"] == "NOT VERIFIED", status


def main():
    checks = []
    def run(name, action):
        try:
            action()
            checks.append({"name": name, "status": "PASS"})
        except Exception as exc:
            checks.append({"name": name, "status": "FAIL", "error": str(exc)})
    with tempfile.TemporaryDirectory() as td:
        folder = Path(td)
        good = folder / "valid.csv"
        canonical().to_csv(good, index=False)
        def positive():
            with patch.object(data_source, "load_config", return_value=CFG):
                assert data_source._history_cache_entry_valid(good, "000001")
        run("valid_canonical_240_rows", positive)
        run("short_40_rows_below_frozen_model_240", lambda: reject(folder, "short", canonical(rows=40)))
        for column in ("code", "schema_version", "provider", "adjust_mode", "volume", "amount", "turnover_rate"):
            run("missing_" + column, lambda c=column: reject(folder, "missing_" + c, canonical().drop(columns=[c])))
        for name, column, value in (
            ("positive_infinity", "close", float("inf")),
            ("negative_quantity", "volume", -1),
            ("invalid_ohlc_range", "high", 1),
            ("wrong_symbol", "code", "000002"),
            ("wrong_adjustment", "adjust_mode", "qfq"),
            ("unknown_provider", "provider", "fixture"),
            ("future_schema", "schema_version", 4),
        ):
            def action(n=name, c=column, v=value):
                frame = canonical()
                frame.loc[0, c] = v
                reject(folder, n, frame)
            run(name, action)
        frame = canonical().iloc[::-1]
        run("nonchronological_dates", lambda: reject(folder, "reversed", frame))
        invalid_dates = canonical()
        invalid_dates["date"] = ["invalid-" + str(i).zfill(6) for i in range(240)]
        run("invalid_date_strings_rejected", lambda: reject(folder, "invalid_dates", invalid_dates))
        intraday_dates = canonical()
        intraday_dates["date"] = pd.date_range("2024-01-02 00:01:00", periods=240, freq="min")
        run("intraday_rows_cannot_count_as_daily_sessions", lambda: reject(folder, "intraday_dates", intraday_dates))
        future_dates = canonical()
        future_dates["date"] = pd.bdate_range(pd.Timestamp.today().normalize() + pd.Timedelta(days=30), periods=240)
        run("future_dates_cannot_count_as_research_history", lambda: reject(folder, "future_dates", future_dates))
        run("qualification_cap_preserves_full_master", lambda: capped_coverage(folder / "qualified"))
        run("daily_cap_preserves_full_master", lambda: capped_coverage(folder / "daily", daily=True))
        run("daily_cache_counts_valid_payloads_only", lambda: daily_invalid_cache(folder / "invalid"))
        run("current_population_keeps_its_own_ninety_percent_gate", lambda: independent_current_coverage(folder / "current-subpopulation"))
    report = {"schema": "stock-ai-history-coverage-contract-v1",
              "source_sha": __import__("os").environ.get("STOCK_SOURCE_SHA"),
              "status": "PASS" if all(x["status"] == "PASS" for x in checks) else "FAIL",
              "minimum_history_rows": CFG["model"]["min_history_days"],
              "scope": "synthetic negative controls; does not certify real network, EXE, GUI or Final",
              "checks": checks}
    (ROOT / "history_coverage_contract_evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
