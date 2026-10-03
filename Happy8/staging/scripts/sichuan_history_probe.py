from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.net_client import NetClient

PAGE_URL = "https://www.scflcp.com.cn/kl8info.jhtml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8SichuanContractProbe/0.1",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
    "Referer": "https://www.scflcp.com.cn/",
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
    return p.scheme.lower() == "https" and p.hostname in {"www.scflcp.com.cn", "scflcp.com.cn"}


def _numbers(text: str) -> list[list[int]]:
    out = []
    for m in re.finditer(
        r"(?<!\d)((?:0?[1-9]|[1-7]\d|80)(?:[\s,，|;/\-]+(?:0?[1-9]|[1-7]\d|80)){19})(?!\d)",
        text,
    ):
        nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
        if len(nums) == 20 and len(set(nums)) == 20 and all(1 <= n <= 80 for n in nums):
            out.append(nums)
            if len(out) >= 40:
                break
    return out


def _fetch(url: str):
    response = NET.get(url, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = bytes(response.content)
    final_url = str(getattr(response, "url", "") or url)
    if int(response.status_code) != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {final_url}")
    if not _official(final_url):
        raise RuntimeError(f"response left official HTTPS host: {final_url}")
    return response, raw, _decode(raw)


def inspect_detail(url: str) -> dict:
    response, raw, markup = _fetch(url)
    content_type = str(response.headers.get("Content-Type", ""))
    final_url = str(response.url)

    if "pdf" in content_type.lower() or urlsplit(final_url).path.lower().endswith(".pdf"):
        if not raw.startswith(b"%PDF-"):
            raise RuntimeError("Sichuan detail advertised as PDF but payload is not a PDF")
        try:
            reader = PdfReader(BytesIO(raw), strict=False)
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            raise RuntimeError("Sichuan official PDF could not be parsed") from exc
        plain = re.sub(r"\s+", " ", text).strip()
        issue_match = re.search(r"第\s*(20\d{5})\s*期", plain)
        date_match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", plain)
        dates = []
        if date_match:
            dates.append(
                f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
            )
        number_candidates = _numbers(plain)
        return {
            "url": final_url,
            "http_status": int(response.status_code),
            "content_type": content_type,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "title": "四川省快乐8官方开奖公告PDF",
            "issue": issue_match.group(1) if issue_match else None,
            "dates": dates,
            "numbers": number_candidates[:4],
            "pdf_pages": len(reader.pages),
            "pdf_header_valid": True,
            "text_head": plain[:1800],
        }

    plain = _plain(markup)
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
    issue = None
    m = re.search(r"第\s*(20\d{5})\s*期", plain)
    if m:
        issue = m.group(1)
    dates = re.findall(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}", plain)
    return {
        "url": final_url,
        "http_status": int(response.status_code),
        "content_type": content_type,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "title": _plain(title_match.group(1))[:240] if title_match else "",
        "issue": issue,
        "dates": dates[:10],
        "numbers": _numbers(plain)[:3],
        "text_head": plain[:1800],
    }


def inspect() -> dict:
    response, raw, markup = _fetch(PAGE_URL)
    final_url = str(response.url)
    plain = _plain(markup)
    report = {
        "schema": "happy8-sichuan-history-contract-probe-v1",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "page": {
            "final_url": final_url,
            "http_status": int(response.status_code),
            "content_type": str(response.headers.get("Content-Type", "")),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "issue_tokens": re.findall(r"20\d{5}", plain)[:200],
            "number_candidates": _numbers(plain)[:20],
            "attempts": list(getattr(response, "happy8_attempts", ())),
        },
        "selects": [],
        "detail_links": [],
        "navigation_links": [],
        "raw_anchor_tags": [],
        "pagination_hints": [],
        "forms": [],
        "script_srcs": [],
        "inline_hints": [],
        "detail_probes": [],
        "note": "Diagnostic only; production admission requires complete historical coverage and provenance validation.",
    }

    total_match = re.search(r"共\s*(\d+)\s*条记录\s*(\d+)\s*/\s*(\d+)\s*页", plain)
    if total_match:
        report["history_index"] = {
            "total_records": int(total_match.group(1)),
            "current_page": int(total_match.group(2)),
            "total_pages": int(total_match.group(3)),
        }
    else:
        report["history_index"] = None

    def inspect_index_page(page_no: int) -> dict:
        url = PAGE_URL if page_no == 1 else f"https://www.scflcp.com.cn/kl8info_{page_no}.jhtml"
        page_response, page_raw, page_markup = _fetch(url)
        page_plain = _plain(page_markup)
        entries = []

        def add_entry(context: str, href: str) -> None:
            context_plain = _plain(context)
            issue_match = re.search(r"(?<!\d)(20\d{5})(?!\d)", context_plain)
            date_match = re.search(r"20\d{2}-\d{2}-\d{2}", context_plain)
            detail_url = urljoin(str(page_response.url), html.unescape(href))
            detail_path = urlsplit(detail_url).path.lower()
            supported = (
                detail_path.endswith(".pdf")
                or re.search(r"/(?:kl8|kl8info)/\d+\.jhtml$", detail_path)
            )
            if not (issue_match and date_match and supported and _official(detail_url)):
                return
            candidate = {
                "issue": issue_match.group(0),
                "date": date_match.group(0),
                "detail_url": detail_url,
            }
            if candidate not in entries:
                entries.append(candidate)

        for row in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", page_markup):
            for href in re.findall(r"(?is)href\s*=\s*['\"]([^'\"]+)['\"]", row):
                add_entry(row, href)

        for match in re.finditer(
            r"(?is)<a\b[^>]*href\s*=\s*['\"]([^'\"]+\.pdf(?:\?[^'\"]*)?)['\"][^>]*>.*?</a>",
            page_markup,
        ):
            context = page_markup[max(0, match.start() - 1000): min(len(page_markup), match.end() + 250)]
            add_entry(context, match.group(1))
        return {
            "page": page_no,
            "url": str(page_response.url),
            "http_status": int(page_response.status_code),
            "bytes": len(page_raw),
            "sha256": hashlib.sha256(page_raw).hexdigest(),
            "entries": entries,
            "issue_tokens": re.findall(r"20\d{5}", page_plain)[:100],
        }

    total_pages = int(report["history_index"]["total_pages"]) if report["history_index"] else 1
    page_set = sorted(set([1, max(1, total_pages // 2), total_pages]))
    report["history_page_probes"] = []
    for page_no in page_set:
        try:
            report["history_page_probes"].append(inspect_index_page(page_no))
        except Exception as exc:
            report["history_page_probes"].append({
                "page": page_no,
                "error": f"{type(exc).__name__}: {exc}",
            })

    for attrs, body in re.findall(r"(?is)<select\b([^>]*)>(.*?)</select>", markup):
        options = []
        for opt_attrs, opt_body in re.findall(r"(?is)<option\b([^>]*)>(.*?)</option>", body):
            label = _plain(opt_body)[:160]
            vm = re.search(r"(?i)\bvalue\s*=\s*['\"]?([^'\"\s>]+)", opt_attrs)
            options.append({"value": html.unescape(vm.group(1)) if vm else "", "label": label})
        onchange_match = re.search(r"(?i)\bonChange\s*=\s*['\"]([^'\"]*)['\"]", attrs)
        report["selects"].append({
            "attrs": re.sub(r"\s+", " ", attrs)[:1000],
            "onchange": html.unescape(onchange_match.group(1))[:1200] if onchange_match else "",
            "options": options[:1000],
        })

    links = []
    for href, body in re.findall(r"(?is)<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", markup):
        absolute = urljoin(final_url, html.unescape(href))
        label = _plain(body)[:240]
        path = urlsplit(absolute).path.lower()
        if _official(absolute) and (
            re.search(r"/(?:kl8|kl8info)/(?:\d+\.jhtml)$", path)
            or path.endswith(".pdf")
        ):
            links.append({"label": label, "url": absolute})
    dedup = []
    seen = set()
    for row in links:
        if row["url"] not in seen:
            seen.add(row["url"])
            dedup.append(row)
    report["detail_links"] = dedup[:300]

    report["raw_anchor_tags"] = [
        re.sub(r"\\s+", " ", tag)[:1200]
        for tag in re.findall(r"(?is)<a\\b[^>]*>", markup)
        if re.search(r"(?i)(?:下一页|尾页|page|pageno|kl8info)", tag)
    ][:300]

    pagination_hints = []
    for token in re.findall(r"""(?is)(?:href|onclick)\\s*=\\s*['\"]([^'\"]+)['\"]""", markup):
        value = html.unescape(token).strip()
        if re.search(r"(?i)(?:kl8info|page|pageno|next|last|下一页|尾页)", value):
            if value not in pagination_hints:
                pagination_hints.append(value[:1200])
    report["pagination_hints"] = pagination_hints[:500]

    navigation = []
    for href, body in re.findall(
        r"(?is)<a\\b[^>]*href\\s*=\\s*['\\\"]([^'\\\"]+)['\\\"][^>]*>(.*?)</a>",
        markup,
    ):
        absolute = urljoin(final_url, html.unescape(href))
        label = _plain(body)[:240]
        parsed = urlsplit(absolute)
        if not _official(absolute):
            continue
        haystack = f"{parsed.path}?{parsed.query} {label}".lower()
        if "/kl8info" in parsed.path.lower() or any(
            token in haystack for token in ("page", "pageno", "history", "previous", "上一", "下一", "首页", "末页", "尾页")
        ):
            row = {"label": label, "url": absolute}
            if row not in navigation:
                navigation.append(row)
    report["navigation_links"] = navigation[:500]

    forms = []
    for attrs, body in re.findall(r"(?is)<form\\b([^>]*)>(.*?)</form>", markup):
        action_match = re.search(r"(?i)\\baction\\s*=\\s*['\\\"]([^'\\\"]*)['\\\"]", attrs)
        method_match = re.search(r"(?i)\\bmethod\\s*=\\s*['\\\"]([^'\\\"]*)['\\\"]", attrs)
        action = urljoin(final_url, html.unescape(action_match.group(1))) if action_match else final_url
        if not _official(action):
            continue
        inputs = []
        for tag in re.findall(r"(?is)<(?:input|button)\\b[^>]*>", body):
            item = {}
            for key in ("name", "id", "type", "value"):
                m = re.search(rf"(?i)\\b{key}\\s*=\\s*['\\\"]([^'\\\"]*)['\\\"]", tag)
                if m:
                    item[key] = html.unescape(m.group(1))[:200]
            if item:
                inputs.append(item)
        forms.append({
            "action": action,
            "method": (method_match.group(1).upper() if method_match else "GET"),
            "inputs": inputs[:100],
        })
    report["forms"] = forms[:100]

    report["script_srcs"] = [
        urljoin(final_url, html.unescape(src))
        for src in re.findall(r"(?is)<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", markup)
    ][:100]

    for body in re.findall(r"(?is)<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", markup):
        compact = re.sub(r"\s+", " ", body)
        for m in re.finditer(r"(?i).{0,180}(?:kl8|page|issue|ajax|fetch|select|history|开奖|期号).{0,320}", compact):
            row = m.group(0)[:700]
            if row not in report["inline_hints"]:
                report["inline_hints"].append(row)
            if len(report["inline_hints"]) >= 120:
                break
        if len(report["inline_hints"]) >= 120:
            break

    probe_urls = [row["url"] for row in dedup[:2]]
    for page in report.get("history_page_probes", []):
        entries = page.get("entries") or []
        if entries:
            for candidate in (entries[0]["detail_url"], entries[-1]["detail_url"]):
                if candidate not in probe_urls:
                    probe_urls.append(candidate)
    for url in probe_urls:
        try:
            report["detail_probes"].append(inspect_detail(url))
        except Exception as exc:
            report["detail_probes"].append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    option_issues = []
    for select in report["selects"]:
        for option in select["options"]:
            m = re.search(r"20\d{5}", option["label"] + " " + option["value"])
            if m:
                option_issues.append(m.group(0))
    all_history_entries = [
        entry
        for page in report.get("history_page_probes", [])
        for entry in (page.get("entries") or [])
    ]
    earliest_issue = min((x["issue"] for x in all_history_entries), default=None)
    latest_issue = max((x["issue"] for x in all_history_entries), default=None)
    tail_page = next(
        (x for x in report.get("history_page_probes", []) if x.get("page") == total_pages),
        None,
    )
    report["history_coverage_probe"] = {
        "earliest_issue_seen": earliest_issue,
        "latest_issue_seen": latest_issue,
        "tail_page_has_entries": bool(tail_page and tail_page.get("entries")),
        "starts_at_2020001": earliest_issue == "2020001",
    }
    report["checks"] = {
        "official_https": _official(final_url),
        "history_index_detected": bool(report["history_index"]),
        "tail_page_fetched": bool(tail_page and tail_page.get("entries")),
        "detail_links_discovered": bool(dedup or all_history_entries),
        "detail_probe_numbers": any(x.get("numbers") for x in report["detail_probes"]),
        "issue_navigation_discovered": bool(
            report["history_index"]
            or option_issues
            or report["navigation_links"]
            or report["pagination_hints"]
            or report["inline_hints"]
        ),
    }
    report["history_navigation_candidates"] = {
        "navigation_link_count": len(report["navigation_links"]),
        "pagination_hint_count": len(report["pagination_hints"]),
        "raw_anchor_tag_count": len(report["raw_anchor_tags"]),
        "form_count": len(report["forms"]),
        "note": (
            "Diagnostic only. A candidate is not production-qualified until an old issue can be fetched "
            "through a repeatable official HTTPS contract and complete 2020001-to-current coverage is proven."
        ),
    }
    report["option_issue_first"] = option_issues[:20]
    report["option_issue_last"] = option_issues[-20:]
    report["contract_discovery"] = (
        "SICHUAN_FULL_HISTORY_CANDIDATE"
        if all(report["checks"].values()) and report["history_coverage_probe"]["starts_at_2020001"]
        else (
            "SICHUAN_PARTIAL_HISTORY_CONTRACT_PASS"
            if all(report["checks"].values())
            else "SICHUAN_HISTORY_CONTRACT_INCOMPLETE"
        )
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = inspect()
    except Exception as exc:
        report = {
            "schema": "happy8-sichuan-history-contract-probe-v1",
            "status": "FAIL",
            "production_accepted": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report.get("status") != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
