from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.szse.cn/api/report/ShowReport/data"
HEADERS = {
    "Referer": "https://www.szse.cn/market/product/stock/list/index.html",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
TARGETS = {
    "current": {"SHOWTYPE": "JSON", "CATALOGID": "1110", "TABKEY": "tab1", "PAGENO": "1", "random": "0.1618033988749895"},
    "terminated": {"SHOWTYPE": "JSON", "CATALOGID": "1793_ssgs", "TABKEY": "tab2", "PAGENO": "1", "random": "0.1414213562373095"},
}


def fetch(params: dict[str, str]) -> tuple[bytes, dict]:
    attempts = []
    last_error = None
    for attempt in range(1, 4):
        try:
            r = requests.get(ENDPOINT, params=params, headers=HEADERS, timeout=(15, 35), allow_redirects=True)
            host = (urlparse(r.url).hostname or "").lower()
            attempts.append({"attempt": attempt, "status": r.status_code, "url": r.url})
            if host != "www.szse.cn" and not host.endswith(".szse.cn"):
                raise RuntimeError(f"non-SZSE redirect: {r.url}")
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                if attempt == 3:
                    raise RuntimeError(f"retryable HTTP {r.status_code}")
            elif r.status_code != 200:
                raise RuntimeError(f"non-retryable HTTP {r.status_code}")
            else:
                raw = r.content
                return raw, {
                    "resolved_url": r.url,
                    "status": r.status_code,
                    "content_type": r.headers.get("Content-Type", ""),
                    "bytes": len(raw),
                    "attempt_count": attempt,
                    "attempts": attempts,
                }
        except requests.RequestException as exc:
            last_error = exc
            attempts.append({"attempt": attempt, "transport_error": f"{type(exc).__name__}: {exc}"})
        if attempt < 3:
            time.sleep((2 ** (attempt - 1)) + 0.2 * attempt)
    raise RuntimeError(f"SZSE JSON probe failed; last_error={last_error!r}; attempts={attempts}")


def summarize(raw: bytes, meta: dict) -> dict:
    summary = dict(meta)
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
        summary["json_type"] = type(obj).__name__
        if isinstance(obj, dict):
            summary["top_level_keys"] = sorted(obj.keys())
            for key in ("data", "rows", "result", "pageHelp"):
                value = obj.get(key)
                if isinstance(value, list):
                    summary[f"{key}_len"] = len(value)
                elif isinstance(value, dict):
                    summary[f"{key}_keys"] = sorted(value.keys())[:40]
        elif isinstance(obj, list):
            summary["top_level_len"] = len(obj)
    except Exception as exc:
        summary["json_parse_error"] = f"{type(exc).__name__}: {exc}"
        summary["prefix_utf8"] = raw[:300].decode("utf-8", errors="replace")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    args.raw_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "schema": "stock-szse-showreport-json-discovery-v1",
        "adjudication": "DISCOVERY_ONLY_NOT_ACCEPTANCE",
        "targets": {},
    }
    failures = []
    for name, params in TARGETS.items():
        try:
            raw, meta = fetch(params)
            (args.raw_dir / f"szse_{name}_showreport.json.raw").write_bytes(raw)
            report["targets"][name] = summarize(raw, meta)
        except Exception as exc:
            report["targets"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            failures.append(name)
    args.output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
