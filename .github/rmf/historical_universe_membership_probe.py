from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOT = ROOT / "RealMoneyFinance"
sys.path.insert(0, str(PRODUCT_ROOT))

from app.netclient import NetClient
from app.source_tencent_full import fetch_daily_bars_tencent_full

SSE_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_HEADERS = {
    "Host": "query.sse.com.cn",
    "Pragma": "no-cache",
    "Referer": "https://www.sse.com.cn/assortment/stock/list/share/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/154 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}
DATE8 = re.compile(r"^\d{8}$")
SYMBOL = re.compile(r"^6\d{5}$")


def _parse_date8(value: object, *, allow_missing: bool) -> date | None:
    raw = str(value or "").strip()
    if allow_missing and raw in {"", "-"}:
        return None
    if not DATE8.fullmatch(raw):
        raise ValueError(f"invalid SSE date value: {raw!r}")
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def _fetch_board(client: NetClient, stock_type: str) -> tuple[list[dict], dict]:
    params = {
        "STOCK_TYPE": stock_type,
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": "",
        "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
        "COMPANY_STATUS": "",
        "type": "inParams",
        "isPagination": "true",
        "pageHelp.cacheSize": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.endPage": "1",
    }
    obj, meta = client.get_json(
        SSE_URL,
        params,
        headers=SSE_HEADERS,
        allow_mislabeled_json=True,
    )
    rows = obj.get("result")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"SSE STOCK_TYPE={stock_type} result empty")
    out: list[dict] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("SSE universe row must be object")
        symbol = str(raw.get("A_STOCK_CODE") or "").strip()
        name = str(raw.get("SEC_NAME_CN") or raw.get("COMPANY_ABBR") or "").strip()
        if not SYMBOL.fullmatch(symbol) or not name:
            raise ValueError(f"invalid SSE symbol/name: {symbol!r}/{name!r}")
        listed = _parse_date8(raw.get("LIST_DATE"), allow_missing=False)
        delisted = _parse_date8(raw.get("DELIST_DATE"), allow_missing=True)
        if delisted is not None and delisted < listed:
            raise ValueError(f"delist before list for {symbol}: {listed} > {delisted}")
        out.append({
            "symbol": symbol,
            "name": name,
            "list_date": listed.isoformat(),
            "delist_date": delisted.isoformat() if delisted else None,
            "state_code": str(raw.get("STATE_CODE") or "").strip(),
            "state_code_stock": str(raw.get("STATE_CODE_STOCK") or "").strip(),
            "product_status": str(raw.get("PRODUCT_STATUS") or "").strip(),
            "stock_type": stock_type,
        })
    return out, {
        "url": str(meta.url).split("?")[0],
        "payload_sha256": meta.payload_sha256,
        "retrieved_at_unix": meta.retrieved_at_unix,
        "row_count": len(out),
        "stock_type": stock_type,
        "company_status_filter": "",
    }


def _eligible(item: dict, asof: date) -> bool:
    listed = date.fromisoformat(item["list_date"])
    delisted = date.fromisoformat(item["delist_date"]) if item["delist_date"] else None
    # Historical state derived from event dates.
    return listed <= asof and (delisted is None or asof < delisted)


