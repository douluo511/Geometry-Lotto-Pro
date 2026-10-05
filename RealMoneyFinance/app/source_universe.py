from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from typing import Any
from types import SimpleNamespace

from .netclient import NetClient


UNIVERSE_URLS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://82.push2.eastmoney.com/api/qt/clist/get",
)
UNIVERSE_URL = UNIVERSE_URLS[0]
SSE_UNIVERSE_URL = "https://query.sse.com.cn/sseQuery/commonQuery.do"
UNIVERSE_FILTER = "m:1+t:2,m:1+t:23"
PUBLIC_UT = "bd1d9ddb04089700cf9c27f6f7426281"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SYMBOL_RE = re.compile(r"^6[0-9]{5}$")


def _normalise_entries(entries: list[dict[str, Any]], min_symbols: int = 500) -> list[dict[str, str]]:
    by_symbol: dict[str, str] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("universe entry must be an object")
        symbol = str(raw.get("symbol", "")).strip()
        name = str(raw.get("name", "")).strip()
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError(f"invalid Shanghai equity symbol: {symbol!r}")
        if not name:
            raise ValueError(f"missing security name for {symbol}")
        previous = by_symbol.get(symbol)
        if previous is not None and previous != name:
            raise ValueError(f"conflicting names for duplicate symbol {symbol}")
        by_symbol[symbol] = name
    if len(by_symbol) < int(min_symbols):
        raise ValueError(
            f"prospective universe is too small for a broad survivorship precommit: "
            f"{len(by_symbol)} < {int(min_symbols)}"
        )
    return [{"symbol": symbol, "name": by_symbol[symbol]} for symbol in sorted(by_symbol)]


def build_prospective_universe_precommit(
    entries: list[dict[str, Any]],
    *,
    asof_date: str,
    retrieved_at_unix: float,
    source_payload_sha256s: list[str],
    code_source_sha: str,
    source_url: str = UNIVERSE_URL,
    source_provider: str = "eastmoney_current_shanghai_equity_universe",
    source_filter: str = UNIVERSE_FILTER,
    declared_total: int | None = None,
    min_symbols: int = 500,
) -> dict[str, Any]:
    normalised = _normalise_entries(entries, min_symbols=min_symbols)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(asof_date)):
        raise ValueError("asof_date must be YYYY-MM-DD")
    if float(retrieved_at_unix) <= 0:
        raise ValueError("retrieved_at_unix must be positive")
    if not str(source_url).lower().startswith("https://"):
        raise ValueError("universe source must use HTTPS")
    if not source_payload_sha256s or any(
        not _SHA256_RE.fullmatch(str(value).lower()) for value in source_payload_sha256s
    ):
        raise ValueError("every source payload must carry a SHA-256 digest")
    if not _COMMIT_RE.fullmatch(str(code_source_sha).lower()):
        raise ValueError("prospective precommit must bind the exact 40-hex source commit")
    if declared_total is not None and int(declared_total) < len(normalised):
        raise ValueError("provider-declared total is smaller than parsed universe")

    payload_hashes = [str(x).lower() for x in source_payload_sha256s]
    canonical = {
        "schema": "rmf-prospective-survivorship-precommit-v1",
        "asof_date": str(asof_date),
        "retrieved_at_unix": float(retrieved_at_unix),
        "source_provider": str(source_provider),
        "source_url": str(source_url),
        "source_filter": str(source_filter),
        "source_payload_sha256s": payload_hashes,
        "declared_total": int(declared_total) if declared_total is not None else None,
        "code_source_sha": str(code_source_sha).lower(),
        "symbols": normalised,
    }
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    precommit_sha256 = hashlib.sha256(raw).hexdigest()
    symbols_raw = "\n".join(item["symbol"] for item in normalised).encode("ascii")
    return {
        "status": "PASS",
        "schema": canonical["schema"],
        "scope": "PROSPECTIVE_PRECOMMIT_ONLY",
        "historical_survivorship_gate": "NOT VERIFIED",
        "asof_date": canonical["asof_date"],
        "retrieved_at_unix": float(retrieved_at_unix),
        "source_provider": canonical["source_provider"],
        "source_url": canonical["source_url"],
        "source_filter": canonical["source_filter"],
        "code_source_sha": canonical["code_source_sha"],
        "source_payload_sha256s": canonical["source_payload_sha256s"],
        "declared_total": canonical["declared_total"],
        "symbol_count": len(normalised),
        "symbols_sha256": hashlib.sha256(symbols_raw).hexdigest(),
        "precommit_sha256": precommit_sha256,
        "symbols": [item["symbol"] for item in normalised],
        "symbol_name_sample": normalised[:5] + normalised[-5:],
        "policy": {
            "no_outcome_selection": True,
            "freeze_membership_at_asof": True,
            "retain_members_if_later_delisted": True,
            "removals_never_delete_historical_members": True,
            "future_additions_require_new_versioned_precommit": True,
        },
        "boundary": (
            "PASS proves a broad current Shanghai-equity universe was frozen before future outcomes "
            "and bound to live source payload hashes plus the exact code commit. It does not prove "
            "historical pre-asof survivorship safety and must not promote the frozen historical "
            "survivorship business gate."
        ),
    }


