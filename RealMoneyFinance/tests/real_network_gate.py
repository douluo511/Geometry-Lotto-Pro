from __future__ import annotations

from pathlib import Path
import json
import os
import tempfile

from app.engine import analyze_observable_activity
from app.netclient import NetClient
from app.source_market import fetch_daily_bars_failover
from app.storage import Storage


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        client = NetClient(root / "evidence" / "network.jsonl", max_attempts=3)
        bars, meta = fetch_daily_bars_failover(client, "600000", 90)
        if meta["http_status"] != 200:
            raise AssertionError("real source did not return HTTP 200")
        if len(bars) < 30:
            raise AssertionError("insufficient real rows")
        store = Storage(root)
        store.persist_raw_metadata(meta)
        store.upsert_bars(bars)
        obs = analyze_observable_activity(store.load_bars("600000", 120))
        if obs.true_capital_identity != "UNAVAILABLE_FROM_PUBLIC_LEVEL1":
            raise AssertionError("identity boundary violated")
        evidence = {
            "status": "PASS",
            "provider": meta["provider"],
            "selected_provider": meta.get("selected_provider"),
            "provider_attempts": meta.get("provider_attempts"),
            "cross_source_validation": meta.get("cross_source_validation"),
            "payload_sha256": meta["payload_sha256"],
            "row_count": len(bars),
            "asof": obs.asof,
            "activity_state": obs.activity_state,
            "true_capital_identity": obs.true_capital_identity,
            "network_evidence": str(root / "evidence" / "network.jsonl"),
        }
        Path("real_network_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
