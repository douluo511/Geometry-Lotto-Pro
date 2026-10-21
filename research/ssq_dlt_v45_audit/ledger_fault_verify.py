"""Read-only receipt and native SQLite recovery checks; no Store/worker import."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile

KIND = "FAULT_FIXTURE_ONLY"


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def expected(key, variant="same"):
    return dict(scope=KIND, key=key, variant=variant,
                padding="X" * (262144 if key == "before_commit" else 128),
                formal_A=0, decision="NO_EDGE")


def read_rows(path, immutable=False):
    uri = path.as_uri() + "?mode=ro" + ("&immutable=1" if immutable else "")
    db = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        db.execute("PRAGMA query_only=ON")
        require(db.execute("PRAGMA application_id").fetchone()[0] == 0x47565035, "FIXTURE_APP_ID")
        require(db.execute("PRAGMA user_version").fetchone()[0] == 1, "FIXTURE_SCHEMA")
        require(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "FIXTURE_INTEGRITY")
        result = {}
        for kind, key, raw, digest in db.execute("SELECT kind,key,payload,sha256 FROM events"):
            value = json.loads(raw)
            require(kind == KIND and key not in result, "FIXTURE_IDENTITIES")
            require(canonical(value) == raw and sha(raw.encode("utf-8")) == digest, "FIXTURE_PAYLOAD_HASH")
            result[key] = value
        return result
    finally:
        db.close()


def tree_manifest(output):
    result = {}
    for p in sorted(output.rglob("*")):
        if not p.is_file():
            continue
        require(not p.is_symlink(), "NO_RECEIPT_FILE_SYMLINKS")
        result[p.relative_to(output).as_posix()] = sha(p.read_bytes())
    return result


def checked_wal(raw):
    """Separate streaming implementation of SQLite's documented WAL format."""
    require(len(raw) >= 32, "WAL_HEADER_REQUIRED")
    u32 = lambda start: int.from_bytes(raw[start:start + 4], "big")
    magic, version, page_size = (u32(i) for i in (0, 4, 8))
    require(magic in (0x377f0682, 0x377f0683) and version == 3007000, "WAL_HEADER_FORMAT")
    require(512 <= page_size <= 65536 and page_size & (page_size - 1) == 0, "WAL_PAGE_SIZE")
    byte_order = "little" if magic == 0x377f0682 else "big"

    def stream_checksum(data, first, second):
        require(len(data) % 8 == 0, "WAL_CHECKSUM_ALIGNMENT")
        for offset in range(0, len(data), 8):
            first = (first + int.from_bytes(data[offset:offset + 4], byte_order) + second) % 2**32
            second = (second + int.from_bytes(data[offset + 4:offset + 8], byte_order) + first) % 2**32
        return first, second

    state = stream_checksum(raw[:24], 0, 0)
    require(state == (u32(24), u32(28)), "WAL_HEADER_CHECKSUM")
    size = 24 + page_size
    count = commit_count = last_commit = 0
    offset = 32
    while offset + size <= len(raw):
        salt_matches = raw[offset + 8:offset + 16] == raw[16:24]
        next_state = stream_checksum(raw[offset:offset + 8] + raw[offset + 24:offset + size], *state)
        if not u32(offset) or not salt_matches or next_state != (u32(offset + 16), u32(offset + 20)):
            break
        count += 1
        state = next_state
        if u32(offset + 4):
            commit_count += 1
            last_commit = count
        offset += size
    return dict(bytes=len(raw), sha256=sha(raw), page_size=page_size, valid_frames=count,
                commit_frames=commit_count, valid_frames_after_last_commit=count - last_commit)