def _fetch_official_sse_universe(
    client: NetClient,
) -> tuple[dict[str, Any], Any, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    payload_hashes: list[str] = []
    retrieved_times: list[float] = []
    for stock_type, board in (("1", "main_a"), ("8", "star")):
        params = {
            "STOCK_TYPE": stock_type,
            "REG_PROVINCE": "",
            "CSRC_CODE": "",
            "STOCK_CODE": "",
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
            "COMPANY_STATUS": "2,4,5,7,8",
            "type": "inParams",
            "isPagination": "true",
            "pageHelp.cacheSize": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.pageSize": "10000",
            "pageHelp.pageNo": "1",
            "pageHelp.endPage": "1",
        }
        try:
            obj, meta = client.get_json(
                SSE_UNIVERSE_URL,
                params,
                headers={
                    "Host": "query.sse.com.cn",
                    "Pragma": "no-cache",
                    "Referer": "https://www.sse.com.cn/assortment/stock/list/share/",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/154 Safari/537.36"
                    ),
                    "Accept": "application/json,text/plain,*/*",
                },
                allow_mislabeled_json=True,
            )
        except Exception as exc:
            attempts.append({
                "url": SSE_UNIVERSE_URL,
                "board": board,
                "stock_type": stock_type,
                "status": "FAIL",
                "error": repr(exc),
            })
            raise RuntimeError(
                "official SSE current-universe query failed: "
                + json.dumps(attempts, ensure_ascii=True, sort_keys=True)
            ) from exc
        result = obj.get("result")
        if not isinstance(result, list) or not result:
            raise ValueError(f"official SSE {board} universe result is empty or malformed")
        board_rows: list[dict[str, Any]] = []
        for row in result:
            if not isinstance(row, dict):
                raise ValueError(f"official SSE {board} universe row must be an object")
            symbol = str(row.get("A_STOCK_CODE", "")).strip()
            name = str(row.get("SEC_NAME_CN") or row.get("COMPANY_ABBR") or "").strip()
            if not _SYMBOL_RE.fullmatch(symbol) or not name:
                raise ValueError(
                    f"official SSE {board} row has invalid code/name: {symbol!r}/{name!r}"
                )
            board_rows.append({"f12": symbol, "f13": 1, "f14": name})
        rows.extend(board_rows)
        page_payload_hashes = getattr(meta, "payload_sha256s", None) or [meta.payload_sha256]
        payload_hashes.extend(page_payload_hashes)
        retrieved_times.append(meta.retrieved_at_unix)
        attempts.append({
            "url": SSE_UNIVERSE_URL,
            "board": board,
            "stock_type": stock_type,
            "status": "PASS",
            "row_count": len(board_rows),
            "payload_sha256": meta.payload_sha256,
        })

    unique_count = len({str(row["f12"]) for row in rows})
    if unique_count != len(rows):
        raise ValueError("official SSE main/STAR universe contains duplicate A-share codes")
    composite = hashlib.sha256(
        "\n".join(payload_hashes).encode("ascii")
    ).hexdigest()
    meta = SimpleNamespace(
        url=SSE_UNIVERSE_URL,
        payload_sha256=composite,
        payload_sha256s=payload_hashes,
        retrieved_at_unix=max(retrieved_times),
    )
    return {"data": {"total": unique_count, "diff": rows}}, meta, attempts


def _fetch_universe_page(client: NetClient, params: dict[str, str]) -> tuple[dict[str, Any], Any, list[dict[str, Any]], str]:
    attempts: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for url in UNIVERSE_URLS:
        try:
            obj, meta = client.get_json(
                url,
                params,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/154 Safari/537.36"
                    ),
                    "Referer": "https://quote.eastmoney.com/center/gridlist.html",
                    "Accept": "application/json,text/plain,*/*",
                },
                allow_mislabeled_json=True,
            )
            attempts.append({
                "url": url,
                "status": "PASS",
                "payload_sha256": meta.payload_sha256,
            })
            return obj, meta, attempts, "eastmoney_current_shanghai_equity_universe"
        except Exception as exc:
            last_error = exc
            attempts.append({
                "url": url,
                "status": "FAIL",
                "error": repr(exc),
            })
    try:
        obj, meta, sse_attempts = _fetch_official_sse_universe(client)
        attempts.extend(sse_attempts)
        return obj, meta, attempts, "sse_official_current_shanghai_equity_universe"
    except Exception as sse_exc:
        attempts.append({
            "url": SSE_UNIVERSE_URL,
            "status": "FAIL",
            "error": repr(sse_exc),
        })
        raise RuntimeError(
            "all configured current-universe sources failed: "
            + json.dumps(attempts, ensure_ascii=True, sort_keys=True)
        ) from sse_exc


