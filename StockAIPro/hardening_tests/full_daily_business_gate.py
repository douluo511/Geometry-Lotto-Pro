from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "staging" / "Stock_AI_Pro" / "versions" / "4.3.0"
DATA_ROOT = ROOT / "_business_gate_data"
os.environ["STOCK_AI_DATA_ROOT"] = str(DATA_ROOT)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    evidence_path = ROOT / "business_daily_evidence.json"
    report = {
        "schema": "stock-ai-full-daily-business-gate-v1",
        "status": "FAIL",
        "scope": "default production configuration daily chain",
        "desktop_exe": "NOT VERIFIED",
        "physical_gui": "NOT VERIFIED",
        "same_hash": "NOT VERIFIED",
        "final_gate": "FAIL",
    }
    try:
        if DATA_ROOT.exists():
            import shutil
            shutil.rmtree(DATA_ROOT)
        DATA_ROOT.mkdir(parents=True)

        doctor = subprocess.run(
            [sys.executable, str(VERSION / "doctor.py")],
            cwd=VERSION, env=os.environ.copy(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
        )
        report["doctor_exit_code"] = doctor.returncode
        report["doctor_output_sha256"] = hashlib.sha256(doctor.stdout.encode("utf-8")).hexdigest()
        if doctor.returncode != 0:
            raise RuntimeError("Doctor failed")

        daily = subprocess.run(
            [sys.executable, str(VERSION / "run_daily.py")],
            cwd=VERSION, env=os.environ.copy(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3300,
        )
        (ROOT / "business_daily.log").write_text(daily.stdout, encoding="utf-8")
        report["daily_exit_code"] = daily.returncode
        report["daily_log_sha256"] = hashlib.sha256(daily.stdout.encode("utf-8")).hexdigest()
        if daily.returncode != 0:
            raise RuntimeError(f"run_daily failed exit={daily.returncode}")

        last_run = load(DATA_ROOT / "state" / "last_run.json")
        if last_run.get("status") != "PASS":
            raise RuntimeError(f"last_run is not PASS: {last_run}")

        latest = DATA_ROOT / "predictions" / "latest"
        required = [
            "manifest.json", "predictions.csv", "summary.json", "model_metrics.json",
            "data_quality.json", "valuation_status.json", "cost_assumptions.json",
            "decision.json", "portfolio_balanced.csv", "portfolio_offense.csv",
            "portfolio_defense.csv",
        ]
        missing = [x for x in required if not (latest / x).is_file()]
        if missing:
            raise RuntimeError(f"frozen prediction missing files: {missing}")

        manifest = load(latest / "manifest.json")
        for name, expected in (manifest.get("files") or {}).items():
            p = latest / name
            if not p.is_file() or sha256(p) != expected:
                raise RuntimeError(f"prediction freeze hash mismatch: {name}")

        summary = load(latest / "summary.json")
        metrics = load(latest / "model_metrics.json")
        quality = load(latest / "data_quality.json")
        valuation = load(latest / "valuation_status.json")
        decision = load(latest / "decision.json")
        chain = load(DATA_ROOT / "state" / "prediction_chain.json")
        maintenance = load(DATA_ROOT / "state" / "maintenance.json")
        update = load(DATA_ROOT / "cache" / "last_update_status.json")

        if int(summary.get("live_universe_size", 0)) != 300:
            raise RuntimeError(f"default live universe was not preserved: {summary.get('live_universe_size')}")
        if float(update.get("ok", 0)) / max(1, float(update.get("total", 0))) < 0.7:
            raise RuntimeError(f"live update ratio below frozen safety threshold: {update}")
        if int(summary.get("validation_embargo_days", -1)) != int(summary.get("horizon_days", -2)):
            raise RuntimeError("validation embargo != prediction horizon")
        model_names = list(summary.get("model_names") or [])
        required_models = {"ridge", "hgb", "extra_trees"}
        if not required_models.issubset(set(model_names)):
            raise RuntimeError(f"production ensemble missing model(s): {model_names}")
        if decision.get("decision") not in {"TRADE", "WATCH", "NO_TRADE"}:
            raise RuntimeError(f"invalid decision state: {decision}")
        if decision.get("model_trust") not in {"HIGH", "MEDIUM", "LOW"}:
            raise RuntimeError(f"invalid model trust: {decision}")
        if not isinstance(metrics.get("rank_ic"), (int, float)) and metrics.get("rank_ic") is not None:
            raise RuntimeError("rank_ic type invalid")
        if float(quality.get("good_ratio", 0)) < 0.7:
            raise RuntimeError(f"live data quality below frozen threshold: {quality}")
        if not chain.get("head_manifest_sha256") or int(chain.get("sequence", 0)) < 1:
            raise RuntimeError("prediction hash chain not frozen")

        maintenance_result = maintenance.get("result") or {}
        if maintenance_result.get("backtest") != "PASS":
            raise RuntimeError(f"automatic backtest not PASS: {maintenance_result}")
        if str(maintenance_result.get("audit", "")).startswith("FAIL") or not maintenance_result.get("audit"):
            raise RuntimeError(f"automatic audit not complete: {maintenance_result}")

        report.update({
            "status": "PASS",
            "asof": summary.get("asof"),
            "live_universe_size": summary.get("live_universe_size"),
            "research_master_size": summary.get("research_master_size"),
            "research_training_symbols": summary.get("research_training_symbols"),
            "validation_rows": summary.get("validation_rows"),
            "production_train_rows": summary.get("production_train_rows"),
            "model_names": model_names,
            "rank_ic": metrics.get("rank_ic"),
            "decision": decision,
            "data_quality_good_ratio": quality.get("good_ratio"),
            "valuation_history_coverage": summary.get("valuation_history_coverage"),
            "history_provider_counts": summary.get("history_provider_counts"),
            "spot_provider": summary.get("spot_provider"),
            "expected_trade_date": summary.get("expected_trade_date"),
            "live_update": update,
            "maintenance": maintenance,
            "prediction_manifest_sha256": sha256(latest / "manifest.json"),
            "prediction_chain": chain,
            "evidence_boundary": "business/runtime source+engine chain PASS; desktop executable and release chain remain separate gates",
        })
    except subprocess.TimeoutExpired as exc:
        report["error"] = f"TimeoutExpired: command exceeded frozen gate limit: {exc.cmd}"
        report["timeout_seconds"] = exc.timeout
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()

    evidence_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
