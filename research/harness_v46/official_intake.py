"""Official-source history intake adapter for V4.7.

Uses the repository's existing game-specific parsers in isolated subprocesses so
both packages named glp cannot collide. This is data acquisition and semantic
cross-check only: local timestamps are untrusted; target/cutoff admission,
external timestamping and formal-A eligibility remain blocked.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .core import GateError, MAX_RAW_SOURCE_BYTES, SOURCE_HOSTS_BY_GAME

SCHEMA = "V47-OFFICIAL-INTAKE-1"
WORKER_SCHEMA = "V47-OFFICIAL-INTAKE-WORKER-1"
REPO_ROOT = Path(__file__).resolve().parents[2]
PARSER_FILES = {
    "SSQ": (
        "SSQ/SSQ/glp/sources.py",
        "SSQ/SSQ/glp/constants.py",
        "SSQ/SSQ/glp/domain.py",
        "SSQ/SSQ/glp/util.py",
        "SSQ/SSQ/glp/net_client.py",
        "research/harness_v46/official_intake.py",
    ),
    "DLT": (
        "DLT/src/glp/sources.py",
        "DLT/src/glp/constants.py",
        "DLT/src/glp/domain.py",
        "DLT/src/glp/util.py",
        "DLT/src/glp/net_client.py",
        "research/harness_v46/official_intake.py",
    ),
}
SOURCE_IDS = {
    "SSQ": {"official_cwl_L0": "national", "official_shanghai_L1": "shanghai"},
    "DLT": {
        "official_sporttery_national": "national",
        "official_jiangsu_sporttery": "jiangsu",
    },
}
EXPECTED_ROOTS = {
    "SSQ": {"national": "cwl.gov.cn", "shanghai": "swlc.net.cn"},
    "DLT": {"national": "sporttery.cn", "jiangsu": "js-lottery.com"},
}
EXPECTED_SOURCE_NAMES = {
    "SSQ": {"national": "official_cwl_L0", "shanghai": "official_shanghai_L1"},
    "DLT": {"national": "official_sporttery_national", "jiangsu": "official_jiangsu_sporttery"},
}
REDIRECT_CODES = {301, 302, 303, 307, 308}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_file_hashes(game: str) -> dict[str, str]:
    if game not in PARSER_FILES:
        raise GateError("UNKNOWN_LOTTERY_FOR_SOURCE_INTAKE")
    result = {}
    for rel in PARSER_FILES[game]:
        path = REPO_ROOT / rel
        if not path.is_file():
            raise GateError("PARSER_DEPENDENCY_MISSING:" + rel)
        result[rel] = _sha(path.read_bytes())
    return result


def _expected_parser_version(game: str) -> str:
    source_path = REPO_ROOT / PARSER_FILES[game][0]
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise GateError("PARSER_SOURCE_NOT_PARSEABLE") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PARSER_VERSION"
            for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError) as exc:
                raise GateError("PARSER_VERSION_NOT_LITERAL") from exc
            if isinstance(value, str) and value:
                return value
    raise GateError("PARSER_VERSION_CONSTANT_MISSING")


def _root_for_url(game: str, url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise GateError("INVALID_SOURCE_URL") from exc
    if (parsed.scheme.lower() != "https" or not host or port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment):
        raise GateError("SOURCE_URL_MUST_BE_CLEAN_HTTPS")
    for root in SOURCE_HOSTS_BY_GAME[game]:
        if host == root or host.endswith("." + root):
            return host, root
    raise GateError("SOURCE_HOST_NOT_ALLOWLISTED_FOR_GAME")


def _canonical_draws(game: str, rows: list[dict]) -> list[dict]:
    if not isinstance(rows, list) or len(rows) < 120:
        raise GateError("SOURCE_HISTORY_REQUIRES_AT_LEAST_120_DRAWS")
    front_max, front_count, back_max, back_count = (
        (33, 6, 16, 1) if game == "SSQ" else (35, 5, 12, 2)
    )
    clean = []
    seen = set()
    last_issue, last_date = -1, None
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"issue", "draw_date", "front", "back"}:
            raise GateError("INVALID_SOURCE_DRAW_SCHEMA")
        issue = str(row["issue"])
        day = row["draw_date"]
        if not issue.isdigit() or int(issue) <= last_issue:
            raise GateError("DUPLICATE_OR_OUT_OF_ORDER_SOURCE_ISSUE")
        if not isinstance(day, str):
            raise GateError("INVALID_SOURCE_DRAW_DATE")
        try:
            parsed_day = datetime.strptime(day[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise GateError("INVALID_SOURCE_DRAW_DATE") from exc
        if parsed_day.isoformat() != day[:10] or (last_date is not None and parsed_day <= last_date):
            raise GateError("NONMONOTONIC_SOURCE_DRAW_DATE")
        front, back = row["front"], row["back"]
        if (not isinstance(front, list) or len(front) != front_count
                or any(type(n) is not int or not 1 <= n <= front_max for n in front)
                or front != sorted(front) or len(set(front)) != front_count):
            raise GateError("INVALID_SOURCE_FRONT_NUMBERS")
        if (not isinstance(back, list) or len(back) != back_count
                or any(type(n) is not int or not 1 <= n <= back_max for n in back)
                or back != sorted(back) or len(set(back)) != back_count):
            raise GateError("INVALID_SOURCE_BACK_NUMBERS")
        if issue in seen:
            raise GateError("DUPLICATE_SOURCE_ISSUE")
        clean.append({"issue": issue, "draw_date": day[:10], "front": front, "back": back})
        seen.add(issue)
        last_issue, last_date = int(issue), parsed_day
    return clean


def _validate_artifacts(game: str, source: dict, parser_version: str) -> list[dict]:
    source_id = source.get("source_id")
    source_root = source.get("source_root")
    artifacts = source.get("raw_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise GateError("SOURCE_HAS_NO_RAW_ARTIFACTS")
    validated = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise GateError("INVALID_RAW_ARTIFACT_SCHEMA")
        required = {
            "url", "requested_url", "raw_sha256", "size_bytes", "content_type",
            "http_status", "fetched_at", "parser_version", "raw_base64",
        }
        if set(artifact) != required:
            raise GateError("INVALID_RAW_ARTIFACT_SCHEMA")
        host, root = _root_for_url(game, artifact["url"])
        _, requested_root = _root_for_url(game, artifact["requested_url"])
        if root != source_root or requested_root != source_root:
            raise GateError("RAW_ARTIFACT_SOURCE_ROOT_MISMATCH")
        if artifact["parser_version"] != parser_version:
            raise GateError("PARSER_VERSION_MISMATCH")
        if type(artifact["http_status"]) is not int or artifact["http_status"] != 200:
            raise GateError("RAW_ARTIFACT_HTTP_STATUS_NOT_200")
        if not isinstance(artifact["content_type"], str) or not artifact["content_type"].strip():
            raise GateError("RAW_ARTIFACT_CONTENT_TYPE_MISSING")
        try:
            raw = base64.b64decode(artifact["raw_base64"], validate=True)
        except Exception as exc:
            raise GateError("RAW_ARTIFACT_BASE64_INVALID") from exc
        if len(raw) != artifact["size_bytes"] or _sha(raw) != artifact["raw_sha256"]:
            raise GateError("RAW_ARTIFACT_BYTES_SHA_MISMATCH")
        try:
            fetched_stamp = datetime.fromisoformat(artifact["fetched_at"].replace("Z", "+00:00"))
            if fetched_stamp.tzinfo is None:
                raise ValueError("timezone is required")
        except (TypeError, ValueError) as exc:
            raise GateError("RAW_ARTIFACT_FETCH_TIME_INVALID") from exc
        validated.append({
            "source_id": source_id, "url": artifact["url"],
            "requested_url": artifact["requested_url"], "host": host,
            "source_root": root, "raw_sha256": artifact["raw_sha256"],
            "size_bytes": len(raw), "content_type": artifact["content_type"],
            "http_status": 200, "fetched_at_local_untrusted": artifact["fetched_at"],
            "parser_version": parser_version, "raw_base64": artifact["raw_base64"],
        })
    return validated


def _transport_failure(game: str, source_id: str, requested_url: str,
                      response_url: str, status: int, content_type: str,
                      raw: bytes, fetched_at: str, parser_version: str) -> dict:
    """Preserve bounded transport-failure evidence without calling it official source data."""
    if game not in EXPECTED_ROOTS or source_id not in EXPECTED_ROOTS[game]:
        raise GateError("UNKNOWN_TRANSPORT_FAILURE_SOURCE")
    if not isinstance(raw, bytes):
        raise GateError("TRANSPORT_FAILURE_BODY_TYPE_INVALID")
    body = base64.b64encode(raw).decode("ascii") if len(raw) <= MAX_RAW_SOURCE_BYTES else None
    return {
        "source_id": source_id,
        "expected_source_root": EXPECTED_ROOTS[game][source_id],
        "requested_url": str(requested_url),
        "response_url_untrusted": str(response_url),
        "http_status": int(status),
        "content_type": str(content_type or ""),
        "fetched_at_local_untrusted": str(fetched_at),
        "parser_version": str(parser_version),
        "raw_sha256": _sha(raw),
        "size_bytes": len(raw),
        "body_base64": body,
        "body_preserved": body is not None,
        "classification": "TRANSPORT_FAILURE_UNTRUSTED_NOT_OFFICIAL_SOURCE_EVIDENCE",
    }


def _normalize_worker_artifact(game: str, source_id: str, meta: dict, raw: bytes,
                               parser_version: str) -> dict:
    if not isinstance(raw, bytes):
        raise GateError("RAW_SOURCE_BYTES_TYPE_INVALID")
    url = str(meta.get("url") or meta.get("final_url") or "")
    requested_url = str(meta.get("requested_url") or url)
    host, root = _root_for_url(game, url)
    _, requested_root = _root_for_url(game, requested_url)
    if root != requested_root:
        raise GateError("SOURCE_REDIRECT_CHANGED_OFFICIAL_ROOT")
    if int(meta.get("http_status", 0)) != 200:
        raise GateError("RAW_SOURCE_HTTP_STATUS_NOT_200")
    content_type = str(meta.get("content_type") or "")
    fetched_at = str(meta.get("fetched_at") or "")
    try:
        fetched_stamp = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        if fetched_stamp.tzinfo is None:
            raise ValueError("timezone is required")
    except ValueError as exc:
        raise GateError("RAW_SOURCE_FETCH_TIME_INVALID") from exc
    digest = _sha(raw)
    if meta.get("sha256") != digest or meta.get("bytes") != len(raw):
        raise GateError("PARSER_RAW_METADATA_MISMATCH")
    if meta.get("parser_version") != parser_version:
        raise GateError("PARSER_VERSION_MISMATCH")
    return {
        "url": url, "requested_url": requested_url, "raw_sha256": digest,
        "size_bytes": len(raw), "content_type": content_type,
        "http_status": 200, "fetched_at": fetched_at,
        "parser_version": parser_version,
        "raw_base64": base64.b64encode(raw).decode("ascii"),
        "_source_id": source_id, "_source_root": root, "_host": host,
    }


def _source_rows(draws) -> list[dict]:
    return [
        {"issue": str(d.issue), "draw_date": str(d.draw_date)[:10],
         "front": list(d.front), "back": list(d.back)}
        for d in draws
    ]


def _reparse_raw_history(game: str, source_module, source_id: str,
                         artifacts: list[dict]) -> list[dict]:
    """Reparse each nonempty preserved response body and compare it to the parser's aggregate."""
    parsed_rows = []
    for artifact in artifacts:
        try:
            raw = base64.b64decode(artifact["raw_base64"], validate=True)
        except Exception as exc:
            raise GateError("RAW_REPARSE_BASE64_INVALID") from exc
        if not raw:
            # Some SSQ history endpoints transiently return empty HTTP 200 bodies;
            # preserve and hash them, but never treat them as a successful draw page.
            continue
        try:
            if game == "SSQ" and source_id == "national":
                payload = json.loads(raw.decode("utf-8-sig"))
                rows = payload.get("result") if isinstance(payload, dict) else None
                if not isinstance(rows, list):
                    raise GateError("SSQ_NATIONAL_RAW_SCHEMA_CHANGED")
                for row in rows:
                    if not isinstance(row, dict):
                        raise GateError("SSQ_NATIONAL_RAW_ROW_INVALID")
                    draw = source_module._draw(row.get("code"), row.get("date"),
                                               row.get("red"), row.get("blue"))
                    parsed_rows.append({
                        "issue": str(draw.issue), "draw_date": str(draw.draw_date)[:10],
                        "front": list(draw.front), "back": list(draw.back),
                    })
            elif game == "SSQ" and source_id == "shanghai":
                parsed_rows.extend(_source_rows(source_module.parse_shanghai_history(raw)))
            elif game == "DLT" and source_id == "national":
                payload = json.loads(raw.decode("utf-8-sig"))
                value = payload.get("value") or {} if isinstance(payload, dict) else {}
                rows = value.get("list") or value.get("records") or []
                if not isinstance(rows, list):
                    raise GateError("DLT_NATIONAL_RAW_SCHEMA_CHANGED")
                for row in rows:
                    if not isinstance(row, dict):
                        raise GateError("DLT_NATIONAL_RAW_ROW_INVALID")
                    draw = source_module._parse_result(
                        str(row.get("lotteryDrawNum")), str(row.get("lotteryDrawTime")),
                        str(row.get("lotteryDrawResult")),
                    )
                    parsed_rows.append({
                        "issue": str(draw.issue), "draw_date": str(draw.draw_date)[:10],
                        "front": list(draw.front), "back": list(draw.back),
                    })
            elif game == "DLT" and source_id == "jiangsu":
                parsed_rows.extend(_source_rows(
                    source_module._parse_jiangsu_html(source_module._decode_html(raw))
                ))
            else:
                raise GateError("UNKNOWN_RAW_REPARSE_ROUTE")
        except GateError:
            raise
        except Exception as exc:
            raise GateError("RAW_REPARSE_FAILED:" + source_id + ":" + type(exc).__name__) from exc
    by_issue = {}
    for row in parsed_rows:
        issue = row["issue"]
        previous = by_issue.get(issue)
        if previous is not None and previous != row:
            raise GateError("RAW_PAGES_CONFLICT_ON_ISSUE:" + issue)
        by_issue[issue] = row
    reparsed = _canonical_draws(game, sorted(by_issue.values(), key=lambda row: int(row["issue"])))
    return reparsed


