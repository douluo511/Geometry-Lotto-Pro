from __future__ import annotations

import math
import random
import statistics
from typing import Any

POLICY = {
    "schema": "investment-scientific-firewall-v1",
    "min_common_days": 90,
    "min_oos_points": 25,
    "history_days": 90,
    "horizon_days": 5,
    "bootstrap_rounds": 499,
    "permutation_rounds": 799,
    "alpha": 0.01,
    "base_roundtrip_cost": 0.0010,
    "stress_roundtrip_cost": 0.0025,
}


def _finite(values):
    return all(math.isfinite(float(x)) for x in values)


def _bootstrap_lower(values: list[float], rounds: int, seed: int) -> float:
    if not values:
        return float("-inf")
    rng=random.Random(seed)
    n=len(values)
    means=[]
    for _ in range(rounds):
        means.append(sum(values[rng.randrange(n)] for _ in range(n))/n)
    means.sort()
    return means[max(0,int(0.025*(rounds-1)))]


def _permutation_p(values: list[float], rounds: int, seed: int) -> float:
    if not values:
        return 1.0
    observed=statistics.mean(values)
    rng=random.Random(seed)
    extreme=1
    for _ in range(rounds):
        simulated=statistics.mean(v if rng.random()<0.5 else -v for v in values)
        if simulated >= observed:
            extreme += 1
    return extreme/(rounds+1)


def _compact_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    return {k:v for k,v in receipt.items() if k != "body_b64"}


