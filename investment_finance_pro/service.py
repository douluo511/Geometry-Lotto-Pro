from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import os

import legacy_backend as legacy
from contracts import validate_snapshot
from engine import InvestmentEngine
from evidence import EvidenceLedger
from net_client import NetClient
from storage import SnapshotStorage

APP_NAME = legacy.APP_NAME
VERSION = "0.2.0"

class InvestmentService:
    def __init__(self, net=None, storage=None, engine=None, evidence=None):
        self.net = net or NetClient()
        self.storage = storage or SnapshotStorage()
        self.engine = engine or InvestmentEngine()
        evidence_path = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "InvestmentFinancePro" / "evidence.jsonl"
        self.evidence = evidence or EvidenceLedger(evidence_path)

    def opportunities(self):
        return self.storage.read()

    def update_all(self):
        started = datetime.now(timezone.utc)
        metrics = {}
        providers = []
        receipts = []
        for symbol in legacy.WATCHLIST:
            try:
                rows, provider, receipt = self.net.fetch_market_history(symbol)
                metrics[symbol] = self.engine.compute_metrics(rows)
                providers.append({"source": provider + ":" + symbol, "ok": True, "detail": f"{len(rows)} rows"})
                receipts.append(receipt)
            except Exception as exc:
                providers.append({"source": "MARKET:" + symbol, "ok": False, "detail": str(exc)})

        macro = {}
        try:
            item, receipt = self.net.fetch_us_treasury_10y()
            macro["US_10Y_TREASURY"] = item
            providers.append({"source": "US_TREASURY:10Y", "ok": True, "detail": "latest official daily yield loaded"})
            receipts.append(receipt)
        except Exception as exc:
            providers.append({"source": "US_TREASURY:10Y", "ok": False, "detail": str(exc)})

        ok_count = sum(1 for p in providers if p["ok"])
        if providers and ok_count == len(providers):
            state = "PASS"
        elif metrics:
            state = "PARTIAL"
        else:
            state = "FAILED"

        payload = {
            "app": APP_NAME,
            "version": VERSION,
            "research_only": True,
            "model_status": "UNVALIDATED",
            "update_state": state,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
            "providers": providers,
            "network_receipts": receipts,
            "macro": macro,
            "metrics": metrics,
            "ranking": self.engine.rank(metrics),
        }
        self.storage.write(payload)
        self.evidence.record("NETWORK", state, providers=providers, receipts=receipts)
        return payload

    def repair(self):
        result = self.storage.repair()
        self.evidence.record("STORAGE", result["status"], result=result)
        return result

    def advanced_analysis(self):
        return {
            "version": VERSION,
            "research_only": True,
            "model_status": "UNVALIDATED",
            "validation_rule": "No strategy becomes VALIDATED_EDGE without independent OOS/holdout/baseline/cost/leakage/ablation evidence.",
            "snapshot": self.storage.read(),
        }

    def self_test(self):
        report = self.engine.deterministic_self_test()
        status = "PASS" if report.get("status") == "PASS" else "FAIL"
        return {"status": status, "version": VERSION, "engine": report}

    def network_smoke(self):
        checks = []
        try:
            rows, provider, receipt = self.net.fetch_market_history("SPY")
            metric = self.engine.compute_metrics(rows)
            checks.append({"source": provider + ":SPY", "status": "PASS", "last_date": metric["date"], "receipt": receipt})
        except Exception as exc:
            checks.append({"source": "MARKET:SPY", "status": "FAIL", "detail": str(exc)})
        try:
            item, receipt = self.net.fetch_us_treasury_10y()
            checks.append({"source": "US_TREASURY:10Y", "status": "PASS", "last_date": item["date"], "receipt": receipt})
        except Exception as exc:
            checks.append({"source": "US_TREASURY:10Y", "status": "FAIL", "detail": str(exc)})
        status = "PASS" if all(x["status"] == "PASS" for x in checks) else "FAIL"
        report = {"status": status, "version": VERSION, "checks": checks}
        self.evidence.record("REAL_NETWORK", status, checks=checks)
        return report

    def health(self):
        return {"status": "PASS", "version": VERSION, "cache_path": str(self.storage.path()), "model_status": "UNVALIDATED"}

def create_service(**kwargs):
    return InvestmentService(**kwargs)
