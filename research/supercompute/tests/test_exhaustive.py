"""Adversarial full-universe lottery enumeration tests, not forecasts."""
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from research.supercompute.exhaustive import (
    SPECS, check_reference, exact_histogram, enumerate_game, main,
)


class ExhaustiveTests(unittest.TestCase):
    def test_official_spaces_exact(self):
        self.assertEqual(math.comb(33, 6) * math.comb(16, 1), 17721088)
        self.assertEqual(math.comb(35, 5) * math.comb(12, 2), 21425712)
        self.assertEqual(sum(math.comb(a, b) * math.comb(c, d)
                             for a, b, c, d in SPECS.values()), 39146800)

    def test_small_game_exhaustive_matches_combinatorial_counts(self):
        small = (7, 3, 4, 2)
        ticket = {"front": [1, 2, 3], "back": [1, 2], "d2": [1, 3]}
        result = enumerate_game("TEST", workers=1, spec=small, reference=ticket)
        self.assertEqual(result["enumerated_outcomes"], 210)
        self.assertEqual(result["expected_outcomes"], 210)
        self.assertEqual(result["histogram"], exact_histogram(small))
        self.assertEqual(result["full_ticket_matches"], 1)
        self.assertEqual(result["d2_matches"], 30)
        self.assertEqual(result["d2_probability"], 1 / 7)
        self.assertEqual(result["full_ticket_probability"], 1 / 210)
        self.assertTrue(result["entire_space_exhausted"])
        self.assertEqual(len(result["partitions"]), 5)

    def test_workers_do_not_change_a_single_ticket_or_digest(self):
        small = (9, 4, 5, 2)
        ticket = {"front": [1, 4, 7, 9], "back": [2, 5], "d2": [4, 9]}
        one = enumerate_game("TEST", workers=1, spec=small, reference=ticket)
        many = enumerate_game("TEST", workers=2, spec=small, reference=ticket)
        # Worker count is configuration only; the content and partition hash
        # of the exact same complete legal ticket universe must be invariant.
        for key in ("enumerated_outcomes", "expected_outcomes", "histogram",
                    "full_ticket_matches", "d2_matches", "partitions"):
            self.assertEqual(one[key], many[key])
        self.assertEqual(one["full_ticket_matches"], 1)
        self.assertEqual(one["d2_matches"], math.comb(7, 2) * math.comb(5, 2))

    def test_invalid_or_duplicate_reference_fails_closed(self):
        bad = [
            {"front": [1, 1, 3], "back": [1, 2], "d2": [1, 3]},
            {"front": [2, 1, 3], "back": [1, 2], "d2": [1, 3]},
            {"front": [1, 2, 8], "back": [1, 2], "d2": [1, 2]},
            {"front": [1, 2, 3], "back": [1, 2], "d2": [1, 4]},
            {"front": [1, 2, 3], "back": [1, 1], "d2": [1, 2]},
            {"front": [1, 2, 3], "back": [1, 2], "d2": [True, 2]},
        ]
        for case in bad:
            with self.subTest(case=case), self.assertRaises(ValueError):
                check_reference(case, (7, 3, 4, 2))

    def test_all_games_use_synthetic_reference_not_future_pick(self):
        for game in SPECS:
            ref = None  # canonical synthetic reference
            result = enumerate_game(game, workers=1,
                                    spec=(7, 3, 4, 2), reference=ref)
            self.assertEqual(result["reference_ticket"]["source"],
                             "SYNTHETIC_CANONICAL_NO_PREDICTION")
            self.assertEqual(result["formal_A"], 0)
            self.assertEqual(result["edge"], "NO_EDGE")
            self.assertEqual(result["enumerated_outcomes"], 210)

    def test_output_receipt_has_self_consistent_hash_and_no_formal_promotion(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "results"
            rc = main(["--game", "test", "--workers", "2", "--out", str(out),
                       "--test-small"])
            self.assertEqual(rc, 0)
            raw = (out / "report.json").read_bytes()
            declared = (out / "report.sha256").read_text().split()[0]
            self.assertEqual(hashlib.sha256(raw).hexdigest(), declared)
            doc = json.loads(raw)
            self.assertEqual(doc["schema"], "SSQDLT_EXHAUSTIVE_OUTCOMES_V1")
            self.assertEqual(doc["total_enumerated_outcomes"], 210)
            self.assertEqual(doc["formal_A"], 0)
            self.assertEqual(doc["edge"], "NO_EDGE")

    def test_reject_unbounded_workers_and_unrequested_test_mode(self):
        with self.assertRaises(ValueError):
            enumerate_game("ssq", workers=9, spec=(7, 3, 4, 2))
        with self.assertRaises(ValueError):
            enumerate_game("ssq", workers=0, spec=(7, 3, 4, 2))
        with self.assertRaises(ValueError):
            enumerate_game("test", workers=1)


if __name__ == "__main__":
    unittest.main()