def _eligible_with_future_events_hidden(item: dict, asof: date) -> bool:
    """Recompute membership after hiding facts that occur strictly after asof.

    A future listing is unknown and therefore cannot make the symbol eligible.
    A future delisting date is replaced by unknown/None; before that event this
    must not change membership. Equality on delist day remains non-member.
    """
    listed = date.fromisoformat(item["list_date"])
    if listed > asof:
        return False
    raw_delisted = date.fromisoformat(item["delist_date"]) if item["delist_date"] else None
    known_delisted = raw_delisted if raw_delisted is not None and raw_delisted <= asof else None
    return known_delisted is None or asof < known_delisted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--network-evidence", required=True, type=Path)
    args = ap.parse_args()

    client = NetClient(args.network_evidence, connect_timeout=5, read_timeout=30, max_attempts=3)
    history, history_meta = fetch_daily_bars_tencent_full(
        client, "600000", 1200, adjustment="qfq"
    )
    if len(history) != 1200 or not history_meta.get("history_coverage_satisfied"):
        raise RuntimeError(
            f"exact 1200-row research history unavailable: {len(history)} / "
            f"{history_meta.get('history_coverage_satisfied')}"
        )
    research_dates = [date.fromisoformat(row.trade_date) for row in history]
    if research_dates != sorted(research_dates) or len(research_dates) != len(set(research_dates)):
        raise RuntimeError("research dates are not unique chronological dates")

    main_rows, main_meta = _fetch_board(client, "1")
    star_rows, star_meta = _fetch_board(client, "8")
    combined = main_rows + star_rows
    by_symbol: dict[str, dict] = {}
    for item in combined:
        previous = by_symbol.get(item["symbol"])
        if previous is not None and previous != item:
            raise RuntimeError(f"conflicting duplicate SSE security: {item['symbol']}")
        by_symbol[item["symbol"]] = item

    target = by_symbol.get("600000")
    if target is None:
        raise RuntimeError("research symbol 600000 absent from official SSE universe")

    snapshots = []
    previous_count = None
    change_dates = []
    target_missing_dates = []
    causal_invariance_mismatches = []
    future_list_records_hidden_total = 0
    future_delist_records_hidden_total = 0
    for d in research_dates:
        members = [item for item in by_symbol.values() if _eligible(item, d)]
        baseline_symbols = {item["symbol"] for item in members}
        causal_symbols = {
            item["symbol"]
            for item in by_symbol.values()
            if _eligible_with_future_events_hidden(item, d)
        }
        if baseline_symbols != causal_symbols:
            causal_invariance_mismatches.append({
                "date": d.isoformat(),
                "baseline_only": sorted(baseline_symbols - causal_symbols)[:20],
                "causal_only": sorted(causal_symbols - baseline_symbols)[:20],
            })
        future_list_records_hidden_total += sum(
            1 for item in by_symbol.values()
            if date.fromisoformat(item["list_date"]) > d
        )
        future_delist_records_hidden_total += sum(
            1 for item in by_symbol.values()
            if item["delist_date"] and date.fromisoformat(item["delist_date"]) > d
        )
        count = len(members)
        if previous_count is not None and count != previous_count:
            change_dates.append({"date": d.isoformat(), "member_count": count, "previous_count": previous_count})
        previous_count = count
        if not _eligible(target, d):
            target_missing_dates.append(d.isoformat())
        snapshots.append((d.isoformat(), count))

    if causal_invariance_mismatches:
        raise RuntimeError(
            "historical membership changes when future-dated listing/delisting facts are hidden: "
            + json.dumps(causal_invariance_mismatches[:5], sort_keys=True)
        )

    sampled = []
    sample_indices = sorted(set([0, len(snapshots)//4, len(snapshots)//2, 3*len(snapshots)//4, len(snapshots)-1]))
    for i in sample_indices:
        sampled.append({"date": snapshots[i][0], "member_count": snapshots[i][1]})

    delisted_total = sum(1 for item in by_symbol.values() if item["delist_date"])
    delisted_before_window_end = sum(
        1 for item in by_symbol.values()
        if item["delist_date"] and date.fromisoformat(item["delist_date"]) <= research_dates[-1]
    )
    listed_during_window = sum(
        1 for item in by_symbol.values()
        if research_dates[0] < date.fromisoformat(item["list_date"]) <= research_dates[-1]
    )

    canonical_rows = [
        {
            "symbol": item["symbol"],
            "list_date": item["list_date"],
            "delist_date": item["delist_date"],
            "stock_type": item["stock_type"],
        }
        for item in sorted(by_symbol.values(), key=lambda x: x["symbol"])
    ]
    canonical_hash = hashlib.sha256(
        json.dumps(canonical_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    evidence = {
        "schema": "rmf-sse-historical-membership-reconstruction-v1",
        "status": "PASS",
        "scope": "historical membership reconstruction evidence only; selection-bias and PIT-availability gates remain separate",
        "research_symbol": "600000",
        "research_provider": history_meta.get("provider"),
        "research_price_adjustment": history_meta.get("price_adjustment"),
        "research_row_count": len(history),
        "research_start": research_dates[0].isoformat(),
        "research_end": research_dates[-1].isoformat(),
        "research_payload_sha256": history_meta.get("payload_sha256"),
        "research_source_payload_sha256s": history_meta.get("source_payload_sha256s"),
        "sse_sources": [main_meta, star_meta],
        "unfiltered_security_count": len(by_symbol),
        "securities_with_delist_date": delisted_total,
        "securities_delisted_by_research_end": delisted_before_window_end,
        "securities_listed_during_research_window": listed_during_window,
        "membership_rule": "LIST_DATE <= asof < DELIST_DATE; missing/'-' DELIST_DATE means no recorded delisting",
        "membership_count_min": min(x[1] for x in snapshots),
        "membership_count_max": max(x[1] for x in snapshots),
        "membership_count_start": snapshots[0][1],
        "membership_count_end": snapshots[-1][1],
        "membership_change_date_count": len(change_dates),
        "membership_change_samples": change_dates[:20],
        "membership_snapshot_samples": sampled,
        "target_official_record": target,
        "target_member_every_research_date": not target_missing_dates,
        "target_missing_date_count": len(target_missing_dates),
        "historical_universe_canonical_sha256": canonical_hash,
        "historical_membership_reconstruction": "PASS",
        "event_time_no_future_leakage_subcontrol": "PASS",
        "causal_event_invariance_checked_dates": len(research_dates),
        "causal_event_invariance_mismatch_count": len(causal_invariance_mismatches),
        "future_list_records_hidden_total": future_list_records_hidden_total,
        "future_delist_records_hidden_total": future_delist_records_hidden_total,
        "historical_pit_availability": "NOT VERIFIED",
        "survivorship_selection_control": "NOT VERIFIED",
        "capital_deployment_ready": False,
        "boundary": (
            "This proves that the current official SSE payload exposes listing/delisting records "
            "sufficient to reconstruct a historical membership set across the exact 1200-row "
            "research window, and whether 600000 belonged to that set. It does not prove that these "
            "membership is invariant when all future-dated listing/delisting facts are hidden, "
            "which proves this reconstruction rule does not use future event dates to change pre-event "
            "membership. It still does not prove the SSE fields were historically available/knowable "
            "at each past date, nor that 600000 was selected ex ante from a frozen investable universe. "
            "Those gates remain NOT VERIFIED."
        ),
    }
    args.output.write_text(json.dumps(evidence, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
