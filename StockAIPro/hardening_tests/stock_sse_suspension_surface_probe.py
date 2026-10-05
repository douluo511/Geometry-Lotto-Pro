from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


BASE_URL = "https://www.sse.com.cn/disclosure/dealinstruc/suspension/stock/"
PUBLIC_DATA_URL = "https://www.sse.com.cn/market/publicdata/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36"
    ),
    "Referer": "https://www.sse.com.cn/",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
MARKERS = (
    "停牌起始日",
    "停牌终止日",
    "停牌时间",
    "停(复)牌原因",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_text(raw: bytes, encoding: str | None) -> str:
    text = raw.decode(encoding or "utf-8", errors="replace")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch(session: requests.Session, url: str, *, params: dict | None = None, attempts: int = 3) -> dict:
    errors: list[dict] = []
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(
                url,
                params=params,
                headers=HEADERS,
                timeout=(8, 20),
                allow_redirects=True,
            )
            final = urlparse(response.url)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            if final.scheme != "https" or not final.hostname or not final.hostname.endswith("sse.com.cn"):
                raise RuntimeError(f"unexpected final URL: {response.url}")
            raw = response.content
            if len(raw) < 500:
                raise RuntimeError(f"implausibly small response: {len(raw)} bytes")
            text = canonical_text(raw, response.encoding)
            return {
                "attempts": attempt,
                "prior_errors": errors,
                "requested_url": url,
                "params": dict(params or {}),
                "final_url": response.url,
                "status_code": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "content_length": len(raw),
                "raw_sha256": sha256_bytes(raw),
                "canonical_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "marker_presence": {marker: marker in text for marker in MARKERS},
                "query_sse_literal_present": "query.sse.com.cn" in text,
                "common_query_literal_present": "commonQuery.do" in text,
                "json_literal_present": "application/json" in text.lower(),
                "no_data_literal_present": "暂无数据" in text,
            }
        except Exception as exc:
            errors.append(
                {
                    "attempt": attempt,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            if attempt == attempts:
                raise RuntimeError(
                    "SSE surface fetch failed after finite retries: "
                    + json.dumps(errors, ensure_ascii=False)
                ) from exc
            time.sleep(1.25 * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


def main() -> int:
    session = requests.Session()
    base = fetch(session, BASE_URL)
    recent = fetch(
        session,
        BASE_URL,
        params={"beginDate": "2026-09-01", "endDate": "2026-09-30"},
    )
    historical = fetch(
        session,
        BASE_URL,
        params={"beginDate": "2017-01-01", "endDate": "2017-01-31"},
    )
    directory = fetch(session, PUBLIC_DATA_URL)

    surface_fields = all(base["marker_presence"].values())
    parameter_sensitive = len(
        {
            base["canonical_text_sha256"],
            recent["canonical_text_sha256"],
            historical["canonical_text_sha256"],
        }
    ) > 1
    explicit_query_literal = any(
        x["query_sse_literal_present"] or x["common_query_literal_present"]
        for x in (base, recent, historical)
    )

    # Diagnostic execution PASS means the official public surfaces were reached
    # reproducibly and inspected. It does NOT claim that a stable machine-readable
    # historical bulk endpoint exists. Absence from static HTML is not proof of
    # non-existence, so the business gate remains fail-closed.
    report = {
        "schema": "stock-ai-sse-suspension-surface-diagnostic-v1",
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "authoritative_product_head": "43168d9e75c70ab55be808d8a51f0c0eb14d83d5",
        "product_bytes_changed": False,
        "official_surfaces": {
            "suspension_stock": base,
            "suspension_stock_recent_range": recent,
            "suspension_stock_historical_range": historical,
            "public_data_directory": directory,
        },
        "adjudication": {
            "official_public_surface_https_reachable": "PASS",
            "suspension_table_field_surface": "SUPPORTED" if surface_fields else "NOT VERIFIED",
            "date_query_changes_static_surface": "SUPPORTED" if parameter_sensitive else "NOT VERIFIED",
            "explicit_machine_query_endpoint_in_static_html": (
                "SUPPORTED" if explicit_query_literal else "NOT VERIFIED"
            ),
            "stable_public_bulk_historical_suspension_endpoint": "NOT VERIFIED",
            "historical_daily_suspension_state": "NOT VERIFIED",
            "shanghai_historical_st_pit": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
        },
        "boundary": (
            "This probe verifies reachability and the static public SSE suspension surface only. "
            "It does not infer a hidden JavaScript/API endpoint from absence or presence of literals, "
            "and it does not convert a public page shell into point-in-time historical suspension evidence."
        ),
        "final_gate": "FAIL",
    }

    with open("stock_sse_suspension_surface_diagnostic.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))

    if report["adjudication"]["official_public_surface_https_reachable"] != "PASS":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
