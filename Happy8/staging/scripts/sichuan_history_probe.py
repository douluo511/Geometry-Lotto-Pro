from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.net_client import NetClient

PAGE_URL = "https://www.scflcp.com.cn/kl8"
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
    plain = _plain(markup)
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
    issue = None
    m = re.search(r"第\s*(20\d{5})\s*期", plain)
    if m:
        issue = m.group(1)
    dates = re.findall(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}", plain)
    return {
        "url": str(response.url),
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", "")),
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
        "script_srcs": [],
        "inline_hints": [],
        "detail_probes": [],
        "note": "Diagnostic only; production admission requires complete historical coverage and provenance validation.",
    }

    for attrs, body in re.findall(r"(?is)<select\b([^>]*)>(.*?)</select>", markup):
        options = []
        for opt_attrs, opt_body in re.findall(r"(?is)<option\b([^>]*)>(.*?)</option>", body):
            label = _plain(opt_body)[:160]
            vm = re.search(r"(?i)\bvalue\s*=\s*['\"]?([^'\"\s>]+)", opt_attrs)
            options.append({"value": html.unescape(vm.group(1)) if vm else "", "label": label})
        report["selects"].append({"attrs": re.sub(r"\s+", " ", attrs)[:500], "options": options[:1000]})

    links = []
    for href, body in re.findall(r"(?is)<a\b[^>]*href\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", markup):
        absolute = urljoin(final_url, html.unescape(href))
        label = _plain(body)[:240]
        if _official(absolute) and re.search(r"/kl8/(?:\d+\.jhtml|[^?#]+)", urlsplit(absolute).path):
            links.append({"label": label, "url": absolute})
    dedup = []
    seen = set()
    for row in links:
        if row["url"] not in seen:
            seen.add(row["url"])
            dedup.append(row)
    report["detail_links"] = dedup[:300]

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

    probe_urls = [row["url"] for row in dedup[:3]]
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
    report["checks"] = {
        "official_https": _official(final_url),
        "current_numbers_machine_readable": bool(report["page"]["number_candidates"]),
        "detail_links_discovered": bool(dedup),
        "detail_probe_numbers": any(x.get("numbers") for x in report["detail_probes"]),
        "issue_navigation_discovered": bool(option_issues or report["inline_hints"]),
    }
    report["option_issue_first"] = option_issues[:20]
    report["option_issue_last"] = option_issues[-20:]
    report["contract_discovery"] = (
        "SICHUAN_HISTORY_CONTRACT_CANDIDATE"
        if all(report["checks"].values())
        else "SICHUAN_HISTORY_CONTRACT_INCOMPLETE"
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
