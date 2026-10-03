from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import requests
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from happy8.net_client import NetClient

BASE = "https://www.gdfc.org.cn/datas/drawinfo/kl8/draw_{issue}.html"
HEBEI_URL = "https://www.hebfucai.cn/game/kl8Announce"
HEBEI_NUMBER_URL = "https://www.hebfucai.cn/getKl8LotteryNumber"
ISSUES = ("2020001", "2021001", "2025231")
NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8OfficialProbe/0.1",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": "https://www.gdfc.org.cn/",
}

GD_HEADER_PROFILES = {
    "standard_chrome": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    },
    "standard_chrome_with_referer": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": "https://www.gdfc.org.cn/",
    },
}


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


def inspect_issue(issue: str) -> dict:
    url = BASE.format(issue=issue)
    record = {"issue": issue, "url": url, "source": "guangdong_welfare_lottery", "release_gate": "DIAGNOSTIC_ONLY"}
    try:
        response = NET.get(url, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
        raw = bytes(response.content)
        final_url = str(getattr(response, "url", "") or url)
        parsed = urlsplit(final_url)
        expected = urlsplit(url)
        record.update({
            "http_status": int(response.status_code),
            "final_url": final_url,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "content_type": str(response.headers.get("Content-Type", "")),
            "attempts": list(getattr(response, "happy8_attempts", ())),
            "official_https_host": parsed.scheme.lower() == "https" and parsed.hostname == expected.hostname,
        })
        if int(response.status_code) != 200 or not record["official_https_host"]:
            record["diagnostic"] = "HTTP_OR_HOST_NOT_USABLE"
            return record

        markup = _decode(raw)
        plain = _plain(markup)
        title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
        record["title"] = _plain(title_match.group(1))[:180] if title_match else ""
        record["issue_visible"] = issue in plain
        date_match = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})", plain)
        record["visible_date"] = "-".join(x.zfill(2) for x in date_match.groups()) if date_match else None

        image_srcs = [
            html.unescape(x)[:300]
            for x in re.findall(r"(?is)<img\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", markup)
        ]
        script_srcs = [
            html.unescape(x)[:300]
            for x in re.findall(r"(?is)<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", markup)
        ]
        record["image_srcs"] = image_srcs[:120]
        record["script_srcs"] = script_srcs[:80]

        candidate_attrs = []
        for tag in re.findall(r"(?is)<(?:span|li|div|img|input)\b[^>]*>", markup):
            if re.search(r"(?i)(?:ball|num|code|result|kj|open|award|lottery|号码|开奖)", tag):
                candidate_attrs.append(re.sub(r"\s+", " ", tag)[:500])
                if len(candidate_attrs) >= 80:
                    break
        record["candidate_markup"] = candidate_attrs

        compact20 = []
        for m in re.finditer(r"(?<!\d)((?:0?[1-9]|[1-7]\d|80)(?:[\s,，|;/\-]+(?:0?[1-9]|[1-7]\d|80)){19})(?!\d)", plain):
            nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
            if len(nums) == 20 and len(set(nums)) == 20 and all(1 <= n <= 80 for n in nums):
                compact20.append(nums)
                if len(compact20) >= 8:
                    break
        record["visible_20_number_candidates"] = compact20

        src_number_hints = []
        for src in image_srcs:
            nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", src)]
            if any(1 <= n <= 80 for n in nums):
                src_number_hints.append({"src": src, "tokens": [n for n in nums if 1 <= n <= 80][:30]})
                if len(src_number_hints) >= 80:
                    break
        record["image_number_hints"] = src_number_hints

        markers = {}
        for marker in ("本期中奖号码", "中奖号码", "开奖号码", "开奖公告"):
            pos = plain.find(marker)
            if pos >= 0:
                markers[marker] = plain[max(0, pos - 120):pos + 700]
        record["text_markers"] = markers
        record["diagnostic"] = (
            "MACHINE_READABLE_20_NUMBERS_VISIBLE"
            if compact20 else
            "HTML_REQUIRES_FURTHER_CONTRACT_DISCOVERY"
        )
        return record
    except Exception as exc:
        record["diagnostic"] = "REQUEST_OR_PARSE_ERROR"
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record



