from __future__ import annotations
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main()->int:
    e=(ROOT/"engine.py").read_text(encoding="utf-8")
    s=(ROOT/"service.py").read_text(encoding="utf-8")
    st=(ROOT/"storage.py").read_text(encoding="utf-8")
    n=(ROOT/"net_client.py").read_text(encoding="utf-8")
    ev=(ROOT/"evidence.py").read_text(encoding="utf-8")
    app=(ROOT/"app.py").read_text(encoding="utf-8")
    spec=(ROOT/"BUSINESS_SPEC.md").read_text(encoding="utf-8")
    checks={
      "no_production_legacy_bypass":all("legacy_backend" not in x for x in (e,s,st,app)),
      "market_metrics":all(x in e for x in ["momentum_20d","volatility_20d_ann","max_drawdown_60d"]),
      "valuation":all(x in e for x in ["pe_proxy","earnings_yield","earnings_yield_spread"]),
      "scenario":all(x in e for x in ["price_shock_minus_10","price_shock_minus_20","risk_state"]),
      "unvalidated_guard":"UNVALIDATED_RESEARCH_RANK" in e and '"model_status": "UNVALIDATED"' in s,
      "treasury":"fetch_us_treasury_10y" in n,
      "fred":"fetch_fred_series" in n and "FRED:DFF" in s and "NY_FED_EFFR" in n,
      "sec":"fetch_sec_companyfacts" in n and "SEC:AAPL" in s,
      "business_dimensions":"business_dimensions" in s,
      "strict_network_ledger":all(x in n for x in ["FINAL_INSECURE_REDIRECT","RETRY_HTTP","RETRY_EXCEPTION","body_b64","requested_url","final_url"]),
      "independent_market_source":"fetch_nasdaq_history" in n and "_crosscheck_market" in n and "NasdaqCrosscheck" in n and "crosscheck_status" in n,
      "freshness_gate":"_require_fresh_date" in n and "stale/future date" in n,
      "raw_evidence_persistence":"raw_dir" in ev and "raw_sha256" in ev and "body_b64" in ev,
      "failed_snapshot_not_committed":'if state == "PASS":' in s and "snapshot_committed" in s,
      "research_boundary":"不是买卖建议" in spec and "不保证收益" in spec,
    }
    status="PASS" if all(checks.values()) else "FAIL"
    report={"schema":"investment-finance-business-gate-v2","status":status,"checks":checks}
    (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
