"""Official-source history intake adapter for V4.7.

Uses the repository's existing game-specific parsers in isolated subprocesses so
both packages named glp cannot collide. This is data acquisition and semantic
cross-check only: local timestamps are untrusted; target/cutoff admission,
external timestamping and formal-A eligibility remain blocked.
"""
from __future__ import annotations

import argparse
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
    "SSQ": {"official_cwl_L0": "national", "official_shanghai_L1": "shanghai"},
    "DLT": {
        "official_sporttery_national": "national",
        "official_jiangsu_sporttery": "jiangsu",
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
        if not raw or len(raw) != artifact["size_bytes"] or _sha(raw) != artifact["raw_sha256"]:
            raise GateError("RAW_ARTIFACT_BYTES_SHA_MISMATCH")
        try:
            datetime.fromisoformat(artifact["fetched_at"].replace("Z", "+00:00"))
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


def _normalize_worker_artifact(game: str, source_id: str, meta: dict, raw: bytes,
                               parser_version: str) -> dict:
    if not isinstance(raw, bytes) or not raw:
        raise GateError("EMPTY_RAW_SOURCE_BYTES")
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
        datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
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


def _install_dlt_redirect_guard(game: str) -> None:
    """Bound DLT Requests redirects to the original allowlisted registrable root."""
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
            if not allow_redirects or int(response.status_code) not in REDIRECT_CODES:
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
    if game == "DLT":
        _install_dlt_redirect_guard(game)
    import glp.sources as source_module

    parser_version = str(source_module.PARSER_VERSION)
    raw_artifacts: list[dict] = []

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
        for source_id, source_name, fetch in source_specs:
            draws, receipt, _manifest = fetch()
            sources.append({
                "source_id": source_id, "source_name": source_name,
                "source_root": "cwl.gov.cn" if source_id == "national" else "swlc.net.cn",
                "url": "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
                       if source_id == "national" else "https://www.swlc.net.cn/lottery/ssq.html",
                "draws": _source_rows(draws),
                "receipt": {
                    "status": receipt.status, "draw_count": receipt.draw_count,
                    "latest_issue": receipt.latest_issue, "raw_sha256": receipt.raw_sha256,
                    "fetched_at": receipt.fetched_at,
                },
            })
    elif game == "DLT":
        national_draws, national_receipt, national_manifest = source_module.fetch_national_history()
        jiangsu_draws, jiangsu_receipt, jiangsu_manifest = source_module.fetch_jiangsu_history()
        for source_id, manifest in (
            ("national", national_manifest), ("jiangsu", jiangsu_manifest),
        ):
            for entry in manifest:
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
        sources = [
            {
                "source_id": "national", "source_name": "official_sporttery_national",
                "source_root": "sporttery.cn",
                "url": "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry",
                "draws": _source_rows(national_draws),
                "receipt": {
                    "status": national_receipt.status, "draw_count": national_receipt.draw_count,
                    "latest_issue": national_receipt.latest_issue, "raw_sha256": national_receipt.raw_sha256,
                    "fetched_at": national_receipt.fetched_at,
                },
            },
            {
                "source_id": "jiangsu", "source_name": "official_jiangsu_sporttery",
                "source_root": "js-lottery.com",
                "url": "https://api.js-lottery.com/Lottery/_ListData",
                "draws": _source_rows(jiangsu_draws),
                "receipt": {
                    "status": jiangsu_receipt.status, "draw_count": jiangsu_receipt.draw_count,
                    "latest_issue": jiangsu_receipt.latest_issue, "raw_sha256": jiangsu_receipt.raw_sha256,
                    "fetched_at": jiangsu_receipt.fetched_at,
                },
            },
        ]
    else:
        raise GateError("UNKNOWN_LOTTERY_FOR_SOURCE_INTAKE")

    for source in sources:
        source["raw_artifacts"] = [
            {k: v for k, v in item.items()
             if k in {"url", "requested_url", "raw_sha256", "size_bytes", "content_type",
                      "http_status", "fetched_at", "parser_version", "raw_base64"}}
            for item in raw_artifacts if item["_source_id"] == source["source_id"]
        ]
    if any(not source["raw_artifacts"] for source in sources):
        raise GateError("SOURCE_RAW_ARTIFACTS_MISSING")
    source_hashes_after = source_file_hashes(game)
    if source_hashes_before != source_hashes_after:
        raise GateError("PARSER_FILES_CHANGED_DURING_FETCH")
    return {
        "schema": WORKER_SCHEMA, "lottery": game,
        "parser_version": parser_version, "source_files_sha256": source_hashes_after,
        "collection_started_at_local_untrusted": started,
        "collection_finished_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
        "sources": sources, "status": "WORKER_FETCH_COMPLETE",
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
        if source.get("source_root") != root:
            raise GateError("SOURCE_ROOT_IDENTITY_MISMATCH")
        rows = _canonical_draws(game, source.get("draws"))
        artifacts = _validate_artifacts(game, source, parser_version)
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
    return validate_worker_payload(payload, expected_game=game)


def collect_both() -> dict:
    results, errors = {}, {}
    for game in ("SSQ", "DLT"):
        try:
            results[game] = collect_live_history(game)
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
            bundle = {
                "schema": "V47-OFFICIAL-INTAKE-BUNDLE-1",
                "created_at_local_untrusted": datetime.now(timezone.utc).isoformat(),
                "games": {args.game: result}, "errors": {},
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
