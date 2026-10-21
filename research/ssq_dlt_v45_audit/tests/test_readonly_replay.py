"""Independent scoring against newly generated synthetic research ledgers only."""
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from research.ssq_dlt_v45.competition import make_plan, evaluate_registered
from research.ssq_dlt_v45.models import generate
from research.ssq_dlt_v45.replay import register_plan, record_prediction, record_draw
from research.ssq_dlt_v45.store import Store, canonical, digest
from research.ssq_dlt_v45_audit.readonly_replay import replay

START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def make_fixture(path, game="SSQ", periods=3):
    store = Store(path)
    issues = [str(2026101+i if game == "SSQ" else 26101+i) for i in range(periods)]
    p = make_plan(game, issues, START.isoformat(), "INVENTED_FIXTURE_NOT_REAL_PROSPECTIVE")
    trial = register_plan(store, p, now=START)
    rows, freezes = [], {}
    for i, issue in enumerate(issues):
        freeze = START + timedelta(days=i+1)
        prediction = generate(game, issue, [])
        record_prediction(store, trial, prediction, freeze, freeze)
        drawn = freeze + timedelta(hours=13)
        front = [1,2,3,4,5,6] if game == "SSQ" else [1,2,3,4,5]
        back = [1] if game == "SSQ" else [1,2]
        record_draw(store, trial, issue, front, back, drawn, drawn+timedelta(minutes=1))
        rows.append(dict(game=game, issue=issue, prediction=prediction, frozen_at=freeze.isoformat(),
                         draw_at=drawn.isoformat(), draw_front=front, draw_back=back))
        freezes[issue] = digest(prediction)
    with store.connect() as db:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return trial, p, rows, freezes


class ReadonlyReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v45-readonly-replay-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "synthetic.sqlite"
        self.trial, self.plan, self.rows, self.freezes = make_fixture(self.path)

    def mutant(self, kind, change, issue=None, rehash=True):
        # This explicitly weakens only a disposable copied fixture to test the reader.
        path = self.root / "malformed-copy.sqlite"
        shutil.copyfile(self.path, path)
        db = sqlite3.connect(path)
        try:
            db.execute("DROP TRIGGER immutable_UPDATE")
            key = self.trial if kind == "r45_trial" else self.trial+":"+(issue or self.plan["expected_issues"][0])
            raw = db.execute("SELECT payload FROM events WHERE kind=? AND key=?", (kind,key)).fetchone()[0]
            value = json.loads(raw);change(value)
            db.execute("UPDATE events SET payload=?,sha256=? WHERE kind=? AND key=?", (canonical(value),digest(value) if rehash else "0"*64,kind,key))
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()
        return path

    def blocked(self, path, reason):
        before = path.read_bytes()
        value = replay(path)
        self.assertEqual(value["status"], "BLOCKED_INCOMPLETE_OR_INVALID_TRIALS")
        trial=value["trials"][0]
        reasons=[trial.get("reason", ""),*(item["reason"] for item in trial.get("failures",[]))]
        self.assertTrue(any(reason in r for r in reasons),reasons)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(value["formal_A"], 0)

    def test_independent_ssq_scores_equal_frozen_producer_and_leave_all_input_bytes(self):
        before = {p.name:p.read_bytes() for p in self.root.iterdir()}
        actual = replay(self.path)
        expected = evaluate_registered("SSQ", self.rows, self.plan, self.freezes, plan_sha256=self.trial)
        trial = actual["trials"][0]
        self.assertEqual(actual["status"], "PASS_READONLY_RESEARCH_REPLAY")
        self.assertEqual(trial["D1_D5_full"], expected["D1_D5_full"])
        for a, b in zip(trial["pairwise_vs_null"], expected["pairwise_vs_null"]):
            for name in ("wins","losses","ties","paired_delta","p_one_sided","p_holm_research"):
                self.assertEqual(a[name],b[name])
        self.assertEqual({p.name:p.read_bytes() for p in self.root.iterdir()},before)
        self.assertEqual((actual["formal_A"],actual["decision"]),(0,"NO_EDGE"))

    def test_independent_dlt_d1_d5_period_scores(self):
        path = self.root/"dlt.sqlite"
        trial, p, rows, hashes = make_fixture(path,"DLT")
        actual = replay(path)["trials"][0]
        expected = evaluate_registered("DLT",rows,p,hashes,plan_sha256=trial)
        self.assertEqual(actual["D1_D5_full"],expected["D1_D5_full"])
        for a,b in zip(actual["scored_periods"],expected["period_scores"]):
            for model in a["models"]:
                for k in range(1,6):
                    for field in ("hits","full","p0"):
                        self.assertEqual(a["models"][model]["D"+str(k)][field],b["models"][model]["D"+str(k)][field])

    def test_cli_new_process_has_no_original_model_store_or_statistics_import(self):
        root = Path(__file__).resolve().parents[3]
        code = "import sys; from research.ssq_dlt_v45_audit.readonly_replay import replay; r=replay(sys.argv[1]); assert not any(n.startswith('research.ssq_dlt_v45.') for n in sys.modules); print(r['status'])"
        result = subprocess.run([sys.executable,"-B","-c",code,str(self.path)],cwd=root,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),"PASS_READONLY_RESEARCH_REPLAY")

    def test_active_or_even_empty_sidecar_is_rejected_without_recovery_writes(self):
        for suffix in ("-wal","-shm","-journal"):
            path=Path(str(self.path)+suffix);path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError,"CLOSED_CHECKPOINTED_LEDGER_REQUIRED"):
                replay(self.path)
            self.assertEqual(path.read_bytes(),b"");path.unlink()

    def test_missing_file_is_not_created(self):
        path=self.root/"missing.sqlite"
        with self.assertRaisesRegex(ValueError,"EXISTING_REGULAR_LEDGER_REQUIRED"):
            replay(path)
        self.assertFalse(path.exists())

    def test_missing_period_is_retained_and_not_scored_as_complete(self):
        path=self.root/"incomplete.sqlite"
        trial,_,_,_=make_fixture(path,periods=1)
        db=sqlite3.connect(path)
        db.execute("DROP TRIGGER immutable_DELETE")
        db.execute("DELETE FROM events WHERE kind='r45_prediction'")
        db.commit();db.close()
        actual=replay(path)
        self.assertEqual(actual["status"],"BLOCKED_INCOMPLETE_OR_INVALID_TRIALS")
        self.assertEqual(actual["trials"][0]["missing_predictions"],["2026101"])
        self.assertEqual(actual["trials"][0]["scored_periods"],[])

    def test_changed_event_sha_fails_closed(self):
        path=self.mutant("r45_draw",lambda v:v.update(front=[7,8,9,10,11,12]),rehash=False)
        with self.assertRaisesRegex(ValueError,"EVENT_CANONICAL_SHA_MISMATCH"):
            replay(path)

    def test_rehashed_post_draw_freeze_is_rejected(self):
        when=self.rows[0]["draw_at"]
        path=self.mutant("r45_prediction",lambda v:v.update(frozen_at=when,accepted_at=when))
        self.blocked(path,"TRIAL_FREEZE_DRAW_ACCEPTANCE_CHRONOLOGY")

    def test_rehashed_draw_acceptance_before_draw_is_rejected(self):
        path=self.mutant("r45_draw",lambda v:v.update(accepted_at=START.isoformat()))
        self.blocked(path,"TRIAL_FREEZE_DRAW_ACCEPTANCE_CHRONOLOGY")

    def test_rehashed_game_crossing_is_rejected(self):
        path=self.mutant("r45_draw",lambda v:v.update(game="DLT"))
        self.blocked(path,"DRAW_GAME_MISMATCH")

    def test_formal_boolean_alias_is_rejected(self):
        path=self.mutant("r45_prediction",lambda v:v.update(formal_A=False))
        self.blocked(path,"RESEARCH_BOUNDARY_CHANGED")

    def test_changed_d2_even_with_updated_prediction_sha_is_rejected(self):
        def change(v):
            v["prediction"]["models"]["R45-HOT60"]["primary_d2"]=[32,33]
            v["prediction_sha256"]=digest(v["prediction"])
        self.blocked(self.mutant("r45_prediction",change),"PRIMARY_D2_MUST_BE_OWN_D2")

    def test_rehashed_null_numbers_cannot_be_changed_to_lose(self):
        def change(v):
            dan=v["prediction"]["models"]["R45-RANDOM-NULL"]["dan"]
            dan["1"]=[1 if dan["1"]!=[1] else 2]
            v["prediction_sha256"]=digest(v["prediction"])
        self.blocked(self.mutant("r45_prediction",change),"FIXED_NULL_DOMAIN_OR_NUMBERS_CHANGED")

    def test_rehashed_model_removed_cannot_reduce_comparison_family(self):
        def change(v):
            del v["prediction"]["models"]["R45-EWMA"]
            v["prediction_sha256"]=digest(v["prediction"])
        self.blocked(self.mutant("r45_prediction",change),"EXACT_FIVE_RESEARCH_MODELS_REQUIRED")

    def test_ledger_replay_result_claim_is_not_used_as_a_score_or_promotion(self):
        store=Store(self.path)
        store.append("r45_replay_result",self.trial,dict(formal_A=999,decision="EDGE",D2_full=99999))
        actual=replay(self.path)
        self.assertEqual(actual["status"],"PASS_READONLY_RESEARCH_REPLAY")
        self.assertEqual(actual["formal_A"],0)
        self.assertEqual(actual["trials"][0]["n"],3)
        self.assertEqual(actual["affected_source_cohort_promotion"],"BLOCKED")

    def test_partial_plan_retains_each_available_period_and_withholds_interim_tests(self):
        path=self.root/"partial.sqlite";shutil.copyfile(self.path,path)
        db=sqlite3.connect(path);db.execute("DROP TRIGGER immutable_DELETE")
        db.execute("DELETE FROM events WHERE kind IN ('r45_prediction','r45_draw','r45_observed_draw') AND key LIKE '%2026103'")
        db.commit();db.close()
        actual=replay(path)["trials"][0]
        self.assertEqual(actual["status"],"BLOCKED_INCOMPLETE_PLAN_SCORES_RETAINED")
        self.assertEqual([p["issue"] for p in actual["scored_periods"]],["2026101","2026102"])
        self.assertEqual((actual["n"],actual["expected_n"],len(actual["period_records"])),(2,3,3))
        self.assertEqual(actual["pairwise_vs_null"],[])
        self.assertEqual(actual["interim_inferential_tests"],"NOT_RUN")
        self.assertEqual(actual["period_records"][2]["status"],"BLOCKED_MISSING_ISSUE_EVIDENCE")

    def test_invalid_period_is_retained_beside_valid_periods_and_blocks_complete_statistics(self):
        path=self.mutant("r45_draw",lambda v:v.update(game="DLT"),issue="2026102")
        actual=replay(path)["trials"][0]
        self.assertEqual([p["issue"] for p in actual["scored_periods"]],["2026101","2026103"])
        self.assertEqual([e["issue"] for e in actual["failures"]],["2026102"])
        self.assertEqual(actual["pairwise_vs_null"],[])
        self.assertFalse(actual["complete_plan"])

    def test_cli_partial_csv_retains_scores_and_missing_row_without_modifying_ledger(self):
        path=self.root/"partial-cli.sqlite";shutil.copyfile(self.path,path)
        db=sqlite3.connect(path);db.execute("DROP TRIGGER immutable_DELETE")
        db.execute("DELETE FROM events WHERE kind='r45_prediction' AND key LIKE '%2026103'")
        db.commit();db.close();before=path.read_bytes()
        out=self.root/"report"
        result=subprocess.run([sys.executable,"-B","-m","research.ssq_dlt_v45_audit.readonly_replay","--input-ledger",str(path),"--output",str(out)],cwd=Path(__file__).resolve().parents[3],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,2,result.stderr)
        with (out/"periods.csv").open(encoding="utf-8-sig",newline="") as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),2*5*5+1)
        self.assertEqual(rows[-1]["issue"],"2026103")
        self.assertEqual(rows[-1]["status"],"BLOCKED_MISSING_ISSUE_EVIDENCE")
        self.assertEqual(path.read_bytes(),before)
        for name,expected in json.loads((out/"SHA256.json").read_bytes())["files"].items():
            self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),expected)


if __name__ == "__main__":
    unittest.main()
