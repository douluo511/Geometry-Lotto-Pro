from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.net_client import NetClient  # noqa: E402

BASE_URL = "https://www.jxfzfc.cn/lottery.php"
AUTHORITY_MARKER = "抚州市慈善和福利彩票事业发展中心"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    "Referer": "https://www.jxfzfc.cn/",
}
NET = NetClient(connect_timeout=8, read_timeout=20, max_attempts=2)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _plain(markup: str) -> str:
    value = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", markup)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _official(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.lower() == "https" and parsed.hostname in {"www.jxfzfc.cn", "jxfzfc.cn"}


def _parse_rows(markup: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for body in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", markup):
        cells = [_plain(cell) for cell in re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", body)]
        row_text = " ".join(cells)
        issue_match = re.search(r"(?<!\d)(20\d{5})(?!\d)", row_text)
        if not issue_match:
            continue
        issue = issue_match.group(1)
        numbers = []
        for cell in cells:
            token = cell.strip()
            if re.fullmatch(r"0?[1-9]|[1-7]\d|80", token):
                numbers.append(int(token))
        if len(numbers) != 20 or len(set(numbers)) != 20 or not all(1 <= n <= 80 for n in numbers):
            continue
        if issue in seen:
            continue
        seen.add(issue)
        date_match = re.search(r"(?<!\d)(20\d{2}-\d{2}-\d{2})(?!\d)", row_text)
        rows.append({
            "issue": issue,
            "date": date_match.group(1) if date_match else None,
            "numbers": numbers,
        })
    return sorted(rows, key=lambda row: row["issue"])


def inspect_page(page: int | None) -> dict:
    params = {"play": "kl8", "sid": "new"}
    if page is not None:
        params["page"] = str(page)
    response = NET.get(BASE_URL, params=params, headers=HEADERS, timeout=(8, 20), allow_redirects=True)
    raw = bytes(response.content)
    final_url = str(getattr(response, "url", "") or BASE_URL)
    markup = _decode(raw)
    plain = _plain(markup)
    pages = []
    for href in re.findall(r"(?is)href\s*=\s*['\"]([^'\"]+)['\"]", markup):
        absolute = urljoin(final_url, html.unescape(href))
        parsed = urlsplit(absolute)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if parsed.hostname in {"www.jxfzfc.cn", "jxfzfc.cn"} and query.get("play") == "kl8" and "page" in query:
            try:
                pages.append(int(query["page"]))
            except Exception:
                pass
    return {
        "requested_page": page,
        "final_url": final_url,
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", "")),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "attempts": list(getattr(response, "happy8_attempts", ())),
        "official_https_host": _official(final_url),
        "authority_marker": AUTHORITY_MARKER in plain,
        "rows": _parse_rows(markup),
        "pagination_pages": sorted(set(pages)),
        "date_tokens": sorted(set(re.findall(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)", plain)))[:50],
        "text_head": plain[:1000],
    }


def inspect() -> dict:
    report = {
        "schema": "happy8-jiangxi-fuzhou-number-history-probe-v1",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "classification_claim": "NUMBER_HISTORY_CANDIDATE_ONLY",
        "pages": [],
        "checks": {},
        "note": (
            "Diagnostic only. This source is not production-admitted here. "
            "Production Draw records still require a verified issue-date contract and full cross-source reconciliation."
        ),
    }
    try:
        current = inspect_page(None)
        early = inspect_page(21)
        report["pages"] = [current, early]
        current_rows = current.get("rows") or []
        early_rows = early.get("rows") or []
        early_map = {row["issue"]: row for row in early_rows}
        latest_issue = max((row["issue"] for row in current_rows), default=None)
        max_page = max(
            [p for page in report["pages"] for p in page.get("pagination_pages", [])],
            default=None,
        )
        report["checks"] = {
            "all_http_200": all(page.get("http_status") == 200 for page in report["pages"]),
            "all_official_https": all(page.get("official_https_host") for page in report["pages"]),
            "authority_marker_present": all(page.get("authority_marker") for page in report["pages"]),
            "current_20_number_rows": bool(current_rows),
            "early_2020001_20_numbers": "2020001" in early_map,
            "pagination_reaches_page_21": bool(max_page and max_page >= 21),
        }
        report["latest_issue_seen"] = latest_issue
        report["earliest_anchor"] = early_map.get("2020001")
        report["max_pagination_page_seen"] = max_page
        report["dates_machine_readable_in_rows"] = any(
            row.get("date")
            for page in report["pages"]
            for row in page.get("rows", [])
        )
        report["contract_discovery"] = (
            "JIANGXI_FUZHOU_NUMBER_HISTORY_CANDIDATE"
            if all(report["checks"].values())
            else "JIANGXI_FUZHOU_NUMBER_HISTORY_INCOMPLETE"
        )
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