def fetch_current_shanghai_universe_precommit(
    client: NetClient,
    *,
    page_size: int = 500,
    max_pages: int = 20,
    min_symbols: int = 500,
) -> dict[str, Any]:
    size = max(50, min(int(page_size), 1000))
    entries: list[dict[str, Any]] = []
    payload_hashes: list[str] = []
    retrieved_times: list[float] = []
    declared_total: int | None = None
    host_attempts: list[dict[str, Any]] = []
    selected_source_urls: list[str] = []
    selected_source_providers: list[str] = []

    for page in range(1, int(max_pages) + 1):
        params = {
            "pn": str(page),
            "pz": str(size),
            "po": "1",
            "np": "1",
            "ut": PUBLIC_UT,
            "fltt": "2",
            "invt": "2",
            "fid": "f12",
            "fs": UNIVERSE_FILTER,
            "fields": "f12,f13,f14",
        }
        obj, meta, page_attempts, source_provider = _fetch_universe_page(client, params)
        host_attempts.extend([
            {"page": page, **attempt} for attempt in page_attempts
        ])
        selected_source_urls.append(str(meta.url).split("?")[0])
        selected_source_providers.append(source_provider)
        data = obj.get("data")
        if not isinstance(data, dict):
            raise ValueError("universe response missing data object")
        total = int(data.get("total") or 0)
        if total <= 0:
            raise ValueError("universe response has non-positive total")
        if declared_total is None:
            declared_total = total
        elif total != declared_total:
            raise ValueError(
                f"universe total changed during pagination: {declared_total} -> {total}"
            )

        diff = data.get("diff")
        if isinstance(diff, dict):
            rows = list(diff.values())
        elif isinstance(diff, list):
            rows = diff
        else:
            raise ValueError("universe response diff must be an object or list")
        if not rows:
            raise ValueError("universe pagination returned an empty page before completion")

        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("universe row must be an object")
            market = int(row.get("f13"))
            if market != 1:
                raise ValueError(f"unexpected non-Shanghai market code: {market}")
            entries.append({
                "symbol": str(row.get("f12", "")).strip(),
                "name": str(row.get("f14", "")).strip(),
            })

        page_payload_hashes = getattr(meta, "payload_sha256s", None)
        if page_payload_hashes:
            payload_hashes.extend(str(value).lower() for value in page_payload_hashes)
        else:
            payload_hashes.append(str(meta.payload_sha256).lower())
        retrieved_times.append(meta.retrieved_at_unix)
        if len({item["symbol"] for item in entries}) >= declared_total:
            break
    else:
        raise RuntimeError("universe pagination exceeded max_pages before declared total was reached")

    unique_count = len({item["symbol"] for item in entries})
    if declared_total is None or unique_count != declared_total:
        raise ValueError(
            f"parsed universe count does not match provider total: {unique_count} != {declared_total}"
        )

    providers = sorted(set(selected_source_providers))
    if len(providers) != 1:
        raise ValueError(f"mixed universe providers across pagination are not allowed: {providers}")
    latest_retrieval = max(retrieved_times)
    china_tz = timezone(timedelta(hours=8))
    asof_date = datetime.fromtimestamp(
        latest_retrieval, tz=timezone.utc
    ).astimezone(china_tz).date().isoformat()
    code_source_sha = os.environ.get("SOURCE_SHA") or os.environ.get("GITHUB_SHA") or ""

    source_filter = (
        "STOCK_TYPE=1,8;COMPANY_STATUS=2,4,5,7,8"
        if providers[0] == "sse_official_current_shanghai_equity_universe"
        else UNIVERSE_FILTER
    )
    result = build_prospective_universe_precommit(
        entries,
        asof_date=asof_date,
        retrieved_at_unix=latest_retrieval,
        source_payload_sha256s=payload_hashes,
        code_source_sha=code_source_sha,
        source_url=selected_source_urls[0] if selected_source_urls else UNIVERSE_URL,
        source_provider=providers[0],
        source_filter=source_filter,
        declared_total=declared_total,
        min_symbols=min_symbols,
    )
    result["selected_source_urls"] = sorted(set(selected_source_urls))
    result["selected_source_providers"] = providers
    result["host_attempts"] = host_attempts
    result["host_failover_used"] = any(
        attempt.get("status") == "FAIL" for attempt in host_attempts
    )
    return result
