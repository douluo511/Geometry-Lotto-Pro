from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys
from typing import Any
import time

from .engine import analyze_observable_activity, reverse_validation
from .netclient import NetClient
from .repair import repair_user_state
from .source_market import fetch_daily_bars_failover
from .storage import Storage
from .build_info import VERSION, SOURCE_SHA


class FinanceService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.storage = Storage(self.root)
        self.client = NetClient(self.root / "evidence" / "network.jsonl")

    def _write_evidence(self, name: str, payload: dict[str, Any]) -> Path:
        target = self.root / "evidence" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        obj = {"generated_at_unix": time.time(), **payload}
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, target)
        return target

    def capital_change(self, symbol: str) -> dict[str, Any]:
        bars = self.storage.load_bars(symbol, 160)
        if len(bars) < 30:
            raise RuntimeError("no validated current data; run core refresh first")
        obs = analyze_observable_activity(bars)
        self.storage.save_observation(obs)
        result = {"observation": obs.to_dict(), "reverse_validation": reverse_validation(obs)}
        self._write_evidence("capital_change.json", {"status": "PASS", **result})
        return result

    def refresh_real_data(self, symbol: str) -> dict[str, Any]:
        bars, meta = fetch_daily_bars_failover(self.client, symbol, 160)
        self.storage.persist_raw_metadata(meta)
        stored = self.storage.upsert_bars(bars)
        obs = analyze_observable_activity(self.storage.load_bars(bars[-1].symbol, 160))
        self.storage.save_observation(obs)
        result = {"status": "PASS", "stored_rows": stored, "source": meta, "observation": obs.to_dict()}
        self._write_evidence("refresh.json", result)
        return result

    def repair(self) -> dict[str, Any]:
        return repair_user_state(self.root)

    def advanced_analysis(self, symbol: str) -> dict[str, Any]:
        result = self.capital_change(symbol)
        result["risk_boundary"] = {
            "personalized_investment_advice": False,
            "true_main_capital_identity": False,
            "capital_deployment_ready": False,
        }
        self._write_evidence("advanced_analysis.json", {"status": "PASS", **result})
        return result

    def software_update(self) -> dict[str, Any]:
        updater = Path(sys.executable).resolve().parent / "RealMoneyFinanceUpdater.exe"
        if not getattr(sys, "frozen", False) or not updater.exists():
            result = {
                "status": "BLOCKED",
                "reason": "independent production updater executable/release context is not available",
            }
            self._write_evidence("software_update.json", result)
            return result
        command = [str(updater), "--root", str(self.root), "--current-version", VERSION,
                   "--target", str(Path(sys.executable).resolve()), "--current-source", SOURCE_SHA]
        p = subprocess.run([*command, "--check"], capture_output=True, text=True, encoding="utf-8", timeout=300)
        try:
            result = json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            result = {"status": "FAIL", "reason": "independent updater produced no structured acceptance result"}
        if p.returncode == 0 and result.get("status") == "PASS":
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen([*command, "--wait-pid", str(os.getpid())],
                                       creationflags=creationflags)
            result = {"status": "RESTART_REQUIRED", "updater_pid": process.pid,
                      "reason": "signed release verified; application closes before independent replacement"}
        elif (p.returncode, result.get("status")) not in ((3, "BLOCKED"), (1, "FAIL")):
            result = {"status": "FAIL", "reason": "updater process/status contract mismatch"}
        result["returncode"] = p.returncode
        self._write_evidence("software_update.json", result)
        return result

