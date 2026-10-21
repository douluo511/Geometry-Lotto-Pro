"""Real process faults against one new fixture ledger; never a production DB."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import struct
import subprocess
import sys
import time
import traceback
import uuid

from research.ssq_dlt_v45.store import Store, canonical, digest
from .acceptance import ROOT, frozen_science, source_manifest

STORE_SHA = "d767a610305dbcebb09619c7e238086d7ee7ff7da4db5e3446bac97dee841b0a"
KIND = "FAULT_FIXTURE_ONLY"
CASES = ("before_commit", "after_commit", "concurrent_same", "concurrent_conflict")
WORKERS = ("before_commit", "after_commit", "concurrent_same_a", "concurrent_same_b",
           "concurrent_conflict_a", "concurrent_conflict_b")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, value):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def payload(key, variant="same"):
    return dict(scope=KIND, key=key, variant=variant,
                padding="X" * (262144 if key == "before_commit" else 128),
                formal_A=0, decision="NO_EDGE")


def wait_until(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise TimeoutError("OWNED_FIXTURE_PROCESS_TIMEOUT")


def pause_for_parent():
    # A parent crash must not leave an unbounded child or SQLite write lock.
    time.sleep(60)
    os._exit(70)


class FaultStore(Store):
    """Instrument the real Store.append COMMIT without replacing its SQL."""
    def __init__(self, path, ready_path, token):
        self.armed = False
        self.ready_path = ready_path
        self.token = token
        super().__init__(path)

    @contextmanager
    def connect(self, readonly=False):
        with super().connect(readonly) as db:
            if self.armed and not readonly:
                # Test-only small cache forces actual uncommitted WAL spill.
                db.execute("PRAGMA cache_size=2")
                db.execute("PRAGMA cache_spill=ON")
                observed = dict(journal_mode=db.execute("PRAGMA journal_mode").fetchone()[0],
                                synchronous=db.execute("PRAGMA synchronous").fetchone()[0])

                def trace(sql):
                    if sql.strip().upper() == "COMMIT":
                        write_new(self.ready_path, dict(token=self.token, pid=os.getpid(), parent_pid=os.getppid(),
                            phase="BEFORE_REAL_COMMIT", in_transaction=db.in_transaction, **observed))
                        pause_for_parent()

                db.set_trace_callback(trace)
            try:
                yield db
            finally:
                db.set_trace_callback(None)


def worker(output, name, token):
    if not __debug__:
        raise RuntimeError("FAULT_ACCEPTANCE_REQUIRES_ASSERTIONS_ENABLED")
    control = json.loads((output / "control.json").read_bytes())
    if (control["schema"] != "V45_OWNED_FIXTURE_CONTROL_2" or control["token"] != token
            or control["owner_pid"] != os.getppid() or control["output"] != str(output)
            or sha((ROOT / "research/ssq_dlt_v45/store.py").read_bytes()) != STORE_SHA):
        raise ValueError("OWNED_FIXTURE_CONTROL_REQUIRED")
    ledger = output / "fixture.sqlite"
    if not ledger.is_file() or ledger.is_symlink():
        raise ValueError("EXISTING_OWNED_FIXTURE_REQUIRED")
    ready_path = output / (name + ".ready.json")
    store = FaultStore(ledger, ready_path, token)
    # Keep a real SQLite connection alive through the parent's kill, preventing
    # the final normal close from removing/checkpointing the WAL first.
    anchor = sqlite3.connect(ledger, isolation_level=None, timeout=10)
    anchor.execute("PRAGMA synchronous=FULL")
    observed = dict(journal_mode=anchor.execute("PRAGMA journal_mode").fetchone()[0],
                    synchronous=anchor.execute("PRAGMA synchronous").fetchone()[0])
    try:
        if name == "before_commit":
            store.armed = True
            store.append(KIND, name, payload(name))
            raise AssertionError("PARENT_DID_NOT_KILL_BEFORE_COMMIT")
        if name == "after_commit":
            result = store.append(KIND, name, payload(name))
            write_new(ready_path, dict(token=token, pid=os.getpid(), parent_pid=os.getppid(), phase="APPEND_RETURNED",
                                      append_result=result, **observed))
            pause_for_parent()
        key, variant = name.rsplit("_", 1)
        write_new(ready_path, dict(token=token, pid=os.getpid(), parent_pid=os.getppid(), phase="BEFORE_APPEND", **observed))
        wait_until(lambda: (output / (key + ".start.json")).exists())
        value = payload(key, variant if key == "concurrent_conflict" else "same")
        try:
            outcome = dict(kind="APPEND", inserted=store.append(KIND, key, value))
        except ValueError as exc:
            if str(exc) != "IMMUTABLE_CONFLICT":
                raise
            outcome = dict(kind="IMMUTABLE_CONFLICT")
        write_new(output / (name + ".result.json"), dict(token=token, pid=os.getpid(), parent_pid=os.getppid(), **outcome))
    finally:
        anchor.close()
    return 0


def checksum(raw, state, order):
    if len(raw) % 8:
        raise ValueError("WAL_CHECKSUM_ALIGNMENT")
    words = struct.unpack(order + str(len(raw) // 4) + "I", raw)
    a, b = state
    for i in range(0, len(words), 2):
        a = (a + words[i] + b) & 0xffffffff
        b = (b + words[i + 1] + a) & 0xffffffff
    return a, b


def wal_summary(raw):
    """Validate salts and cumulative checksums, not just apparent frame headers.

    Format: https://sqlite.org/fileformat2.html#wal_file_format
    """
    if len(raw) < 32:
        raise ValueError("LIVE_WAL_REQUIRED")
    magic, version, page_size, _, salt1, salt2, a, b = struct.unpack(">8I", raw[:32])
    if magic not in (0x377f0682, 0x377f0683) or version != 3007000:
        raise ValueError("INVALID_WAL_HEADER")
    if page_size < 512 or page_size > 65536 or page_size & (page_size - 1):
        raise ValueError("INVALID_WAL_PAGE_SIZE")
    order = "<" if magic == 0x377f0682 else ">"
    state = checksum(raw[:24], (0, 0), order)
    if state != (a, b):
        raise ValueError("INVALID_WAL_HEADER_CHECKSUM")
    valid = commits = last_commit = 0
    step = 24 + page_size
    for offset in range(32, len(raw) - step + 1, step):
        header = raw[offset:offset + 24]
        pg, db_size, s1, s2, a, b = struct.unpack(">6I", header)
        next_state = checksum(header[:8] + raw[offset + 24:offset + step], state, order)
        if not pg or (s1, s2) != (salt1, salt2) or next_state != (a, b):
            break  # A reused WAL can retain invalid old tail frames.
        state = next_state
        valid += 1
        if db_size:
            commits += 1
            last_commit = valid
    return dict(bytes=len(raw), sha256=sha(raw), page_size=page_size, valid_frames=valid,
                commit_frames=commits, valid_frames_after_last_commit=valid - last_commit,
                format_source="https://sqlite.org/fileformat2.html#wal_file_format")


def run(output):
    if not __debug__:
        raise RuntimeError("FAULT_ACCEPTANCE_REQUIRES_ASSERTIONS_ENABLED")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before, science_before = source_manifest(), frozen_science()
    token = uuid.uuid4().hex  # IPC identity only, never a prediction seed.
    write_new(output / "control.json", dict(schema="V45_OWNED_FIXTURE_CONTROL_2",
        owner_pid=os.getpid(), token=token, output=str(output)))
    write_new(output / "source_manifest.json", before)
    store = Store(output / "fixture.sqlite")
    baseline = payload("baseline")
    store.append(KIND, "baseline", baseline)
    children, handles, cases = [], [], []
    failure = None

    def spawn(name):
        command = [sys.executable, "-B", "-m", __spec__.name, "--output", str(output),
                   "--worker", name, "--token", token]
        out = (output / (name + ".stdout.log")).open("xb")
        err = (output / (name + ".stderr.log")).open("xb")
        handles.extend((out, err))
        child = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err)
        children.append(child)
        return child

    def ready(child, name):
        path = output / (name + ".ready.json")

        def check():
            if path.exists():
                try:
                    value = json.loads(path.read_bytes())
                except (json.JSONDecodeError, PermissionError):
                    return None
                assert value["pid"] == child.pid and value["token"] == token
                assert value["parent_pid"] == os.getpid()
                assert value["journal_mode"] == "wal" and value["synchronous"] == 2
                assert child.poll() is None
                return value
            if child.poll() is not None:
                raise RuntimeError("WORKER_EXITED_BEFORE_FAULT_POINT:" + name)
            return None
        return wait_until(check)

    try:
        assert before["research/ssq_dlt_v45/store.py"] == STORE_SHA
        for name in CASES[:2]:
            child = spawn(name)
            point = ready(child, name)
            if name == "before_commit":
                assert point["phase"] == "BEFORE_REAL_COMMIT" and point["in_transaction"]
            else:
                assert point["phase"] == "APPEND_RETURNED" and point["append_result"] is True
            # Capture DB+WAL while the only writer is paused, before recovery opens.
            raw_db = (output / "fixture.sqlite").read_bytes()
            raw_wal = (output / "fixture.sqlite-wal").read_bytes()
            summary = wal_summary(raw_wal)
            if name == "before_commit":
                assert summary["valid_frames_after_last_commit"] > 0
            else:
                assert summary["valid_frames"] > 0 and summary["commit_frames"] > 0
                assert summary["valid_frames_after_last_commit"] == 0
            (output / (name + ".captured.db")).write_bytes(raw_db)
            (output / (name + ".captured.wal")).write_bytes(raw_wal)
            assert child.poll() is None, "FAULT_POINT_CHILD_NOT_LIVE_BEFORE_KILL"
            child.kill()  # Only this Popen handle; no user-supplied PID or system reboot.
            code = child.wait(timeout=10)
            assert code != 0
            recovered = Store(output / "fixture.sqlite")
            observed = recovered.read(KIND, name)
            assert observed == (None if name == "before_commit" else payload(name))
            assert recovered.read(KIND, "baseline") == baseline
            if name == "after_commit":
                assert recovered.append(KIND, name, payload(name)) is False
                try:
                    recovered.append(KIND, name, payload(name, "changed"))
                except ValueError as exc:
                    assert str(exc) == "IMMUTABLE_CONFLICT"
                else:
                    raise AssertionError("COMMITTED_IDENTITY_WAS_OVERWRITTEN")
            cases.append(dict(name=name, status="PASS", fault_point=point,
                child_pid=child.pid, killed_owned_process=True, child_exit_code=code,
                captured_db_sha256=sha(raw_db), captured_wal=summary,
                recovered_present=observed is not None, baseline_preserved=True))
        for name in CASES[2:]:
            pair = [spawn(name + suffix) for suffix in ("_a", "_b")]
            points = [ready(child, name + suffix) for child, suffix in zip(pair, ("_a", "_b"))]
            write_new(output / (name + ".start.json"), dict(token=token, owned_worker_pids=[c.pid for c in pair]))
            for child in pair:
                assert child.wait(timeout=30) == 0
            results = [json.loads((output / (name + suffix + ".result.json")).read_bytes()) for suffix in ("_a", "_b")]
            assert all(r["pid"] == c.pid and r["token"] == token for r, c in zip(results, pair))
            assert all(r["parent_pid"] == os.getpid() for r in results)
            if name == "concurrent_same":
                assert sorted(r["inserted"] for r in results if r["kind"] == "APPEND") == [False, True]
                expected = payload(name)
            else:
                assert sorted(r["kind"] for r in results) == ["APPEND", "IMMUTABLE_CONFLICT"]
                winner = next(i for i, r in enumerate(results) if r["kind"] == "APPEND")
                assert results[winner]["inserted"] is True
                expected = payload(name, "ab"[winner])
            assert Store(output / "fixture.sqlite").read(KIND, name) == expected
            assert store.read(KIND, "baseline") == baseline
            cases.append(dict(name=name, status="PASS", processes=results, ready_points=points,
                              baseline_preserved=True, final_payload_sha256=digest(expected)))
        with store.connect(True) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("SELECT kind,key FROM events ORDER BY key").fetchall() == [
                (KIND, k) for k in ("after_commit", "baseline", "concurrent_conflict", "concurrent_same")]
        assert len(store.rows(KIND)) == 4
    except Exception:
        failure = traceback.format_exc()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)
        for stream in handles:
            stream.close()
    after, science_after = source_manifest(), frozen_science()
    passed = (failure is None and len(cases) == 4 and before == after
              and science_before == science_after and science_after["status"] == "PASS")
    report = dict(schema="V45_REAL_PROCESS_LEDGER_FAULTS_2",
        status="PASS_REAL_PROCESS_SCENARIOS_ONLY" if passed else "FAIL",
        cases=cases, scenarios_passed=len(cases), planned_scenarios=4, failure=failure,
        source_unchanged=before == after, original_frozen_science=science_after,
        source_manifest_sha256=sha(canonical(before).encode("utf-8")),
        python=sys.version, sqlite_version=sqlite3.sqlite_version, platform=platform.platform(),
        owned_children_exited=all(c.poll() is not None for c in children),
        scope="OWN_NEW_FIXTURE_REAL_PROCESS_KILL_AND_MULTIPROCESS_WRITES_NOT_PHYSICAL_POWER",
        production_ledgers_opened=0, old_real_holdouts_read=False, new_model_search="NOT_RUN",
        physical_power="NOT_RUN", physical_network="NOT_RUN", real_boot="NOT_RUN",
        elapsed_PT30M="NOT_RUN", full_nine_P0="BLOCKED", R2="BLOCKED", formal_A=0,
        qualified_prospective_samples=0, decision="NO_EDGE", final_gate="FAIL")
    write_new(output / "faults.json", report)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=WORKERS, help=argparse.SUPPRESS)
    parser.add_argument("--token", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args.output.resolve(), args.worker, args.token)
    if args.token:
        parser.error("--token is internal to owned fixture workers")
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
