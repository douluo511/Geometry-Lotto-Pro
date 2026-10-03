from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys
from typing import Any

from .engine import analyze_observable_activity, reverse_validation
from .netclient import NetClient
from .repair import repair_user_state
from .source_eastmoney import fetch_daily_bars
from .storage import Storage


class FinanceService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.storage = Storage(self.root)
        self.client = NetClient(self.root / "evidence" / "network.jsonl")

    def capital_change(self, symbol: str) -> dict[str, Any]:
        bars = self.storage.load_bars(symbol, 160)
        if len(bars) < 30:
            raise RuntimeError("no validated current data; run core refresh first")
        obs = analyze_observable_activity(bars)
        self.storage.save_observation(obs)
        return {"observation": obs.to_dict(), "reverse_validation": reverse_validation(obs)}

    def refresh_real_data(self, symbol: str) -> dict[str, Any]:
        bars, meta = fetch_daily_bars(self.client, symbol, 160)
        self.storage.persist_raw_metadata(meta)
        stored = self.storage.upsert_bars(bars)
        obs = analyze_observable_activity(self.storage.load_bars(bars[-1].symbol, 160))
        self.storage.save_observation(obs)
        return {"status": "PASS", "stored_rows": stored, "source": meta, "observation": obs.to_dict()}

    def repair(self) -> dict[str, Any]:
        return repair_user_state(self.root)

    def advanced_analysis(self, symbol: str) -> dict[str, Any]:
        result = self.capital_change(symbol)
        result["risk_boundary"] = {
            "personalized_investment_advice": False,
            "true_main_capital_identity": False,
            "capital_deployment_ready": False,
        }
        return result

    def software_update(self) -> dict[str, Any]:
        updater = Path(sys.executable).resolve().parent / "RealMoneyFinanceUpdater.exe"
        if not getattr(sys, "frozen", False) or not updater.exists():
            return {
                "status": "BLOCKED",
                "reason": "independent production updater executable/release context is not available",
            }
        p = subprocess.run([str(updater), "--root", str(self.root)], capture_output=True, text=True, timeout=300)
        status = "PASS" if p.returncode == 0 else ("BLOCKED" if p.returncode == 3 else "FAIL")
        return {"status": status, "returncode": p.returncode,
                "stdout": p.stdout[-10000:], "stderr": p.stderr[-10000:],
                "reason": "signed production release endpoint is not configured" if p.returncode == 3 else None}
