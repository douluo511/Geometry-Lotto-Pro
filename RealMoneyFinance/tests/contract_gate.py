from __future__ import annotations

from pathlib import Path
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
    def get_json(self, url, params, headers=None):
        assert headers and headers.get("Referer") == "https://quote.eastmoney.com/"
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

def main() -> int:
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
    }
    Path("contract_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
