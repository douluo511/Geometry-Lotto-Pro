from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import os

from contracts import validate_snapshot
from engine import InvestmentEngine
from evidence import EvidenceLedger
from net_client import NetClient
from scientific_validation import run_scientific_firewall
from storage import SnapshotStorage

APP_NAME = "Investment Finance Pro"
WATCHLIST = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
SEC_CIK={"AAPL":320193,"MSFT":789019,"NVDA":1045810,"GOOGL":1652044,"AMZN":1018724}
VERSION = "0.4.0"

def _compact_receipt(value):
    if isinstance(value, list):
        return [_compact_receipt(x) for x in value]
    if isinstance(value, dict):
        return {k:_compact_receipt(v) for k,v in value.items() if k != "body_b64"}
    return value

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
        raw_receipts = []
        for symbol in WATCHLIST:
            try:
                rows, provider, receipt = self.net.fetch_market_history(symbol)
                metrics[symbol] = self.engine.compute_metrics(rows)
                crosscheck_ok = receipt.get("crosscheck_status") == "PASS"
                providers.append({
                    "source": provider + ":" + symbol,
                    "ok": crosscheck_ok,
                    "detail": f"{len(rows)} rows; crosscheck={receipt.get('crosscheck_status','UNKNOWN')}",
                })
                raw_receipts.append(receipt)
                receipts.append(_compact_receipt(receipt))
            except Exception as exc:
                providers.append({"source": "MARKET:" + symbol, "ok": False, "detail": str(exc)})

        macro = {}
        fundamentals = {}
        try:
            item, receipt = self.net.fetch_us_treasury_10y()
            macro["US_10Y_TREASURY"] = item
            providers.append({"source": "US_TREASURY:10Y", "ok": True, "detail": "latest official daily yield loaded"})
            raw_receipts.append(receipt)
            receipts.append(_compact_receipt(receipt))
        except Exception as exc:
            providers.append({"source": "US_TREASURY:10Y", "ok": False, "detail": str(exc)})

        try:
            item, receipt = self.net.fetch_fred_series("DFF")
            macro["FED_FUNDS_EFFECTIVE"] = item
            providers.append({"source":"FRED:DFF","ok":True,"detail":"latest effective federal funds rate loaded"})
            raw_receipts.append(receipt)
            receipts.append(_compact_receipt(receipt))
        except Exception as exc:
            providers.append({"source":"FRED:DFF","ok":False,"detail":str(exc)})

        for symbol,cik in SEC_CIK.items():
            try:
                item,receipt=self.net.fetch_sec_companyfacts(symbol,cik)
                fundamentals[symbol]=item
                providers.append({"source":"SEC:"+symbol,"ok":True,"detail":"latest 10-K annual diluted EPS loaded"})
                raw_receipts.append(receipt)
                receipts.append(_compact_receipt(receipt))
            except Exception as exc:
                providers.append({"source":"SEC:"+symbol,"ok":False,"detail":str(exc)})

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
            "fundamentals": fundamentals,
            "metrics": metrics,
            "ranking": self.engine.rank(metrics, fundamentals, macro),
        }
        if state == "PASS":
            self.storage.write(payload)
        self.evidence.record(
            "NETWORK",
            state,
            providers=providers,
            receipts=raw_receipts,
            snapshot_committed=(state == "PASS"),
        )
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
            "business_dimensions":["market","risk","valuation","macro","scenario"],
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
            market_ok = receipt.get("crosscheck_status") == "PASS"
            checks.append({
                "source": provider + ":SPY",
                "status": "PASS" if market_ok else "FAIL",
                "last_date": metric["date"],
                "crosscheck_status": receipt.get("crosscheck_status","UNKNOWN"),
                "receipt": receipt,
            })
        except Exception as exc:
            checks.append({"source": "MARKET:SPY", "status": "FAIL", "detail": str(exc)})
        try:
            item, receipt = self.net.fetch_us_treasury_10y()
            checks.append({"source":"US_TREASURY:10Y","status":"PASS","last_date":item["date"],"receipt":receipt})
        except Exception as exc:
            checks.append({"source":"US_TREASURY:10Y","status":"FAIL","detail":str(exc)})
        try:
            item,receipt=self.net.fetch_fred_series("DFF")
            checks.append({"source":"FRED:DFF","status":"PASS","last_date":item["date"],"receipt":receipt})
        except Exception as exc:
            checks.append({"source":"FRED:DFF","status":"FAIL","detail":str(exc)})
        try:
            item,receipt=self.net.fetch_sec_companyfacts("AAPL",SEC_CIK["AAPL"])
            checks.append({"source":"SEC:AAPL","status":"PASS","filed":item["filed"],"receipt":receipt})
        except Exception as exc:
            checks.append({"source":"SEC:AAPL","status":"FAIL","detail":str(exc)})
        status = "PASS" if all(x["status"] == "PASS" for x in checks) else "FAIL"
        raw_checks = checks
        report = {"status": status, "version": VERSION, "checks": _compact_receipt(raw_checks)}
        self.evidence.record("REAL_NETWORK", status, checks=raw_checks)
        return report

    def scientific_validation(self):
        report, raw_receipts = run_scientific_firewall(self.net, self.engine, list(WATCHLIST))
        self.evidence.record(
            "SCIENTIFIC_FIREWALL",
            report.get("status", "FAIL"),
            report=report,
            receipts=raw_receipts,
        )
        return report

    def health(self):
        cached = self.storage.read()
        return {
            "status": "PASS",
            "version": VERSION,
            "cache_path": str(self.storage.path()),
            "model_status": "UNVALIDATED",
            "snapshot_status": (cached or {}).get("update_state", "NONE"),
        }

def create_service(**kwargs):
    return InvestmentService(**kwargs)
