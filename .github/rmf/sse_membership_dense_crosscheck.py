from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOT = ROOT / "RealMoneyFinance"
sys.path.insert(0, str(PRODUCT_ROOT))

from app.netclient import NetClient
from app.source_tencent_full import fetch_daily_bars_tencent_full

HERE = Path(__file__).resolve().parent
MEMBERSHIP_PATH = HERE / "historical_universe_membership_probe.py"

URL = "https://query.sse.com.cn/commonQuery.do"
SQL_ID = "COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C"
PRODUCT_CODE = "01,02,03,11,17"
HEADERS = {
    "Host": "query.sse.com.cn",
    "Referer": "https://www.sse.com.cn/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def as_int(value: object) -> int:
    raw = str(value or "").strip().replace(",", "")
    if not raw.isdigit():
        raise ValueError(f"invalid integer field {raw!r}")
    return int(raw)


def month_end_research_dates(dates: list[date]) -> list[date]:
    chosen: OrderedDict[tuple[int, int], date] = OrderedDict()
    for d in dates:
        chosen[(d.year, d.month)] = d
    return list(chosen.values())


def official_count(client: NetClient, day: date) -> dict:
    iso = day.isoformat()
    obj, meta = client.get_json(
        URL,
        {
            "sqlId": SQL_ID,
            "PRODUCT_CODE": PRODUCT_CODE,
            "type": "inParams",
            "SEARCH_DATE": iso,
        },
        headers=HEADERS,
        allow_mislabeled_json=True,
    )
    rows = obj.get("result") if isinstance(obj, dict) else None
    receipt = {
        "date": iso,
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "row_count": len(rows) if isinstance(rows, list) else None,
    }
    if not isinstance(rows, list) or not rows:
        return {**receipt, "status": "NOT VERIFIED", "reason": "no official row list"}

    date8 = iso.replace("-", "")
    main = [
        r for r in rows
        if isinstance(r, dict)
        and str(r.get("PRODUCT_CODE") or "").strip() == "01"
        and str(r.get("TRADE_DATE") or "").strip() == date8
    ]
    star = [
        r for r in rows
        if isinstance(r, dict)
        and str(r.get("PRODUCT_CODE") or "").strip() == "03"
        and str(r.get("TRADE_DATE") or "").strip() == date8
    ]
    if len(main) != 1 or len(star) != 1:
        return {
            **receipt,
            "status": "NOT VERIFIED",
            "reason": "unique PRODUCT_CODE 01 + 03 rows unavailable",
            "product_codes": [str(r.get("PRODUCT_CODE") or "") for r in rows if isinstance(r, dict)],
            "trade_dates": [str(r.get("TRADE_DATE") or "") for r in rows if isinstance(r, dict)],
        }

    return {
        **receipt,
        "status": "PASS",
        "main_count": as_int(main[0].get("LIST_NUM")),
        "star_count": as_int(star[0].get("LIST_NUM")),
        "main_plus_star": as_int(main[0].get("LIST_NUM")) + as_int(star[0].get("LIST_NUM")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--network-evidence", required=True, type=Path)
    args = ap.parse_args()

    membership = load_module("membership", MEMBERSHIP_PATH)
    client = NetClient(args.network_evidence, connect_timeout=5, read_timeout=30, max_attempts=3)

    history, history_meta = fetch_daily_bars_tencent_full(
        client, "600000", 1200, adjustment="qfq"
    )
    if len(history) != 1200 or not history_meta.get("history_coverage_satisfied"):
        raise RuntimeError("exact 1200-row research history unavailable")
    research_dates = [date.fromisoformat(row.trade_date) for row in history]
    sample_dates = month_end_research_dates(research_dates)

    main_rows, main_meta = membership._fetch_board(client, "1")
    star_rows, star_meta = membership._fetch_board(client, "8")
    combined = main_rows + star_rows
    by_symbol = {}
    for item in combined:
        previous = by_symbol.get(item["symbol"])
        if previous is not None and previous != item:
            raise RuntimeError(f"conflicting duplicate SSE security: {item['symbol']}")
        by_symbol[item["symbol"]] = item

    comparisons = []
    mismatches = []
    unavailable = []
    for d in sample_dates:
        reconstructed = sum(1 for item in by_symbol.values() if membership._eligible(item, d))
        official = official_count(client, d)
        item = {
            "date": d.isoformat(),
            "reconstructed": reconstructed,
            "official": official,
            "match": None,
        }
        if official.get("status") == "PASS":
            item["match"] = official["main_plus_star"] == reconstructed
            if not item["match"]:
                mismatches.append({
                    "date": d.isoformat(),
                    "reconstructed": reconstructed,
                    "official": official["main_plus_star"],
                })
        else:
            unavailable.append({
                "date": d.isoformat(),
                "reason": official.get("reason"),
            })
        comparisons.append(item)

    comparable = [x for x in comparisons if x["official"].get("status") == "PASS"]
    matched = [x for x in comparable if x.get("match") is True]
    coverage = len(comparable) / len(sample_dates) if sample_dates else 0.0

    dense_pass = (
        bool(sample_dates)
        and len(mismatches) == 0
        and len(comparable) >= 48
        and coverage >= 0.80
    )

    canonical = [
        {
            "date": x["date"],
            "reconstructed": x["reconstructed"],
            "official_count": x["official"].get("main_plus_star"),
            "official_status": x["official"].get("status"),
            "match": x["match"],
        }
        for x in comparisons
    ]
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    evidence = {
        "schema": "rmf-sse-historical-membership-dense-crosscheck-v1",
        "status": "PASS" if dense_pass else "NOT VERIFIED",
        "research_rows": len(history),
        "research_start": research_dates[0].isoformat(),
        "research_end": research_dates[-1].isoformat(),
        "sample_strategy": "last actual 600000 research trading date in each calendar month",
        "sample_date_count": len(sample_dates),
        "comparable_date_count": len(comparable),
        "matched_date_count": len(matched),
        "unavailable_date_count": len(unavailable),
        "comparison_coverage": coverage,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "unavailable": unavailable,
        "comparisons": comparisons,
        "canonical_comparison_sha256": digest,
        "research_source": {
            "provider": history_meta.get("provider"),
            "price_adjustment": history_meta.get("price_adjustment"),
            "payload_sha256": history_meta.get("payload_sha256"),
        },
        "sse_sources": [main_meta, star_meta],
        "adjudication": {
            "dense_historical_membership_crosscheck": "PASS" if dense_pass else "NOT VERIFIED",
            "historical_membership_reconstruction": "SUPPORTED" if dense_pass else "NOT VERIFIED",
            "historical_pit_availability": "NOT VERIFIED",
            "survivorship_selection_control": "NOT VERIFIED",
            "capital_deployment_ready": False,
            "product_bytes_changed": False,
            "final_gate": "FAIL",
        },
        "boundary": (
            "Dense agreement between reconstructed membership and independent official SSE daily aggregate "
            "listed counts strengthens the reconstruction rule. It still does not prove those current "
            "LIST_DATE/DELIST_DATE fields were historically knowable at each past date, and therefore cannot "
            "promote historical PIT availability or survivorship selection control."
        ),
    }

    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": evidence["schema"],
        "status": evidence["status"],
        "sample_date_count": evidence["sample_date_count"],
        "comparable_date_count": evidence["comparable_date_count"],
        "matched_date_count": evidence["matched_date_count"],
        "unavailable_date_count": evidence["unavailable_date_count"],
        "comparison_coverage": evidence["comparison_coverage"],
        "mismatch_count": evidence["mismatch_count"],
        "adjudication": evidence["adjudication"],
    }, sort_keys=True))
    return 0 if dense_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
