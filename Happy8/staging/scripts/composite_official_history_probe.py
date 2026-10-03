from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jiangsu_history_probe import inspect_page as inspect_jiangsu_page  # noqa: E402
from jiangxi_fuzhou_history_probe import inspect_page as inspect_fuzhou_page  # noqa: E402

MAX_FUZHOU_PAGES = 30
MAX_JIANGSU_PAGES = 150


def _add_unique(mapping: dict[str, object], issue: str, value: object, conflicts: list[dict], source: str) -> None:
    existing = mapping.get(issue)
    if existing is None:
        mapping[issue] = value
        return
    if existing != value:
        conflicts.append({
            "source": source,
            "issue": issue,
            "first": existing,
            "second": value,
        })


def _fuzhou_history() -> tuple[dict[str, list[int]], list[dict], list[dict]]:
    first = inspect_fuzhou_page(1)
    pages = first.get("pagination_pages") or []
    max_page = max(pages, default=1)
    if max_page < 21:
        raise RuntimeError(f"Fuzhou pagination did not reach known early-history page 21: max={max_page}")
    if max_page > MAX_FUZHOU_PAGES:
        raise RuntimeError(f"Fuzhou pagination exceeded safety bound: {max_page}>{MAX_FUZHOU_PAGES}")

    number_map: dict[str, list[int]] = {}
    conflicts: list[dict] = []
    receipts: list[dict] = []

    for page_no in range(1, max_page + 1):
        page = first if page_no == 1 else inspect_fuzhou_page(page_no)
        rows = page.get("rows") or []
        if page.get("http_status") != 200 or not page.get("official_https_host") or not page.get("authority_marker"):
            raise RuntimeError(f"Fuzhou page authority/network validation failed: page={page_no}")
        for row in rows:
            issue = str(row.get("issue") or "")
            numbers = [int(x) for x in (row.get("numbers") or [])]
            if len(numbers) != 20 or len(set(numbers)) != 20 or not all(1 <= x <= 80 for x in numbers):
                raise RuntimeError(f"Fuzhou invalid 20-number row: page={page_no} issue={issue}")
            _add_unique(number_map, issue, numbers, conflicts, "jiangxi_fuzhou")
        receipts.append({
            "page": page_no,
            "final_url": page.get("final_url"),
            "http_status": page.get("http_status"),
            "bytes": page.get("bytes"),
            "sha256": page.get("sha256"),
            "row_count": len(rows),
            "authority_marker": page.get("authority_marker"),
        })

    return number_map, receipts, conflicts


def _jiangsu_dates() -> tuple[dict[str, str], list[dict], list[dict]]:
    sentinel_issue = "2021016"
    sentinel = inspect_jiangsu_page(1, sentinel_issue)
    sentinel_matches = [
        hint for hint in (sentinel.get("cwl_announcement_date_hints") or [])
        if str(hint.get("issue") or "") == sentinel_issue
    ]
    if sentinel.get("http_status") != 200 or len(sentinel_matches) != 1:
        raise RuntimeError(
            "Jiangsu required historical issue-date evidence unavailable: "
            f"issue={sentinel_issue} status={sentinel.get('http_status')} "
            f"matches={sentinel_matches!r}"
        )

    first = inspect_jiangsu_page(1)
    pages = first.get("pagination_pages") or []
    max_page = max(pages, default=1)
    if max_page < 100:
        raise RuntimeError(f"Jiangsu pagination unexpectedly short: max={max_page}")
    if max_page > MAX_JIANGSU_PAGES:
        raise RuntimeError(f"Jiangsu pagination exceeded safety bound: {max_page}>{MAX_JIANGSU_PAGES}")

    date_map: dict[str, str] = {}
    conflicts: list[dict] = []
    receipts: list[dict] = []

    for page_no in range(1, max_page + 1):
        page = first if page_no == 1 else inspect_jiangsu_page(page_no)
        if page.get("http_status") != 200:
            raise RuntimeError(f"Jiangsu page HTTP failure: page={page_no} status={page.get('http_status')}")
        hints = page.get("cwl_announcement_date_hints") or []
        for hint in hints:
            issue = str(hint.get("issue") or "")
            day = str(hint.get("date") or "")
            if len(issue) != 7 or not issue.isdigit() or len(day) != 10:
                raise RuntimeError(f"Jiangsu malformed issue/date hint: page={page_no} hint={hint}")
            _add_unique(date_map, issue, day, conflicts, "jiangsu")
        receipts.append({
            "page": page_no,
            "final_url": page.get("final_url"),
            "http_status": page.get("http_status"),
            "bytes": page.get("bytes"),
            "sha256": page.get("sha256"),
            "issue_count": len(page.get("issue_tokens") or []),
            "date_hint_count": len(hints),
        })

    return date_map, receipts, conflicts


