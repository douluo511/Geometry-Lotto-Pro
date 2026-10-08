"""Restricted cash-only provider model; observed matching never proves historical PIT."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
import re
from urllib.parse import urlparse

CASH_MODEL = "tencent_600000_cash_offset_v1"
OHLC = ("open", "high", "low", "close")

def verify_cash_offset(qfq, raw, events, event_meta, *, source_content_bound):
    qmap = {r.trade_date:r for r in qfq}
    rmap = {r.trade_date:r for r in raw}
    dates = sorted(set(qmap) & set(rmap))
    result = {
        "status":"NOT VERIFIED", "point_in_time_lineage":"NOT VERIFIED",
        "adjustment_matching_status":"NOT VERIFIED",
        "observed_factor_event_matching_status":"NOT VERIFIED",
        "numerical_cash_offset_status":"NOT VERIFIED",
        "official_cash_notice_binding":"NOT VERIFIED",
        "adjustment_model_contract":CASH_MODEL,
        "factor_detection_method":"cash_only_all_ohlc_offset_v1",
        "factor_estimator":"published_per_share_cash_offset_with_cent_rounding_v1",
        "price_tick":0.01,"cash_offset_rounding_bound":0.01,
        "verified_event_count":0,"significant_factor_changes":0,
        "unexplained_factor_changes":0,"matched_events":[],
        "unmatched_valid_events":[],"invalid_notice_events":[],
        "unexplained_changes":[],"cash_offset_mismatches":[],
        "official_notice_gaps":[],
        "boundary":"Current observed cash-offset matching only. Current back-adjustment can change pre-notice features; historical as-of receipts and causal reconstruction are not implemented.",
    }
    if not dates or qfq[0].symbol!="600000" or not source_content_bound:
        result["reason"]="cash-only profile requires exact symbol and source-content binding"
        return result
    if set(qmap)!=set(rmap):
        result["reason"]="cash-only verification requires every qfq and raw research date"
        return result
    if event_meta.get("cash_unit")!="CNY_PER_10_SHARES":
        result["reason"]="provider per-ten-share cash unit must be explicit"
        return result
    actions=[]
    for event in events:
        ex=str(event.get("ex_dividend_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",ex):
            result["invalid_notice_events"].append(event);continue
        try: date.fromisoformat(ex)
        except ValueError:
            result["invalid_notice_events"].append(event);continue
        if ex<=dates[0] or ex>dates[-1]:continue
        notice=str(event.get("plan_notice_date") or "")
        try:
            timely=date.fromisoformat(notice)<=date.fromisoformat(ex)
            cash=Decimal(str(event.get("pretax_bonus_rmb")))/Decimal(10)
            bonus=Decimal(str(event.get("bonus_ratio") or 0))
            transfer=Decimal(str(event.get("transfer_ratio") or 0))
        except Exception:
            result["invalid_notice_events"].append(event);continue
        if (event.get("symbol")!="600000" or not timely or not cash.is_finite()
                or cash<=0 or not bonus.is_finite() or not transfer.is_finite()
                or bonus!=0 or transfer!=0):
            result["invalid_notice_events"].append(event);continue
        if ex not in qmap or not any(d<ex for d in dates):
            result["unmatched_valid_events"].append(event);continue
        actions.append((event,cash))
    if len({e["ex_dividend_date"] for e,c in actions})!=len(actions):
        result["reason"]="duplicate cash-action date"
        return result
    docs=event_meta.get("official_cash_action_evidence",[])
    if not isinstance(docs,list):docs=[]
    for event,cash in actions:
        matches=[doc for doc in docs if isinstance(doc,dict)
                 and doc.get("symbol")==event["symbol"]
                 and doc.get("ex_dividend_date")==event["ex_dividend_date"]]
        qualified=False
        for doc in matches:
            try:
                parsed=urlparse(str(doc.get("url","")))
                published=date.fromisoformat(str(doc.get("published_date","")))
                doccash=Decimal(str(doc.get("cash_per_share")))
                qualified=(parsed.scheme=="https" and parsed.hostname=="news.spdb.com.cn"
                    and parsed.path.startswith("/investor_relation/company_report/")
                    and parsed.path.lower().endswith(".pdf")
                    and re.fullmatch(r"[0-9a-f]{64}",str(doc.get("payload_sha256",""))) is not None
                    and doc.get("cash_unit")=="CNY_PER_SHARE" and doccash==cash
                    and published<=date.fromisoformat(event["ex_dividend_date"])
                    and doc.get("document_cash_match")=="PASS"
                    and doc.get("document_date_match")=="PASS"
                    and doc.get("document_kind","ordinary_cash_implementation")=="ordinary_cash_implementation")
            except Exception:qualified=False
            if qualified:break
        if not qualified:result["official_notice_gaps"].append({"ex_dividend_date":event["ex_dividend_date"],"reason":"independent ordinary-share implementation PDF cash/date/unit proof missing"})
    mismatches=[]
    for d in dates:
        expected=-sum((cash for event,cash in actions if d<event["ex_dividend_date"]),Decimal(0))
        for field in OHLC:
            actual=Decimal(str(getattr(qmap[d],field)))-Decimal(str(getattr(rmap[d],field)))
            # Two independently cent-rounded observed prices have a combined
            # absolute quantization bound of one cent. This is a physical price
            # tick bound, not a change to frozen factor/date tolerances.
            if abs(actual-expected)>Decimal("0.010000000001"):
                mismatches.append({"trade_date":d,"field":field,"observed_offset":float(actual),
                                   "expected_cash_offset":float(expected),"residual":float(actual-expected)})
    result["cash_offset_mismatches"]=mismatches[:40]
    result["cash_offset_mismatch_count"]=len(mismatches)
    numeric=bool(actions) and not mismatches and not result["invalid_notice_events"] and not result["unmatched_valid_events"]
    result["numerical_cash_offset_status"]="PASS" if numeric else "NOT VERIFIED"
    official=bool(actions) and not result["official_notice_gaps"]
    result["official_cash_notice_binding"]="PASS" if official else "NOT VERIFIED"
    matched=[]
    contexts=[]
    for event,cash in actions:
        ex=event["ex_dividend_date"]
        idx=dates.index(ex)
        before=dates[idx-1]
        fields_ok=all(abs((Decimal(str(getattr(qmap[ex],f)))-Decimal(str(getattr(rmap[ex],f))))
                         -(Decimal(str(getattr(qmap[before],f)))-Decimal(str(getattr(rmap[before],f))))-cash)
                      <=Decimal("0.020000000001") for f in OHLC)
        if fields_ok:
            matched.append({"event":event,"cash_per_share":float(cash),"calendar_days_after_ex_date":0,
                            "offset_change":{"previous_trade_date":before,"trade_date":ex,"cash_offset_increase":float(cash)}})
        else:result["unmatched_valid_events"].append(event)
        observations=[]
        for d in dates[max(0,idx-5):min(len(dates),idx+6)]:
            observations.append({"trade_date":d,
                "qfq_ohlc":{f:getattr(qmap[d],f) for f in OHLC},
                "raw_ohlc":{f:getattr(rmap[d],f) for f in OHLC},
                "qfq_minus_raw_ohlc":{f:float(Decimal(str(getattr(qmap[d],f)))-Decimal(str(getattr(rmap[d],f)))) for f in OHLC},
                "qfq_payload_sha256":qmap[d].raw_sha256,"raw_payload_sha256":rmap[d].raw_sha256})
        contexts.append({"kind":"cash_action","pivot_date":ex,"event":event,"observations":observations})
    result["matched_events"]=matched
    result["verified_event_count"]=len(matched)
    result["significant_factor_changes"]=len(actions)
    result["action_factor_contexts"]=contexts
    if mismatches:
        result["unexplained_factor_changes"]=1
        result["unexplained_changes"]=[{"reason":"cash offset differs from complete announced action ledger","mismatch_count":len(mismatches)}]
    observed=numeric and official and len(matched)==len(actions) and not result["unmatched_valid_events"]
    result["adjustment_matching_status"]="PASS" if observed else "NOT VERIFIED"
    result["observed_factor_event_matching_status"]=result["adjustment_matching_status"]
    result["reason"]="historical point-in-time availability and causal reconstruction remain unverified"
    return result
