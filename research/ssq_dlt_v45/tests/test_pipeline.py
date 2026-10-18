"""Independent integration faults for the V4.5 research pipeline.

All draw fixtures are synthetic. A killed child process exercises SQLite crash
rollback; it does not stand in for a real power outage, reboot, or network loss.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from research.ssq_dlt_v45 import runtime, sources
from research.ssq_dlt_v45.store import Store


NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _history(game, count=120):
    start = date(2026, 5, 1)
    rows = []
    for index in range(count):
        maximum, front_count, back_count = (33, 6, 1) if game == "SSQ" else (35, 5, 2)
        front = sorted({1 + ((index * 3 + n * 5) % maximum) for n in range(front_count)})
        if len(front) != front_count:
            front = list(range(1, front_count + 1))
        back = [1 + index % 16] if game == "SSQ" else sorted([1 + index % 6, 7 + index % 6])
        rows.append({"issue": f"2026{index + 1:03d}" if game == "SSQ" else f"26{index + 1:03d}",
                     "draw_date": (start + timedelta(days=index)).isoformat(),
                     "front": front, "back": back})
    return rows


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class StoreFaultIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v45-store-independent-")
        self.root = Path(self.temp.name)
        self.db = self.root / "append-only.sqlite3"
        self.payload = {"fixture": "SYNTHETIC_ONLY", "model": "research/RandomNULL", "value": [3, 8]}

    def tearDown(self):
        self.temp.cleanup()

    def _store(self):
        return Store(self.db)

    def test_identical_retry_is_noop_and_conflict_fails_after_reopen(self):
        self.assertTrue(self._store().append("prediction", "same-issue", self.payload))
        self.assertFalse(self._store().append("prediction", "same-issue", self.payload))
        with self.assertRaises(ValueError):
            self._store().append("prediction", "same-issue", {**self.payload, "value": [4, 8]})
        self.assertEqual(len(self._store().rows("prediction")), 1)
        self.assertEqual(self._store().read("prediction", "same-issue"), self.payload)

    def test_concurrent_duplicate_writers_commit_exactly_once(self):
        # Initialize before contention so this measures duplicate transactions.
        self._store()
        def write(_):
            return Store(self.db).append("prediction", "one-identity", self.payload)
        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(write, range(24)))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(len(self._store().rows("prediction")), 1)

    def test_sql_update_delete_and_replace_are_rejected(self):
        self._store().append("prediction", "protected", self.payload)
        with closing(sqlite3.connect(self.db)) as cx:
            tables = [row[0] for row in cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            populated = [name for name in tables if cx.execute("SELECT count(*) FROM " + _quote(name)).fetchone()[0]]
            self.assertTrue(populated, "No populated ledger table was found")
            table = next((name for name in populated if "key" in [row[1] for row in cx.execute("PRAGMA table_info(" + _quote(name) + ")")]), populated[0])
            column = cx.execute("PRAGMA table_info(" + _quote(table) + ")").fetchone()[1]
            mutations = ["UPDATE " + _quote(table) + " SET " + _quote(column) + "=" + _quote(column),
                         "DELETE FROM " + _quote(table),
                         "INSERT OR REPLACE INTO " + _quote(table) + " SELECT * FROM " + _quote(table)]
            for statement in mutations:
                with self.subTest(statement=statement):
                    with self.assertRaises(sqlite3.DatabaseError):
                        cx.execute(statement)
                    cx.rollback()
        self.assertEqual(self._store().read("prediction", "protected"), self.payload)

    def test_uncommitted_insert_is_rolled_back_after_real_child_exit(self):
        self._store().append("prediction", "baseline", self.payload)
        # Inspect actual schema, copy a real row, and change its identity. The
        # child exits without commit/close, forcing the next connection to recover.
        program = r'''
import json, os, sqlite3, sys
db=sys.argv[1]
cx=sqlite3.connect(db, timeout=10)
cx.execute("PRAGMA synchronous=FULL")
tables=[r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
q=lambda x: '"'+x.replace('"','""')+'"'
for table in tables:
    columns=[r[1] for r in cx.execute("PRAGMA table_info("+q(table)+")")]
    if 'key' not in columns: continue
    row=cx.execute('SELECT * FROM '+q(table)+' LIMIT 1').fetchone()
    if row is None: continue
    values=list(row);values[columns.index('key')]='uncommitted-crash-probe'
    for i,info in enumerate(cx.execute("PRAGMA table_info("+q(table)+")").fetchall()):
        if info[5] and isinstance(values[i],int):values[i]+=100000
    cx.execute('BEGIN IMMEDIATE')
    cx.execute('INSERT INTO '+q(table)+' VALUES('+','.join('?' for _ in values)+')',values)
    print(json.dumps({'inserted_uncommitted':True,'table':table}),flush=True)
    os._exit(77)
raise RuntimeError('No ledger table with key column')
'''
        child = subprocess.run([sys.executable, "-c", program, str(self.db)], capture_output=True, text=True, timeout=20)
        self.assertEqual(child.returncode, 77, child.stderr)
        self.assertTrue(json.loads(child.stdout)["inserted_uncommitted"])
        self.assertEqual(len(self._store().rows("prediction")), 1)
        self.assertEqual(self._store().read("prediction", "baseline"), self.payload)
        with closing(sqlite3.connect(self.db)) as cx:
            self.assertEqual(cx.execute("PRAGMA integrity_check").fetchone()[0], "ok")


class SourceFaultIntegrationTests(unittest.TestCase):
    def test_future_draw_date_cannot_enter_history(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                rows = _history(game)
                rows[-1] = {**rows[-1], "draw_date": "2026-10-18"}
                with self.assertRaises(ValueError):
                    sources.validate_history(game, rows, now=NOW)

    def test_duplicate_issue_cannot_enter_history(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                rows = _history(game)
                with self.assertRaises(ValueError):
                    sources.validate_history(game, rows + [rows[-1]], now=NOW)

    def test_official_sources_must_agree_on_all_common_issues(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                left = _history(game)
                right = json.loads(json.dumps(left))
                # Keep the latest draw unchanged; conflict an earlier shared draw.
                used = set(right[-2]["front"])
                replacement = next(n for n in range(1, 34 if game == "SSQ" else 36) if n not in used)
                right[-2]["front"][0] = replacement
                right[-2]["front"].sort()
                with self.assertRaises(ValueError):
                    sources.agree(game, left, right)

    def test_stale_second_source_cannot_supply_latest_quorum(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                rows = _history(game)
                with self.assertRaises(ValueError):
                    sources.agree(game, rows, rows[:-1])

    def test_matching_sources_return_shared_rows(self):
        for game in ("SSQ", "DLT"):
            with self.subTest(game=game):
                rows = _history(game)
                checked = sources.validate_history(game, list(reversed(rows)), now=NOW)
                projected = [{k: row[k] for k in ("issue", "draw_date", "front", "back")} for row in checked]
                self.assertEqual(projected, rows)
                self.assertEqual(sources.agree(game, rows, rows[-20:]), rows[-20:])


class RuntimeFaultIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v45-pipeline-independent-")
        self.root = Path(self.temp.name)
        self.config = {"state_dir": str(self.root / "state"), "history": {},
                       "live_sources": False, "preview": True, "recipient": None}
        for game in ("SSQ", "DLT"):
            draws = _history(game)
            path = self.root / (game.lower() + "-synthetic-history.json")
            path.write_bytes(_canonical({"game": game, "draws": draws,
                                         "canonical_hash": hashlib.sha256(_canonical(draws)).hexdigest()}))
            self.config["history"][game] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def tearDown(self):
        self.temp.cleanup()

    def test_pinned_source_tampering_is_rejected(self):
        path = Path(self.config["history"]["SSQ"]["path"])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["draws"][-1]["back"] = [16 if value["draws"][-1]["back"] != [16] else 15]
        path.write_bytes(_canonical(value))
        report = runtime.run(self.config, now=NOW)
        self.assertEqual(report["games"]["SSQ"]["status"], "BLOCKED")
        self.assertEqual(report["games"]["SSQ"]["reason"], "HISTORY_SHA_MISMATCH")
        self.assertNotIn("preview", report["games"]["SSQ"])

    def test_caller_authorization_and_tsa_booleans_do_not_enable_formal_mode(self):
        for flag in ("authorized", "formal", "tsa_verified"):
            with self.subTest(flag=flag):
                with self.assertRaises(ValueError):
                    runtime.run({**self.config, flag: True}, now=NOW)

    def test_no_official_target_produces_unassigned_research_only(self):
        report = runtime.run(self.config, now=NOW)
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertIn("UNASSIGNED", rendered.upper())
        self.assertIn("NO_EDGE", rendered)
        self.assertEqual(report["formal_A"], 0)
        for game in ("SSQ", "DLT"):
            self.assertEqual(report["games"][game]["status"], "RESEARCH_UNASSIGNED")
            self.assertIsNone(report["games"][game]["target"])
            self.assertIn("preview", report["games"][game])
        self.assertFalse(list((self.root / "state").rglob("*.freeze.json")))
        store = Store(self.root / "state" / "research.sqlite3")
        self.assertEqual(store.rows("freeze"), [])

    def test_same_slot_restart_does_not_overwrite_saved_preview(self):
        first = runtime.run(self.config, now=NOW)
        folder = Path(first["run_receipt"]["report_directory"])
        candidates = list(folder.iterdir())
        self.assertTrue(candidates, "Expected saved preview report artifacts for the first run")
        original = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in candidates}
        # A new run() invocation constructs the store again and must reuse this slot.
        second = runtime.run(self.config, now=NOW + timedelta(minutes=1))
        self.assertTrue(second["run_receipt"]["reused"])
        self.assertEqual(second["run_receipt"]["report_directory"], str(folder))
        for name, (payload, modified) in original.items():
            self.assertEqual(Path(name).read_bytes(), payload)
            self.assertEqual(Path(name).stat().st_mtime_ns, modified)
        self.assertIn("UNASSIGNED", json.dumps(first).upper())
        self.assertIn("UNASSIGNED", json.dumps(second).upper())

    def test_failed_slot_can_retry_after_pinned_file_is_restored(self):
        path = Path(self.config["history"]["SSQ"]["path"])
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        first = runtime.run(self.config, now=NOW)
        self.assertEqual(first["games"]["SSQ"]["status"], "BLOCKED")
        failed_report = Path(first["run_receipt"]["report_directory"]) / "report.json"
        failed_bytes = failed_report.read_bytes()
        path.write_bytes(original)
        second = runtime.run(self.config, now=NOW + timedelta(minutes=1))
        self.assertEqual(second["games"]["SSQ"]["status"], "RESEARCH_UNASSIGNED")
        self.assertEqual(second["games"]["DLT"]["status"], "RESEARCH_UNASSIGNED")
        self.assertEqual(failed_report.read_bytes(), failed_bytes)

    def test_fresh_python_process_restart_reuses_completed_cycle(self):
        config_path = self.root / "config.json"
        config_path.write_bytes(_canonical(self.config))
        program = "\n".join([
            "from pathlib import Path",
            "from datetime import datetime",
            "import json, sys",
            "from research.ssq_dlt_v45.runtime import run",
            "config=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))",
            "result=run(config,now=datetime.fromisoformat(sys.argv[2]))",
            "print(json.dumps(result['run_receipt']))",
        ])
        receipts = []
        for timestamp in (NOW, NOW + timedelta(minutes=1)):
            child = subprocess.run([sys.executable, "-c", program, str(config_path), timestamp.isoformat()],
                                   capture_output=True, text=True, timeout=30,
                                   cwd=Path(__file__).resolve().parents[3])
            self.assertEqual(child.returncode, 0, child.stderr)
            receipts.append(json.loads(child.stdout))
        self.assertFalse(receipts[0]["reused"])
        self.assertTrue(receipts[1]["reused"])
        self.assertEqual(receipts[0]["report_directory"], receipts[1]["report_directory"])


if __name__ == "__main__":
    unittest.main()
