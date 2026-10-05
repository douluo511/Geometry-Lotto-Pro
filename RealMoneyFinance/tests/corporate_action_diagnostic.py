from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.netclient import NetClient
from app.source_corporate_actions import fetch_share_bonus_events, verify_corporate_action_lineage
from app.source_tencent_full import fetch_daily_bars_tencent_full


def _finite(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite numeric value in diagnostic")
    return number


def _factor_points(qfq_rows, raw_rows) -> list[dict]:
    qmap = {row.trade_date: row for row in qfq_rows}
    rmap = {row.trade_date: row for row in raw_rows}
    dates = sorted(set(qmap) & set(rmap))
    half_tick = 0.005
    points = []
    for trade_date in dates:
        qrow = qmap[trade_date]
        rrow = rmap[trade_date]
        ratios = []
        lowers = []
        uppers = []
        values = {}
        for field in ("open", "high", "low", "close"):
            qvalue = _finite(getattr(qrow, field))
            rvalue = _finite(getattr(rrow, field))
            if qvalue <= half_tick or rvalue <= half_tick:
                raise ValueError(f"non-positive/too-small OHLC at {trade_date} {field}")
            ratios.append(qvalue / rvalue)
            lowers.append((qvalue - half_tick) / (rvalue + half_tick))
            uppers.append((qvalue + half_tick) / (rvalue - half_tick))
            values[field] = {"qfq": qvalue, "raw": rvalue}
        lower = max(lowers)
        upper = min(uppers)
        points.append(
            {
                "trade_date": trade_date,
                "factor": median(ratios),
                "factor_interval_lower": lower,
                "factor_interval_upper": upper,
                "factor_interval_consistent": lower <= upper,
                "ohlc_factor_spread": max(ratios) - min(ratios),
                "ohlc": values,
            }
        )
    return points


def _interval_gap(left: dict, right: dict) -> tuple[bool, float]:
    if not left["factor_interval_consistent"] or not right["factor_interval_consistent"]:
        return False, 0.0
    llo = float(left["factor_interval_lower"])
    lup = float(left["factor_interval_upper"])
    rlo = float(right["factor_interval_lower"])
    rup = float(right["factor_interval_upper"])
    if lup < rlo:
        return True, rlo / lup - 1.0
    if rup < llo:
        return True, llo / rup - 1.0
    return False, 0.0


def _nearest_events(events: list[dict], trade_date: str, radius_days: int = 30) -> list[dict]:
    target = date.fromisoformat(trade_date)
    out = []
    for event in events:
        ex_text = str(event.get("ex_dividend_date") or "")
        try:
            ex_day = date.fromisoformat(ex_text)
        except Exception:
            continue
        delta = (target - ex_day).days
        if abs(delta) <= radius_days:
            out.append(
                {
                    "calendar_days_from_ex_date": delta,
                    "event": event,
                }
            )
    out.sort(key=lambda item: (abs(item["calendar_days_from_ex_date"]), item["calendar_days_from_ex_date"]))
    return out


def _adjacent_detail(change: dict, points_by_date: dict[str, dict], events: list[dict]) -> dict:
    previous_date = str(change.get("previous_trade_date") or "")
    trade_date = str(change.get("trade_date") or "")
    left = points_by_date.get(previous_date)
    right = points_by_date.get(trade_date)
    if left is None or right is None:
        return {
            "status": "NOT VERIFIED",
            "reason": "change dates are not adjacent factor points in current payload",
            "change": change,
        }
    adjacent_jump = abs(float(right["factor"]) / float(left["factor"]) - 1.0)
    separated, gap = _interval_gap(left, right)
    return {
        "status": "PASS",
        "change": change,
        "previous_point": left,
        "current_point": right,
        "adjacent_factor_jump": adjacent_jump,
        "adjacent_intervals_separated": separated,
        "adjacent_quantization_interval_gap": gap,
        "nearest_events_within_30_calendar_days": _nearest_events(events, trade_date, 30),
        "diagnostic_boundary": (
            "This is diagnostic evidence only. It does not change the frozen factor-change tolerance, "
            "does not reclassify any corporate-action gate, and cannot turn NOT VERIFIED into PASS."
        ),
    }


def main() -> int:
    evidence_dir = ROOT / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    client = NetClient(evidence_dir / "corporate_action_diagnostic_network.jsonl", max_attempts=3)

    qfq_rows, qfq_meta = fetch_daily_bars_tencent_full(client, "600000", 500, adjustment="qfq")
    raw_rows, raw_meta = fetch_daily_bars_tencent_full(client, "600000", 500, adjustment="raw")
    events, event_meta = fetch_share_bonus_events(client, "600000", 100)

    lineage = verify_corporate_action_lineage(
        qfq_rows,
        raw_rows,
        events,
        qfq_meta,
        raw_meta,
        event_meta,
    )

    points = _factor_points(qfq_rows, raw_rows)
    by_date = {point["trade_date"]: point for point in points}
    unexplained = [
        _adjacent_detail(change, by_date, events)
        for change in lineage.get("unexplained_changes", [])
    ]
    matched = [
        _adjacent_detail(item.get("factor_change", {}), by_date, events)
        for item in lineage.get("matched_events", [])
    ]

    report = {
        "schema": "rmf-corporate-action-adjacent-diagnostic-v1",
        "status": "PASS",
        "symbol": "600000",
        "diagnostic_only": True,
        "acceptance_thresholds_changed": False,
        "lineage_status": lineage.get("status"),
        "lineage_point_in_time": lineage.get("point_in_time_lineage"),
        "lineage_significant_factor_changes": lineage.get("significant_factor_changes"),
        "lineage_verified_event_count": lineage.get("verified_event_count"),
        "lineage_unexplained_factor_changes": lineage.get("unexplained_factor_changes"),
        "qfq_payload_sha256": qfq_meta.get("payload_sha256"),
        "raw_payload_sha256": raw_meta.get("payload_sha256"),
        "event_payload_sha256": event_meta.get("payload_sha256"),
        "unexplained_adjacent_diagnostics": unexplained,
        "matched_adjacent_diagnostics": matched,
        "lineage_evidence": lineage,
        "rule": (
            "Diagnostic execution PASS only proves the evidence was collected and quantified. "
            "Corporate-action PIT remains governed by the existing production verifier."
        ),
    }

    output = evidence_dir / "corporate_action_adjacent_diagnostic.json"
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