def verify(output):
    output = output.resolve()
    before = tree_manifest(output)
    report = json.loads((output / "faults.json").read_bytes())
    control = json.loads((output / "control.json").read_bytes())
    require(report["schema"] == "V45_REAL_PROCESS_LEDGER_FAULTS_2", "V2_RECEIPT_REQUIRED_USE_VERSION_MATCHED_VERIFIER")
    require(control.get("schema") == "V45_OWNED_FIXTURE_CONTROL_2"
            and type(control.get("owner_pid")) is int and control["owner_pid"] > 0
            and type(control.get("token")) is str and re.fullmatch(r"[a-f0-9]{32}", control["token"])
            and type(control.get("output")) is str and control["output"], "FIXTURE_CONTROL_CONTRACT")
    require(report["status"] == "PASS_REAL_PROCESS_SCENARIOS_ONLY" and report["failure"] is None, "RECEIPT_NOT_PASS")
    require(type(report["scenarios_passed"]) is type(report["planned_scenarios"]) is int
            and report["scenarios_passed"] == report["planned_scenarios"] == 4, "INCOMPLETE_SCENARIOS")
    require(report["source_unchanged"] is True and report["owned_children_exited"] is True, "INCOMPLETE_EXECUTION")
    require(canonical(report["original_frozen_science"]) == canonical(dict(status="PASS", files=49, mismatches=[])), "SCIENCE_CHANGED")
    boundaries = dict(production_ledgers_opened=0, old_real_holdouts_read=False,
                      new_model_search="NOT_RUN", physical_power="NOT_RUN",
                      physical_network="NOT_RUN", real_boot="NOT_RUN", elapsed_PT30M="NOT_RUN",
                      full_nine_P0="BLOCKED", R2="BLOCKED", formal_A=0,
                      qualified_prospective_samples=0, decision="NO_EDGE", final_gate="FAIL")
    require(all(type(report.get(k)) is type(v) and report[k] == v for k, v in boundaries.items()),
            "BOUNDARY_CHANGED")
    manifest = json.loads((output / "source_manifest.json").read_bytes())
    require(sha(canonical(manifest).encode("utf-8")) == report["source_manifest_sha256"], "SOURCE_MANIFEST_HASH")
    require(manifest["research/ssq_dlt_v45/store.py"] == "d767a610305dbcebb09619c7e238086d7ee7ff7da4db5e3446bac97dee841b0a", "STORE_NOT_ORIGINAL")
    for name in ("ledger_faults.py", "ledger_fault_verify.py"):
        require(manifest.get("research/ssq_dlt_v45_audit/" + name) == sha((Path(__file__).parent / name).read_bytes()),
                "CURRENT_PRODUCER_AND_VERIFIER_SOURCE_BINDING_REQUIRED")
    frozen = json.loads((Path(__file__).parent / "FROZEN_SCIENCE_SHA256.json").read_bytes())
    require(len(frozen["files"]) == 49 and all(manifest.get(n) == h for n, h in frozen["files"].items()), "FROZEN_SOURCE_MANIFEST_MISMATCH")
    names = ("before_commit", "after_commit", "concurrent_same", "concurrent_conflict")
    require([c["name"] for c in report["cases"]] == list(names), "CASE_IDENTITIES")
    require(all(c["status"] == "PASS" and c["baseline_preserved"] is True for c in report["cases"]), "CASE_NOT_PASS")
    recovered = {}
    for case in report["cases"][:2]:
        name = case["name"]
        point = case["fault_point"]
        require(canonical(point) == canonical(json.loads((output / (name + ".ready.json")).read_bytes())), "RAW_FAULT_POINT_MISMATCH")
        require(case["status"] == "PASS" and case["killed_owned_process"] is True
                and type(case["child_exit_code"]) is int and case["child_exit_code"] != 0, "KILL_NOT_ESTABLISHED")
        require(type(case["child_pid"]) is int and point["pid"] == case["child_pid"] and point["token"] == control["token"]
                and point["journal_mode"] == "wal" and type(point["synchronous"]) is int and point["synchronous"] == 2, "FAULT_POINT_IDENTITY")
        require(type(point["pid"]) is int and point["pid"] > 0 and point["pid"] != control["owner_pid"]
                and type(point.get("parent_pid")) is int and point["parent_pid"] == control["owner_pid"], "FAULT_PARENT_CHILD_BINDING")
        if name == "before_commit":
            require(point["phase"] == "BEFORE_REAL_COMMIT" and point["in_transaction"] is True
                    and case["recovered_present"] is False, "BEFORE_COMMIT_CONTRACT")
        else:
            require(point["phase"] == "APPEND_RETURNED" and point["append_result"] is True
                    and case["recovered_present"] is True, "AFTER_COMMIT_CONTRACT")
        raw_db = (output / (name + ".captured.db")).read_bytes()
        raw_wal = (output / (name + ".captured.wal")).read_bytes()
        require(sha(raw_db) == case["captured_db_sha256"] and sha(raw_wal) == case["captured_wal"]["sha256"], "CAPTURE_HASH")
        wal = checked_wal(raw_wal)
        require(all(type(case["captured_wal"].get(k)) is type(value) and case["captured_wal"][k] == value
                    for k, value in wal.items()), "WAL_FRAME_SUMMARY_MISMATCH")
        if name == "before_commit":
            require(wal["valid_frames_after_last_commit"] > 0, "UNCOMMITTED_WAL_REQUIRED")
        else:
            require(wal["commit_frames"] > 0 and wal["valid_frames_after_last_commit"] == 0, "COMMITTED_WAL_REQUIRED")
        # Native SQLite interprets its own WAL checksums in a disposable copy.
        # This is independent of the producer's Python WAL parser and Store.
        with tempfile.TemporaryDirectory(prefix="v45-forensic-") as temp:
            dbpath = Path(temp) / "fixture.sqlite"
            dbpath.write_bytes(raw_db)
            Path(str(dbpath) + "-wal").write_bytes(raw_wal)
            rows = read_rows(dbpath)
        wanted = {"baseline": expected("baseline")}
        if name == "after_commit":
            wanted[name] = expected(name)
        require(canonical(rows) == canonical(wanted), "NATIVE_CAPTURE_RECOVERY_MISMATCH")
        recovered[name] = dict(rows=len(rows), canonical_rows_sha256=sha(canonical(rows).encode("utf-8")))
    for case in report["cases"][2:]:
        name = case["name"]
        results = case["processes"]
        require(len(results) == len(case["ready_points"]) == 2, "TWO_PROCESSES_REQUIRED")
        require(len({r["pid"] for r in results}) == 2 and all(r["token"] == control["token"] for r in results), "PROCESS_IDENTITIES")
        raw_results = [json.loads((output / (name + suffix + ".result.json")).read_bytes()) for suffix in ("_a", "_b")]
        require(canonical(results) == canonical(raw_results), "WORKER_RESULT_MISMATCH")
        start_path = output / (name + ".start.json")
        require(start_path.is_file(), "CONCURRENT_BARRIER_REQUIRED")
        start = json.loads(start_path.read_bytes())
        require(canonical(start) == canonical(dict(token=control["token"], owned_worker_pids=[r["pid"] for r in results])), "CONCURRENT_BARRIER_IDENTITY")
        for suffix, point, result in zip(("_a", "_b"), case["ready_points"], results):
            require(canonical(point) == canonical(json.loads((output / (name + suffix + ".ready.json")).read_bytes()))
                    and type(point["pid"]) is int and point["pid"] == result["pid"]
                    and point["token"] == control["token"]
                    and point["phase"] == "BEFORE_APPEND" and point["journal_mode"] == "wal"
                    and type(point["synchronous"]) is int and point["synchronous"] == 2, "RAW_CONCURRENCY_POINT_MISMATCH")
            require(type(result["pid"]) is int and result["pid"] > 0 and result["pid"] != control["owner_pid"]
                    and type(result.get("parent_pid")) is type(point.get("parent_pid")) is int
                    and result["parent_pid"] == point["parent_pid"] == control["owner_pid"], "CONCURRENT_PARENT_CHILD_BINDING")
        if name == "concurrent_same":
            require(all(r["kind"] == "APPEND" for r in results)
                    and all(type(r["inserted"]) is bool for r in results)
                    and sorted(r["inserted"] for r in results) == [False, True], "IDEMPOTENCY_NOT_ESTABLISHED")
        else:
            require(sorted(r["kind"] for r in results) == ["APPEND", "IMMUTABLE_CONFLICT"], "CONFLICT_NOT_ESTABLISHED")
            require(next(r for r in results if r["kind"] == "APPEND")["inserted"] is True, "WINNER_NOT_INSERTED")
    live_wal = Path(str(output / "fixture.sqlite") + "-wal")
    require(not live_wal.exists() or live_wal.stat().st_size == 0, "FINAL_FIXTURE_STILL_HAS_WAL")
    final = read_rows(output / "fixture.sqlite", immutable=True)
    winner = next(i for i, r in enumerate(report["cases"][3]["processes"]) if r["kind"] == "APPEND")
    wanted = {"baseline": expected("baseline"), "after_commit": expected("after_commit"),
              "concurrent_same": expected("concurrent_same"), "concurrent_conflict": expected("concurrent_conflict", "ab"[winner])}
    require(canonical(final) == canonical(wanted), "FINAL_IMMUTABLE_CONTENT_MISMATCH")
    for case in report["cases"][2:]:
        require(case["final_payload_sha256"] == sha(canonical(final[case["name"]]).encode("utf-8")), "FINAL_PAYLOAD_DIGEST_MISMATCH")
    require(tree_manifest(output) == before, "EVIDENCE_CHANGED_BY_VERIFIER")
    return dict(status="PASS_READ_ONLY_NATIVE_SQLITE_RECOVERY_ONLY", recovered_captures=recovered,
                final_rows=len(final), source_receipt_sha256=before["faults.json"], evidence_files=len(before),
                original_evidence_unchanged=True, producer_wal_parser_or_store_executed=False,
                receipt_contract="V45_REAL_PROCESS_LEDGER_FAULTS_2", producer_frame_counts_recomputed=True,
                current_producer_and_verifier_source_bound=True,
                live_process_faults_reexecuted=False, independent_hardware_witness=False,
                full_nine_P0="BLOCKED", formal_A=0, decision="NO_EDGE")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.input), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
