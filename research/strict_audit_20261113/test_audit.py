import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from research.strict_audit_20261113 import audit as a

class StatisticsTests(unittest.TestCase):
    def test_zero_success_has_positive_exact_upper(self):
        x = a.interval(0, 100)
        self.assertEqual(x["exact95"][0], 0)
        self.assertAlmostEqual(x["exact95"][1], 0.03621669264517642)
        self.assertIsNone(a.interval(0, 0)["rate"])
        with self.assertRaises(ValueError): a.interval(5, 4)

    def test_theory_and_holm_hand_values(self):
        self.assertAlmostEqual(a.theory("SSQ")["d2"], 15/528)
        self.assertAlmostEqual(a.theory("DLT")["ticket"], 1/21425712)
        self.assertEqual(a.holm({"a": .01, "b": .04, "c": .03}),
                         {"a": .03, "c": .06, "b": .06})
        self.assertEqual(a.paired([1,1,0],[0,0,0])["p"], .25)

    def test_selection_never_reads_test_or_selects_random(self):
        names = ["random_null", "alpha", "beta", "supercompute_random_null"]
        self.assertEqual(a.select_model([99,2,2,98], names), "alpha")
        self.assertEqual(a.select_model([99,1,2,98], names), "beta")

    def test_paired_bootstrap_preserves_duplicate_columns(self):
        x = np.array([[1,1,0],[0,0,1]]*12)
        means = a.bootstrap_means(x, 100, 5, 11)
        self.assertTrue(np.array_equal(means[:,0], means[:,1]))
        self.assertTrue(np.allclose(means.sum(axis=1)-means[:,0], 1))
        self.assertTrue(np.array_equal(means, a.bootstrap_means(x,100,5,11)))

    def test_constant_correlation_is_null_not_nan(self):
        result = a.correlations(np.array([[0,0,1],[0,1,1],[0,0,1]]), ["a","b","c"])
        self.assertIsNone(result["phi"][0][1])
        json.dumps(result, allow_nan=False)

