"""Synthetic fixtures only: never counted as qualified lottery predictions."""
import random
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from research.harness_v46 import core


def fixture(lottery="SSQ", size=140):
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


class GateTests(unittest.TestCase):
    def test_six_agents_two_lotteries_deterministic(self):
        for lottery in ("SSQ", "DLT"):
            data = fixture(lottery)
            for model in core.MODELS:
                with self.subTest(lottery=lottery, model=model):
                    p = core.forecast(data, model)
                    self.assertEqual(p, core.forecast(data, model))
                    self.assertEqual(len(p["candidates_1_to_5"]), 5)
                    self.assertEqual(p["primary_d2"], p["candidates_1_to_5"][:2])
                    self.assertTrue(core.validate_forecast(p, data))
                    self.assertEqual(p["evidence_class"], "SHADOW")
                    self.assertFalse(p["formal_a_eligible"])

    def test_null_not_moved_by_history(self):
        a = fixture()
        b = fixture()
        b["draws"][1]["front"], b["draws"][2]["front"] = (
            b["draws"][2]["front"], b["draws"][1]["front"])
        # Only the historical contents changed, not random NULL's selections.
        self.assertEqual(
            core.forecast(a, "random_null")["candidates_1_to_5"],
            core.forecast(b, "random_null")["candidates_1_to_5"])

    def test_future_publication_rejected(self):
        data = fixture()
        data["draws"][-1]["published_at"] = "2026-10-24T00:00:00+00:00"
        with self.assertRaises(core.GateError):
            core.forecast(data, "hot60")

    def test_duplicate_or_out_of_order_rejected(self):
        data = fixture()
        data["draws"][2]["issue"] = data["draws"][1]["issue"]
        with self.assertRaises(core.GateError):
            core.validate_snapshot(data)

    def test_time_and_target_gates(self):
        data = fixture()
        data["target_issue"] = data["draws"][-1]["issue"]
        with self.assertRaises(core.GateError):
            core.validate_snapshot(data)
        data = fixture()
        data["as_of"] = "2026-10-24T00:00:00+08:00"
        with self.assertRaises(core.GateError):
            core.validate_snapshot(data)

    def test_incomplete_history_blocked(self):
        data = fixture(size=59)
        for model in core.MODELS[:5]:
            with self.subTest(model=model), self.assertRaises(core.GateError):
                core.forecast(data, model)
        self.assertTrue(core.forecast(data, "random_null"))

    def test_tamper_rejected(self):
        data = fixture()
        p = core.forecast(data, "hot60")
        p["primary_d2"] = list(reversed(p["primary_d2"]))
        with self.assertRaises(core.GateError):
            core.validate_forecast(p, data)
        p = core.forecast(data, "hot60")
        p["parameters_sha256"] = "bad"
        with self.assertRaises(core.GateError):
            core.validate_forecast(p, data)
        p = core.forecast(data, "hot60")
        p["formal_a_eligible"] = True
        with self.assertRaises(core.GateError):
            core.validate_forecast(p, data)

    def test_replay_rejects_legal_but_substituted_numbers(self):
        # All mutations keep legal ball ranges and may preserve primary D2.
        for lottery in ("SSQ", "DLT"):
            data = fixture(lottery)
            rules = core.RULES[lottery]
            for model in core.MODELS:
                with self.subTest(lottery=lottery, model=model):
                    p = core.forecast(data, model)
                    p["candidates_1_to_5"][2], p["candidates_1_to_5"][3] = (
                        p["candidates_1_to_5"][3], p["candidates_1_to_5"][2])
                    with self.assertRaises(core.GateError):
                        core.validate_forecast(p, data)

                    p = core.forecast(data, model)
                    other_back = [n for n in range(1, rules["back_pool"] + 1)
                                  if n not in p["ticket"]["back"]]
                    p["ticket"]["back"] = sorted(other_back[:rules["back"]])
                    with self.assertRaises(core.GateError):
                        core.validate_forecast(p, data)

                    p = core.forecast(data, model)
                    p["version"] = "forged-version"
                    with self.assertRaises(core.GateError):
                        core.validate_forecast(p, data)

                    if lottery == "SSQ":
                        p = core.forecast(data, model)
                        filler = next(n for n in range(1, rules["pool"] + 1)
                                      if n not in p["ticket"]["front"])
                        sixth = next(n for n in p["ticket"]["front"]
                                     if n not in p["candidates_1_to_5"])
                        p["ticket"]["front"] = sorted(
                            (set(p["ticket"]["front"]) - {sixth}) | {filler})
                        with self.assertRaises(core.GateError):
                            core.validate_forecast(p, data)

    def test_null_attribution_cannot_be_replaced(self):
        data = fixture()
        p = core.forecast(data, "random_null")
        p["null_seed_id"] = "substituted"
        with self.assertRaises(core.GateError):
            core.validate_forecast(p, data)

    def test_immutable_freeze_and_duplicate(self):
        data = fixture()
        p = core.forecast(data, "pairwise_d2")
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        sha = core.freeze_shadow(db, "TEST-001", data, p, "2026-10-21T00:00:00+00:00")
        self.assertEqual(len(sha), 64)
        self.assertEqual(db.execute("SELECT count(*) FROM audit_events").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            core.freeze_shadow(db, "TEST-001", data, p, "2026-10-21T00:00:00+00:00")
        self.assertEqual(db.execute("SELECT count(*) FROM audit_events").fetchone()[0], 1)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE predictions SET evidence_class='A'")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM predictions")
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM audit_events")

    def test_batch_rollback_all_or_nothing(self):
        data = fixture()
        p = core.forecast(data, "hot60")
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        with self.assertRaises(sqlite3.IntegrityError):
            with db:
                core.freeze_shadow(db, "ROLLBACK-TEST", data, p, "2026-10-21T00:00:00+00:00")
                core.freeze_shadow(db, "ROLLBACK-TEST", data, p, "2026-10-21T00:00:00+00:00")
        self.assertEqual(db.execute("SELECT count(*) FROM predictions").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM audit_events").fetchone()[0], 0)

    def test_late_freeze_blocked(self):
        data = fixture()
        p = core.forecast(data, "hot60")
        db = sqlite3.connect(":memory:")
        core.init_ledger(db)
        with self.assertRaises(core.GateError):
            core.freeze_shadow(db, "TEST-002", data, p, "2026-10-24T00:00:00+08:00")
        self.assertEqual(db.execute("SELECT count(*) FROM predictions").fetchone()[0], 0)

    def test_scoring_d2_front_only(self):
        data = fixture("DLT")
        p = core.forecast(data, "hot60")
        front = sorted(p["candidates_1_to_5"])
        result = {"lottery": "DLT", "issue": "29999", "front": front, "back": [1, 2]}
        scores = core.score(p, result)
        self.assertEqual([scores[f"D{k}"] for k in range(1, 6)], [1, 1, 1, 1, 1])
        self.assertEqual(scores["hit_count_5"], 5)
        result["issue"] = "29998"
        with self.assertRaises(core.GateError):
            core.score(p, result)


if __name__ == "__main__":
    unittest.main()
