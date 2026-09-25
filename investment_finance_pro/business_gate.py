from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def main()->int:
 e=(ROOT/"engine.py").read_text(encoding="utf-8"); s=(ROOT/"service.py").read_text(encoding="utf-8"); n=(ROOT/"net_client.py").read_text(encoding="utf-8")
 checks={
  "engine_not_legacy_proxy":"legacy_backend" not in e,
  "market_metrics":all(x in e for x in ["momentum_20d","volatility_20d_ann","max_drawdown_60d"]),
  "valuation":all(x in e for x in ["pe_proxy","earnings_yield","earnings_yield_spread"]),
  "scenario":all(x in e for x in ["price_shock_minus_10","price_shock_minus_20","risk_state"]),
  "unvalidated_guard":"UNVALIDATED_RESEARCH_RANK" in e,
  "treasury":"fetch_us_treasury_10y" in n,
  "fred":"fetch_fred_series" in n and "FRED:DFF" in s,
  "sec":"fetch_sec_companyfacts" in n and "SEC:AAPL" in s,
  "business_dimensions":"business_dimensions" in s,
 }
 status="PASS" if all(checks.values()) else "FAIL"
 report={"schema":"investment-finance-business-gate-v1","status":status,"checks":checks}
 (ROOT/"business_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
 print(json.dumps(report,ensure_ascii=True)); return 0 if status=="PASS" else 2
if __name__=="__main__": raise SystemExit(main())
