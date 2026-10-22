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

from .core import GateError, SOURCE_HOSTS_BY_GAME

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
    ),
    "DLT": (
        "DLT/src/glp/sources.py",
        "DLT/src/glp/constants.py",
        "DLT/src/glp/domain.py",
        "DLT/src/glp/util.py",
        "DLT/src/glp/net_client.py",
    ),
}
SOURCE_IDS = {
    "SSQ": {
        "official_cwl_L0": "national",
        "official_shanghai_L1": "shanghai",
        "official_hebei_L2": "hebei",
    },
    "DLT": {
        "official_sporttery_national": "national",
        "official_jiangsu_sporttery": "jiangsu",
        "official_gansu_sporttery": "gansu",
    },
}
EXPECTED_ROOTS = {
    "SSQ": {"national": "cwl.gov.cn", "shanghai": "swlc.net.cn", "hebei": "yzfcw.com"},
    "DLT": {"national": "sporttery.cn", "jiangsu": "js-lottery.com", "gansu": "gstc.org.cn"},
}
EXPECTED_SOURCE_NAMES = {
    "SSQ": {
        "national": "official_cwl_L0", "shanghai": "official_shanghai_L1",
        "hebei": "official_hebei_L2",
    },
    "DLT": {
        "national": "official_sporttery_national",
        "jiangsu": "official_jiangsu_sporttery",
        "gansu": "official_gansu_sporttery",
    },
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


def _canonical_draws(game: str, rows: list[dict], *, minimum: int = 120) -> list[dict]:
    if type(minimum) is not int or minimum < 1:
        raise GateError("INVALID_SOURCE_HISTORY_MINIMUM")
    if not isinstance(rows, list) or len(rows) < minimum:
        raise GateError(f"SOURCE_HISTORY_REQUIRES_AT_LEAST_{minimum}_DRAWS")
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
        # Duplicate dates cannot be silently accepted: historical corrections require
        # an explicit independently verified exception in a new source contract.
        if parsed_day.isoformat() != day[:10] or (last_date is not None and parsed_day <= last_date):
            raise GateError("NONMONOTONIC_SOURCE_DRAW_DATE:" + issue + ":" + day[:10])
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


def calendar_diagnostics(game: str, rows: list[dict]) -> list[dict]:
    """Diagnostic anomalies only; never rewrite official timestamps or draw dates."""
    if game not in SOURCE_IDS or not isinstance(rows, list):
        raise GateError("INVALID_CALENDAR_DIAGNOSTIC_INPUT")
    anomalies = []
    previous = None
    for row in rows:
        if not isinstance(row, dict):
            raise GateError("INVALID_CALENDAR_DIAGNOSTIC_ROW")
        issue, day = str(row.get("issue", "")), str(row.get("draw_date", ""))
        try:
            actual = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            anomalies.append({"issue": issue, "draw_date": day, "reason": "INVALID_DATE"})
            continue
        if previous is not None and actual <= previous:
            anomalies.append({"issue": issue, "draw_date": day,
                              "reason": "DATE_NOT_STRICTLY_INCREASING"})
        if game == "DLT" and actual.weekday() not in {0, 2, 5}:
            # Flag for source-backed exception review rather than claiming a
            # calendar exception can never happen.
            anomalies.append({"issue": issue, "draw_date": day,
                              "reason": "OUTSIDE_REGULAR_MON_WED_SAT_DRAW_CALENDAR"})
        previous = actual
    return anomalies


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
        if type(artifact["http_status"]) is not int or not 100 <= artifact["http_status"] <= 599:
            raise GateError("RAW_ARTIFACT_HTTP_STATUS_INVALID")
        if (not isinstance(artifact["content_type"], str)
                or (artifact["http_status"] == 200 and not artifact["content_type"].strip())):
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
            "http_status": artifact["http_status"], "fetched_at_local_untrusted": artifact["fetched_at"],
            "parser_version": parser_version, "raw_base64": artifact["raw_base64"],
        })
    return validated


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
    status = meta.get("http_status")
    if type(status) is not int or not 100 <= status <= 599:
        raise GateError("RAW_SOURCE_HTTP_STATUS_INVALID")
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
        "http_status": status, "fetched_at": fetched_at,
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
    if game == "SSQ" and source_id == "hebei":
        home, announcement = [], []
        for artifact in artifacts:
            if artifact.get("http_status") != 200:
                continue
            try:
                raw = base64.b64decode(artifact["raw_base64"], validate=True)
            except Exception as exc:
                raise GateError("HEBEI_RAW_BASE64_INVALID") from exc
            requested = artifact.get("requested_url")
            if requested == source_module.HEBEI_URL:
                home.append(raw)
            elif requested == source_module.HEBEI_ANNOUNCE_URL:
                announcement.append(raw)
            else:
                raise GateError("UNEXPECTED_HEBEI_SOURCE_ENDPOINT")
        if len(home) != 1 or len(announcement) != 1:
            raise GateError("HEBEI_BOTH_OFFICIAL_RAW_PAGES_REQUIRED")
        draw = source_module.parse_hebei_latest(home[0], announcement[0])
        return _canonical_draws(game, _source_rows([draw]), minimum=1)
    parsed_rows = []
    for artifact in artifacts:
        try:
            raw = base64.b64decode(artifact["raw_base64"], validate=True)
        except Exception as exc:
            raise GateError("RAW_REPARSE_BASE64_INVALID") from exc
        if artifact.get("http_status") != 200:
            # Failed HTTP responses are preserved as diagnostic evidence but are
            # never parsed as draw data, even if the server returned HTML/JSON.
            continue
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
            elif game == "DLT" and source_id == "gansu":
                parsed_rows.extend(_source_rows(
                    source_module._parse_gansu_history(source_module._decode_html(raw))
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
    minimum = 10 if game == "DLT" and source_id == "gansu" else 120
    reparsed = _canonical_draws(
        game, sorted(by_issue.values(), key=lambda row: int(row["issue"])), minimum=minimum
    )
    return reparsed


def _rows_sha256(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha(payload.encode("utf-8"))


def _install_dlt_redirect_guard(game: str, failure_recorder=None) -> None:
    """Bound redirects and preserve non-200 response bodies as untrusted diagnostics."""
    import requests
    from urllib.parse import urljoin

    original_get = requests.get

    def safe_get(url, *args, **kwargs):
        params = kwargs.pop("params", None)
        allow_redirects = kwargs.pop("allow_redirects", True)
        _, initial_root = _root_for_url(game, str(url))
        current_url, current_params = str(url), params
        for _ in range(6):
            response = original_get(
                current_url, *args, params=current_params,
                allow_redirects=False, **kwargs,
            )
            status = int(response.status_code)
            if status != 200 and failure_recorder is not None:
                final_url = str(response.url or current_url)
                _, response_root = _root_for_url(game, final_url)
                source_id = {
                    "sporttery.cn": "national",
                    "js-lottery.com": "jiangsu",
                    "gstc.org.cn": "gansu",
                }.get(response_root)
                if source_id is not None:
                    raw = bytes(response.content)
                    failure_recorder(source_id, {
                        "url": final_url, "requested_url": current_url,
                        "http_status": status,
                        "content_type": str(response.headers.get("Content-Type", "")),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "sha256": _sha(raw), "bytes": len(raw),
                        "parser_version": _expected_parser_version(game),
                    }, raw)
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
    raw_artifacts: list[dict] = []
    parser_version = _expected_parser_version(game)
    if game == "DLT":
        def record_dlt_failure(source_id, meta, raw):
            raw_artifacts.append(_normalize_worker_artifact(
                game, source_id, meta, bytes(raw), parser_version
            ))
        _install_dlt_redirect_guard(game, record_dlt_failure)
    import glp.sources as source_module
    if str(source_module.PARSER_VERSION) != parser_version:
        raise GateError("PARSER_VERSION_CHANGED_DURING_IMPORT")

    if game == "SSQ":
        from glp.constants import SSQ_HISTORY_START_ISSUE

        def recorder(meta, raw):
            source_name = str(meta.get("source") or "")
            source_id = SOURCE_IDS[game].get(source_name)
            if source_id is None:
                raise GateError("UNEXPECTED_SSQ_SOURCE_ID:" + source_name)
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
        sources = []
        errors = {}
        for source_id, source_name, fetch in source_specs:
            root = "cwl.gov.cn" if source_id == "national" else "swlc.net.cn"
            url = ("https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
                   if source_id == "national" else "https://www.swlc.net.cn/lottery/ssq.html")
            try:
                draws, receipt, _manifest = fetch()
                sources.append({
                    "source_id": source_id, "source_name": source_name,
                    "source_root": root, "url": url, "draws": _source_rows(draws),
                    "receipt": {
                        "status": receipt.status, "draw_count": receipt.draw_count,
                        "latest_issue": receipt.latest_issue, "raw_sha256": receipt.raw_sha256,
                        "fetched_at": receipt.fetched_at,
                    },
                })
            except Exception as exc:
                errors[source_id] = f"{type(exc).__name__}: {exc}"
                sources.append({
                    "source_id": source_id, "source_name": source_name,
                    "source_root": root, "url": url, "draws": [],
                    "receipt": None, "error": errors[source_id],
                })
        # Hebei is an independent official provincial publisher, but its
        # homepage + announcement provide only the latest issue, never 120+.
        if "national" in errors:
            try:
                hebei_draw, hebei_receipt, _raw_pages = source_module.fetch_hebei_latest(
                    record_raw=recorder
                )
                sources.append({
                    "source_id": "hebei", "source_name": "official_hebei_L2",
                    "source_root": "yzfcw.com", "url": source_module.HEBEI_URL,
                    "draws": _source_rows([hebei_draw]),
                    "receipt": {
                        "status": hebei_receipt.status, "draw_count": hebei_receipt.draw_count,
                        "latest_issue": hebei_receipt.latest_issue,
                        "raw_sha256": hebei_receipt.raw_sha256,
                        "fetched_at": hebei_receipt.fetched_at,
                    },
                })
            except Exception as exc:
                errors["hebei"] = f"{type(exc).__name__}: {exc}"
                sources.append({
                    "source_id": "hebei", "source_name": "official_hebei_L2",
                    "source_root": "yzfcw.com", "url": source_module.HEBEI_URL,
                    "draws": [], "receipt": None, "error": errors["hebei"],
                })
    elif game == "DLT":
        errors = {}
        national_data = jiangsu_data = gansu_data = None
        try:
            national_data = source_module.fetch_national_history()
        except Exception as exc:
            errors["national"] = f"{type(exc).__name__}: {exc}"
        try:
            jiangsu_data = source_module.fetch_jiangsu_history()
        except Exception as exc:
            errors["jiangsu"] = f"{type(exc).__name__}: {exc}"
        # The Gansu official history page provides a smaller recent window.
        # Use it only as an independent fallback paired with a 120+ issue primary.
        if national_data is None or jiangsu_data is None:
            try:
                gansu_data = source_module.fetch_gansu_recent(20)
            except Exception as exc:
                errors["gansu"] = f"{type(exc).__name__}: {exc}"

        source_specs = [
            ("national", "official_sporttery_national", "sporttery.cn",
             "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry", national_data),
            ("jiangsu", "official_jiangsu_sporttery", "js-lottery.com",
             "https://api.js-lottery.com/Lottery/_ListData", jiangsu_data),
        ]
        if national_data is None or jiangsu_data is None:
            source_specs.append((
                "gansu", "official_gansu_sporttery", "gstc.org.cn",
                "https://www.gstc.org.cn/wanfa/dlt_history", gansu_data,
            ))
        sources = []
        for source_id, source_name, root, url, data in source_specs:
            if data is None:
                sources.append({
                    "source_id": source_id, "source_name": source_name,
                    "source_root": root, "url": url, "draws": [],
                    "receipt": None, "error": errors.get(source_id, "SOURCE_FETCH_FAILED"),
                })
                continue
            draws, receipt, manifest = data
            manifest_items = manifest if isinstance(manifest, list) else [manifest]
            for entry in manifest_items:
                encoded = entry.get("body_b64")
                if not isinstance(encoded, str):
                    raise GateError("DLT_PARSER_RAW_BODY_MISSING")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except Exception as exc:
                    raise GateError("DLT_PARSER_RAW_BODY_BASE64_INVALID") from exc
                meta = {
                    "url": entry.get("final_url") or entry.get("requested_url"),
                    "requested_url": entry.get("requested_url") or entry.get("final_url"),
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
                "source_root": root, "url": url, "draws": _source_rows(draws),
                "receipt": {
                    "status": receipt.status, "draw_count": receipt.draw_count,
                    "latest_issue": receipt.latest_issue, "raw_sha256": receipt.raw_sha256,
                    "fetched_at": receipt.fetched_at,
                },
            })
    else:
        raise GateError("UNKNOWN_LOTTERY_FOR_SOURCE_INTAKE")

    for source in sources:
        source_id = source["source_id"]
        internal_artifacts = [item for item in raw_artifacts if item["_source_id"] == source_id]
        source["raw_artifacts"] = [
            {k: v for k, v in item.items()
             if k in {"url", "requested_url", "raw_sha256", "size_bytes", "content_type",
                      "http_status", "fetched_at", "parser_version", "raw_base64"}}
            for item in internal_artifacts
        ]
        if not source["raw_artifacts"]:
            if not source.get("error"):
                source["error"] = "SOURCE_RAW_ARTIFACTS_MISSING"
                errors[source_id] = source["error"]
            source["raw_reparse_status"] = "NOT_RUN"
            continue
        if source.get("error") or not source.get("draws"):
            source["raw_reparse_status"] = "NOT_RUN_SOURCE_FETCH_FAILED"
            continue
        try:
            anomalies = calendar_diagnostics(game, source["draws"])
            if anomalies:
                source["calendar_anomalies"] = anomalies
                raise GateError("SOURCE_DRAW_CALENDAR_ANOMALIES:" + json.dumps(
                    anomalies[:12], ensure_ascii=False, sort_keys=True
                ))
            reparsed = _reparse_raw_history(game, source_module, source_id, source["raw_artifacts"])
            source_draws = _canonical_draws(
                game, source["draws"], minimum=_source_minimum(game, source_id)
            )
            if reparsed != source_draws:
                raise GateError("RAW_REPARSED_ROWS_DIFFER_FROM_SOURCE_OUTPUT:" + source_id)
            source["raw_reparse_status"] = "PASS"
            source["raw_reparse_sha256"] = _rows_sha256(reparsed)
        except Exception as exc:
            source["error"] = f"{type(exc).__name__}: {exc}"
            errors[source_id] = source["error"]
            source["raw_reparse_status"] = "FAIL"
    source_hashes_after = source_file_hashes(game)
    if source_hashes_before != source_hashes_after:
        raise GateError("PARSER_FILES_CHANGED_DURING_FETCH")
    valid_ids = {
        source["source_id"] for source in sources
        if source.get("raw_reparse_status") == "PASS" and source.get("draws")
    }
    if game == "SSQ":
        has_valid_pair = any(pair.issubset(valid_ids) for pair in (
            {"national", "shanghai"}, {"shanghai", "hebei"}
        ))
    else:
        has_valid_pair = any(pair.issubset(valid_ids) for pair in (
            {"national", "jiangsu"}, {"national", "gansu"}, {"jiangsu", "gansu"}
        ))
    return {
        "schema": WORKER_SCHEMA, "lottery": game,
        "parser_version": parser_version, "source_files_sha256": source_hashes_after,
        "collection_started_at_local_untrusted": started,
        "collection_finished_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
        "sources": sources, "errors": errors,
        "status": "WORKER_FETCH_COMPLETE" if has_valid_pair else "WORKER_FETCH_PARTIAL",
        "timestamp_trust": "LOCAL_CLOCK_UNTRUSTED",
    }


def _source_id_set_valid(game: str, source_items: list[dict]) -> bool:
    ids = [s.get("source_id") for s in source_items if isinstance(s, dict)]
    if len(ids) != len(source_items) or len(set(ids)) != len(ids):
        return False
    if game == "SSQ":
        return len(ids) in (2, 3) and {"national", "shanghai"}.issubset(ids) and set(ids).issubset({"national", "shanghai", "hebei"})
    return 2 <= len(ids) <= 3 and set(ids).issubset({"national", "jiangsu", "gansu"})


def _source_minimum(game: str, source_id: str) -> int:
    if game == "SSQ" and source_id == "hebei":
        return 1
    return 10 if game == "DLT" and source_id == "gansu" else 120


def _validate_partial_worker_payload(payload: dict, game: str, parser_version: str,
                                    current_hashes: dict[str, str]) -> dict:
    source_items = payload.get("sources")
    if not isinstance(source_items, list) or not _source_id_set_valid(game, source_items):
        raise GateError("INVALID_PARTIAL_SOURCE_IDENTITY_SET")
    checked_sources = []
    for source in source_items:
        source_id = source.get("source_id")
        host, root = _root_for_url(game, source.get("url"))
        if root != EXPECTED_ROOTS[game].get(source_id):
            raise GateError("SOURCE_ID_NOT_BOUND_TO_EXPECTED_OFFICIAL_ROOT")
        if source.get("source_root") != root:
            raise GateError("SOURCE_ROOT_IDENTITY_MISMATCH")
        if source.get("source_name") != EXPECTED_SOURCE_NAMES[game].get(source_id):
            raise GateError("SOURCE_NAME_IDENTITY_MISMATCH")
        raw_list = source.get("raw_artifacts", [])
        if not isinstance(raw_list, list):
            raise GateError("INVALID_PARTIAL_RAW_ARTIFACT_LIST")
        artifacts = _validate_artifacts(game, source, parser_version) if raw_list else []
        valid_draws = []
        if source.get("raw_reparse_status") == "PASS" and source.get("draws"):
            valid_draws = _canonical_draws(
                game, source["draws"], minimum=_source_minimum(game, source_id)
            )
            if source.get("raw_reparse_sha256") != _rows_sha256(valid_draws):
                raise GateError("RAW_REPARSE_SHA_MISMATCH")
            receipt = source.get("receipt")
            if (not isinstance(receipt, dict) or receipt.get("status") != "PASS"
                    or receipt.get("draw_count") != len(valid_draws)
                    or receipt.get("latest_issue") != valid_draws[-1]["issue"]):
                raise GateError("SOURCE_RECEIPT_DOES_NOT_MATCH_PARSED_HISTORY")
        checked_sources.append({
            "source_id": source_id, "source_name": source.get("source_name"),
            "url": source["url"], "host": host, "source_root": root,
            "draws": valid_draws, "draw_count": len(valid_draws),
            "raw_artifacts": artifacts, "receipt": source.get("receipt"),
            "error": source.get("error"),
            "calendar_anomalies": source.get("calendar_anomalies", []),
            "raw_reparse_status": source.get("raw_reparse_status", "NOT_RUN"),
        })
    errors = payload.get("errors", {})
    if not isinstance(errors, dict):
        raise GateError("INVALID_PARTIAL_SOURCE_ERRORS")
    artifact_count = sum(len(s["raw_artifacts"]) for s in checked_sources)
    return {
        "schema": SCHEMA, "lottery": game, "status": "SOURCE_FETCH_PARTIAL",
        "source_count": sum(bool(s["draws"]) for s in checked_sources),
        "source_roots": [s["source_root"] for s in checked_sources],
        "source_summaries": [
            {"source_id": s["source_id"], "source_root": s["source_root"],
             "draw_count": s["draw_count"],
             "latest_issue": s["draws"][-1]["issue"] if s["draws"] else None,
             "raw_artifact_count": len(s["raw_artifacts"]),
             "raw_reparse_status": s["raw_reparse_status"], "error": s["error"],
             "calendar_anomalies": s["calendar_anomalies"]}
            for s in checked_sources
        ],
        "consensus_draw_count": 0, "consensus_draws": [], "sources": checked_sources,
        "source_files_sha256": current_hashes,
        "collection_started_at_local_untrusted": payload.get("collection_started_at_local_untrusted"),
        "collection_finished_at_local_untrusted": payload.get("collection_finished_at_local_untrusted"),
        "raw_artifact_count": artifact_count,
        "raw_byte_sha_validation": "PASS" if artifact_count else "NO_ARTIFACTS",
        "source_origin_authenticity": "NOT_CRYPTOGRAPHICALLY_VERIFIED",
        "publication_time_authenticity": "NOT_VERIFIED",
        "official_history_admission": "BLOCKED",
        "official_target_admission": "BLOCKED", "external_tsa": "NOT_RUN",
        "formal_A": 0, "decision": "NO_EDGE", "errors": errors,
        "limitations": [
            "No qualified two-source pair passed all source, raw-byte, parser and overlap checks.",
            "Preserved failure bodies are diagnostic evidence, not draw data.",
            "No target issue, sales cutoff, trusted pre-draw timestamp, or formal-A eligibility is established.",
        ],
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
    if payload.get("status") != "WORKER_FETCH_COMPLETE":
        return _validate_partial_worker_payload(payload, game, parser_version, current_hashes)
    source_items = payload.get("sources")
    if not isinstance(source_items, list) or not _source_id_set_valid(game, source_items):
        raise GateError("INVALID_COMPLETE_SOURCE_IDENTITY_SET")

    checked_sources = []
    candidates = {}
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
        raw_list = source.get("raw_artifacts", [])
        if not isinstance(raw_list, list):
            raise GateError("INVALID_RAW_ARTIFACT_LIST")
        artifacts = _validate_artifacts(game, source, parser_version) if raw_list else []
        rows = []
        valid_source = source.get("raw_reparse_status") == "PASS" and bool(source.get("draws"))
        if valid_source:
            rows = _canonical_draws(
                game, source["draws"], minimum=_source_minimum(game, source_id)
            )
            if source.get("raw_reparse_sha256") != _rows_sha256(rows):
                raise GateError("RAW_REPARSE_SHA_MISMATCH")
            receipt = source.get("receipt")
            if (not isinstance(receipt, dict) or receipt.get("status") != "PASS"
                    or receipt.get("draw_count") != len(rows)
                    or receipt.get("latest_issue") != rows[-1]["issue"]):
                raise GateError("SOURCE_RECEIPT_DOES_NOT_MATCH_PARSED_HISTORY")
            candidates[source_id] = {
                "source_id": source_id, "source_name": source.get("source_name"),
                "url": url, "host": host, "source_root": root,
                "draws": rows, "draw_count": len(rows), "raw_artifacts": artifacts,
                "receipt": receipt,
            }
        checked_sources.append({
            "source_id": source_id, "source_name": source.get("source_name"),
            "url": url, "host": host, "source_root": root,
            "draws": rows, "draw_count": len(rows), "raw_artifacts": artifacts,
            "receipt": source.get("receipt"), "error": source.get("error"),
            "raw_reparse_status": source.get("raw_reparse_status", "NOT_RUN"),
        })

    if game == "SSQ" and {"national", "shanghai"}.issubset(candidates):
        pair_ids, minimum_overlap = ("national", "shanghai"), 120
    elif game == "SSQ" and {"shanghai", "hebei"}.issubset(candidates):
        pair_ids, minimum_overlap = ("shanghai", "hebei"), 1
    elif game == "SSQ":
        raise GateError("NO_VALID_SSQ_OFFICIAL_SOURCE_PAIR")
    elif {"national", "jiangsu"}.issubset(candidates):
        pair_ids, minimum_overlap = ("national", "jiangsu"), 120
    elif {"national", "gansu"}.issubset(candidates):
        pair_ids, minimum_overlap = ("national", "gansu"), 10
    elif {"jiangsu", "gansu"}.issubset(candidates):
        pair_ids, minimum_overlap = ("jiangsu", "gansu"), 10
    else:
        raise GateError("NO_VALID_TWO_SOURCE_PAIR")

    pair = [candidates[pair_ids[0]], candidates[pair_ids[1]]]
    maps = [{row["issue"]: row for row in source["draws"]} for source in pair]
    if pair[0]["draws"][-1]["issue"] != pair[1]["draws"][-1]["issue"]:
        raise GateError("OFFICIAL_SOURCE_LATEST_ISSUE_MISMATCH")
    common = sorted(set(maps[0]) & set(maps[1]), key=int)
    if len(common) < minimum_overlap:
        raise GateError("OFFICIAL_SOURCE_OVERLAP_TOO_SMALL")
    mismatches = [issue for issue in common if maps[0][issue] != maps[1][issue]]
    if mismatches:
        raise GateError("OFFICIAL_SOURCE_DRAW_CONFLICT:" + ",".join(mismatches[:10]))
    primary = pair[0]
    verified_overlap = [maps[0][issue] for issue in common]
    # A 120+ primary history with 20 independently checked recent rows must
    # NEVER be labelled as 120+ independently verified consensus history.
    full_dual_source = len(common) >= 120
    evidence_tier = "FULL_120_PLUS_OVERLAP" if full_dual_source else "LIMITED_RECENT_OVERLAP"
    artifact_count = sum(len(source["raw_artifacts"]) for source in checked_sources)
    errors = payload.get("errors", {})
    if not isinstance(errors, dict):
        raise GateError("INVALID_SOURCE_ERRORS")
    warnings = {k: v for k, v in errors.items() if k not in pair_ids}
    return {
        "schema": SCHEMA, "lottery": game,
        "status": "HISTORY_CROSSCHECK_PASS" if full_dual_source else "HISTORY_CROSSCHECK_LIMITED",
        "history_validation_tier": evidence_tier,
        "source_count": 2, "selected_source_ids": list(pair_ids),
        "source_roots": [s["source_root"] for s in pair],
        "overlap_count": len(common),
        "consensus_draw_count": len(verified_overlap),
        "consensus_draws": verified_overlap,
        "primary_history_draw_count": len(primary["draws"]),
        "primary_history_draws": primary["draws"],
        "unverified_primary_history_draw_count": len(primary["draws"]) - len(common),
        "source_summaries": [
            {"source_id": s["source_id"], "source_root": s["source_root"],
             "draw_count": s["draw_count"],
             "latest_issue": s["draws"][-1]["issue"] if s["draws"] else None,
             "raw_artifact_count": len(s["raw_artifacts"]),
             "raw_reparse_status": s["raw_reparse_status"],
             "error": s["error"], "parser_version": parser_version}
            for s in checked_sources
        ],
        "sources": checked_sources, "source_files_sha256": current_hashes,
        "collection_started_at_local_untrusted": payload.get("collection_started_at_local_untrusted"),
        "collection_finished_at_local_untrusted": payload.get("collection_finished_at_local_untrusted"),
        "raw_artifact_count": artifact_count, "raw_byte_sha_validation": "PASS" if artifact_count else "NO_ARTIFACTS",
        "parser_to_raw_binding": "SAME_PROCESS_REPARSE_MATCHED",
        "source_origin_authenticity": "NOT_CRYPTOGRAPHICALLY_VERIFIED",
        "publication_time_authenticity": "NOT_VERIFIED",
        "official_history_admission": (
            "SHADOW_HISTORY_ONLY" if full_dual_source else "BLOCKED_120_ISSUE_DUAL_SOURCE"
        ),
        "official_target_admission": "BLOCKED", "external_tsa": "NOT_RUN",
        "formal_A": 0, "decision": "NO_EDGE", "warnings": warnings,
        "limitations": [
            "Independently agreed issues only are reported as consensus_draws; primary_history_draws are not all independently verified.",
            "A fallback recent overlap smaller than 120 does not satisfy the preregistered dual-source 120+ gate.",
            "This is a two-source history cross-check, not target/cutoff admission.",
            "Source publication times and origin are not independently authenticated.",
            "Local capture timestamps are not trusted timestamps; an external seal must precede any forecast.",
            "The verified overlap does not upgrade any model to formal A or demonstrate a D2 edge.",
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
    return validate_worker_payload(payload, expected_game=game)


def collect_both() -> dict:
    results, errors = {}, {}
    for game in ("SSQ", "DLT"):
        try:
            results[game] = collect_live_history(game)
            if results[game].get("status") != "HISTORY_CROSSCHECK_PASS":
                errors[game] = json.dumps(results[game].get("errors", {
                    "intake": "OFFICIAL_HISTORY_NOT_CROSSCHECKED"
                }), ensure_ascii=False, sort_keys=True)
        except Exception as exc:
            errors[game] = f"{type(exc).__name__}: {exc}"
            results[game] = {
                "schema": SCHEMA, "lottery": game, "status": "BLOCKED",
                "error": errors[game], "official_history_admission": "BLOCKED",
                "official_target_admission": "BLOCKED", "formal_A": 0, "decision": "NO_EDGE",
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
    for game, result in bundle.get("games", {}).items():
        for source in result.get("sources", []):
            for artifact in source.get("raw_artifacts", []):
                raw = base64.b64decode(artifact.pop("raw_base64"), validate=True)
                if _sha(raw) != artifact["raw_sha256"]:
                    raise GateError("RAW_SHA_CHANGED_BEFORE_BUNDLE_WRITE")
                relative = Path("raw") / game / source["source_id"] / (artifact["raw_sha256"] + ".bin")
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as handle:
                    handle.write(raw)
                artifact["artifact_path"] = relative.as_posix()
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
            game_errors = {} if result.get("status") == "HISTORY_CROSSCHECK_PASS" else {
                args.game: json.dumps(result.get("errors", {
                    "intake": "OFFICIAL_HISTORY_NOT_CROSSCHECKED"
                }), ensure_ascii=False, sort_keys=True)
            }
            bundle = {
                "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
                "created_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
                "games": {args.game: result}, "errors": game_errors,
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
