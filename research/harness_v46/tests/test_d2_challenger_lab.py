"""Research-only D2 challenger: adversarial retrospective walk-forward tests.

Every test uses invented draws; nothing is a real future forecast or evidence
of improving lottery odds. Original official slots and six-model core remain untouched.
"""
import copy
import unittest

from research.harness_v46 import core
from research.harness_v46.tests.test_core import fixture
from research.harness_v46 import d2_challenger_lab as lab


class D2ChallengerLabTests(unittest.TestCase):
    def setUp(self):
        self.bundle = {g: fixture(g, size=145) for g in ("SSQ", "DLT")}

    def test_fixed_candidate_is_deterministic_legal_and_differs_from_core_identity(self):
        for game in ("SSQ", "DLT"):
            history = self.bundle[game]["draws"][:120]
            pair = lab.pick_recency_pair(history, game)
            self.assertEqual(pair, lab.pick_recency_pair(copy.deepcopy(history), game))
            self.assertEqual(len(pair), 2)
            self.assertEqual(len(set(pair)), 2)
            self.assertTrue(all(type(n) is int and 1 <= n <= core.RULES[game]["pool"] for n in pair))
            self.assertEqual(lab.CHALLENGER_ID, "RECENCY_PAIR_H45_120_V1")
            self.assertEqual(lab.WINDOW, 120)
            self.assertEqual(lab.HALF_LIFE, 45)
            self.assertEqual(len(lab.challenger_contract_sha256()), 64)

    def test_each_future_issue_is_scored_once_without_using_it_for_its_prediction(self):
        report = lab.audit_walk_forward(self.bundle)
        self.assertEqual(report["schema"], "V47-D2-EXPLORATORY-WALKFORWARD-1")
        self.assertEqual(report["draws_by_game"], {"SSQ": 25, "DLT": 25})
        self.assertEqual(report["data_provenance"], "CALLER_SUPPLIED_UNVERIFIED_HISTORY")
        self.assertEqual(report["evidence_class"], "RETROSPECTIVE_EXPLORATORY_NOT_PROSPECTIVE")
        self.assertEqual(report["formal_A"], 0)
        self.assertEqual(report["decision"], "NO_EDGE")
        self.assertFalse(report["qualified_prospective"])
        self.assertEqual(len(report["rows"]), 50)
        for game in ("SSQ", "DLT"):
            original = self.bundle[game]["draws"]
            rows = [r for r in report["rows"] if r["lottery"] == game]
            self.assertEqual([r["issue"] for r in rows], [d["issue"] for d in original[120:]])
            for row in rows:
                self.assertEqual(set(row["pairs"]), {"challenger", "pairwise_d2", "random_null"})
                self.assertEqual(set(row["d2_hits"]), set(row["pairs"]))
                for arm in row["pairs"]:
                    self.assertIn(row["d2_hits"][arm], (0, 1))
        self.assertEqual(report, lab.audit_walk_forward(copy.deepcopy(self.bundle)))

    def test_target_outcome_mutation_does_not_change_its_preceding_prediction(self):
        a = lab.audit_walk_forward(self.bundle)
        altered = copy.deepcopy(self.bundle)
        original = altered["DLT"]["draws"][120]["front"]
        altered["DLT"]["draws"][120]["front"] = next(
            sorted({n, *original[1:]})
            for n in range(1, 36) if n not in original
        )
        b = lab.audit_walk_forward(altered)
        ra = next(r for r in a["rows"] if r["lottery"] == "DLT")
        rb = next(r for r in b["rows"] if r["lottery"] == "DLT")
        self.assertEqual(ra["issue"], rb["issue"])
        self.assertEqual(ra["pairs"], rb["pairs"])
        self.assertNotEqual(a["input_bundle_sha256"], b["input_bundle_sha256"])

    def test_late_published_training_row_is_rejected_not_skipped(self):
        b = copy.deepcopy(self.bundle)
        target = b["SSQ"]["draws"][120]
        b["SSQ"]["draws"][119]["published_at"] = target["drawn_at"]
        with self.assertRaisesRegex(core.GateError, "TRAINING_NOT_PUBLISHED_BEFORE_TEST_DRAW"):
            lab.audit_walk_forward(b)

    def test_complete_two_game_input_required_and_model_cannot_be_tuned_posthoc(self):
        with self.assertRaisesRegex(core.GateError, "EXACT_TWO_GAMES_REQUIRED"):
            lab.audit_walk_forward({"SSQ": self.bundle["SSQ"]})
        with self.assertRaises(TypeError):
            lab.audit_walk_forward(self.bundle, half_life=5)
        with self.assertRaisesRegex(core.GateError, "D2_CHALLENGER_WARMUP_120_REQUIRED"):
            lab.pick_recency_pair(self.bundle["SSQ"]["draws"][:119], "SSQ")

    def test_fixed_null_is_unchanged_when_past_data_are_modified(self):
        a = lab.audit_walk_forward(self.bundle)
        b = copy.deepcopy(self.bundle)
        # Valid prior historical row mutation; affect research model, never NULL.
        row = b["SSQ"]["draws"][3]
        row["front"] = sorted([n for n in range(1, 34) if n not in row["front"]][:6])
        c = lab.audit_walk_forward(b)
        pairs_a = [(r["issue"],r["pairs"]["random_null"]) for r in a["rows"] if r["lottery"] == "SSQ"]
        pairs_c = [(r["issue"],r["pairs"]["random_null"]) for r in c["rows"] if r["lottery"] == "SSQ"]
        self.assertEqual(pairs_a, pairs_c)

    def test_perfect_synthetic_hit_still_no_edge_claim(self):
        result = lab.audit_walk_forward(self.bundle)
        for game, stats in result["exploratory_statistics"].items():
            self.assertEqual(stats["n"], 25)
            self.assertEqual(stats["registration"], "NOT_PREREGISTERED")
            self.assertGreaterEqual(stats["paired_p_unadjusted"], 0)
            self.assertLessEqual(stats["paired_p_unadjusted"], 1)
        self.assertEqual(result["decision"], "NO_EDGE")


    def test_cli_emits_complete_hash_bound_research_report(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "synthetic.json"
            p.write_text(json.dumps(self.bundle), encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = lab.main(["--snapshot-bundle", str(p)])
            self.assertEqual(code, 0)
            report = json.loads(out.getvalue())
            self.assertEqual(report["draws_by_game"], {"SSQ": 25, "DLT": 25})
            self.assertEqual(report["input_bundle_sha256"], core.digest(self.bundle))
            self.assertEqual(report["decision"], "NO_EDGE")


if __name__ == "__main__":
    unittest.main()
