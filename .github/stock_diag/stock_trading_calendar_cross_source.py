from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import akshare as ak

START="20180101"
END="20260930"
SYMBOL="sh000001"


def normalize_dates(df, provider):
    if df is None or df.empty:
        raise RuntimeError(f"{provider}: empty index history")
    cols=list(df.columns)
    date_col=next((c for c in cols if str(c).lower() in {"date","日期","trade_date"}),None)
    if date_col is None:
        raise RuntimeError(f"{provider}: no date column in {cols}")
    dates=pd.to_datetime(df[date_col],errors="coerce").dropna()
    dates=dates[(dates>=pd.Timestamp("2018-01-01")) & (dates<=pd.Timestamp("2026-09-30"))]
    values=sorted(set(dates.dt.strftime("%Y-%m-%d").tolist()))
    if len(values)<1500:
        raise RuntimeError(f"{provider}: implausibly short frozen-window date set {len(values)}")
    return values


def digest(values):
    payload="\n".join(values).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def main():
    em=ak.stock_zh_index_daily_em(symbol=SYMBOL,start_date=START,end_date=END)
    tx=ak.stock_zh_index_daily_tx(symbol=SYMBOL)
    em_dates=normalize_dates(em,"eastmoney")
    tx_dates=normalize_dates(tx,"tencent")

    em_set=set(em_dates); tx_set=set(tx_dates)
    only_em=sorted(em_set-tx_set)
    only_tx=sorted(tx_set-em_set)
    exact_equal=(em_dates==tx_dates)
    canonical_dates=em_dates if exact_equal else []

    report={
        "schema":"stock-trading-calendar-cross-source-v2",
        "symbol":SYMBOL,
        "frozen_window":{"start":"2018-01-01","end":"2026-09-30"},
        "providers":{
            "eastmoney":{"rows":len(em_dates),"first":em_dates[0],"last":em_dates[-1],"date_sha256":digest(em_dates)},
            "tencent":{"rows":len(tx_dates),"first":tx_dates[0],"last":tx_dates[-1],"date_sha256":digest(tx_dates)},
        },
        "comparison":{
            "exact_date_sequence_equal":exact_equal,
            "eastmoney_only_count":len(only_em),
            "tencent_only_count":len(only_tx),
            "eastmoney_only_sample":only_em[:30],
            "tencent_only_sample":only_tx[:30],
        },
        "canonical_trading_dates":{
            "status":"SUPPORTED" if exact_equal else "NOT VERIFIED",
            "rows":len(canonical_dates),
            "date_sha256":digest(canonical_dates) if canonical_dates else None,
            "dates":canonical_dates,
        },
        "adjudication":{
            "research_trading_date_sequence":"SUPPORTED" if exact_equal else "NOT VERIFIED",
            "independent_provider_agreement":"PASS" if exact_equal else "FAIL",
            "historical_daily_suspension_state":"NOT VERIFIED",
            "shanghai_historical_st_pit":"NOT VERIFIED",
            "full_historical_st_pit":"NOT VERIFIED",
            "advanced_business":"NOT VERIFIED",
            "product_bytes_changed":False,
            "final_gate":"FAIL",
        },
    }
    Path("stock_trading_calendar_cross_source.json").write_text(
        json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps({
        "schema":report["schema"],
        "providers":report["providers"],
        "comparison":report["comparison"],
        "canonical_trading_dates":{
            "status":report["canonical_trading_dates"]["status"],
            "rows":report["canonical_trading_dates"]["rows"],
            "date_sha256":report["canonical_trading_dates"]["date_sha256"],
        },
        "adjudication":report["adjudication"],
    },ensure_ascii=True,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
