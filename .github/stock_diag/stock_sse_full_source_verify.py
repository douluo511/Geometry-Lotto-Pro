"""Verify exact SSE native capture artifacts; never establishes historical PIT."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = "douluo511/Geometry-Lotto-Pro"
SOURCE_RUN = 37790681278
SOURCE_HEAD = "40cde7b4e4d69d0a1ae83d9760aee0c2e6ee1c7c"
PRODUCT_BASE = "895fab5d4eb4be3d0b06e2c6c82c473911f4b8d1"
WINDOWS = [("2018-01-01", "2020-12-31"), ("2021-01-01", "2023-12-31"), ("2024-01-01", "2026-10-08")]
ARTIFACTS = [{"id":11556806115,"sha256":"f373cec4cf7fdd5c5483b647b37d7afbdd6187c32a0a0041e4d2eea917a01b11","size":228512},{"id":11555379176,"sha256":"f908b51c3787387cc0536f36b418445ea9bddf54bae5a62a41130268b9e423b1","size":231189},{"id":11555559510,"sha256":"bb6d1a8ab705e81a37e80d1629b0d3e0b1fb870ada3d7f6996f7f54506059dbd","size":297425}]
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_MANIFEST = 64 * 1024 * 1024

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def authenticated(url):
    return Request(url, headers={"Authorization": "Bearer "+os.environ["DIAG_GITHUB_TOKEN"], "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})

def json_api(url):
    with build_opener(NoRedirect()).open(authenticated(url), timeout=30) as response:
        return json.load(response)

def identity(metadata, expected, window):
    required_name = "STOCK-SSE-FULL-NATIVE-"+str(window)+"-"+SOURCE_HEAD
    if metadata.get("id") != expected["id"] or metadata.get("expired") is not False or metadata.get("name") != required_name or metadata.get("workflow_run", {}).get("id") != SOURCE_RUN or metadata.get("workflow_run", {}).get("head_sha") != SOURCE_HEAD or metadata.get("digest") != "sha256:"+expected["sha256"] or metadata.get("size_in_bytes") != expected["size"]:
        raise ValueError("exact_capture_artifact_identity_rejected")
    if not isinstance(expected["size"], int) or not 0 < expected["size"] <= MAX_ARCHIVE or not re.fullmatch("[0-9a-f]{64}", expected["sha256"]):
        raise ValueError("unsafe_or_noncanonical_pinned_archive")

def download(expected, window):
    base = "https://api.github.com/repos/"+REPO+"/actions/artifacts/"+str(expected["id"])
    metadata = json_api(base)
    identity(metadata, expected, window)
    try:
        build_opener(NoRedirect()).open(authenticated(base+"/zip"), timeout=30)
        raise ValueError("artifact_redirect_missing")
    except HTTPError as redirect:
        if redirect.code not in (301, 302, 303, 307, 308):
            raise
        signed = redirect.headers["Location"]
    parsed = urlsplit(signed)
    if parsed.scheme != "https" or not ((parsed.hostname or "").endswith(".blob.core.windows.net") or (parsed.hostname or "").endswith(".githubusercontent.com")) or parsed.username or parsed.password:
        raise ValueError("artifact_storage_origin_rejected")
    # The temporary signed URL and token are never emitted or forwarded.
    with build_opener().open(Request(signed), timeout=60) as response:
        archive = response.read(expected["size"]+1)
    if len(archive) != expected["size"] or sha(archive) != expected["sha256"]:
        raise ValueError("exact_capture_archive_digest_or_size_rejected")
    return archive, {key: metadata.get(key) for key in ("id", "name", "size_in_bytes", "digest", "created_at", "updated_at")}

def members(archive):
    found = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        if sum(item.file_size for item in zipped.infolist()) > MAX_EXPANDED:
            raise ValueError("expanded_archive_bound_exceeded")
        for item in zipped.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename or item.is_dir():
                raise ValueError("archive_path_rejected")
            name = path.name
            if name != "historical-capture.json" and not re.fullmatch(r"source-[0-9]{3,4}\.raw", name):
                raise ValueError("unexpected_archive_member")
            if name in found or item.file_size > (MAX_MANIFEST if name == "historical-capture.json" else 8*1024*1024):
                raise ValueError("duplicate_or_oversized_archive_member")
            found[name] = zipped.read(item)
    if "historical-capture.json" not in found:
        raise ValueError("capture_manifest_missing")
    return found

def manifest_identity(report, window):
    if report.get("schema") != "stock-sse-historical-suspension-source-capture-v1" or report.get("status") != "PASS" or report.get("diagnostic_head_sha") != SOURCE_HEAD or report.get("source_product_base_sha") != PRODUCT_BASE or report.get("windows") != [list(WINDOWS[window])] or report.get("frozen_coverage_target") != ["2018-01-01", "2026-10-08"] or report.get("qualified_record_count") != 0 or report.get("final_gate") != "FAIL":
        raise ValueError("exact_full_capture_manifest_identity_rejected")
    if report.get("source_schema_scope") != "HISTORICAL_PINNED_QUERY_SCHEMA_ONLY" or report.get("fresh_HTML_source_gate") != "NOT VERIFIED":
        raise ValueError("historical_schema_scope_falsely_promoted")

def validate_capture(found, window, native):
    report = json.loads(found["historical-capture.json"])
    manifest_identity(report, window)
    queries = report.get("queries")
    if not isinstance(queries, list) or len(queries) != 1:
        raise ValueError("frozen_native_query_denominator_rejected")
    query = queries[0]
    if query.get("status") != "PASS" or query.get("flavor") != "new" or query.get("window") != list(WINDOWS[window]) or query.get("endpoint") != "https://query.sse.com.cn/commonSoaQuery.do" or query.get("unresolved_native_rows") != []:
        raise ValueError("native_query_scope_or_unresolved_rows_rejected")
    params = query.get("params", {})
    if params.get("sqlId") != "GW_PL_JYTS_TFPXX" or params.get("productCode") != "" or params.get("keyWords") != "" or params.get("startStopDate") != WINDOWS[window][0].replace("-", "") or params.get("endStopDate") != WINDOWS[window][1].replace("-", ""):
        raise ValueError("native_query_date_or_population_changed")
    receipts = query.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("native_page_receipts_missing")
    pages, prior, raw_names, raw_manifest = [], None, set(), []
    for number, receipt in enumerate(receipts, 1):
        name = receipt.get("raw_path")
        if name in raw_names or name not in found or receipt.get("status") != "PASS" or receipt.get("http_status") != 200 or receipt.get("sha256") != sha(found[name]) or receipt.get("bytes") != len(found[name]):
            raise ValueError("native_page_hash_or_status_rejected")
        raw_names.add(name)
        from urllib.parse import parse_qs
        url = receipt.get("actual_url")
        parsed = urlsplit(url or "")
        actual_params = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.scheme != "https" or parsed.netloc != "query.sse.com.cn" or parsed.path != "/commonSoaQuery.do" or actual_params.get("sqlId") != ["GW_PL_JYTS_TFPXX"] or actual_params.get("startStopDate") != [WINDOWS[window][0].replace("-", "")] or actual_params.get("endStopDate") != [WINDOWS[window][1].replace("-", "")] or actual_params.get("productCode") != [""] or actual_params.get("keyWords") != [""] or actual_params.get("pageHelp.pageNo") != [str(number)] or actual_params.get("pageHelp.pageSize") != ["25"]:
            raise ValueError("exact_native_request_identity_rejected")
        rows, counts = native.parse_page(found[name], number, 25, prior)
        prior = prior or counts
        pages.append(rows)
        raw_manifest.append({"page_number": number, "raw_path": name, "raw_sha256": sha(found[name]), "bytes": len(found[name]), "row_count": len(rows), "http_status": 200, "recorded_at_utc": receipt.get("recorded_at_utc")})
    if set(found) != raw_names | {"historical-capture.json"}:
        raise ValueError("missing_or_unaccounted_raw_page_file")
    rows = native.complete_pages(pages, prior)
    digests = [sha(canonical(row)) for row in rows]
    if query.get("raw_row_sha256_sequence") != digests or query.get("native_row_count") != len(rows) or query.get("native_pagination") != prior or report.get("native_query_row_count") != len(rows) or report.get("observed_pages") != len(receipts):
        raise ValueError("native_whole_row_denominator_rejected")
    candidates = [native.event_candidate(row, "new", *WINDOWS[window]) for row in rows]
    recorded = report.get("event_candidates")
    if not isinstance(recorded, list) or len(recorded) != len(candidates) or report.get("candidate_count") != len(candidates):
        raise ValueError("native_candidate_denominator_rejected")
    for actual, recorded_row in zip(candidates, recorded):
        if any(recorded_row.get(key) != value for key, value in actual.items()) or recorded_row.get("query_index") != 0:
            raise ValueError("native_row_semantics_recomputed_disagree")
    return rows, candidates, {"window": list(WINDOWS[window]), "capture_manifest_sha256": sha(found["historical-capture.json"]), "native_total": prior["total"], "native_page_count": prior["pageCount"], "verified_pages": len(receipts), "native_unique_rows_in_window": len(set(digests)), "raw_pages": raw_manifest}

def self_test():
    good = {"id": 1, "sha256": "a"*64, "size": 100}
    meta = {"id": 1, "expired": False, "name": "STOCK-SSE-FULL-NATIVE-0-"+SOURCE_HEAD, "workflow_run": {"id": SOURCE_RUN, "head_sha": SOURCE_HEAD}, "digest": "sha256:"+"a"*64, "size_in_bytes": 100}
    identity(meta, good, 0)
    def rejected(function):
        try:
            function()
        except (ValueError, KeyError, TypeError):
            return
        raise AssertionError("FALSE ARTIFACT PASS")
    for key, value in (("id", 2), ("expired", True), ("name", "wrong"), ("digest", "sha256:"+"b"*64), ("size_in_bytes", 99), ("workflow_run", {"id": SOURCE_RUN, "head_sha": "0"*40})):
        rejected(lambda key=key, value=value: identity(dict(meta, **{key: value}), good, 0))
    for bad_path in ("../historical-capture.json", "/historical-capture.json", "x\\historical-capture.json", "unexpected.txt"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zipped:
            zipped.writestr(bad_path, "{}")
        rejected(lambda: members(buf.getvalue()))
    print("SSE EXACT ARTIFACT IDENTITY / ZIP PATH CONTROLS 11/11 PASS")
    # Real parser is exercised on a complete canonical native-page fixture.
    # These bytes are explicitly adversarial test data, never source evidence.
    import copy
    from urllib.parse import urlencode
    spec = importlib.util.spec_from_file_location("native_control", Path(__file__).with_name("stock_sse_suspend_source.py"))
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    row = {"productCode": "600000", "productName": "TEST ONLY", "startStopDate": "20180102", "endStopDate": "20180103", "controlType": "TR", "stopTime": "WH", "stopReason": "TEST ONLY", "type": "LSTP"}
    counts = {"pageNo": 1, "pageSize": 25, "pageCount": 1, "total": 1}
    raw = canonical({"result": [row], "pageHelp": counts})
    params = {"sqlId": "GW_PL_JYTS_TFPXX", "startStopDate": "20180101", "endStopDate": "20201231", "pageHelp.pageNo": 1, "pageHelp.pageSize": 25, "productCode": "", "keyWords": ""}
    candidate = native.event_candidate(row, "new", *WINDOWS[0])
    candidate["query_index"] = 0
    report = {"schema": "stock-sse-historical-suspension-source-capture-v1", "status": "PASS", "diagnostic_head_sha": SOURCE_HEAD, "source_product_base_sha": PRODUCT_BASE, "windows": [list(WINDOWS[0])], "frozen_coverage_target": ["2018-01-01", "2026-10-08"], "qualified_record_count": 0, "final_gate": "FAIL", "source_schema_scope": "HISTORICAL_PINNED_QUERY_SCHEMA_ONLY", "fresh_HTML_source_gate": "NOT VERIFIED", "native_query_row_count": 1, "observed_pages": 1, "candidate_count": 1, "event_candidates": [candidate], "queries": [{"status": "PASS", "flavor": "new", "window": list(WINDOWS[0]), "endpoint": "https://query.sse.com.cn/commonSoaQuery.do", "params": params, "unresolved_native_rows": [], "native_row_count": 1, "native_pagination": counts, "raw_row_sha256_sequence": [sha(canonical(row))], "receipts": [{"raw_path": "source-101.raw", "status": "PASS", "http_status": 200, "sha256": sha(raw), "bytes": len(raw), "actual_url": "https://query.sse.com.cn/commonSoaQuery.do?"+urlencode(params)}]}]}
    def files(value):
        return {"historical-capture.json": canonical(value), "source-101.raw": raw}
    validate_capture(files(report), 0, native)
    mutations = [
        lambda value: value.update(diagnostic_head_sha="0"*40),
        lambda value: value.update(qualified_record_count=1),
        lambda value: value["queries"][0].update(window=["2018-01-01", "2021-01-01"]),
        lambda value: value["queries"][0]["params"].update(productCode="600000"),
        lambda value: value["queries"][0]["receipts"][0].update(sha256="0"*64),
        lambda value: value["queries"][0]["receipts"][0].update(actual_url="https://query.sse.com.cn/commonSoaQuery.do?"+urlencode(dict(params, **{"pageHelp.pageNo": 2}))),
        lambda value: value["queries"][0].update(native_row_count=0),
        lambda value: value["queries"][0].update(raw_row_sha256_sequence=["0"*64]),
        lambda value: value["event_candidates"][0].update(asof_information_availability="PASS"),
        lambda value: value["event_candidates"][0].update(qualified_daily_suspension="PASS"),
    ]
    for mutation in mutations:
        damaged = copy.deepcopy(report)
        mutation(damaged)
        rejected(lambda: validate_capture(files(damaged), 0, native))
    rejected(lambda: validate_capture({"historical-capture.json": canonical(report)}, 0, native))
    rejected(lambda: validate_capture(dict(files(report), **{"source-102.raw": raw}), 0, native))
    print("SSE WHOLE RAW PAGE / DATE / DENOMINATOR / ASOF FALSE-PASS CONTROLS 13/13 PASS")


def verify(output):
    output.mkdir(parents=True, exist_ok=False)
    ledger = {"schema": "stock-sse-full-native-source-coverage-ledger-v1", "status": "FAIL", "verification_head_sha": os.environ.get("SOURCE_SHA"), "source_capture_head_sha": SOURCE_HEAD, "source_capture_run_id": SOURCE_RUN, "source_product_base_sha": PRODUCT_BASE, "frozen_window": ["2018-01-01", "2026-10-08"], "window_receipts": [], "qualified_record_count": 0, "full_historical_issuer_day_ST_halt_asof_authority": "NOT VERIFIED", "historical_publication_availability": "NOT VERIFIED", "actual_effective_resume_state": "NOT VERIFIED", "repository_independence": "NOT VERIFIED", "formal_Release_redownload": "NOT VERIFIED", "final_gate": "FAIL", "delivery_allowed": False}
    try:
        run = json_api("https://api.github.com/repos/"+REPO+"/actions/runs/"+str(SOURCE_RUN))
        if run.get("id") != SOURCE_RUN or run.get("head_sha") != SOURCE_HEAD:
            raise ValueError("capture_run_head_identity_rejected")
        spec = importlib.util.spec_from_file_location("native_source", Path(__file__).with_name("stock_sse_suspend_source.py"))
        native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(native)
        all_rows, all_candidates = [], []
        for window, expected in enumerate(ARTIFACTS):
            archive, meta = download(expected, window)
            found = members(archive)
            rows, candidates, receipt = validate_capture(found, window, native)
            receipt["artifact"] = meta
            receipt["actual_downloaded_zip_sha256"] = sha(archive)
            receipt["actual_downloaded_zip_bytes"] = len(archive)
            ledger["window_receipts"].append(receipt)
            all_rows.extend(rows)
            all_candidates.extend(candidates)
        if len(ledger["window_receipts"]) != 3:
            raise ValueError("full_three_window_coverage_missing")
        hashes = [sha(canonical(row)) for row in all_rows]
        unique_rows = {sha(canonical(row)): row for row in all_rows}
        groups = defaultdict(set)
        for digest, row in unique_rows.items():
            # An event key is a diagnostic join candidate, never issuer authority.
            key = tuple(str(row.get(name)) for name in ("productCode", "startStopDate", "controlType", "type", "stopTime"))
            groups[key].add(digest)
        conflicts = [{"native_event_key_candidate": list(key), "raw_row_sha256": sorted(values)} for key, values in groups.items() if len(values) > 1]
        dates = [candidate["explicit_start_day"] for candidate in all_candidates if candidate["explicit_start_day"]]
        ledger.update({"status": "PASS", "accepted_scope": "Exact candidate diagnostic source artifact redownload / raw-page hash / complete native API pagination ONLY", "native_query_rows_sum": len(all_rows), "global_unique_raw_rows": len(unique_rows), "cross_window_repeated_raw_rows": len(hashes)-len(set(hashes)), "global_unique_native_code_candidates": len({row["productCode"] for row in all_rows}), "native_explicit_start_min": min(dates) if dates else None, "native_explicit_start_max": max(dates) if dates else None, "native_record_type_counts_in_unique_rows": dict(Counter(str(row.get("type")) for row in unique_rows.values())), "native_business_type_counts_in_unique_rows": dict(Counter(str(row.get("controlType")) for row in unique_rows.values())), "candidate_identity_counts_before_dedupe": dict(Counter(row["identity_status"] for row in all_candidates)), "candidate_duration_counts_before_dedupe": dict(Counter(row["duration_scope"] for row in all_candidates)), "future_resume_fields_after_query_asof_count": sum(row["future_end_visible_after_query_asof"] is True for row in all_candidates), "native_event_key_candidate_conflict_count": len(conflicts), "native_event_key_candidate_conflicts": conflicts, "normalization_status": "NOT VERIFIED", "raw_row_sha256_dedupe_manifest": sorted(unique_rows), "empty_result_semantics": "UNKNOWN; never NORMAL"})
    except Exception as exc:
        ledger["error_type"] = type(exc).__name__
        ledger["error"] = str(exc) if isinstance(exc, ValueError) else "exact_source_verification_failed"
    finally:
        ledger["verification_recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "sse-full-native-source-coverage-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in ledger.items() if key not in ("raw_row_sha256_dedupe_manifest", "native_event_key_candidate_conflicts")}, ensure_ascii=False, sort_keys=True))
    return 0 if ledger["status"] == "PASS" else 2

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.output:
        raise SystemExit(verify(args.output))
    else:
        parser.error("--self-test or --output required")
