from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.net_client import NetClient

BASE = "https://www.jslottery.com/"
HISTORY_URL = "https://www.jslottery.com/winning_history_a"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8JiangsuHistoryProbe/0.1",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
    "Referer": BASE,
}
NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)


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
    p = urlsplit(url)
    return p.scheme.lower() == "https" and p.hostname == "www.jslottery.com"


def _numbers(text: str) -> list[list[int]]:
    out = []
    for m in re.finditer(
        r"(?<!\d)((?:0?[1-9]|[1-7]\d|80)(?:[\s,，|;/\-]+(?:0?[1-9]|[1-7]\d|80)){19})(?!\d)",
        text,
    ):
        nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
        if len(nums) == 20 and len(set(nums)) == 20 and all(1 <= n <= 80 for n in nums):
            out.append(nums)
            if len(out) >= 20:
                break
    return out


def _fetch(url: str, *, params=None) -> tuple[object, bytes, str]:
    response = NET.get(url, params=params, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = bytes(response.content)
    final_url = str(getattr(response, "url", "") or url)
    if int(response.status_code) != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {final_url}")
    if not _official(final_url):
        raise RuntimeError(f"response left official HTTPS host: {final_url}")
    return response, raw, _decode(raw)


def inspect_page(page: int, periods: str = "") -> dict:
    params = {
        "locale": "zh-CN",
        "lottery_type_id": "17",
        "page": str(page),
        "periods": periods,
    }
    response, raw, markup = _fetch(HISTORY_URL, params=params)
    final_url = str(response.url)
    plain = _plain(markup)
    anchors = []
    for href, body in re.findall(r"(?is)<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", markup):
        label = _plain(body)[:240]
        absolute = urljoin(final_url, html.unescape(href))
        if re.search(r"20\d{5}", label) or re.search(r"(?i)(?:winning|lottery|detail|notice|history)", absolute):
            anchors.append({"label": label, "href": html.unescape(href)[:500], "url": absolute[:700]})
    pagination = []
    for href in re.findall(r"(?is)href\s*=\s*['\"]([^'\"]+)['\"]", markup):
        absolute = urljoin(final_url, html.unescape(href))
        parsed = urlsplit(absolute)
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if parsed.hostname == "www.jslottery.com" and "page" in q and q.get("lottery_type_id") == "17":
            try:
                p = int(q["page"])
            except Exception:
                continue
            pagination.append(p)
    issue_contexts = []
    for match in list(re.finditer(r"20\d{5}", markup))[:12]:
        issue_contexts.append(re.sub(r"\s+", " ", markup[max(0, match.start()-500):match.end()+900])[:1600])

    attribute_candidates = []
    for match in re.finditer(
        r"""(?is)\b(?:href|src|onclick|data-[a-z0-9_-]+|value)\s*=\s*['\"]([^'\"]+)['\"]""",
        markup,
    ):
        value = html.unescape(match.group(1)).strip()
        if re.search(r"(?i)(?:2020\d{3}|2021\d{3}|winning|lottery|period|issue|history|detail|ajax)", value):
            if value not in attribute_candidates:
                attribute_candidates.append(value[:1200])

    script_srcs = [
        urljoin(final_url, html.unescape(src))
        for src in re.findall(r"""(?is)<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]""", markup)
    ][:100]
    inline_hints = []
    for body in re.findall(r"(?is)<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", markup):
        compact = re.sub(r"\s+", " ", body)
        for match in re.finditer(
            r"(?i).{0,220}(?:winning_history|lottery_type_id|periods|ajax|fetch|url\s*:|issue|开奖).{0,420}",
            compact,
        ):
            row = match.group(0)[:900]
            if row not in inline_hints:
                inline_hints.append(row)
            if len(inline_hints) >= 100:
                break
        if len(inline_hints) >= 100:
            break

    return {
        "page": page,
        "periods": periods,
        "final_url": final_url,
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", "")),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "attempts": list(getattr(response, "happy8_attempts", ())),
        "issue_tokens": re.findall(r"20\d{5}", plain)[:100],
        "visible_20_number_candidates": _numbers(plain),
        "anchors": anchors[:100],
        "pagination_pages": sorted(set(pagination))[:500],
        "issue_contexts": issue_contexts,
        "attribute_candidates": attribute_candidates[:200],
        "script_srcs": script_srcs,
        "inline_hints": inline_hints,
        "text_head": plain[:1800],
    }


def inspect_detail(url: str) -> dict:
    response, raw, markup = _fetch(url)
    plain = _plain(markup)
    return {
        "url": str(response.url),
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", "")),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "issue_tokens": re.findall(r"20\d{5}", plain)[:30],
        "date_tokens": re.findall(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}", plain)[:20],
        "visible_20_number_candidates": _numbers(plain),
        "text_head": plain[:1600],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = {
        "schema": "happy8-jiangsu-history-contract-probe-v1",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "pages": [],
        "detail_probes": [],
        "note": "Diagnostic only; production admission requires reproducible complete-history coverage, schema validation, provenance and current crosscheck.",
    }
    try:
        for page in (1, 100, 105):
            report["pages"].append(inspect_page(page))
        report["period_searches"] = [
            inspect_page(1, "2020001"),
            inspect_page(1, "2021001"),
        ]
        detail_urls = []
        for page in report["pages"]:
            for anchor in page["anchors"]:
                url = anchor["url"]
                if _official(url) and re.search(r"20\d{5}", anchor["label"]):
                    if url not in detail_urls:
                        detail_urls.append(url)
                if len(detail_urls) >= 4:
                    break
            if len(detail_urls) >= 4:
                break
        for url in detail_urls:
            try:
                report["detail_probes"].append(inspect_detail(url))
            except Exception as exc:
                report["detail_probes"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

        early_visible = any(
            any(issue.startswith(("2020", "2021")) for issue in page["issue_tokens"])
            for page in report["pages"]
        )
        exact_start_search = any(
            "2020001" in page["issue_tokens"] for page in report["period_searches"]
        )
        current_visible = any(
            any(issue.startswith("2026") for issue in page["issue_tokens"])
            for page in report["pages"]
        )
        details_have_numbers = any(x.get("visible_20_number_candidates") for x in report["detail_probes"])
        report["checks"] = {
            "official_https_pages": all(_official(page["final_url"]) for page in report["pages"]),
            "early_history_visible": early_visible,
            "current_history_visible": current_visible,
            "detail_links_discovered": bool(detail_urls),
            "detail_numbers_machine_readable": details_have_numbers,
            "exact_start_issue_search": exact_start_search,
        }
        report["contract_discovery"] = (
            "JIANGSU_HISTORY_CONTRACT_CANDIDATE"
            if all(report["checks"].values())
            else "JIANGSU_HISTORY_CONTRACT_INCOMPLETE"
        )
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report.get("status") != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