def inspect() -> dict:
    report = {
        "schema": "happy8-two-official-source-full-history-reconciliation-v1",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "classification_claim": "COMPOSITE_FULL_HISTORY_CANDIDATE_ONLY",
        "composite_candidate": False,
        "checks": {},
        "note": (
            "Diagnostic only. Jiangxi Fuzhou supplies issue->20 numbers; Jiangsu official index supplies "
            "issue-bound CWL announcement URL dates. Production admission requires frozen start/date-order "
            "validation, complete set reconciliation plus an independent "
            "current-draw crosscheck in the production source chain."
        ),
    }
    try:
        numbers, fuzhou_receipts, fuzhou_conflicts = _fuzhou_history()
        dates, jiangsu_receipts, jiangsu_conflicts = _jiangsu_dates()

        number_issues = set(numbers)
        missing_date_issues = sorted(number_issues - set(dates))
        if len(missing_date_issues) > 20:
            raise RuntimeError(
                f"Jiangsu date fallback safety bound exceeded: {len(missing_date_issues)}"
            )
        exact_search_receipts = []
        for issue in missing_date_issues:
            page = inspect_jiangsu_page(1, issue)
            if page.get("http_status") != 200:
                raise RuntimeError(
                    f"Jiangsu exact issue search HTTP failure: issue={issue} "
                    f"status={page.get('http_status')}"
                )
            matching = [
                hint for hint in (page.get("cwl_announcement_date_hints") or [])
                if str(hint.get("issue") or "") == issue
            ]
            if len(matching) != 1:
                raise RuntimeError(
                    f"Jiangsu exact issue search did not yield exactly one visible date: "
                    f"issue={issue} matches={matching!r}"
                )
            _add_unique(
                dates,
                issue,
                str(matching[0].get("date") or ""),
                jiangsu_conflicts,
                "jiangsu_exact_issue_search",
            )
            exact_search_receipts.append({
                "issue": issue,
                "final_url": page.get("final_url"),
                "http_status": page.get("http_status"),
                "bytes": page.get("bytes"),
                "sha256": page.get("sha256"),
                "visible_pair_count": len(matching),
            })

        date_issues = set(dates)
        only_numbers = sorted(number_issues - date_issues)
        only_dates = sorted(date_issues - number_issues)
        common = sorted(number_issues & date_issues)

        first_issue = min(common) if common else None
        latest_issue = max(common) if common else None
        first_draw = None
        latest_draw = None
        if first_issue:
            first_draw = {
                "issue": first_issue,
                "date": dates[first_issue],
                "numbers": numbers[first_issue],
            }
        if latest_issue:
            latest_draw = {
                "issue": latest_issue,
                "date": dates[latest_issue],
                "numbers": numbers[latest_issue],
            }

        ordered_date_issues = sorted(date_issues)
        date_order_strict = True
        prior_day = None
        for issue in ordered_date_issues:
            current_day = datetime.strptime(dates[issue], "%Y-%m-%d").date()
            if prior_day is not None and current_day <= prior_day:
                date_order_strict = False
                break
            prior_day = current_day

        checks = {
            "fuzhou_no_conflicts": not fuzhou_conflicts,
            "jiangsu_no_conflicts": not jiangsu_conflicts,
            "number_history_starts_2020001": min(number_issues, default=None) == "2020001",
            "date_history_starts_2020001": min(date_issues, default=None) == "2020001",
            "date_start_anchor_2020_10_28": dates.get("2020001") == "2020-10-28",
            "date_order_strict": date_order_strict,
            "sets_equal": number_issues == date_issues,
            "no_missing_number_issues": not only_dates,
            "no_missing_date_issues": not only_numbers,
            "latest_issue_equal": max(number_issues, default=None) == max(date_issues, default=None),
            "minimum_history_size": len(common) >= 2000,
            "first_draw_complete": bool(
                first_draw
                and len(first_draw["date"]) == 10
                and len(first_draw["numbers"]) == 20
            ),
            "latest_draw_complete": bool(
                latest_draw
                and len(latest_draw["date"]) == 10
                and len(latest_draw["numbers"]) == 20
            ),
        }

        report.update({
            "checks": checks,
            "composite_candidate": all(checks.values()),
            "fuzhou_number_issue_count": len(number_issues),
            "jiangsu_date_issue_count": len(date_issues),
            "matched_issue_count": len(common),
            "first_issue": first_issue,
            "latest_issue": latest_issue,
            "first_draw": first_draw,
            "latest_draw": latest_draw,
            "only_in_fuzhou_numbers": only_numbers[:100],
            "only_in_jiangsu_dates": only_dates[:100],
            "only_in_fuzhou_count": len(only_numbers),
            "only_in_jiangsu_count": len(only_dates),
            "fuzhou_conflicts": fuzhou_conflicts[:20],
            "jiangsu_conflicts": jiangsu_conflicts[:20],
            "fuzhou_page_receipts": fuzhou_receipts,
            "jiangsu_page_receipts": jiangsu_receipts,
            "jiangsu_exact_issue_search_receipts": exact_search_receipts,
        })
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = inspect()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report.get("status") != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
