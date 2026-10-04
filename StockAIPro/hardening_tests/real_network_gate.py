from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "_real_network_gate_data"
os.environ["STOCK_AI_DATA_ROOT"] = str(DATA_ROOT)
VERSION = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
sys.path.insert(0, str(VERSION))

from stock_ai.config import ensure_dirs, load_config
from stock_ai.data_quality import inspect_histories
from stock_ai.data_source import (
    fetch_expected_trade_date,
    fetch_market_snapshot,
    update_symbol_history,
)
from stock_ai.features import build_dataset


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out = ROOT / "real_network_evidence.json"
    report = {
        "schema": "stock-ai-source-real-network-v1",
        "status": "FAIL",
        "scope": "real production acquisition -> validation -> canonical storage -> feature/data-quality business consumption",
        "final_product_real_network": "NOT VERIFIED",
    }
    try:
        ensure_dirs()
        cfg = load_config()
        cfg["universe"]["live_top_n"] = 5
        cfg["universe"]["min_turnover_cny"] = 0
        cfg["network"]["retry_attempts"] = 2
        cfg["network"]["retry_backoff_seconds"] = 0.25
        cfg["network"]["retry_jitter_seconds"] = 0.1

        snapshot = fetch_market_snapshot(cfg)
        required = {"code", "name", "price", "amount", "spot_provider"}
        missing = sorted(required - set(snapshot.columns))
        if missing:
            raise RuntimeError(f"validated market snapshot missing fields: {missing}")
        if snapshot.empty:
            raise RuntimeError("validated market snapshot is empty")
        snapshot = snapshot.head(5).copy()
        canonical_snapshot = DATA_ROOT / "cache" / "real_network_snapshot.csv"
        canonical_snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.to_csv(canonical_snapshot, index=False, encoding="utf-8-sig")

        code = str(snapshot.iloc[0]["code"])
        hist = update_symbol_history(code, cfg)
        if hist.empty or len(hist) < 60:
            raise RuntimeError(f"history insufficient for {code}: rows={len(hist)}")
        hist_file = DATA_ROOT / "data" / "history" / f"{code}.csv"
        if not hist_file.is_file():
            raise RuntimeError("canonical history file was not committed")

        expected_trade_date = fetch_expected_trade_date()
        quality = inspect_histories({code: hist})
        if float(quality.get("good_ratio", 0)) <= 0:
            raise RuntimeError(f"data quality failed: {quality}")

        features = build_dataset(
            {code: hist},
            int(cfg["model"]["horizon_days"]),
            min(60, int(cfg["model"]["min_history_days"])),
        )
        if features.empty:
            raise RuntimeError("feature stage produced no rows from real canonical history")
        feature_file = DATA_ROOT / "cache" / "real_network_features.csv"
        features.tail(200).to_csv(feature_file, index=False, encoding="utf-8-sig")

        receipts_path = DATA_ROOT / "evidence" / "netclient_raw.jsonl"
        if not receipts_path.is_file():
            raise RuntimeError("NetClient RAW receipt file missing")
        calls = [json.loads(x) for x in receipts_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        passed_calls = [x for x in calls if x.get("status") == "PASS"]
        raw = [r for call in passed_calls for r in call.get("raw_responses", [])]
        if not raw:
            raise RuntimeError("no real RAW HTTP receipt was captured")
        for receipt in raw:
            if receipt.get("request", {}).get("scheme") != "https":
                raise RuntimeError("non-HTTPS RAW receipt present")
            if not str(receipt.get("content_type", "")).strip():
                raise RuntimeError("RAW receipt missing Content-Type")
            digest = str(receipt.get("payload_sha256", ""))
            if len(digest) != 64:
                raise RuntimeError("RAW receipt missing payload SHA-256")
            status = int(receipt.get("status_code", 0))
            if status < 200 or status >= 300:
                raise RuntimeError(f"non-success RAW response retained in accepted path: {status}")

        report.update({
            "status": "PASS",
            "selected_code": code,
            "spot_provider": str(snapshot.iloc[0]["spot_provider"]),
            "snapshot_rows": int(len(snapshot)),
            "history_rows": int(len(hist)),
            "feature_rows": int(len(features)),
            "expected_trade_date": expected_trade_date,
            "canonical_snapshot_sha256": sha256(canonical_snapshot),
            "canonical_history_sha256": sha256(hist_file),
            "feature_sha256": sha256(feature_file),
            "netclient_call_count": len(calls),
            "netclient_pass_call_count": len(passed_calls),
            "raw_http_receipt_count": len(raw),
            "data_quality": quality,
            "pipeline_stage_status": {
                "RAW": "PASS",
                "VALIDATED": "PASS",
                "CANONICAL": "PASS",
                "FEATURE": "PASS",
                "RESULT": "PASS_SOURCE_INTEGRATION_ONLY",
                "EVIDENCE": "PASS",
            },
            "boundary": "This does not validate the full production prediction/model/OOS business chain.",
        })
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
