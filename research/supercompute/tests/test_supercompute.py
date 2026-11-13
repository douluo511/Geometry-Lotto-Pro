"""No-network tests for SSQ+DLT CPU research engine."""
import copy
import math
import tempfile
import unittest
from pathlib import Path
from research.supercompute.engine import (
    SPECS, chance, check_balls, compute, simulate, snapshot, ticket, walk_forward, wilson,
)


class EngineTest(unittest.TestCase):
    def test_both_repository_snapshots(self):
        for game in SPECS:
            data, meta = snapshot(game)
            self.assertGreater(len(data), 120)
            self.assertEqual(len(data), meta["rows"])
            self.assertEqual(data[-1]["issue"], meta["asof_issue"])
            self.assertEqual(meta["status"], "historical_snapshot_not_live_verified")

    def test_exact_fair_probability(self):
        for name, (fm, fp, bm, bp) in SPECS.items():
            self.assertEqual(chance(name)["full_ticket_one_in"],
                             math.comb(fm, fp) * math.comb(bm, bp))
            self.assertAlmostEqual(chance(name)["dan2_probability"],
                                   math.comb(fm - 2, fp - 2) / math.comb(fm, fp))

    def test_bad_balls_rejected(self):
        for balls in ([1, 1, 2, 3, 4, 5], [1, 2, 3, 4, 5, 34],
                      [True, 2, 3, 4, 5, 6], [2, 1, 3, 4, 5, 6]):
            with self.assertRaises(ValueError):
                check_balls(balls, 6, 33)

    def test_invalid_snapshot_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"game":"ssq","draws":[]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                snapshot("ssq", path)

    def test_no_future_leak(self):
        data, _ = snapshot("ssq")
        history = data[:130]
        earlier = {m: ticket(history, "ssq", m, 19) for m in
                   ("HOT60", "EWMA30")}
        changed = copy.deepcopy(data)
        changed[130]["front"] = [1, 2, 3, 4, 5, 6]
        later = {m: ticket(changed[:130], "ssq", m, 19) for m in earlier}
        self.assertEqual(earlier, later)

    def test_all_tickets_legal(self):
        for game, (fm, fp, bm, bp) in SPECS.items():
            rows, _ = snapshot(game)
            for model in ("HOT60", "EWMA30"):
                t = ticket(rows, game, model, 7)
                check_balls(t["front"], fp, fm)
                check_balls(t["back"], bp, bm)
                self.assertEqual(len(t["dan2"]), 2)
                self.assertTrue(set(t["dan2"]).issubset(t["front"]))
                self.assertFalse(t["formal_prediction"])

    def test_parallel_same_result_as_serial(self):
        a, b = simulate("dlt", 230, 1, 17), simulate("dlt", 230, 2, 17)
        self.assertEqual(a["dan2_hits"], b["dan2_hits"])
        self.assertEqual(a["dan2_wilson95"], b["dan2_wilson95"])

    def test_backtest_past_only(self):
        data, _ = snapshot("ssq")
        r = walk_forward(data[:148], "ssq", 12, 2026)
        self.assertTrue(r["strictly_past_only"])
        self.assertEqual(r["models"]["HOT60"]["evaluated"], 12)
        self.assertEqual(r["first_evaluated_issue"], data[136]["issue"])

    def test_research_cannot_be_promoted(self):
        r = compute("dlt", 4, 100, 1, 7)
        self.assertEqual(r["formal_A"], 0)
        self.assertEqual(r["edge"], "NO_EDGE")

    def test_limits_and_interval(self):
        self.assertEqual(wilson(0, 1)[0], 0)
        with self.assertRaises(ValueError):
            wilson(0, 0)
        with self.assertRaises(ValueError):
            simulate("ssq", 3000000, 1, 0)


if __name__ == "__main__":
    unittest.main()
