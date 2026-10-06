from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import requests

ENDPOINT = "https://www.bse.cn/nqxxController/nqxxCnzq.do"
HEADERS = {
    "Referer": "https://www.bse.cn/nq/listedcompany.html",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
FORM = [
    ("page", "0"),
    ("typejb", "T"),
    ("xxfcbj[]", "2"),
    ("xxzqdm", ""),
    ("sortfield", "xxzqdm"),
    ("sorttype", "asc"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def official_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "bse.cn" or host.endswith(".bse.cn")


def parse_json_or_jsonp(raw: bytes):
    text = raw.decode("utf-8-sig", errors="strict").strip()
    try:
        return json.loads(text), "JSON"
    except Exception:
        pass
    match = re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.]*\((.*)\)\s*;?", text, flags=re.S)
    if not match:
        raise ValueError("response is neither JSON nor strict JSONP")
    return json.loads(match.group(1)), "JSONP"


def fetch() -> tuple[bytes, dict]:
    attempts = []
    last_error = None
    session = requests.Session()
    for attempt in range(1, 4):
        try:
            r = session.post(
                ENDPOINT,
                data=FORM,
                headers=HEADERS,
                timeout=(15, 35),
                allow_redirects=True,
            )
            rec = {
                "attempt": attempt,
                "status": int(r.status_code),
                "resolved_url": r.url,
                "bytes": len(r.content),
                "sha256": sha256_bytes(r.content),
            }
            attempts.append(rec)
            if not official_host(r.url):
                raise RuntimeError(f"non-BSE redirect: {r.url}")
            if r.status_code == 429 or 500 <= r.status_code <= 599:
                if attempt == 3:
                    raise RuntimeError(f"retryable BSE HTTP {r.status_code}")
            elif r.status_code != 200:
                raise RuntimeError(f"non-retryable BSE HTTP {r.status_code}")
            elif not r.content:
                raise RuntimeError("empty BSE response")
            else:
                return r.content, {
                    "request_url": r.request.url,
                    "resolved_url": r.url,
                    "status": int(r.status_code),
                    "content_type": str(r.headers.get("Content-Type") or ""),
                    "bytes": len(r.content),
                    "sha256": sha256_bytes(r.content),
                    "attempt_count": attempt,
                    "attempts": attempts,
                }
        except requests.RequestException as exc:
            last_error = exc
            attempts.append({
                "attempt": attempt,
                "transport_error": f"{type(exc).__name__}: {exc}",
            })
        if attempt < 3:
            time.sleep((2 ** (attempt - 1)) + 0.2 * attempt)
    raise RuntimeError(f"BSE transport failed; last_error={last_error!r}; attempts={attempts}")


def summarize_structure(obj) -> dict:
    dict_key_sets: dict[tuple[str, ...], int] = {}
    list_lengths = []
    scalar_samples = {}
    pagination_candidates = []

    def walk(value, path: str):
        if isinstance(value, dict):
            keys = tuple(sorted(str(k) for k in value.keys()))
            dict_key_sets[keys] = dict_key_sets.get(keys, 0) + 1
            lower = {str(k).lower(): v for k, v in value.items()}
            pagination_names = {
                "totalpages", "totalelements", "number", "numberofelements", "size",
                "pagecount", "recordcount", "pageno", "pagesize", "total", "pages",
            }
            if pagination_names & set(lower):
                pagination_candidates.append({
                    "path": path,
                    "values": {
                        k: v for k, v in value.items()
                        if str(k).lower() in pagination_names
                    },
                })
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if not isinstance(child, (dict, list)) and len(scalar_samples) < 120:
                    scalar_samples.setdefault(child_path, child)
                walk(child, child_path)
        elif isinstance(value, list):
            list_lengths.append({"path": path, "length": len(value)})
            for index, child in enumerate(value[:50]):
                walk(child, f"{path}[{index}]")

    walk(obj, "")
    common_key_sets = sorted(
        (
            {"count": count, "keys": list(keys)}
            for keys, count in dict_key_sets.items()
        ),
        key=lambda x: (-x["count"], x["keys"]),
    )[:30]
    return {
        "top_level_type": type(obj).__name__,
        "top_level_keys": sorted(obj.keys()) if isinstance(obj, dict) else None,
        "top_level_length": len(obj) if isinstance(obj, list) else None,
        "common_dict_key_sets": common_key_sets,
        "list_lengths": sorted(list_lengths, key=lambda x: (-x["length"], x["path"]))[:40],
        "pagination_candidates": pagination_candidates[:40],
        "scalar_samples": scalar_samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--raw", required=True, type=Path)
    args = parser.parse_args()

    raw, transport = fetch()
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    args.raw.write_bytes(raw)

    try:
        obj, parse_mode = parse_json_or_jsonp(raw)
        parse_status = "PASS"
        parse_error = None
        structure = summarize_structure(obj)
    except Exception as exc:
        parse_mode = None
        parse_status = "FAIL"
        parse_error = f"{type(exc).__name__}: {exc}"
        structure = {
            "prefix_utf8": raw[:500].decode("utf-8", errors="replace"),
        }

    report = {
        "schema": "stock-bse-current-lifecycle-authority-discovery-v1",
        "status": "PASS" if parse_status == "PASS" else "NOT VERIFIED",
        "scope": "BSE first-party current-securities machine-contract discovery only",
        "product_bytes_changed": False,
        "endpoint": ENDPOINT,
        "form": FORM,
        "transport": transport,
        "raw_path": args.raw.as_posix(),
        "raw_sha256": sha256_bytes(raw),
        "parse_status": parse_status,
        "parse_mode": parse_mode,
        "parse_error": parse_error,
        "structure": structure,
        "adjudication": {
            "bse_machine_surface": "SUPPORTED_DISCOVERY" if parse_status == "PASS" else "NOT VERIFIED",
            "bse_current_lifecycle_authority": "NOT VERIFIED",
            "bse_historical_lifecycle_authority": "NOT VERIFIED",
            "bse_historical_pit_availability": "NOT VERIFIED",
            "full_three_market_authority": "NOT VERIFIED",
            "full_historical_st_pit": "NOT VERIFIED",
            "advanced_business": "NOT VERIFIED",
            "final_gate": "FAIL",
        },
        "boundary": (
            "A discovery PASS proves only that the official BSE endpoint returned parseable first-party "
            "machine data with preserved raw bytes. No row schema, pagination denominator, lifecycle "
            "completeness, historical replay, PIT availability, Advanced Business or Final claim is promoted."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "transport": report["transport"],
        "parse_status": report["parse_status"],
        "structure": report["structure"],
        "adjudication": report["adjudication"],
    }, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
