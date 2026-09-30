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

ROOT_URL = "https://www.zhcw.com/kjxx/kl8/"
DETAIL_URL = "https://www.zhcw.com/kjxx/kl8/kjxq/?kjData=2020001"
FIRST_NOTICE_URL = "https://www.zhcw.com/c/2020-10-29/625046.shtml"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Happy8MediaContractProbe/0.1",
    "Accept": "text/html,application/xhtml+xml,application/javascript,text/javascript,*/*;q=0.5",
    "Referer": "https://www.zhcw.com/",
}
NET = NetClient(connect_timeout=10, read_timeout=30, max_attempts=3)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _same_host(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme.lower() == "https" and parsed.hostname in {"www.zhcw.com", "zhcw.com"}


def _fetch(url: str) -> tuple[object, bytes, str]:
    response = NET.get(url, headers=HEADERS, timeout=(10, 30), allow_redirects=True)
    raw = bytes(response.content)
    final_url = str(getattr(response, "url", "") or url)
    if int(response.status_code) != 200:
        raise RuntimeError(f"media HTTP {response.status_code}: {final_url}")
    if not _same_host(final_url):
        raise RuntimeError(f"media response left HTTPS host: {final_url}")
    if not raw:
        raise RuntimeError("media response was empty")
    return response, raw, final_url


def _record(url: str, response: object, raw: bytes, final_url: str) -> dict:
    return {
        "url": url,
        "final_url": final_url,
        "http_status": int(response.status_code),
        "content_type": str(response.headers.get("Content-Type", "")),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "attempts": list(getattr(response, "happy8_attempts", ())),
    }


def _contract_hints(text: str) -> dict:
    urls: list[str] = []
    lines: list[str] = []
    for token in re.findall(r"""(?is)(?:https?://[^'"\s<>]+|/[A-Za-z0-9_./?=&%{}$:+-]{3,})""", text):
        value = html.unescape(token).strip()[:1000]
        if re.search(r"(?i)(?:kl8|kjxx|kaijiang|lottery|history|issue|kjData|page|query|api|ajax)", value):
            if value not in urls:
                urls.append(value)
        if len(urls) >= 250:
            break
    compact = text.replace("\r", "\n")
    for row in compact.split("\n"):
        if re.search(r"(?i)(?:kl8|kjxx|kjData|issue|pageSize|pageNo|history|ajax|fetch|axios|url\s*:|api)", row):
            line = re.sub(r"\s+", " ", row).strip()[:1800]
            if line and line not in lines:
                lines.append(line)
        if len(lines) >= 250:
            break
    return {"url_hints": urls, "keyword_lines": lines}


def inspect() -> dict:
    report = {
        "schema": "happy8-zhcw-designated-media-contract-probe-v1",
        "status": "DIAGNOSTIC_ONLY",
        "production_accepted": False,
        "classification_claim": "NOT_EVALUATED_FOR_PRODUCTION",
        "pages": [],
        "scripts": [],
        "note": (
            "Diagnostic only. This probe does not classify zhcw.com as an official production source. "
            "Production admission would separately require authority/provenance review, reproducible "
            "2020001-to-current history coverage, raw-byte evidence, schema validation and current "
            "crosscheck against an independent official lottery center source."
        ),
    }

    page_markup = ""
    for label, url in (
        ("history_template", ROOT_URL),
        ("first_issue_detail_template", DETAIL_URL),
        ("first_issue_notice", FIRST_NOTICE_URL),
    ):
        try:
            response, raw, final_url = _fetch(url)
            text = _decode(raw)
            item = {"label": label, **_record(url, response, raw, final_url)}
            item["issue_tokens"] = sorted(set(re.findall(r"(?<!\d)20\d{5}(?!\d)", text)))[:200]
            item["number_sequences"] = [
                [int(x) for x in seq]
                for seq in re.findall(
                    r"((?:\b(?:0?[1-9]|[1-7]\d|80)[、,，\s]+){19}\b(?:0?[1-9]|[1-7]\d|80)\b)",
                    re.sub(r"(?is)<[^>]+>", " ", html.unescape(text)),
                )[:20]
                for seq in [re.findall(r"\d{1,2}", seq)]
                if len(seq) == 20
            ]
            item["forms"] = [
                re.sub(r"\s+", " ", x)[:900]
                for x in re.findall(r"(?is)<form\b[^>]*>", text)[:30]
            ]
            item["inputs"] = [
                re.sub(r"\s+", " ", x)[:900]
                for x in re.findall(r"(?is)<input\b[^>]*>", text)[:80]
            ]
            item["script_srcs"] = [
                html.unescape(x).strip()
                for x in re.findall(r"""(?is)<script\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""", text)
            ][:100]
            item.update(_contract_hints(text))
            report["pages"].append(item)
            if label == "history_template":
                page_markup = text
        except Exception as exc:
            report["pages"].append({"label": label, "url": url, "error": f"{type(exc).__name__}: {exc}"})

    if page_markup:
        seen: set[str] = set()
        srcs = [
            html.unescape(x).strip()
            for x in re.findall(r"""(?is)<script\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""", page_markup)
        ]
        for src in srcs:
            url = urljoin(ROOT_URL, src)
            if url in seen or not _same_host(url):
                continue
            seen.add(url)
            record = {"src": src, "url": url}
            try:
                response, raw, final_url = _fetch(url)
                text = _decode(raw)
                record.update(_record(url, response, raw, final_url))
                record.update(_contract_hints(text))
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            if record.get("keyword_lines") or record.get("url_hints"):
                report["scripts"].append(record)
            if len(report["scripts"]) >= 30:
                break

    useful = any(
        page.get("issue_tokens") or page.get("number_sequences") or page.get("url_hints")
        for page in report["pages"]
    ) or any(script.get("url_hints") or script.get("keyword_lines") for script in report["scripts"])
    report["contract_discovery"] = "HINTS_FOUND" if useful else "NO_HISTORY_DATA_CONTRACT_FOUND"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
