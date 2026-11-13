"""Mother V1: exact registry, all-model outputs, physical proof and leak gates."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta, date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.harness_v46 import core
from research.mother_v1.fixture import invented_bundle
from research.mother_v1.mother import MotherBlocked, forecast_all, sha
from research.mother_v1.registry import (
    ALL_MODELS, REGISTERED_V47, EXPLORATORY_V47, LEGACY_SUPERCOMPUTE, PHYSICAL,
)


class MotherRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = invented_bundle()
        cls.first = forecast_all(cls.bundle)

    def test_six_plus_five_plus_three_plus_two_per_game(self):
        self.assertEqual(6, len(REGISTERED_V47))
        self.assertEqual(5, len(EXPLORATORY_V47))
        self.assertEqual(3, len(LEGACY_SUPERCOMPUTE))
        self.assertEqual(2, len(PHYSICAL))
        self.assertEqual(16, len(ALL_MODELS))
        self.assertEqual(0, self.first["formal_A"])
        self.assertEqual("NO_EDGE", self.first["decision"])
        for game in ("SSQ", "DLT"):
            rows = self.first["games"][game]["models"]
            self.assertEqual(16, len(rows))
            self.assertEqual(list(ALL_MODELS), [r["name"] for r in rows])
            self.assertEqual(len(rows), len({r["name"] for r in rows}))
            self.assertTrue(all(r["formal_A"] == 0 for r in rows))

    def test_all_nonphysical_models_must_emit_legal_tickets(self):
        for game in ("SSQ", "DLT"):
            r = core.RULES[game]
            for row in self.first["games"][game]["models"]:
                if row["name"] in PHYSICAL:
                    continue
                ticket = row["ticket"]
                self.assertIsNotNone(ticket)
                for field, count, high in [
                    ("front", r["front"], r["pool"]),
                    ("back", r["back"], r["back_pool"]),
                ]:
                    nums = ticket[field]
                    self.assertEqual(count, len(nums))
                    self.assertEqual(sorted(set(nums)), nums)
                    self.assertTrue(all(1 <= n <= high for n in nums))

    def test_physical_no_fabrication_and_labeled_null_baseline(self):
        for game in ("SSQ", "DLT"):
            rows = self.first["games"][game]["models"]
            null = next(row for row in rows if row["name"] == "random_null")
            physical = [row for row in rows if row["name"] in PHYSICAL]
            self.assertEqual(2, len(physical))
            for row in physical:
                self.assertIsNone(row["ticket"])
                self.assertFalse(row["physical_prediction_verified"])
                self.assertTrue(row["status"].startswith("ABSTAIN_"))
                self.assertFalse(row["fallback_is_physical_forecast"])
                self.assertEqual(null["ticket"], row["display_only_random_null_fallback"])

    def test_hash_stable_and_original_v47_null_control(self):
        self.assertEqual(sha(self.first), sha(forecast_all(self.bundle)))
        for game in ("SSQ", "DLT"):
            ctx = self.bundle[game]
            old_rank = core._model_ranking({
                "lottery": game, "target_issue": ctx["target_issue"],
                "draws": ctx["history"]}, "random_null")
            row = next(r for r in self.first["games"][game]["models"]
                       if r["name"] == "random_null")
            self.assertEqual(sorted(old_rank[:core.RULES[game]["front"]]),
                             row["ticket"]["front"])

    def test_no_future_or_target_issue_labels_in_training(self):
        for game in ("SSQ", "DLT"):
            modified = deepcopy(self.bundle)
            modified[game]["history"][-1]["issue"] = modified[game]["target_issue"]
            with self.subTest(game=game):
                with self.assertRaises(MotherBlocked):
                    forecast_all(modified)
            modified = deepcopy(self.bundle)
            modified[game]["history"][-1]["draw_date"] = modified[game]["target_draw_date"]
            with self.assertRaises(MotherBlocked):
                forecast_all(modified)

    def test_out_of_order_missing_issue_and_bad_ball_count(self):
        for game in ("SSQ", "DLT"):
            bad = deepcopy(self.bundle)
            bad[game]["history"][30]["issue"] = bad[game]["history"][31]["issue"]
            with self.assertRaises(MotherBlocked):
                forecast_all(bad)
            bad = deepcopy(self.bundle)
            bad[game]["history"][12]["front"][0] = 0
            with self.assertRaises(core.GateError):
                forecast_all(bad)

    def test_false_source_authenticity_claim_blocked(self):
        bad = deepcopy(self.bundle)
        bad["SSQ"]["provenance"] = "OFFICIALLY_VERIFIED_NO_EVIDENCE"
        with self.assertRaisesRegex(MotherBlocked, "AUTHENTICITY_UNSUPPORTED"):
            forecast_all(bad)

    def test_year_rollover_sequence(self):
        from research.mother_v1.mother import _next_issue
        self.assertTrue(_next_issue("SSQ", "2025154", "2026001"))
        self.assertTrue(_next_issue("DLT", "25152", "26001"))
        self.assertFalse(_next_issue("SSQ", "2026121", "2026123"))

    def test_malformed_physical_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "DLT" / "draws"
            target.mkdir(parents=True)
            (target / "26101.json").write_text('{"issue":"26101","x":"fake"}')
            with self.assertRaisesRegex(MotherBlocked, "PHYSICAL_CANONICAL_LEDGER_INVALID"):
                forecast_all(self.bundle, physical_ledger=root)

    def test_verified_physical_historical_rows_produce_only_exit_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draws = root / "DLT" / "draws"
            draws.mkdir(parents=True)
            history = self.bundle["DLT"]["history"]
            for i, hist in enumerate(history[-60:]):
                raw = {"game": "DLT", "issue": hist["issue"],
                       "draw_date": hist["draw_date"],
                       "front_sorted": hist["front"], "back_sorted": hist["back"],
                       "front_order": list(reversed(hist["front"])),
                       "back_order": list(reversed(hist["back"])),
                       "ball_group": 1 + i % 3}
                (draws / (hist["issue"] + ".json")).write_text(json.dumps(raw))
            # This test isolates the aggregation logic. Actual source verifier
            # is tested separately against original SHA-linked HTML fixtures.
            with patch("research.mother_v1.mother.dlt_physical_source.verify", return_value={}):
                with patch("research.mother_v1.mother.ssq_physical_source.verify", return_value={}):
                    result = forecast_all(self.bundle, physical_ledger=root)
            dlt = result["games"]["DLT"]
            self.assertEqual(60, dlt["physical_count"])
            arms = {r["name"]: r for r in dlt["models"] if r["name"] in PHYSICAL}
            self.assertEqual("PREDICTED_SHADOW_PHYSICAL_EXPLORATORY_NO_EDGE",
                             arms["physical_exit_order"]["status"])
            self.assertIsNotNone(arms["physical_exit_order"]["ticket"])
            self.assertEqual("ABSTAIN_NO_VERIFIED_PREDRAW_BALL_GROUP",
                             arms["physical_ball_group"]["status"])
            self.assertIsNone(arms["physical_ball_group"]["ticket"])

    def test_physical_postdraw_issue_and_balls_conflict_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            draws = root / "DLT" / "draws"
            draws.mkdir(parents=True)
            hist = self.bundle["DLT"]["history"][-1]
            row = {"issue": self.bundle["DLT"]["target_issue"], "draw_date": hist["draw_date"],
                   "front_sorted": hist["front"], "back_sorted": hist["back"],
                   "front_order": hist["front"], "back_order": hist["back"],
                   "ball_group": 1}
            (draws / (row["issue"] + ".json")).write_text(json.dumps(row))
            with patch("research.mother_v1.mother.dlt_physical_source.verify", return_value={}):
                with self.assertRaisesRegex(MotherBlocked, "OUTSIDE_TRAINING"):
                    forecast_all(self.bundle, physical_ledger=root)
            row["issue"] = hist["issue"]
            row["front_sorted"] = [1, 2, 3, 4, 5]
            (draws / (row["issue"] + ".json")).write_text(json.dumps(row))
            (draws / (self.bundle["DLT"]["target_issue"] + ".json")).unlink()
            with patch("research.mother_v1.mother.dlt_physical_source.verify", return_value={}):
                with self.assertRaisesRegex(MotherBlocked, "BALL_CONFLICT"):
                    forecast_all(self.bundle, physical_ledger=root)


if __name__ == "__main__":
    unittest.main()
