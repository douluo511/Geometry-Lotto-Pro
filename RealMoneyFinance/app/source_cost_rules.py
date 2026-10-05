from __future__ import annotations

from html import unescape
import re

from .netclient import NetClient


SSE_FEE_URL = "https://www.sse.com.cn/services/tradingservice/charge/ssecharge/c/c_20251231_10803655.shtml"
STAMP_TAX_BASE_URL = "https://tianjin.chinatax.gov.cn/11200000000/0300/030005/20220725150235434.shtml"
STAMP_TAX_HALF_URL = "https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm"


def _visible_text(raw: str) -> str:
    text = re.sub(r"<script\\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<style\\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\\s+", " ", text).strip()


def parse_official_cost_rules(sse_html: str, stamp_base_html: str, stamp_half_html: str) -> dict:
    sse = _visible_text(sse_html)
    base = _visible_text(stamp_base_html)
    half = _visible_text(stamp_half_html)

    sse_rate_ok = ("0.00341%" in sse) or ("0.0341‰" in sse)
    stamp_base_ok = ("千分之一" in base) or ("0.1%" in base)
    stamp_half_ok = "减半征收" in half and ("2023年8月28日" in half or "2023-08-28" in half)

    checks = {
        "sse_a_share_handling_fee_0_00341_percent_each_side": sse_rate_ok,
        "stamp_tax_statutory_base_0_1_percent": stamp_base_ok,
        "stamp_tax_halved_from_2023_08_28": stamp_half_ok,
    }
    status = "PASS" if all(checks.values()) else "NOT VERIFIED"
    return {
        "status": status,
        "checks": checks,
        "exchange_handling_fee_bps_each_side": 0.341 if sse_rate_ok else None,
        "sell_stamp_tax_bps": 5.0 if stamp_base_ok and stamp_half_ok else None,
        "scope": (
            "official regulatory fee/tax calibration only; broker commission and observed execution "
            "slippage are separate required evidence and remain NOT VERIFIED"
        ),
    }


def fetch_official_cost_rules(client: NetClient) -> dict:
    sse_text, sse_meta = client.get_text(SSE_FEE_URL)
    base_text, base_meta = client.get_text(STAMP_TAX_BASE_URL)
    half_text, half_meta = client.get_text(STAMP_TAX_HALF_URL)
    parsed = parse_official_cost_rules(sse_text, base_text, half_text)
    parsed["sources"] = {
        "sse_fee_table": {
            "url": sse_meta.url,
            "payload_sha256": sse_meta.payload_sha256,
            "retrieved_at_unix": sse_meta.retrieved_at_unix,
        },
        "stamp_tax_base": {
            "url": base_meta.url,
            "payload_sha256": base_meta.payload_sha256,
            "retrieved_at_unix": base_meta.retrieved_at_unix,
        },
        "stamp_tax_half": {
            "url": half_meta.url,
            "payload_sha256": half_meta.payload_sha256,
            "retrieved_at_unix": half_meta.retrieved_at_unix,
        },
    }
    return parsed
