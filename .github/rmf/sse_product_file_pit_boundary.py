from __future__ import annotations

import argparse
from io import BytesIO
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import requests
from pypdf import PdfReader

SSE_SPEC_URL = (
    "https://www.sse.com.cn/services/tradingtech/development/c/10822594/files/"
    "2096257019bf484f9b9935fa73f94721.pdf"
)


def _compact(text: str) -> str:
    return "".join(str(text or "").replace("\u200b", "").split())


def fetch_spec(max_attempts: int = 3) -> dict:
    errors = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/154 Safari/537.36"
        ),
        "Accept": "application/pdf,*/*;q=0.8",
        "Referer": "https://www.sse.com.cn/",
    }
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(
                SSE_SPEC_URL,
                headers=headers,
                timeout=(5, 30),
                allow_redirects=True,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise RuntimeError(f"retryable HTTP {response.status_code}")
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(b"%PDF"):
                raise RuntimeError("official SSE spec is not PDF-shaped")
            reader = PdfReader(BytesIO(payload))
            extracted = "\n".join((page.extract_text() or "") for page in reader.pages)
            if not extracted.strip():
                raise RuntimeError("official SSE spec text extraction is empty")
            compact = _compact(extracted)
            file_id = "cpxx0201MMDD"
            has_file = file_id in compact
            has_preopen = "开市前发布" in compact or "开市前生成" in compact
            has_suspended = "包含停牌的产品" in compact
            has_trade_date_semantics = (
                "MMDD表示月日格式的交易日使用的日期" in compact
                or ("MMDD" in compact and "交易日" in compact)
            )
            schedule_supported = has_file and has_preopen and has_trade_date_semantics
            content_scope_supported = has_file and has_suspended
            return {
                "status": "SUPPORTED" if (schedule_supported or content_scope_supported) else "NOT VERIFIED",
                "source_url": str(response.url),
                "http_status": int(response.status_code),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "attempts": attempt,
                "prior_attempt_errors": errors,
                "pdf_payload_sha256": hashlib.sha256(payload).hexdigest(),
                "extracted_text_sha256": hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
                "page_count": len(reader.pages),
                "file_identifier": file_id if has_file else "NOT VERIFIED",
                "file_identifier_present": has_file,
                "pre_open_publication_language_present": has_preopen,
                "contains_suspended_products_language_present": has_suspended,
                "trading_date_filename_semantics_present": has_trade_date_semantics,
                "market_participant_daily_product_file_schedule": (
                    "SUPPORTED" if schedule_supported else "NOT VERIFIED"
                ),
                "daily_file_includes_suspended_products": (
                    "SUPPORTED" if content_scope_supported else "NOT VERIFIED"
                ),
                "historical_file_contents_replayable_now": "NOT VERIFIED",
                "historical_pit_content_availability": "NOT VERIFIED",
                "survivorship_selection_control": "NOT VERIFIED",
                "leakage_point_in_time": "NOT VERIFIED",
                "capital_deployment_ready": False,
                "final_gate": "FAIL",
                "boundary": (
                    "Official SSE specification may support that a trading-date product-information "
                    "file is published before market open and includes suspended products. This does "
                    "not prove that exact historical daily files across the frozen 2021-2026 research "
                    "window are currently retrievable/replayable, nor that their historical contents "
                    "have been bound to the RMF research universe."
                ),
            }
        except Exception as exc:
            errors.append({
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            if attempt < max_attempts:
                time.sleep(1.25 * (2 ** (attempt - 1)))
    return {
        "status": "NOT VERIFIED",
        "source_url": SSE_SPEC_URL,
        "attempts": max_attempts,
        "errors": errors,
        "market_participant_daily_product_file_schedule": "NOT VERIFIED",
        "daily_file_includes_suspended_products": "NOT VERIFIED",
        "historical_file_contents_replayable_now": "NOT VERIFIED",
        "historical_pit_content_availability": "NOT VERIFIED",
        "survivorship_selection_control": "NOT VERIFIED",
        "leakage_point_in_time": "NOT VERIFIED",
        "capital_deployment_ready": False,
        "final_gate": "FAIL",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    evidence = {
        "schema": "rmf-sse-daily-product-file-pit-boundary-v1",
        "evidence": fetch_spec(),
    }
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
