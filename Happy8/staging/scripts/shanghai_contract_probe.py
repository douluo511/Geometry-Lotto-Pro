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

from happy8.net_client import NetClient

PAGE_URL = "https://www.swlc.net.cn/lottery/kl8.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8ShanghaiContractProbe/0.3",
    "Accept": "text/html,application/xhtml+xml,application/javascript,text/javascript,*/*;q=0.5",
    "Referer": "https://www.swlc.net.cn/",
}
NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)

ANCHOR_ISSUES = (
    "2020001",
    "2021001",
    "2022001",
    "2023001",
    "2024001",
    "2025001",
)


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


def _same_official_host(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.lower() == "https" and parsed.hostname == "www.swlc.net.cn"


def _numbers(text: str) -> list[list[int]]:
    out: list[list[int]] = []
    for match in re.finditer(
        r"(?<!\d)((?:0?[1-9]|[1-7]\d|80)(?:[\s,，|;/\-]+(?:0?[1-9]|[1-7]\d|80)){19})(?!\d)",
        text,
    ):
        nums = [int(x) for x in re.findall(r"\d{1,2}", match.group(1))]
        if len(nums) == 20 and len(set(nums)) == 20 and all(1 <= x <= 80 for x in nums):
            if nums not in out:
                out.append(nums)
        if len(out) >= 40:
            break
    return out


def _parse_draw_rows(markup: str) -> list[dict]:
    plain = _plain(markup)
    rows: list[dict] = []
    seen: set[tuple[str, str, tuple[int, ...]]] = set()

    # Production parser contract: issue + ISO date + exactly twenty two-digit numbers.
    pattern = re.compile(
        r"(20\d{5})\s+(20\d{2}-\d{2}-\d{2})(?:\([^)]*\))?\s+((?:\d{2}\s*){20})(?!\d)"
    )
    for issue, day, compact in pattern.findall(plain):
        nums = tuple(int(x) for x in re.findall(r"\d{2}", compact))
        if len(nums) != 20 or len(set(nums)) != 20 or not all(1 <= x <= 80 for x in nums):
            continue
        key = (issue, day, nums)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"issue": issue, "date": day, "numbers": list(nums)})

    # Diagnostic fallback only: inspect DOM/text neighbourhood when exact production
    # row shape is not present. This is evidence, not production admission.
    if not rows:
        for issue_match in re.finditer(r"(?<!\d)(20\d{5})(?!\d)", plain):
            issue = issue_match.group(1)
            window = plain[max(0, issue_match.start() - 120): issue_match.end() + 800]
            date_match = re.search(r"20\d{2}-\d{2}-\d{2}", window)
            candidates = _numbers(window)
            if date_match and candidates:
                key = (issue, date_match.group(0), tuple(candidates[0]))
                if key not in seen:
                    seen.add(key)
                    rows.append({
                        "issue": issue,
                        "date": date_match.group(0),
                        "numbers": candidates[0],
                        "diagnostic_fallback": True,
                    })
    return rows


def _fetch(params: dict[str, str] | None) -> dict:
    response = NET.get(
        PAGE_URL,
        params=params,
        headers=HEADERS,
        timeout=(10, 30),
        allow_redirects=True,
    )
    raw = bytes(response.content)
    final_url = str(getattr(response, "url", "") or PAGE_URL)
    record = {
        "requested_url": PAGE_URL,
        "params": params or {},
        "final_url": final_url,
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", "")),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "official_https_host": _same_official_host(final_url),
        "attempts": list(getattr(response, "happy8_attempts", ())),
        "issue_tokens": [],
        "number_candidates": [],
        "draw_rows": [],
        "form_tags": [],
        "input_tags": [],
        "script_srcs": [],
    }
    if int(response.status_code) != 200 or not record["official_https_host"]:
        record["status"] = "FAIL"
        return record

    parsed = urlsplit(final_url)
    actual_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    record["actual_params"] = actual_params
    if params is not None and actual_params != params:
        record["query_identity"] = "FAIL"
    else:
        record["query_identity"] = "PASS"

    markup = _decode(raw)
    plain = _plain(markup)
    record["issue_tokens"] = sorted(set(re.findall(r"(?<!\d)20\d{5}(?!\d)", plain)))[:300]
    record["number_candidates"] = _numbers(plain)[:40]
    record["draw_rows"] = _parse_draw_rows(markup)[:120]
    record["form_tags"] = [
        re.sub(r"\s+", " ", x)[:800]
        for x in re.findall(r"(?is)<form\b[^>]*>", markup)[:20]
    ]
    record["input_tags"] = [
        re.sub(r"\s+", " ", x)[:800]
        for x in re.findall(r"(?is)<input\b[^>]*>", markup)[:40]
    ]
    record["script_srcs"] = [
        html.unescape(x).strip()
        for x in re.findall(r"(?is)<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", markup)
    ][:100]
    record["text_head"] = plain[:1200]
    record["status"] = "PASS"
    return record


