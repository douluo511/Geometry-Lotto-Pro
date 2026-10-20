"""Read-only receipt and native SQLite recovery checks; no Store/worker import."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
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


def verify(output):
    output = output.resolve()
    before = tree_manifest(output)
    report = json.loads((output / "faults.json").read_bytes())
    control = json.loads((output / "control.json").read_bytes())
    require(report["schema"] == "V45_REAL_PROCESS_LEDGER_FAULTS_1", "RECEIPT_SCHEMA")
    require(report["status"] == "PASS_REAL_PROCESS_SCENARIOS_ONLY" and report["failure"] is None, "RECEIPT_NOT_PASS")
    require(report["scenarios_passed"] == report["planned_scenarios"] == 4, "INCOMPLETE_SCENARIOS")
    require(report["source_unchanged"] and report["owned_children_exited"], "INCOMPLETE_EXECUTION")
    require(report["original_frozen_science"] == dict(status="PASS", files=49, mismatches=[]), "SCIENCE_CHANGED")
    require(report["formal_A"] == 0 and report["qualified_prospective_samples"] == 0
            and report["decision"] == "NO_EDGE" and report["R2"] == "BLOCKED"
            and report["full_nine_P0"] == "BLOCKED" and report["physical_power"] == "NOT_RUN", "BOUNDARY_CHANGED")
    manifest = json.loads((output / "source_manifest.json").read_bytes())
    require(sha(canonical(manifest).encode("utf-8")) == report["source_manifest_sha256"], "SOURCE_MANIFEST_HASH")
    require(manifest["research/ssq_dlt_v45/store.py"] == "d767a610305dbcebb09619c7e238086d7ee7ff7da4db5e3446bac97dee841b0a", "STORE_NOT_ORIGINAL")
    frozen = json.loads((Path(__file__).parent / "FROZEN_SCIENCE_SHA256.json").read_bytes())
    require(len(frozen["files"]) == 49 and all(manifest.get(n) == h for n, h in frozen["files"].items()), "FROZEN_SOURCE_MANIFEST_MISMATCH")
    names = ("before_commit", "after_commit", "concurrent_same", "concurrent_conflict")
    require([c["name"] for c in report["cases"]] == list(names), "CASE_IDENTITIES")
    require(all(c["status"] == "PASS" and c["baseline_preserved"] is True for c in report["cases"]), "CASE_NOT_PASS")
    recovered = {}
    for case in report["cases"][:2]:
        name = case["name"]
        point = case["fault_point"]
        require(point == json.loads((output / (name + ".ready.json")).read_bytes()), "RAW_FAULT_POINT_MISMATCH")
        require(case["status"] == "PASS" and case["killed_owned_process"] is True
                and type(case["child_exit_code"]) is int and case["child_exit_code"] != 0, "KILL_NOT_ESTABLISHED")
        require(point["pid"] == case["child_pid"] and point["token"] == control["token"]
                and point["journal_mode"] == "wal" and point["synchronous"] == 2, "FAULT_POINT_IDENTITY")
        if name == "before_commit":
            require(point["phase"] == "BEFORE_REAL_COMMIT" and point["in_transaction"] is True
                    and case["recovered_present"] is False, "BEFORE_COMMIT_CONTRACT")
        else:
            require(point["phase"] == "APPEND_RETURNED" and point["append_result"] is True
                    and case["recovered_present"] is True, "AFTER_COMMIT_CONTRACT")
        raw_db = (output / (name + ".captured.db")).read_bytes()
        raw_wal = (output / (name + ".captured.wal")).read_bytes()
        require(sha(raw_db) == case["captured_db_sha256"] and sha(raw_wal) == case["captured_wal"]["sha256"], "CAPTURE_HASH")
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
        require(rows == wanted, "NATIVE_CAPTURE_RECOVERY_MISMATCH")
        recovered[name] = dict(rows=len(rows), canonical_rows_sha256=sha(canonical(rows).encode("utf-8")))
    for case in report["cases"][2:]:
        name = case["name"]
        results = case["processes"]
        require(len(results) == len(case["ready_points"]) == 2, "TWO_PROCESSES_REQUIRED")
        require(len({r["pid"] for r in results}) == 2 and all(r["token"] == control["token"] for r in results), "PROCESS_IDENTITIES")
        raw_results = [json.loads((output / (name + suffix + ".result.json")).read_bytes()) for suffix in ("_a", "_b")]
        require(results == raw_results, "WORKER_RESULT_MISMATCH")
        for suffix, point, result in zip(("_a", "_b"), case["ready_points"], results):
            require(point == json.loads((output / (name + suffix + ".ready.json")).read_bytes())
                    and point["pid"] == result["pid"] and point["token"] == control["token"]
                    and point["phase"] == "BEFORE_APPEND" and point["journal_mode"] == "wal"
                    and point["synchronous"] == 2, "RAW_CONCURRENCY_POINT_MISMATCH")
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
    require(final == wanted, "FINAL_IMMUTABLE_CONTENT_MISMATCH")
    require(tree_manifest(output) == before, "EVIDENCE_CHANGED_BY_VERIFIER")
    return dict(status="PASS_READ_ONLY_NATIVE_SQLITE_RECOVERY_ONLY", recovered_captures=recovered,
                final_rows=len(final), source_receipt_sha256=before["faults.json"], evidence_files=len(before),
                original_evidence_unchanged=True, producer_wal_parser_or_store_executed=False,
                producer_frame_counts_recomputed=False,
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