def run_scientific_firewall(net, engine, symbols: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    histories={}
    providers={}
    raw_receipts=[]
    errors=[]
    for symbol in symbols:
        try:
            rows,provider,receipt=net.fetch_market_history(symbol)
            if receipt.get("crosscheck_status") != "PASS":
                raise ValueError(f"independent market crosscheck is {receipt.get('crosscheck_status','UNKNOWN')}")
            rows=sorted(rows,key=lambda x:x["date"])
            histories[symbol]=rows
            providers[symbol]={"status":"PASS","provider":provider,"rows":len(rows),"receipt":_compact_receipt(receipt)}
            raw_receipts.append(receipt)
        except Exception as exc:
            providers[symbol]={"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")

    if errors:
        return ({
            "status":"FAIL","scientific_gate":"FAIL","edge_state":"UNKNOWN",
            "model_status":"UNVALIDATED","promotion_allowed":False,
            "policy":dict(POLICY),"providers":providers,"errors":errors,
        }, raw_receipts)

    common=set.intersection(*(set(r["date"] for r in rows) for rows in histories.values()))
    dates=sorted(common)
    if len(dates) < POLICY["min_common_days"]:
        return ({
            "status":"FAIL","scientific_gate":"FAIL","edge_state":"UNKNOWN",
            "model_status":"UNVALIDATED","promotion_allowed":False,
            "policy":dict(POLICY),"providers":providers,
            "errors":[f"common history too short: {len(dates)}"],
        }, raw_receipts)

    by_symbol={s:{r["date"]:r for r in rows} for s,rows in histories.items()}
    history_days=POLICY["history_days"]
    horizon=POLICY["horizon_days"]
    start=max(61,len(dates)-70)
    end=len(dates)-horizon
    observations=[]
    leakage_ok=True

    for i in range(start,end):
        asof=dates[i]
        future=dates[i+horizon]
        metrics={}
        for symbol in symbols:
            prior_dates=[d for d in dates[:i+1] if d in by_symbol[symbol]][-history_days:]
            rows=[by_symbol[symbol][d] for d in prior_dates]
            if len(rows)<61:
                metrics={}
                break
            if any(r["date"]>asof for r in rows):
                leakage_ok=False
            metrics[symbol]=engine.compute_metrics(rows)
        if len(metrics)!=len(symbols):
            continue

        ranked=engine.rank(metrics,{}, {})
        chosen=ranked[0]["symbol"]
        momentum_choice=max(symbols,key=lambda s:float(metrics[s].get("momentum_20d") or -999.0))
        risk_choice=min(symbols,key=lambda s:(
            float(metrics[s].get("volatility_20d_ann") or 999.0)
            + abs(float(metrics[s].get("max_drawdown_60d") or 0.0))
        ))
        rng=random.Random(20260929+i)
        random_choice=symbols[rng.randrange(len(symbols))]

        forwards={}
        for symbol in symbols:
            p0=float(by_symbol[symbol][asof]["close"])
            p1=float(by_symbol[symbol][future]["close"])
            forwards[symbol]=p1/p0-1.0
        benchmark=statistics.mean(forwards.values())
        observations.append({
            "asof":asof,"future_date":future,"chosen":chosen,
            "gain_gross":forwards[chosen]-benchmark,
            "gain_net":forwards[chosen]-benchmark-POLICY["base_roundtrip_cost"],
            "gain_stress":forwards[chosen]-benchmark-POLICY["stress_roundtrip_cost"],
            "momentum_gain":forwards[momentum_choice]-benchmark-POLICY["base_roundtrip_cost"],
            "risk_gain":forwards[risk_choice]-benchmark-POLICY["base_roundtrip_cost"],
            "random_gain":forwards[random_choice]-benchmark-POLICY["base_roundtrip_cost"],
        })

    gains=[x["gain_net"] for x in observations]
    stress=[x["gain_stress"] for x in observations]
    half=len(gains)//2
    halves=[gains[:half],gains[half:]]
    enough=len(gains)>=POLICY["min_oos_points"] and all(len(x)>=10 for x in halves)
    finite=_finite(gains+stress) if gains else False
    lower=_bootstrap_lower(gains,POLICY["bootstrap_rounds"],4101) if gains else float("-inf")
    stress_lower=_bootstrap_lower(stress,POLICY["bootstrap_rounds"],4102) if stress else float("-inf")
    p=_permutation_p(gains,POLICY["permutation_rounds"],5101) if gains else 1.0
    half_lowers=[
        _bootstrap_lower(chunk,299,6000+j) if chunk else float("-inf")
        for j,chunk in enumerate(halves)
    ]
    full_mean=statistics.mean(gains) if gains else float("-inf")
    random_mean=statistics.mean(x["random_gain"] for x in observations) if observations else float("-inf")
    momentum_mean=statistics.mean(x["momentum_gain"] for x in observations) if observations else float("-inf")
    risk_mean=statistics.mean(x["risk_gain"] for x in observations) if observations else float("-inf")

    apparent_edge=bool(
        enough and finite and leakage_ok
        and full_mean>0 and lower>0 and stress_lower>0 and p<POLICY["alpha"]
        and all(x>0 for x in half_lowers)
        and full_mean>random_mean
    )

    integrity_checks={
        "chronological_oos": all(x["future_date"]>x["asof"] for x in observations),
        "leakage_sentinel": leakage_ok,
        "minimum_oos_points": enough,
        "finite_statistics": finite,
        "equal_weight_baseline": bool(observations),
        "transaction_cost_stress": bool(stress),
        "bootstrap": bool(gains),
        "permutation": bool(gains),
        "dual_holdout_halves": all(len(x)>=10 for x in halves),
        "random_baseline": bool(observations),
        "component_ablation": bool(observations),
    }
    protocol_pass=all(integrity_checks.values())
    report={
        "schema":POLICY["schema"],
        "status":"PASS" if protocol_pass else "FAIL",
        "scientific_gate":"PASS" if protocol_pass else "FAIL",
        "edge_state":"CANDIDATE_SIGNAL" if apparent_edge else "NO_EDGE",
        "model_status":"UNVALIDATED",
        "promotion_allowed":False,
        "promotion_reason":"No automatic promotion path exists; independent preregistered confirmation is required even if a candidate signal appears.",
        "policy":dict(POLICY),
        "providers":providers,
        "oos":{
            "n":len(gains),
            "mean_net_gain_vs_equal_weight":full_mean if gains else None,
            "bootstrap95_lower":lower if gains else None,
            "permutation_p":p,
            "stress_cost_bootstrap95_lower":stress_lower if gains else None,
            "half_bootstrap95_lower":half_lowers,
        },
        "baselines":{
            "random_mean_gain":random_mean if observations else None,
            "momentum_only_mean_gain":momentum_mean if observations else None,
            "risk_only_mean_gain":risk_mean if observations else None,
        },
        "integrity_checks":integrity_checks,
        "apparent_edge":apparent_edge,
        "observations":observations,
    }
    return report,raw_receipts