def _script_contract(page_record: dict) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()
    for src in page_record.get("script_srcs", []):
        url = urljoin(str(page_record.get("final_url") or PAGE_URL), src)
        if url in seen or not _same_official_host(url):
            continue
        seen.add(url)
        item = {"src": src, "url": url}
        try:
            response = NET.get(url, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
            body = bytes(response.content)
            final_url = str(getattr(response, "url", "") or url)
            item.update({
                "http_status": int(response.status_code),
                "final_url": final_url,
                "content_type": str(response.headers.get("Content-Type", "")),
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "official_https_host": _same_official_host(final_url),
            })
            text = _decode(body)
            lines = []
            for line in text.replace("\r", "\n").split("\n"):
                if re.search(
                    r"(?i)(?:fetch|ajax|xhr|url\s*:|endpoint|api|history|lottery|issue|start_issue|end_issue|query|previous)",
                    line,
                ):
                    compact = re.sub(r"\s+", " ", line).strip()
                    if compact and compact not in lines:
                        lines.append(compact[:1400])
                    if len(lines) >= 160:
                        break
            item["keyword_lines"] = lines
            # Preserve the complete small official frontend script as diagnostic evidence.
            # This is bounded to avoid unbounded evidence growth; production admission still
            # requires a separately validated source contract.
            if len(body) <= 4096:
                item["body_text"] = text
        except Exception as exc:
            item["error"] = f"{type(exc).__name__}: {exc}"
        records.append(item)
    return records


def inspect() -> dict:
    current = _fetch({"view": "previous", "limit": "100"})
    exact = []
    for issue in ANCHOR_ISSUES:
        exact.append(
            {
                "issue": issue,
                "response": _fetch(
                    {
                        "view": "previous",
                        "start_issue": issue,
                        "end_issue": issue,
                    }
                ),
            }
        )

    range_probe = _fetch(
        {
            "view": "previous",
            "start_issue": "2021001",
            "end_issue": "2021099",
        }
    )

    exact_checks = []
    for item in exact:
        issue = item["issue"]
        response = item["response"]
        matching = [row for row in response.get("draw_rows", []) if row.get("issue") == issue]
        exact_checks.append({
            "issue": issue,
            "http_pass": response.get("status") == "PASS",
            "query_identity": response.get("query_identity"),
            "issue_visible": issue in response.get("issue_tokens", []),
            "machine_readable_draw": bool(matching),
            "matching_rows": matching[:3],
        })

    report = {
        "schema": "happy8-shanghai-frontend-contract-probe-v3",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "current": current,
        "exact_issue_probes": exact,
        "range_probe": range_probe,
        "scripts": _script_contract(current),
        "checks": {
            "current_official_https": current.get("status") == "PASS",
            "current_draws_machine_readable": bool(current.get("draw_rows")),
            "start_issue_2020001_visible": any(
                x["issue"] == "2020001" and x["issue_visible"] for x in exact_checks
            ),
            "start_issue_2020001_machine_readable": any(
                x["issue"] == "2020001" and x["machine_readable_draw"] for x in exact_checks
            ),
            "all_anchor_queries_preserved": all(
                x["query_identity"] == "PASS" for x in exact_checks
            ),
            "all_anchor_draws_machine_readable": all(
                x["machine_readable_draw"] for x in exact_checks
            ),
            "range_query_preserved": range_probe.get("query_identity") == "PASS",
            "range_draws_machine_readable": bool(range_probe.get("draw_rows")),
        },
        "exact_issue_checks": exact_checks,
        "note": (
            "Diagnostic only. Production admission requires start issue 2020001 plus complete "
            "contiguous coverage to current, raw-byte evidence and independent official crosscheck."
        ),
    }

    checks = report["checks"]
    if (
        checks["current_official_https"]
        and checks["current_draws_machine_readable"]
        and checks["start_issue_2020001_machine_readable"]
        and checks["all_anchor_queries_preserved"]
        and checks["all_anchor_draws_machine_readable"]
        and checks["range_query_preserved"]
        and checks["range_draws_machine_readable"]
    ):
        report["contract_discovery"] = "SHANGHAI_FULL_HISTORY_CONTRACT_CANDIDATE"
    elif checks["current_draws_machine_readable"]:
        report["contract_discovery"] = "SHANGHAI_CURRENT_CONTRACT_ONLY"
    else:
        report["contract_discovery"] = "SHANGHAI_HISTORY_CONTRACT_INCOMPLETE"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = inspect()
    except Exception as exc:
        report = {
            "schema": "happy8-shanghai-frontend-contract-probe-v2",
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