def inspect_hebei_contract() -> dict:
    url = HEBEI_URL
    record = {
        "url": url,
        "source": "hebei_welfare_lottery",
        "release_gate": "DIAGNOSTIC_ONLY",
    }
    headers = dict(HEADERS)
    headers["Referer"] = "https://www.hebfucai.cn/"
    try:
        response = NET.get(url, headers=headers, timeout=(10, 30), allow_redirects=True)
        raw = bytes(response.content)
        final_url = str(getattr(response, "url", "") or url)
        parsed = urlsplit(final_url)
        expected = urlsplit(url)
        record.update({
            "http_status": int(response.status_code),
            "final_url": final_url,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "content_type": str(response.headers.get("Content-Type", "")),
            "attempts": list(getattr(response, "happy8_attempts", ())),
            "official_https_host": parsed.scheme.lower() == "https" and parsed.hostname == expected.hostname,
        })
        if int(response.status_code) != 200 or not record["official_https_host"]:
            record["diagnostic"] = "HTTP_OR_HOST_NOT_USABLE"
            return record

        markup = _decode(raw)
        plain = _plain(markup)
        title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", markup)
        record["title"] = _plain(title_match.group(1))[:180] if title_match else ""

        forms = [
            re.sub(r"\s+", " ", tag)[:500]
            for tag in re.findall(r"(?is)<form\b[^>]*>", markup)[:30]
        ]
        selects = [
            re.sub(r"\s+", " ", tag)[:500]
            for tag in re.findall(r"(?is)<select\b[^>]*>", markup)[:30]
        ]
        option_pairs = []
        for attrs, body in re.findall(r"(?is)<option\b([^>]*)>(.*?)</option>", markup)[:3000]:
            text_value = _plain(body)[:120]
            value_match = re.search(r"(?i)\bvalue\s*=\s*['\"]?([^'\"\s>]+)", attrs)
            raw_value = html.unescape(value_match.group(1))[:160] if value_match else ""
            issue_match = re.search(r"20\d{5}", text_value)
            option_pairs.append({
                "value": raw_value,
                "text": text_value,
                "issue": issue_match.group(0) if issue_match else None,
            })
        option_issues = [x["issue"] for x in option_pairs if x["issue"]]
        record["forms"] = forms
        record["selects"] = selects
        record["option_count"] = len(option_pairs)
        record["option_issue_count"] = len(option_issues)
        record["option_pairs_first"] = option_pairs[:10]
        record["option_pairs_last"] = option_pairs[-10:]
        record["option_issue_first"] = option_issues[:10]
        record["option_issue_last"] = option_issues[-10:]

        script_srcs = [
            html.unescape(x)[:400]
            for x in re.findall(r"(?is)<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", markup)
        ]
        record["script_srcs"] = script_srcs[:120]

        inline_hints = []
        for body in re.findall(r"(?is)<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", markup):
            compact = re.sub(r"\s+", " ", body)
            for match in re.finditer(
                r"(?i).{0,140}(?:kl8|issue|period|announce|ajax|fetch|select|开奖|期号).{0,260}",
                compact,
            ):
                inline_hints.append(match.group(0)[:500])
                if len(inline_hints) >= 100:
                    break
            if len(inline_hints) >= 100:
                break
        record["inline_hints"] = inline_hints

        urls = []
        for value in re.findall(r"""(?is)(?:https?://[^'"\s<>]+|/[A-Za-z0-9_./?=&%-]{4,})""", markup):
            if re.search(r"(?i)(?:kl8|announce|issue|period|draw|lottery|kj|api)", value):
                value = html.unescape(value)[:500]
                if value not in urls:
                    urls.append(value)
                if len(urls) >= 120:
                    break
        record["contract_url_hints"] = urls

        candidates = []
        for m in re.finditer(
            r"(?<!\d)((?:0?[1-9]|[1-7]\d|80)(?:[\s,，|;/\-]+(?:0?[1-9]|[1-7]\d|80)){19})(?!\d)",
            plain,
        ):
            nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
            if len(nums) == 20 and len(set(nums)) == 20 and all(1 <= n <= 80 for n in nums):
                candidates.append(nums)
                if len(candidates) >= 30:
                    break
        record["visible_20_number_candidates"] = candidates
        record["visible_issue_tokens"] = re.findall(r"20\d{5}", plain)[:80]

        def post_number_probe(label: str, lottery_id: str) -> dict:
            probe = {"label": label, "lottery_id": str(lottery_id), "url": HEBEI_NUMBER_URL}
            try:
                post_headers = dict(headers)
                post_headers["X-Requested-With"] = "XMLHttpRequest"
                result = requests.post(
                    HEBEI_NUMBER_URL,
                    data={"lotteryId": str(lottery_id)},
                    headers=post_headers,
                    timeout=(10, 20),
                    allow_redirects=True,
                )
                body = bytes(result.content)
                final = str(result.url)
                probe.update({
                    "http_status": int(result.status_code),
                    "final_url": final,
                    "raw_sha256": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body),
                    "content_type": str(result.headers.get("Content-Type", "")),
                    "official_https_host": (
                        urlsplit(final).scheme.lower() == "https"
                        and urlsplit(final).hostname == urlsplit(HEBEI_NUMBER_URL).hostname
                    ),
                })
                values = []
                try:
                    payload = json.loads(_decode(body))
                    if isinstance(payload, list):
                        for item in payload:
                            if not isinstance(item, dict):
                                continue
                            key = str(item.get("key", "")).strip()
                            value = str(item.get("value", "")).strip()
                            if key == "announceTime":
                                probe["announce_time"] = value
                            if len(values) < 20 and re.fullmatch(r"0?[1-9]|[1-7]\d|80", value):
                                values.append(int(value))
                except Exception as exc:
                    probe["json_error"] = f"{type(exc).__name__}: {exc}"
                probe["first_20_values"] = values
                probe["valid_20_numbers"] = (
                    len(values) == 20 and len(set(values)) == 20 and all(1 <= n <= 80 for n in values)
                )
                probe["body_head"] = _decode(body)[:700]
            except Exception as exc:
                probe["error"] = f"{type(exc).__name__}: {exc}"
            return probe

        post_probes = []
        if option_pairs:
            current = option_pairs[0]
            if current.get("value"):
                post_probes.append(post_number_probe("current_option_value", current["value"]))
            if current.get("issue"):
                post_probes.append(post_number_probe("current_issue_literal", current["issue"]))
        # Keep one negative control proving that the public issue number is not
        # accepted as Hebei's internal lotteryId. Earlier bounded historical-ID
        # sampling was disproved by schema mismatch and is intentionally not
        # repeated on subsequent runs.
        post_probes.append(post_number_probe("early_issue_literal_2021001", "2021001"))
        record["number_endpoint_probes"] = post_probes
        record["diagnostic"] = (
            "HEBEI_CONTRACT_DISCOVERED"
            if selects or inline_hints or urls or option_issues
            else "HEBEI_HTML_HAS_NUMBERS_BUT_NO_QUERY_CONTRACT"
        )
        return record
    except Exception as exc:
        record["diagnostic"] = "REQUEST_OR_PARSE_ERROR"
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record


