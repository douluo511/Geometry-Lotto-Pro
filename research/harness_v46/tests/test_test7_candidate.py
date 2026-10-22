"""Independent synthetic-only checks of the unregistered test7 candidate."""
import random
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from itertools import combinations

from research.harness_v46 import core, test7_candidate as challenger

def fixture(lottery, size=140):
    r = core.RULES[lottery]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    draws = []
    for i in range(size):
        rng = random.Random(98765 + i * 3 + (0 if lottery == "SSQ" else 1))
        stamp = start + timedelta(days=i)
        draws.append({
            "issue": str(26001 + i),
            "front": sorted(rng.sample(range(1, r["pool"] + 1), r["front"])),
            "back": sorted(rng.sample(range(1, r["back_pool"] + 1), r["back"])),
            "drawn_at": stamp.isoformat(),
            "published_at": (stamp + timedelta(hours=1)).isoformat(),
        })
    return {
        "lottery": lottery,
        "as_of": "2026-10-20T00:00:00+00:00",
        "sales_cutoff": "2026-10-23T12:00:00+08:00",
        "target_draw_at": "2026-10-23T21:00:00+08:00",
        "target_issue": "29999",
        "draws": draws,
        "provenance": {"status": "SYNTHETIC_FIXTURE_NOT_OFFICIAL"},
    }

class Test7Candidate(unittest.TestCase):
    def test_minimum_120_is_fail_closed_for_both_games(self):
        for lottery in ("SSQ", "DLT"):
            with self.subTest(lottery=lottery):
                with self.assertRaises(core.GateError):
                    challenger.select_proposal(fixture(lottery, 119))
                self.assertEqual(len(challenger.select_proposal(fixture(lottery, 120))["candidates_1_to_5"]), 5)

    def test_exact_pair_score_independent_fraction_oracle(self):
        for lottery in ("SSQ", "DLT"):
            with self.subTest(lottery=lottery):
                draws = fixture(lottery)["draws"]
                w, k = 30, core.RULES[lottery]["front"]
                scores = challenger.pair_scores(draws, lottery, w)
                for a, b in combinations(range(1, core.RULES[lottery]["pool"] + 1), 2):
                    tail = draws[-w:]
                    a_count = sum(a in d["front"] for d in tail)
                    b_count = sum(b in d["front"] for d in tail)
                    cooccurrence = sum(a in d["front"] and b in d["front"] for d in tail)
                    expected = Fraction(a_count * b_count * (k - 1), w * k)
                    oracle = (Fraction(cooccurrence) - expected) / (w + 200)
                    self.assertEqual(scores[(a, b)], oracle)

    def test_independent_argmax_oracle_for_both_lotteries(self):
        for lottery in ("SSQ", "DLT"):
            with self.subTest(lottery=lottery):
                snap = fixture(lottery)
                scores = [challenger.pair_scores(snap["draws"], lottery, w)
                          for w in (30, 60, 120)]
                ranked = sorted(scores[0], key=lambda p: (-min(v[p] for v in scores), p))
                got = challenger.select_proposal(snap)
                self.assertEqual(got["primary_d2"], list(ranked[0]))
                self.assertEqual(got["primary_d2"], got["candidates_1_to_5"][:2])
                self.assertFalse(got["formal_a_eligible"])
                self.assertEqual(got["registration_status"], "EXPLORATORY_UNREGISTERED")
                self.assertEqual(len(set(got["ticket"]["front"])), core.RULES[lottery]["front"])
                self.assertEqual(len(got["ticket"]["back"]), core.RULES[lottery]["back"])
                self.assertTrue(set(got["candidates_1_to_5"]).issubset(got["ticket"]["front"]))
                self.assertEqual(got, challenger.select_proposal(snap))

    def test_mechanism_differs_from_existing_marginal_plus_residual(self):
        # Synthetic fixtures demonstrate a code-level mechanism distinction,
        # NOT genuine forecasting skill or evidence to choose a champion.
        pairs = {}
        for lottery in ("SSQ", "DLT"):
            snap = fixture(lottery)
            proposed = challenger.select_proposal(snap)["primary_d2"]
            incumbent = core.forecast(snap, "challenger")["primary_d2"]
            pairs[lottery] = (proposed, incumbent)
        self.assertNotEqual(pairs["SSQ"][0], pairs["SSQ"][1])
        self.assertNotEqual(pairs["DLT"][0], pairs["DLT"][1])

    def test_older_than_120_is_not_used_to_choose_pair(self):
        for lottery in ("SSQ", "DLT"):
            snap = fixture(lottery, 140)
            p1 = challenger.select_proposal(snap)
            modified = fixture(lottery, 140)
            r = core.RULES[lottery]
            modified["draws"][1]["front"] = list(range(r["front"] + 1, 2 * r["front"] + 1))
            p2 = challenger.select_proposal(modified)
            self.assertNotEqual(p1["snapshot_sha256"], p2["snapshot_sha256"])
            self.assertEqual(p1["candidates_1_to_5"], p2["candidates_1_to_5"])

    def test_numeric_pair_tie_is_exact_and_ascending(self):
        for lottery in ("SSQ", "DLT"):
            snap = fixture(lottery, 120)
            fixed = list(range(1, core.RULES[lottery]["front"] + 1))
            for d in snap["draws"]:
                d["front"] = fixed[:]
            self.assertEqual(challenger.select_proposal(snap)["primary_d2"], [1, 2])

    def test_future_published_data_rejected(self):
        snap = fixture("DLT")
        snap["draws"][-1]["published_at"] = "2026-10-25T00:00:00+00:00"
        with self.assertRaises(core.GateError):
            challenger.select_proposal(snap)

    def test_all_parameters_bound_and_no_prospective_claims(self):
        p = challenger.parameter_contract()
        self.assertEqual(p["windows"], [30, 60, 120])
        self.assertEqual(p["tau"], 200)
        self.assertEqual(p["minimum_history"], 120)
        self.assertEqual(p["core_version"], core.VERSION)
        self.assertEqual(p["parent_core_source_sha256"], core.model_source_sha256())
        self.assertEqual(p["ticket_back"]["engine"], core.TICKET_BACK_ENGINE)
        self.assertEqual(p["ticket_back"]["seed"], core.NULL_SEED)
        self.assertEqual(len(core.digest(p)), 64)
        self.assertNotIn(challenger.CANDIDATE_ID, core.MODELS)