def _rows_sha256(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha(payload.encode("utf-8"))


def _install_dlt_redirect_guard(game: str, transport_failures: list[dict],
                                parser_version: str) -> None:
    """Bound redirects and retain failed HTTP responses as untrusted transport evidence."""
    import requests
    from urllib.parse import urljoin

    original_get = requests.get

    def safe_get(url, *args, **kwargs):
        params = kwargs.pop("params", None)
        allow_redirects = kwargs.pop("allow_redirects", True)
        _, initial_root = _root_for_url(game, str(url))
        source_id = next(
            (sid for sid, root in EXPECTED_ROOTS[game].items() if root == initial_root),
            None,
        )
        if source_id is None:
            raise GateError("SOURCE_ID_NOT_BOUND_TO_EXPECTED_OFFICIAL_ROOT")
        current_url, current_params = str(url), params
        for _ in range(6):
            response = original_get(
                current_url, *args, params=current_params,
                allow_redirects=False, **kwargs,
            )
            status = int(getattr(response, "status_code", 0) or 0)
            if status != 200 and status not in REDIRECT_CODES:
                transport_failures.append(_transport_failure(
                    game, source_id, current_url,
                    str(getattr(response, "url", "") or current_url),
                    status, str(getattr(response, "headers", {}).get("Content-Type", "")),
                    bytes(getattr(response, "content", b"")),
                    datetime.now(timezone.utc).isoformat(), parser_version,
                ))
            if not allow_redirects or status not in REDIRECT_CODES:
                return response
            location = response.headers.get("Location")
            if not location:
                return response
            next_url = urljoin(str(response.url or current_url), location)
            _, next_root = _root_for_url(game, next_url)
            if next_root != initial_root:
                raise GateError("SOURCE_REDIRECT_CHANGED_OFFICIAL_ROOT")
            current_url, current_params = next_url, None
        raise GateError("SOURCE_REDIRECT_LIMIT_EXCEEDED")

    requests.get = safe_get


def _worker(game: str) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    source_hashes_before = source_file_hashes(game)
    source_dir = REPO_ROOT / ("SSQ/SSQ" if game == "SSQ" else "DLT/src")
    sys.path.insert(0, str(source_dir))
    import glp.sources as source_module

    parser_version = str(source_module.PARSER_VERSION)
    raw_artifacts: list[dict] = []
    transport_failures: list[dict] = []
    source_errors: dict[str, str] = {}
    sources: list[dict] = []

    if game == "SSQ":
        from glp.constants import SSQ_HISTORY_START_ISSUE

        def recorder(meta, raw):
            source_name = str(meta.get("source") or "")
            source_id = SOURCE_IDS[game].get(source_name)
            if source_id is None:
                raise GateError("UNEXPECTED_SSQ_SOURCE_ID:" + source_name)
            if int(meta.get("http_status", 0)) != 200:
                transport_failures.append(_transport_failure(
                    game, source_id, str(meta.get("requested_url") or meta.get("url") or ""),
                    str(meta.get("url") or meta.get("requested_url") or ""),
                    int(meta.get("http_status", 0)), str(meta.get("content_type") or ""),
                    bytes(raw), str(meta.get("fetched_at") or datetime.now(timezone.utc).isoformat()),
                    parser_version,
                ))
                # A recorder is observational: never mask the parser's own retry/error path.
                return
            raw_artifacts.append(_normalize_worker_artifact(
                game, source_id, meta, bytes(raw), parser_version
            ))

        source_specs = (
            ("national", "official_cwl_L0",
             lambda: source_module.fetch_national_history(record_raw=recorder)),
            ("shanghai", "official_shanghai_L1",
             lambda: source_module.fetch_shanghai_full_history(
                 start_issue=SSQ_HISTORY_START_ISSUE, record_raw=recorder
             )),
        )
        for source_id, source_name, fetch in source_specs:
            try:
                draws, receipt, _manifest = fetch()
                sources.append({
                    "source_id": source_id, "source_name": source_name,
                    "source_root": EXPECTED_ROOTS[game][source_id],
                    "url": "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
                           if source_id == "national" else "https://www.swlc.net.cn/lottery/ssq.html",
                    "draws": _source_rows(draws),
                    "receipt": {
                        "status": receipt.status, "draw_count": receipt.draw_count,
                        "latest_issue": receipt.latest_issue, "raw_sha256": receipt.raw_sha256,
                        "fetched_at": receipt.fetched_at,
                    },
                })
            except Exception as exc:
                source_errors[source_id] = f"{type(exc).__name__}: {exc}"

    elif game == "DLT":
        _install_dlt_redirect_guard(game, transport_failures, parser_version)
        source_specs = (
            ("national", "official_sporttery_national",
             "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry",
             source_module.fetch_national_history),
            ("jiangsu", "official_jiangsu_sporttery",
             "https://api.js-lottery.com/Lottery/_ListData",
             source_module.fetch_jiangsu_history),
        )
        for source_id, source_name, source_url, fetch in source_specs:
            try:
                draws, receipt, source_manifest = fetch()
                for entry in source_manifest:
                    encoded = entry.get("body_b64")
                    if not isinstance(encoded, str):
                        raise GateError("DLT_PARSER_RAW_BODY_MISSING")
                    try:
                        raw = base64.b64decode(encoded, validate=True)
                    except Exception as exc:
                        raise GateError("DLT_PARSER_RAW_BODY_BASE64_INVALID") from exc
                    meta = {
                        "url": entry.get("final_url") or entry.get("requested_url") or source_url,
                        "requested_url": entry.get("requested_url") or source_url,
                        "http_status": entry.get("http_status"),
                        "content_type": entry.get("content_type"),
                        "fetched_at": entry.get("fetched_at"),
                        "sha256": entry.get("sha256"),
                        "bytes": entry.get("bytes"),
                        "parser_version": entry.get("parser_version"),
                    }
                    raw_artifacts.append(_normalize_worker_artifact(
                        game, source_id, meta, raw, parser_version
                    ))
                sources.append({
                    "source_id": source_id, "source_name": source_name,
                    "source_root": EXPECTED_ROOTS[game][source_id], "url": source_url,
                    "draws": _source_rows(draws),
                    "receipt": {
                        "status": receipt.status, "draw_count": receipt.draw_count,
                        "latest_issue": receipt.latest_issue, "raw_sha256": receipt.raw_sha256,
                        "fetched_at": receipt.fetched_at,
                    },
                })
            except Exception as exc:
                source_errors[source_id] = f"{type(exc).__name__}: {exc}"
    else:
        raise GateError("UNKNOWN_LOTTERY_FOR_SOURCE_INTAKE")

    verified_sources = []
    for source in sources:
        source_id = source["source_id"]
        internal_artifacts = [item for item in raw_artifacts if item["_source_id"] == source_id]
        if not internal_artifacts:
            source_errors[source_id] = "GateError: SOURCE_RAW_ARTIFACTS_MISSING"
            continue
        source["raw_artifacts"] = [
            {k: v for k, v in item.items()
             if k in {"url", "requested_url", "raw_sha256", "size_bytes", "content_type",
                      "http_status", "fetched_at", "parser_version", "raw_base64"}}
            for item in internal_artifacts
        ]
        try:
            reparsed = _reparse_raw_history(game, source_module, source_id, source["raw_artifacts"])
            source_draws = _canonical_draws(game, source["draws"])
            if reparsed != source_draws:
                raise GateError("RAW_REPARSED_ROWS_DIFFER_FROM_SOURCE_OUTPUT:" + source_id)
            source["raw_reparse_status"] = "PASS"
            source["raw_reparse_sha256"] = _rows_sha256(reparsed)
            verified_sources.append(source)
        except Exception as exc:
            source_errors[source_id] = f"{type(exc).__name__}: {exc}"

    source_hashes_after = source_file_hashes(game)
    if source_hashes_before != source_hashes_after:
        raise GateError("PARSER_FILES_CHANGED_DURING_FETCH")
    failed_ids = set(source_errors)
    unadmitted = [
        {k: v for k, v in item.items()
         if k in {"url", "requested_url", "raw_sha256", "size_bytes", "content_type",
                  "http_status", "fetched_at", "parser_version", "raw_base64",
                  "_source_id", "_source_root", "_host"}}
        for item in raw_artifacts if item["_source_id"] in failed_ids
    ]
    return {
        "schema": WORKER_SCHEMA, "lottery": game,
        "parser_version": parser_version, "source_files_sha256": source_hashes_after,
        "collection_started_at_local_untrusted": started,
        "collection_finished_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
        "sources": verified_sources,
        "source_errors": source_errors,
        "unadmitted_raw_artifacts": unadmitted,
        "transport_failures": transport_failures,
        "status": "WORKER_BLOCKED" if source_errors else "WORKER_FETCH_COMPLETE",
        "timestamp_trust": "LOCAL_CLOCK_UNTRUSTED",
    }


def validate_worker_payload(payload: dict, *, expected_game: str | None = None) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != WORKER_SCHEMA:
        raise GateError("INVALID_OFFICIAL_INTAKE_WORKER_SCHEMA")
    game = payload.get("lottery")
    if game not in SOURCE_IDS or (expected_game is not None and game != expected_game):
        raise GateError("OFFICIAL_INTAKE_GAME_MISMATCH")
    current_hashes = source_file_hashes(game)
    if payload.get("source_files_sha256") != current_hashes:
        raise GateError("PARSER_SOURCE_HASH_CHANGED_DURING_HANDOFF")
    parser_version = payload.get("parser_version")
    if not isinstance(parser_version, str) or not parser_version:
        raise GateError("PARSER_VERSION_REQUIRED")
    if parser_version != _expected_parser_version(game):
        raise GateError("PARSER_VERSION_DOES_NOT_MATCH_SOURCE_CODE")
    source_items = payload.get("sources")
    if not isinstance(source_items, list) or len(source_items) != 2:
        raise GateError("EXACTLY_TWO_SOURCE_HISTORIES_REQUIRED")
    expected_ids = set(SOURCE_IDS[game].values())
    if {s.get("source_id") for s in source_items if isinstance(s, dict)} != expected_ids:
        raise GateError("SOURCE_IDENTITY_SET_MISMATCH")

    checked_sources = []
    for source in source_items:
        source_id = source.get("source_id")
        url = source.get("url")
        host, root = _root_for_url(game, url)
        if root != EXPECTED_ROOTS[game].get(source_id):
            raise GateError("SOURCE_ID_NOT_BOUND_TO_EXPECTED_OFFICIAL_ROOT")
        if source.get("source_root") != root:
            raise GateError("SOURCE_ROOT_IDENTITY_MISMATCH")
        if source.get("source_name") != EXPECTED_SOURCE_NAMES[game].get(source_id):
            raise GateError("SOURCE_NAME_IDENTITY_MISMATCH")
        rows = _canonical_draws(game, source.get("draws"))
        artifacts = _validate_artifacts(game, source, parser_version)
        if source.get("raw_reparse_status") != "PASS":
            raise GateError("RAW_REPARSE_NOT_PASSED")
        if source.get("raw_reparse_sha256") != _rows_sha256(rows):
            raise GateError("RAW_REPARSE_SHA_MISMATCH")
        receipt = source.get("receipt")
        if (not isinstance(receipt, dict) or receipt.get("status") != "PASS"
                or receipt.get("draw_count") != len(rows)
                or receipt.get("latest_issue") != rows[-1]["issue"]):
            raise GateError("SOURCE_RECEIPT_DOES_NOT_MATCH_PARSED_HISTORY")
        checked_sources.append({
            "source_id": source_id, "source_name": source.get("source_name"),
            "url": url, "host": host, "source_root": root,
            "draws": rows, "draw_count": len(rows), "raw_artifacts": artifacts,
            "receipt": source.get("receipt"),
        })
    if checked_sources[0]["source_root"] == checked_sources[1]["source_root"]:
        raise GateError("TWO_DISTINCT_OFFICIAL_SOURCE_ROOTS_REQUIRED")

    maps = [{row["issue"]: row for row in source["draws"]} for source in checked_sources]
    if checked_sources[0]["draws"][-1]["issue"] != checked_sources[1]["draws"][-1]["issue"]:
        raise GateError("OFFICIAL_SOURCE_LATEST_ISSUE_MISMATCH")
    common = sorted(set(maps[0]) & set(maps[1]), key=int)
    if len(common) < 120:
        raise GateError("OFFICIAL_SOURCE_OVERLAP_LT_120")
    mismatches = [issue for issue in common if maps[0][issue] != maps[1][issue]]
    if mismatches:
        raise GateError("OFFICIAL_SOURCE_DRAW_CONFLICT:" + ",".join(mismatches[:10]))
    consensus = _canonical_draws(game, [maps[0][issue] for issue in common])
    artifact_count = sum(len(source["raw_artifacts"]) for source in checked_sources)
    return {
        "schema": SCHEMA, "lottery": game, "status": "HISTORY_CROSSCHECK_PASS",
        "source_count": 2, "source_roots": [s["source_root"] for s in checked_sources],
        "source_summaries": [
            {"source_id": s["source_id"], "source_root": s["source_root"],
             "draw_count": s["draw_count"], "latest_issue": s["draws"][-1]["issue"],
             "raw_artifact_count": len(s["raw_artifacts"]), "parser_version": parser_version}
            for s in checked_sources
        ],
        "consensus_draw_count": len(consensus), "consensus_draws": consensus,
        "sources": checked_sources, "source_files_sha256": current_hashes,
        "collection_started_at_local_untrusted": payload.get("collection_started_at_local_untrusted"),
        "collection_finished_at_local_untrusted": payload.get("collection_finished_at_local_untrusted"),
        "raw_artifact_count": artifact_count, "raw_byte_sha_validation": "PASS",
        "parser_to_raw_binding": "SAME_PROCESS_SOURCE_PARSER_OUTPUT_AND_RAW_BYTES",
        "source_origin_authenticity": "NOT_CRYPTOGRAPHICALLY_VERIFIED",
        "publication_time_authenticity": "NOT_VERIFIED",
        "official_history_admission": "SHADOW_HISTORY_ONLY",
        "official_target_admission": "BLOCKED", "external_tsa": "NOT_RUN",
        "formal_A": 0, "decision": "NO_EDGE",
        "limitations": [
            "Raw bytes and parsed records are emitted by the same existing parser process and are hash-bound, but source publication times and origin are not independently authenticated.",
            "The collector does not derive or certify the next target issue, actual sales cutoff, or special draw schedule.",
            "Local capture timestamps are not trusted timestamps; a verified external seal must be applied before any forecast.",
            "This bundle is historical source evidence only and cannot promote a prediction to formal A.",
        ],
    }


def collect_live_history(game: str, *, timeout_seconds: int = 600) -> dict:
    if game not in SOURCE_IDS:
        raise GateError("UNKNOWN_LOTTERY_FOR_SOURCE_INTAKE")
    before = source_file_hashes(game)
    completed = subprocess.run(
        [sys.executable, "-m", "research.harness_v46.official_intake", "--worker", game],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout_seconds,
        check=False, env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    after = source_file_hashes(game)
    if before != after:
        raise GateError("PARSER_FILES_CHANGED_DURING_FETCH")
    if completed.returncode != 0:
        raise GateError("OFFICIAL_SOURCE_WORKER_FAILED:" + completed.stderr[-2000:])
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GateError("OFFICIAL_SOURCE_WORKER_NON_JSON_OUTPUT:" + completed.stdout[-500:]) from exc
    if payload.get("source_files_sha256") != before:
        raise GateError("PARSER_SOURCE_HASH_CHANGED_DURING_HANDOFF")
    if payload.get("schema") != WORKER_SCHEMA or payload.get("lottery") != game:
        raise GateError("OFFICIAL_SOURCE_WORKER_IDENTITY_MISMATCH")
    if payload.get("status") == "WORKER_BLOCKED":
        source_errors = payload.get("source_errors")
        if not isinstance(source_errors, dict) or not source_errors:
            raise GateError("BLOCKED_WORKER_MISSING_SOURCE_ERRORS")
        return {
            "schema": SCHEMA, "lottery": game, "status": "BLOCKED",
            "error": "; ".join(f"{k}: {v}" for k, v in sorted(source_errors.items())),
            "source_errors": source_errors,
            "sources": payload.get("sources", []),
            "unadmitted_raw_artifacts": payload.get("unadmitted_raw_artifacts", []),
            "transport_failures": payload.get("transport_failures", []),
            "source_files_sha256": before,
            "timestamp_trust": "LOCAL_CLOCK_UNTRUSTED",
            "official_history_admission": "BLOCKED",
            "official_target_admission": "BLOCKED",
            "external_tsa": "NOT_RUN", "formal_A": 0, "decision": "NO_EDGE",
        }
    return validate_worker_payload(payload, expected_game=game)


def collect_both() -> dict:
    results, errors = {}, {}
    for game in ("SSQ", "DLT"):
        try:
            result = collect_live_history(game)
            results[game] = result
            if result.get("status") == "BLOCKED":
                errors[game] = str(result.get("error") or "OFFICIAL_INTAKE_BLOCKED")
        except Exception as exc:
            errors[game] = f"{type(exc).__name__}: {exc}"
            results[game] = {
                "schema": SCHEMA, "lottery": game, "status": "BLOCKED",
                "error": errors[game], "official_history_admission": "BLOCKED",
                "official_target_admission": "BLOCKED", "external_tsa": "NOT_RUN",
                "formal_A": 0, "decision": "NO_EDGE",
            }
    return {
        "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
        "created_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
        "games": results, "errors": errors, "official_target_admission": "BLOCKED",
        "external_tsa": "NOT_RUN", "formal_A": 0, "decision": "NO_EDGE",
    }


def write_bundle(bundle: dict, output_dir: str | Path) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=False)

    def write_encoded(game: str, source_id: str, artifact: dict, *,
                      base64_key: str, directory: str, filename_prefix: str = ""):
        encoded = artifact.get(base64_key)
        if encoded is None:
            artifact["body_preserved"] = False
            return
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise GateError("RAW_BUNDLE_BASE64_INVALID") from exc
        if len(raw) != artifact.get("size_bytes") or _sha(raw) != artifact.get("raw_sha256"):
            raise GateError("RAW_SHA_CHANGED_BEFORE_BUNDLE_WRITE")
        relative = Path(directory) / game / source_id / (
            filename_prefix + artifact["raw_sha256"] + ".bin"
        )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(raw)
        artifact.pop(base64_key, None)
        artifact["artifact_path"] = relative.as_posix()
        artifact["body_preserved"] = True

    for game, result in bundle.get("games", {}).items():
        for source in result.get("sources", []):
            for artifact in source.get("raw_artifacts", []):
                write_encoded(game, source["source_id"], artifact,
                              base64_key="raw_base64", directory="raw")
        for idx, artifact in enumerate(result.get("unadmitted_raw_artifacts", []), start=1):
            source_id = str(artifact.get("_source_id") or artifact.get("source_id") or "unknown")
            write_encoded(game, source_id, artifact, base64_key="raw_base64",
                          directory="raw-unadmitted", filename_prefix=f"{idx:04d}-")
            artifact.pop("_source_id", None)
            artifact.pop("_source_root", None)
            artifact.pop("_host", None)
            artifact["classification"] = "UNADMITTED_RAW_RESPONSE_NOT_CROSSCHECKED"
        for idx, artifact in enumerate(result.get("transport_failures", []), start=1):
            source_id = str(artifact.get("source_id") or "unknown")
            write_encoded(game, source_id, artifact, base64_key="body_base64",
                          directory="transport-failures", filename_prefix=f"{idx:04d}-")
            artifact["classification"] = "TRANSPORT_FAILURE_UNTRUSTED_NOT_OFFICIAL_SOURCE_EVIDENCE"
    manifest_path = destination / "intake.json"
    with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(bundle, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V4.7 official history intake; no target admission.")
    parser.add_argument("--game", choices=("SSQ", "DLT", "ALL"), default="ALL")
    parser.add_argument("--output-dir", help="new directory; existing paths are never overwritten")
    parser.add_argument("--worker", choices=("SSQ", "DLT"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        try:
            payload = _worker(args.worker)
            sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0
        except Exception as exc:
            sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
            return 2
    if not args.output_dir:
        parser.error("--output-dir is required outside worker mode")
    if args.game == "ALL":
        bundle = collect_both()
    else:
        try:
            result = collect_live_history(args.game)
            bundle = {
                "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
                "created_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
                "games": {args.game: result},
                "errors": ({args.game: str(result.get("error") or "OFFICIAL_INTAKE_BLOCKED")}
                           if result.get("status") == "BLOCKED" else {}),
                "official_target_admission": "BLOCKED", "external_tsa": "NOT_RUN",
                "formal_A": 0, "decision": "NO_EDGE",
            }
        except Exception as exc:
            bundle = {
                "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
                "created_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
                "games": {args.game: {
                    "schema": SCHEMA, "lottery": args.game, "status": "BLOCKED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "official_history_admission": "BLOCKED", "official_target_admission": "BLOCKED",
                    "formal_A": 0, "decision": "NO_EDGE",
                }},
                "errors": {args.game: f"{type(exc).__name__}: {exc}"},
                "official_target_admission": "BLOCKED", "external_tsa": "NOT_RUN",
                "formal_A": 0, "decision": "NO_EDGE",
            }
    path = write_bundle(bundle, args.output_dir)
    print(json.dumps({
        "manifest_path": str(path),
        "games": {g: v.get("status") for g, v in bundle["games"].items()},
        "errors": bundle.get("errors", {}),
        "official_target_admission": "BLOCKED", "formal_A": 0, "decision": "NO_EDGE",
    }, ensure_ascii=False, sort_keys=True))
    return 0 if not bundle.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
