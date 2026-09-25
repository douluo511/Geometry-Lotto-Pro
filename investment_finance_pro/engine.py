from __future__ import annotations
import math, statistics
from datetime import date,timedelta

def pct_change(a:float,b:float)->float:
    return (b/a-1.0) if a else 0.0

def max_drawdown(closes:list[float])->float:
    peak=closes[0]; worst=0.0
    for v in closes:
        peak=max(peak,v); worst=min(worst,v/peak-1.0)
    return worst

class InvestmentEngine:
    def compute_metrics(self, rows):
        closes=[float(r["close"]) for r in rows]
        if len(closes)<30: raise ValueError("Need at least 30 closes")
        returns=[pct_change(closes[i-1],closes[i]) for i in range(1,len(closes))]
        recent20=returns[-20:]
        vol20=statistics.pstdev(recent20)*math.sqrt(252) if len(recent20)>=2 else 0.0
        return {
          "date":rows[-1]["date"],"close":round(closes[-1],4),
          "change_1d":round(pct_change(closes[-2],closes[-1]),6),
          "momentum_20d":round(pct_change(closes[-21],closes[-1]),6),
          "momentum_60d":round(pct_change(closes[-61],closes[-1]),6) if len(closes)>=61 else None,
          "volatility_20d_ann":round(vol20,6),
          "max_drawdown_60d":round(max_drawdown(closes[-60:]),6),"rows":len(rows),
        }

    def valuation(self, price:float, fundamentals:dict|None, treasury10y:float|None):
        eps=float((fundamentals or {}).get("annual_diluted_eps") or 0.0)
        pe=(price/eps) if eps>0 else None
        ey=(eps/price) if price>0 and eps>0 else None
        rf=(float(treasury10y)/100.0) if treasury10y is not None else None
        spread=(ey-rf) if ey is not None and rf is not None else None
        return {
          "annual_diluted_eps":round(eps,4) if eps else None,
          "pe_proxy":round(pe,3) if pe is not None else None,
          "earnings_yield":round(ey,6) if ey is not None else None,
          "treasury_10y":treasury10y,
          "earnings_yield_spread":round(spread,6) if spread is not None else None,
          "valuation_status":"ANNUAL_EPS_PROXY" if pe is not None else "INSUFFICIENT_FUNDAMENTALS",
        }

    def scenario(self, metric:dict, valuation:dict):
        vol=max(float(metric.get("volatility_20d_ann") or 0),0.0001)
        dd=abs(float(metric.get("max_drawdown_60d") or 0))
        return {
          "risk_state":"HIGH" if vol>=0.40 or dd>=0.25 else ("MEDIUM" if vol>=0.25 or dd>=0.15 else "LOWER"),
          "price_shock_minus_10":round(float(metric["close"])*0.90,4),
          "price_shock_minus_20":round(float(metric["close"])*0.80,4),
          "volatility_20d_ann":metric.get("volatility_20d_ann"),
          "max_drawdown_60d":metric.get("max_drawdown_60d"),
          "valuation_status":valuation.get("valuation_status"),
        }

    def score(self, metric:dict, valuation:dict):
        mom=float(metric.get("momentum_20d") or 0.0)
        vol=max(float(metric.get("volatility_20d_ann") or 0.0),0.05)
        dd=abs(float(metric.get("max_drawdown_60d") or 0.0))
        base=mom/vol-0.35*dd
        spread=valuation.get("earnings_yield_spread")
        if spread is not None:
            base += max(-0.25,min(0.25,float(spread)*2.0))
        return base

    def rank(self, metrics, fundamentals=None, macro=None):
        fundamentals=fundamentals or {}; macro=macro or {}
        t10=(macro.get("US_10Y_TREASURY") or {}).get("value")
        rows=[]
        for symbol,m in metrics.items():
            val=self.valuation(float(m["close"]),fundamentals.get(symbol),t10)
            rows.append({
              "symbol":symbol,"close":m["close"],"change_1d":m["change_1d"],
              "momentum_20d":m["momentum_20d"],"volatility_20d_ann":m["volatility_20d_ann"],
              "max_drawdown_60d":m["max_drawdown_60d"],"valuation":val,
              "scenario":self.scenario(m,val),"score":round(self.score(m,val),6),
              "status":"UNVALIDATED_RESEARCH_RANK",
            })
        rows.sort(key=lambda x:x["score"],reverse=True); return rows

    def deterministic_self_test(self):
        rows=[]; price=100.0; start=date(2026,1,1)
        for i in range(90):
            price*=1.0+(0.001 if i%7 else -0.002)
            rows.append({"date":(start+timedelta(days=i)).isoformat(),"open":price,"high":price*1.01,"low":price*0.99,"close":price,"volume":1000000+i})
        m=self.compute_metrics(rows)
        f={"TEST":{"annual_diluted_eps":5.0}}
        r=self.rank({"TEST":m},f,{"US_10Y_TREASURY":{"value":4.0}})
        checks={
          "metrics":m["close"]>0 and m["volatility_20d_ann"]>=0,
          "valuation":r[0]["valuation"]["pe_proxy"] is not None,
          "scenario":r[0]["scenario"]["risk_state"] in {"LOWER","MEDIUM","HIGH"},
          "guard":r[0]["status"]=="UNVALIDATED_RESEARCH_RANK",
        }
        return {"status":"PASS" if all(checks.values()) else "FAIL","checks":checks}
