"""Offline, pinned saved-byte reconstruction; never execute archive code.

The result is an archival SHADOW dataset. A URL, draw date, capture clock or
timestamp receipt cannot supply the missing per-row publication/availability
time. This module neither verifies a TSA nor grants formal training eligibility.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import stat
from urllib.parse import parse_qs, urlsplit
import zipfile


SCOPE = "SAVED_BYTES_RECONSTRUCTION_ONLY"
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 512
PROJECTION = ("game", "issue", "date", "front", "back")
NULL_TIMES = ("available_at", "available_at_upper_bound", "publisher_publication_at",
              "actual_draw_at", "training_cutoff_at", "available_at_evidence",
              "available_at_upper_bound_evidence")


class SnapshotRejected(ValueError):
    """A byte, identity, temporal or reconstruction contract failed."""


def require(condition, reason):
    if not condition:
        raise SnapshotRejected(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def parse(data):
    def reject_constant(_):
        raise SnapshotRejected("NONFINITE_JSON")
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=reject_constant)


def safe_path(name):
    if not isinstance(name, str) or not name or any(ord(c) < 32 for c in name):
        return False
    if any(c in name for c in '\\:*?"<>|') or name.startswith("/"):
        return False
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{stem}{i}" for stem in ("COM", "LPT") for i in range(1, 10)}
    return all(p and p not in (".", "..") and p.rstrip(" .") == p
               and p.split(".")[0].upper() not in reserved for p in name.split("/"))


def _pin(value):
    require(isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value), "INVALID_SHA256_PIN")


def _table(table):
    require(isinstance(table, list) and 0 < len(table) <= MAX_MEMBERS, "INVALID_FILE_TABLE")
    result = {}
    folded = set()
    for row in table:
        name = row["file"]
        require(safe_path(name) and name.casefold() not in folded, "UNSAFE_OR_DUPLICATE_FILE_TABLE_PATH")
        _pin(row["sha256"])
        require(type(row["size"]) is int and 0 <= row["size"] <= MAX_MEMBER_BYTES, "FILE_SIZE_BOUND")
        result[name] = row
        folded.add(name.casefold())
    return result


def _file_matches(data, row):
    require(len(data) == row["size"] and sha(data) == row["sha256"], "BOUND_FILE_BYTES_MISMATCH")


def _projection(row):
    result = {key: row[key] for key in PROJECTION}
    game = result["game"]
    require(game in ("SSQ", "DLT"), "UNKNOWN_GAME")
    fc, fn, bc, bn, width = (6, 33, 1, 16, 7) if game == "SSQ" else (5, 35, 2, 12, 5)
    require(isinstance(result["issue"], str) and re.fullmatch(f"[0-9]{{{width}}}", result["issue"]), "ISSUE_IDENTITY")
    value = result["date"]
    require(isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value), "DRAW_DATE_FORMAT")
    parsed_date = date.fromisoformat(value)
    year = result["issue"][:4] if game == "SSQ" else "20" + result["issue"][:2]
    require(year == str(parsed_date.year) and 1 <= int(result["issue"][-3:]) <= 366,
            "ISSUE_DATE_IDENTITY")
    for arr, count, maximum in ((result["front"], fc, fn), (result["back"], bc, bn)):
        require(isinstance(arr, list) and len(arr) == count
                and all(type(x) is int and 1 <= x <= maximum for x in arr)
                and len(set(arr)) == count and sorted(arr) == arr, "DRAW_NUMBERS")
    return result


def _raw_projection(game, item):
    if game == "SSQ":
        stamp = item["date"]
        require(isinstance(stamp, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:\([^\r\n]*\))?", stamp), "RAW_DATE_FORMAT")
        issue, day = item["code"], stamp[:10]
        front = item["red"].split(",")
        back = item["blue"].split(",")
    else:
        issue, day = item["lotteryDrawNum"], item["lotteryDrawTime"]
        numbers = item["lotteryDrawResult"].split()
        front, back = numbers[:5], numbers[5:]
    require(all(re.fullmatch(r"[0-9]{1,2}", n) for n in front + back), "RAW_NUMBER_FORMAT")
    return _projection(dict(game=game, issue=issue, date=day,
                            front=[int(n) for n in front], back=[int(n) for n in back]))


def _central_url(value, game):
    require(isinstance(value, str) and not any(ord(c) <= 32 for c in value), "RAW_SOURCE_URL")
    url = urlsplit(value)
    host, path = (("www.cwl.gov.cn", "/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice")
                  if game == "SSQ" else ("webapi.sporttery.cn", "/gateway/lottery/getHistoryPageListV1.qry"))
    require(url.scheme == "https" and url.netloc == host and url.path == path and not url.fragment,
            "RAW_SOURCE_URL")
    query = parse_qs(url.query, strict_parsing=True)
    if game == "DLT":
        require(query.get("gameNo") == ["85"], "RAW_SOURCE_GAME_IDENTITY")
    else:
        require(query.get("name") == ["ssq"], "RAW_SOURCE_GAME_IDENTITY")


def _verify(path, expected_archive_sha256, expected_manifest_sha256, expected_counts):
    _pin(expected_archive_sha256)
    _pin(expected_manifest_sha256)
    require(set(expected_counts) == {"SSQ", "DLT"}
            and all(type(x) is int and 0 < x <= 10000 for x in expected_counts.values()), "EXPECTED_COUNTS")
    require(path.stat().st_size <= MAX_ARCHIVE_BYTES, "ARCHIVE_SIZE_BOUND")
    archive_bytes = path.read_bytes()
    require(len(archive_bytes) <= MAX_ARCHIVE_BYTES and sha(archive_bytes) == expected_archive_sha256,
            "ARCHIVE_SHA256_MISMATCH")
    # The same hashed bytes are read, preventing a pathname swap between hash and ZIP parse.
    import io
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        infos = archive.infolist()
        require(0 < len(infos) <= MAX_MEMBERS, "ARCHIVE_MEMBER_BOUND")
        require(sum(i.file_size for i in infos) <= MAX_TOTAL_BYTES, "ARCHIVE_TOTAL_BOUND")
        names = [i.filename for i in infos]
        require(all(safe_path(n) for n in names)
                and len(set(n.casefold() for n in names)) == len(names), "UNSAFE_OR_DUPLICATE_ZIP_PATH")
        roots = {n.split("/")[0] for n in names}
        require(len(roots) == 1 and all("/" in n for n in names), "SINGLE_ARCHIVE_ROOT_REQUIRED")
        require(all(not i.is_dir() and not stat.S_ISLNK(i.external_attr >> 16)
                    and not i.flag_bits & 1 and i.file_size <= MAX_MEMBER_BYTES for i in infos), "UNSAFE_ZIP_MEMBER")
        root = next(iter(roots)) + "/"
        # Reading every bounded member verifies CRC. No member is extracted or executed.
        entries = {i.filename[len(root):]: archive.read(i) for i in infos}
    outer = _table(parse(entries["SHA_MANIFEST.json"])["files"])
    require(set(outer) == set(entries) - {"SHA_MANIFEST.json"}, "OUTER_MANIFEST_COVERAGE")
    for name, record in outer.items():
        _file_matches(entries[name], record)
    manifest_bytes = entries["snapshot/manifest.json"]
    require(sha(manifest_bytes) == expected_manifest_sha256, "MANIFEST_SHA256_MISMATCH")
    manifest = parse(manifest_bytes)
    require(canonical(manifest) == manifest_bytes, "MANIFEST_CANONICAL_BYTES")
    require(manifest["schema"] == "V41_SOURCE_ASOF_MANIFEST_1"
            and manifest["kind"] == "DATA_SNAPSHOT_COMMITMENT_V1"
            and manifest["evidence_roots"] == {"data01": "evidence/data01"}, "MANIFEST_SCHEMA")
    require(manifest["row_counts"] == expected_counts
            and all(type(n) is int for n in manifest["row_counts"].values()), "MANIFEST_ROW_COUNTS")
    require(manifest["edge"] == "NO_EDGE" and type(manifest["formal_A_samples"]) is int
            and manifest["formal_A_samples"] == 0
            and manifest["formal_training_eligibility"] == "BLOCKED"
            and manifest["history_publication_time_proven"] is False, "MANIFEST_NOT_SHADOW")
    table = _table(manifest["file_table"])
    fixed = {"history_snapshot.json", "row_mapping.json", "source_manifest.json", "code/mapper.py"}
    require(fixed <= set(table), "MISSING_FIXED_BINDINGS")
    files = {name: entries["snapshot/" + name] for name in table}
    for name, record in table.items():
        _file_matches(files[name], record)
        require(entries["timestamp_proof/committed/" + name] == files[name], "COMMITTED_COPY_MISMATCH")
    require(entries["timestamp_proof/committed/manifest.json"] == manifest_bytes, "COMMITTED_MANIFEST_MISMATCH")
    bindings = manifest["source_bindings"]
    binding_names = {"history": "history_snapshot.json", "row_mapping": "row_mapping.json",
                     "source_manifest": "source_manifest.json", "mapper": "code/mapper.py"}
    require(set(bindings) == set(binding_names), "SOURCE_BINDING_SET")
    for key, name in binding_names.items():
        require(bindings[key]["file"] == name, "SOURCE_BINDING_PATH")
        _file_matches(files[name], bindings[key])
    require(bindings["mapper"]["version"] == "1.0.0", "MAPPER_VERSION")
    history, mapping, sources = (parse(files[n]) for n in
                                 ("history_snapshot.json", "row_mapping.json", "source_manifest.json"))
    require(history["schema"] == "GLP_HISTORY_SNAPSHOT_v44_1"
            and mapping["schema"] == "SSQ_DLT_SAVED_BYTES_ROW_MAPPING_V1"
            and sources["schema"] == "GLP_OFFICIAL_SOURCE_MANIFEST_v44_1", "DATA_SCHEMA")
    require(mapping["mapper_version"] == "1.0.0" and mapping["policy"] == "CENTRAL_HTTP_JSON_ONLY_V1", "MAPPING_POLICY")
    require(history["formal_training_allowed"] is False and history["model_cutoff_at"] is None, "HISTORY_NOT_SHADOW")
    require(mapping["counts"] == expected_counts and mapping["total_rows"] == sum(expected_counts.values())
            and history["total_rows"] == sum(expected_counts.values())
            and history["available_at_null_rows"] == sum(expected_counts.values()), "DATA_ROW_COUNTS")
    for key, name in (("history", "history_snapshot.json"), ("source_manifest", "source_manifest.json")):
        _file_matches(files[name], mapping[key])
    raw_index, reconstructed = {}, defaultdict(list)
    raw_paths = set()
    original_sources = sources["original_HTTP_sources"]
    for raw in mapping["raw_sources"]:
        game, raw_id = raw["game"], raw["raw_id"]
        require(game in expected_counts and raw_id not in raw_index, "RAW_IDENTITY")
        _pin(raw_id)
        ref = raw["file_ref"]
        require(ref == {"evidence_root": "data01", "relative_path": f"sources/{raw_id}.bin"}, "RAW_BOUND_PATH")
        name = f"evidence/data01/sources/{raw_id}.bin"
        data = files[name]
        require(raw["raw_sha256"] == raw_id == sha(data) and raw["size"] == len(data)
                and raw["available_at"] is None, "RAW_BYTE_OR_TIME_BINDING")
        for url in (raw["requested_url"], raw["final_url"]):
            _central_url(url, game)
        require(any(s["sha256"] == raw_id and s["bytes"] == len(data)
                    and s["final_url"] == raw["final_url"] and s["requested_url"] == raw["requested_url"]
                    and s["available_at"] is None and s["publisher_exact_at"] is None
                    and s["http_status"] == 200 for s in original_sources), "SOURCE_METADATA_BINDING")
        obj = parse(data)
        if game == "SSQ":
            require(type(obj["state"]) is int and obj["state"] == 0 and raw["record_array"] == "result", "RAW_RESPONSE_STATUS")
            items, pointer = obj["result"], "/result/"
        else:
            require(obj["success"] is True and raw["record_array"] == "value.list", "RAW_RESPONSE_STATUS")
            items, pointer = obj["value"]["list"], "/value/list/"
        require(isinstance(items, list) and type(raw["record_count"]) is int
                and len(items) == raw["record_count"], "RAW_RECORD_COUNT")
        raw_index[raw_id] = game
        raw_paths.add(name)
        for position, item in enumerate(items):
            row = _raw_projection(game, item)
            reconstructed[(game, row["issue"])].append(dict(
                projection=row, match=dict(raw_id=raw_id, record_json_pointer=pointer + str(position), record_position=position)))
    require(set(files) == fixed | raw_paths, "EXTRANEOUS_SNAPSHOT_BINDING")
    rows, projected, row_index = [], [], {}
    require(set(history["games"]) == set(expected_counts), "HISTORY_GAME_SET")
    for game in ("SSQ", "DLT"):
        game_data = history["games"][game]
        originals = game_data["rows"]
        require(game_data["row_count"] == len(originals) == expected_counts[game], "HISTORY_GAME_COUNT")
        for original in originals:
            row = _projection(original)
            key = (game, row["issue"])
            require(row["game"] == game and key not in row_index, "HISTORY_ROW_IDENTITY")
            require(all(field in original and original[field] is None for field in NULL_TIMES)
                    and original["historical_predraw_asof_proven"] is False
                    and original["formal_training_eligible"] is False, "HISTORY_ASOF_NOT_NULL")
            require(original["draw_date_timezone"] == "Asia/Shanghai", "DRAW_TIMEZONE")
            matches = reconstructed[key]
            require(matches and all(r["projection"] == row for r in matches), "RAW_HISTORY_CONFLICT")
            expected_matches = [r["match"] for r in matches]
            row_source_ids = {s["capture_sha256"] for s in original["sources"]}
            # The history preserves additional, excluded historical source
            # metadata. Only the central raw IDs in matches are reconstructed;
            # retaining another label never establishes a second-source proof.
            require({m["raw_id"] for m in expected_matches} <= row_source_ids
                    and all(s["available_at"] is None and s["publisher_exact_at"] is None
                            and s["availability_evidence"] is None for s in original["sources"]),
                    "HISTORY_SOURCE_BINDING")
            record = dict(row, available_at=None, original_row=original, matches=expected_matches)
            rows.append(record)
            projected.append(row)
            row_index[key] = record
    require(set(row_index) == set(reconstructed), "RAW_HISTORY_COVERAGE")
    mapped_keys = set()
    for mapped in mapping["rows"]:
        row = _projection(mapped)
        key = (row["game"], row["issue"])
        require(key in row_index and key not in mapped_keys and mapped["row_id"] == ":".join(key), "MAPPING_ROW_IDENTITY")
        target = row_index[key]
        require(isinstance(mapped["matches"], list)
                and all(type(m["record_position"]) is int for m in mapped["matches"]), "MAPPING_POSITION_TYPE")
        require(row == {k: target[k] for k in PROJECTION} and mapped["available_at"] is None
                and mapped["matches"] == target["matches"], "MAPPING_RAW_POINTER_MISMATCH")
        mapped_keys.add(key)
    require(mapped_keys == set(row_index), "MAPPING_COVERAGE")
    require(sha(canonical(projected)) == mapping["canonical_draw_rows_sha256"], "PROJECTION_DIGEST")
    return dict(snapshot_sha256=expected_manifest_sha256, archive_sha256=expected_archive_sha256,
                manifest_bytes=manifest_bytes, files=files, rows=rows, counts=dict(expected_counts),
                verification_scope=SCOPE)


def verify_snapshot_archive(path, expected_archive_sha256, expected_manifest_sha256, *, expected_counts=None):
    """Verify immutable evidence bytes; all inputs remain read-only and inert.

    Pins must come from a separately reviewed handoff. Counts default to this
    501+501 delivery; callers testing another saved-byte snapshot must pin counts.
    """
    try:
        return _verify(Path(path), expected_archive_sha256, expected_manifest_sha256,
                       {"SSQ": 501, "DLT": 501} if expected_counts is None else expected_counts)
    except SnapshotRejected:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, OSError,
            zipfile.BadZipFile, RuntimeError, RecursionError) as exc:
        raise SnapshotRejected(f"MALFORMED_OR_UNREADABLE_SNAPSHOT: {type(exc).__name__}") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    require(args.archive.is_absolute() and args.db.is_absolute() and args.output.is_absolute(), "ABSOLUTE_PATHS_REQUIRED")
    require(len({p.resolve() for p in (args.archive, args.db, args.output)}) == 3, "DISTINCT_PATHS_REQUIRED")
    require(not args.output.exists(), "RECEIPT_ALREADY_EXISTS")
    verified = verify_snapshot_archive(args.archive, args.archive_sha256, args.manifest_sha256)
    # No database is opened until every evidence contract has passed.
    from .shadow_store import ShadowStore
    store = ShadowStore(args.db)
    appended = store.append_snapshot(verified)
    report = dict(store.summary(verified["snapshot_sha256"]), appended=appended,
                  verification_scope=SCOPE, tsa_verification="NOT_RUN_BY_IMPORTER",
                  publication_time_admission="BLOCKED", candidates_created=0,
                  R2="BLOCKED", formal_A=0, decision="NO_EDGE",
                  repository_independence="FAIL", final_gate="FAIL")
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