def inspect_guangdong_header_profiles(issue: str = "2025231") -> list[dict]:
    url = BASE.format(issue=issue)
    probes = []
    for label, headers in GD_HEADER_PROFILES.items():
        row = {"label": label, "issue": issue, "url": url}
        try:
            response = NET.get(
                url,
                headers=headers,
                timeout=(10, 30),
                allow_redirects=True,
            )
            raw = bytes(response.content)
            final_url = str(getattr(response, "url", "") or url)
            parsed = urlsplit(final_url)
            expected = urlsplit(url)
            markup = _decode(raw)
            plain = _plain(markup)
            row.update({
                "http_status": int(response.status_code),
                "final_url": final_url,
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "content_type": str(response.headers.get("Content-Type", "")),
                "attempts": list(getattr(response, "happy8_attempts", ())),
                "official_https_host": (
                    parsed.scheme.lower() == "https"
                    and parsed.hostname == expected.hostname
                ),
                "issue_visible": issue in plain,
                "has_draw_marker": any(
                    marker in plain
                    for marker in ("本期中奖号码", "中奖号码", "开奖号码", "开奖公告")
                ),
                "body_head": plain[:500],
            })
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        probes.append(row)
    return probes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    guangdong = [inspect_issue(issue) for issue in ISSUES]
    hebei = inspect_hebei_contract()
    guangdong_header_profiles = inspect_guangdong_header_profiles()
    report = {
        "schema": "happy8-official-fallback-probe-v4",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "sources": ["guangdong_welfare_lottery", "hebei_welfare_lottery"],
        "issues": list(ISSUES),
        "guangdong_probes": guangdong,
        "guangdong_header_profile_probes": guangdong_header_profiles,
        "hebei_probe": hebei,
        "note": "Diagnostic evidence only. No source is admitted to production without a reproducible historical contract and raw provenance.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