class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prior = a.load_prior()[0]
        cls.history = a.load_history()
    def test_real_cache_counts_and_future_free_events(self):
        a.validate_prior(self.prior, self.history)
    def test_tamper_and_reorder_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "HASH"):
            a.load_prior_bytes(b"not the preserved zip")
        bad = copy.deepcopy(self.prior)
        bad["games"]["SSQ"]["test"]["events"][0]["index"] += 1
        with self.assertRaises(ValueError): a.validate_prior(bad,self.history)
        bad = copy.deepcopy(self.prior)
        events = bad["games"]["DLT"]["test"]["events"]
        events[0],events[1] = events[1],events[0]
        with self.assertRaises(ValueError): a.validate_prior(bad,self.history)
    def test_future_dated_training_prefix_rejected(self):
        bad=copy.deepcopy(self.history)
        bad["SSQ"][0]["draw_date"]="2099-01-01"
        with self.assertRaises(ValueError): a.validate_prior(self.prior,bad)
    def test_prior_search_valid_json_tamper_rejected(self):
        raw=(a.ROOT/"research/harness_v46/evidence/recency_ablation_20261024/statistics_summary.json.gz").read_bytes()
        obj=json.loads(gzip.decompress(raw))
        obj["p_unadjusted"][next(iter(obj["p_unadjusted"]))]=0.000001
        with self.assertRaisesRegex(ValueError,"HASH"):
            a.load_historical_search(gzip.compress(json.dumps(obj).encode()))
    def test_later_replay_never_claims_current_next_issue(self):
        self.assertEqual(a.temporal_label("2026-11-15","2026-11-13T12:00:00Z"),
                         "UNOPENED_AT_EXECUTION_DATE_RECHECK_OFFICIAL_SOURCE")
        self.assertEqual(a.temporal_label("2026-11-15","2026-11-16T12:00:00Z"),
                         "HISTORICAL_REPLAY_NOT_CURRENT")
        self.assertEqual(a.temporal_label("2026-11-15","2026-11-14T16:00:00Z"),
                         "HISTORICAL_REPLAY_NOT_CURRENT")
    def test_official_text_and_record_must_agree(self):
        record=json.loads((a.HERE/"evidence/official_verification.json").read_text())
        for game,official in record["games"].items():
            snapshot=json.loads((a.HERE/"evidence"/official["snapshot"]).read_text(encoding="utf-8"))
            a.verify_official_snapshot(game,official,snapshot)
            wrong=copy.deepcopy(official);wrong["latest_issue"]="9999999"
            with self.assertRaises(ValueError): a.verify_official_snapshot(game,wrong,snapshot)
    def test_changing_test_winner_does_not_change_validation_selection(self):
        changed=copy.deepcopy(self.prior)
        for game in ("SSQ","DLT"):
            p=changed["games"][game]["test"]; n=p["n"]
            for event in p["events"]: event["d2_hit"]["hot60"]=1
            p["model_scores"]["hot60"]["d2"]=n
            wins=n-p["model_scores"]["random_null"]["d2"]
            changed["games"][game]["significance"]["hot60"]["p_joint_nominal"]=max(
                a.old._tail(n,n,a.theory(game)["d2"]),a.old._paired_p(wins,0))
        result=a.compute(changed,10)
        self.assertEqual(result["games"]["SSQ"]["selected_from_validation"],"ewma")
        self.assertEqual(result["games"]["DLT"]["selected_from_validation"],"recency_pair_h45_120")
    def test_all_next_model_rows_match_mother_and_physics_abstains(self):
        from research.mother_v1.mother import _one_regular
        contexts=a.historical_example.build()
        for game,context in contexts.items():
            rows=a.all_model_candidates(game,context)
            self.assertEqual(len(rows),16)
            active=[r for r in rows if r["status"]=="RESEARCH_CANDIDATE"]
            self.assertEqual(len(active),14)
            for r in active:
                mother=_one_regular(context,game,r["model"])
                self.assertEqual(r["front"],mother["ticket"]["front"])
                self.assertEqual(r["back"],mother["ticket"]["back"])
                self.assertEqual(r["d2"],mother["primary_d2"])
            for r in rows:
                if r["status"]=="ABSTAIN":
                    self.assertIsNone(r["front"])
                    self.assertIsNone(r["d2"])
    def test_already_drawn_target_or_tail_mismatch_rejected(self):
        context = {"target_issue":"2026131","target_draw_date":"2026-11-15",
                   "history":[{"issue":"2026130","draw_date":"2026-11-12",
                               "front":[1,2,6,16,20,28],"back":[2]}]}
        official = {"latest_issue":"2026130","front":[1,2,6,16,20,28],"back":[2],
                    "retrieved_utc":"2026-11-13T12:00:00Z"}
        a.check_target(context, official)
        bad = copy.deepcopy(context); bad["target_issue"] = "2026130"
        with self.assertRaises(ValueError): a.check_target(bad,official)
        bad = copy.deepcopy(official); bad["retrieved_utc"]="2026-11-16T12:00:00Z"
        with self.assertRaises(ValueError): a.check_target(context,bad)
        bad = copy.deepcopy(official); bad["front"]=[1,2,3,4,5,6]
        with self.assertRaises(ValueError): a.check_target(context,bad)
    def test_clean_holdout_never_relabels_exposed_data(self):
        clean = a.clean_holdout()
        self.assertEqual(clean["n"],0)
        self.assertIsNone(clean["winner"])
        self.assertEqual(clean["status"],"BLOCKED")
    def test_create_only_output_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as p:
            out=Path(p)/"result"
            a.write_results(out,{"a.json":{"value":1}})
            with self.assertRaises(FileExistsError):
                a.write_results(out,{"a.json":{"value":2}})
            self.assertEqual(json.loads((out/"a.json").read_text())["value"],1)

if __name__ == "__main__": unittest.main()
